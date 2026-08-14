"""Tests for G3-HOLDOUT-09A freeze-bound holdout harness.

Covers: Freeze ID / frozen knob tamper rejection; wrong dataset / holdout eval id
rejection; CLI has no performance overrides and only allows --preflight-only in
09A; preflight is 0-LLM / 0-embedding / 0-index and does not read the holdout
file or private manifest; one-shot attempt ledger state machine (second active /
completed / failed_system / invalid_infrastructure all reject); generation Gold
sentinel isolation; actual execution source commit + freeze id enter Holdout
identity; Dev Gate3E2EConfig identity/run_id compatibility unchanged.

No LLM / retrieval / embedding / sealed access. Uses tmp_path + public freeze
fixture + fake git repos only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from evaluation.gate3.e2e import (
    GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    Gate3E2EConfig,
)
from evaluation.gate3.holdout import (
    HoldoutInfrastructureFailure,
    _parse_generation_cases_from_holdout,
    assert_no_forbidden_overrides,
    atomic_create_attempt,
    build_holdout_config_from_freeze,
    check_attempt_allowed,
    execute_holdout,
    preflight_holdout,
    read_attempt_ledger,
    update_attempt_status,
    validate_frozen_knobs,
    validate_sealed,
)

FREEZE_SRC = Path(__file__).resolve().parent.parent / "docs/experiments" / "gate3_system_freeze.json"
PLANNER_SHA = "5b209054f5274fa8f1f88975625c80b78d7e9e2a84569179288fed0c3a3b5c95"
DEV_COMMIT = "f" * 40


def _freeze_json():
    return json.loads(FREEZE_SRC.read_text("utf-8"))


def _freeze(tmp_path, mutate=None):
    freeze = _freeze_json()
    if mutate is not None:
        mutate(freeze)
    p = tmp_path / "freeze.json"
    p.write_text(json.dumps(freeze, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _dev_config():
    return Gate3E2EConfig(
        source_commit=DEV_COMMIT, corpus_id="870e5864df67", corpus_file_count=37,
        gate3_dataset_freeze_id="257fa0d0a6d6",
        dev_evaluation_set_id="f2144030d754", dev_case_count=24,
        dev_jsonl_sha256="0b" * 32, planner_prompt_sha256=PLANNER_SHA,
        judge_prompt_sha256=GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    )


def _holdout_config(tmp_path, mutate=None, actual_commit=DEV_COMMIT):
    return build_holdout_config_from_freeze(
        _freeze(tmp_path, mutate),
        actual_execution_source_commit=actual_commit,
        holdout_jsonl_path="h.jsonl", private_manifest_path="p.json",
        frozen_index_manifest_path="m.json", corpus_root="c", output_root="o",
    )


def _make_dirty_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                   check=True)
    f = repo / "a.txt"
    f.write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    f.write_text("v2", encoding="utf-8")  # tracked modification
    return repo


def _clean_git_repo(tmp_path):
    repo = tmp_path / "clean_repo"
    if (repo / ".git").exists():
        return repo  # 幂等：多次执行复用同一 clean repo
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                   check=True)
    (repo / "a.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    return repo


def _preflight_args(tmp_path, **kw):
    base = dict(
        repo=str(_clean_git_repo(tmp_path)),
        freeze_json_path=_freeze(tmp_path),
        holdout_jsonl_path=str(tmp_path / "no_such_holdout.jsonl"),
        private_manifest_path=str(tmp_path / "no_such_manifest.json"),
        frozen_index_manifest_path=str(tmp_path / "manifest.json"),
        corpus_root=str(tmp_path / "corpus"),
        output_root=str(tmp_path / "out"),
        attempt_ledger_path=str(tmp_path / "ledger.json"),
    )
    base.update(kw)
    return base


class TestHoldoutIdentity:
    def test_identity_binds_freeze_and_actual_commit(self, tmp_path):
        c1 = _holdout_config(tmp_path, actual_commit=DEV_COMMIT)
        c2 = _holdout_config(tmp_path, actual_commit="a" * 40)
        assert c1.holdout_run_id != c2.holdout_run_id
        assert c1.gate3_system_freeze_id == "2ec11a69b173"
        assert c1.holdout_evaluation_set_id == "79a6bc0814a3"
        assert c1.holdout_case_count == 12
        payload = c1.identity_payload()
        assert payload["actual_execution_source_commit"] == DEV_COMMIT
        assert payload["gate3_system_freeze_id"] == "2ec11a69b173"
        assert "dev_evaluation_set_id" not in payload  # 独立于 Dev 身份

    def test_holdout_identity_independent_from_dev(self, tmp_path):
        h = _holdout_config(tmp_path).identity_payload()
        d = _dev_config().identity_payload()
        assert h != d
        assert "dev_case_count" not in h
        assert h["holdout_case_count"] == 12


class TestFreezeValidation:
    def test_freeze_id_tamper_rejects(self, tmp_path):
        with pytest.raises(ValueError):
            _holdout_config(tmp_path, mutate=lambda f: f.__setitem__(
                "gate3_system_freeze_id", "0" * 12))

    def test_frozen_planner_knob_tamper_rejects(self, tmp_path):
        with pytest.raises(ValueError):
            _holdout_config(tmp_path, mutate=lambda f: f["planner"].__setitem__(
                "model", "gpt-4"))

    def test_frozen_generator_knob_tamper_rejects(self, tmp_path):
        with pytest.raises(ValueError):
            _holdout_config(tmp_path, mutate=lambda f: f["generator"].__setitem__(
                "temperature", 1.5))

    def test_retrieval_merge_knob_tamper_rejects(self, tmp_path):
        with pytest.raises(ValueError):
            _holdout_config(tmp_path, mutate=lambda f: f[
                "retrieval_runtime_config"].__setitem__("merge_policy", "bogus"))

    def test_wrong_gate3_dataset_freeze_rejects(self, tmp_path):
        with pytest.raises(ValueError):
            _holdout_config(tmp_path, mutate=lambda f: f[
                "dataset_identities"].__setitem__("gate3_dataset_freeze_id", "0" * 12))

    def test_wrong_holdout_evaluation_set_id_rejects(self, tmp_path):
        with pytest.raises(ValueError):
            _holdout_config(tmp_path, mutate=lambda f: f[
                "dataset_identities"].__setitem__("holdout_evaluation_set_id", "0" * 12))

    def test_valid_freeze_config_builds(self, tmp_path):
        cfg = _holdout_config(tmp_path)
        validate_frozen_knobs(cfg)
        assert cfg.retrieval["merge_policy"] == "subquery_rrf_merge_v2"
        assert cfg.planner["model"] == "deepseek-chat"
        assert cfg.generator["model"] == "deepseek-v4-flash"
        assert cfg.judge["model"] == "deepseek-chat"


class TestCLI:
    def test_no_perf_overrides_allowed(self):
        for arg in ("--planner-model", "--generator-model", "--judge-model",
                    "--temperature", "--top-k", "--merge-policy",
                    "--merge-rrf-k", "--max-evidence"):
            with pytest.raises(SystemExit):
                assert_no_forbidden_overrides([arg, "x"])

    def test_cli_without_preflight_rejects(self, tmp_path):
        import scripts.run_gate3_e2e_holdout as cli
        args = [
            "--repo", str(Path.cwd()),
            "--freeze-json", _freeze(tmp_path),
            "--holdout-jsonl", "h", "--private-manifest", "p",
            "--frozen-index-manifest", "m", "--corpus-root", "c",
            "--output-root", str(tmp_path / "o"),
            "--attempt-ledger", str(tmp_path / "l"),
        ]
        with pytest.raises(SystemExit):
            cli.main(args)

    def test_cli_preflight_rejects_perf_override(self, tmp_path):
        import scripts.run_gate3_e2e_holdout as cli
        args = [
            "--preflight-only",
            "--freeze-json", _freeze(tmp_path),
            "--holdout-jsonl", "h", "--private-manifest", "p",
            "--frozen-index-manifest", "m", "--corpus-root", "c",
            "--output-root", str(tmp_path / "o"),
            "--attempt-ledger", str(tmp_path / "l"),
            "--generator-model", "xxx",
        ]
        with pytest.raises(SystemExit):
            cli.main(args)


class TestPreflight:
    def test_dirty_tracked_tree_rejects(self, tmp_path):
        repo = _make_dirty_git_repo(tmp_path)
        with pytest.raises(RuntimeError):
            preflight_holdout(**{**_preflight_args(tmp_path), "repo": str(repo)})

    def test_preflight_zero_llm_and_no_reads(self, tmp_path):
        report = preflight_holdout(**_preflight_args(tmp_path))
        assert report["preflight"] == "ok"
        assert report["llm_calls"] == 0
        assert report["retrieval_calls"] == 0
        assert report["embedding_calls"] == 0
        assert report["sealed_read"] is False

    def test_preflight_does_not_read_holdout_or_manifest(self, tmp_path):
        # 传入不存在的 holdout/private-manifest 路径 → 若 preflight 读取它们会失败；
        # 成功即证明只做 path contract，不 read_text/open。
        report = preflight_holdout(**_preflight_args(tmp_path))
        assert report["preflight"] == "ok"

    def test_preflight_output_exists_rejects(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        with pytest.raises(FileExistsError):
            preflight_holdout(**{**_preflight_args(tmp_path), "output_root": str(out)})

    def test_preflight_consumed_attempt_rejects(self, tmp_path):
        ledger = tmp_path / "ledger.json"
        ledger.write_text(json.dumps({
            "schema_version": "holdout_attempt_ledger_v1",
            "attempts": [{
                "attempt_id": "x", "status": "completed",
                "gate3_system_freeze_id": "2ec11a69b173",
                "gate3_dataset_freeze_id": "257fa0d0a6d6",
                "holdout_evaluation_set_id": "79a6bc0814a3",
                "actual_execution_source_commit": "f" * 40,
                "started_at": "2026-08-14T00:00:00+00:00",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(RuntimeError):
            preflight_holdout(**{**_preflight_args(tmp_path),
                                 "attempt_ledger_path": str(ledger)})

    def test_preflight_does_not_create_attempt(self, tmp_path):
        ledger = tmp_path / "ledger.json"
        preflight_holdout(**{**_preflight_args(tmp_path),
                             "attempt_ledger_path": str(ledger)})
        assert not ledger.exists()


class TestAttemptLedger:
    def _ledger(self, tmp_path, attempts, *, strict=True):
        # 默认补全必填字段使 read_attempt_ledger 严格校验通过（status 由调用方给定）；
        # strict=False 时原样写入（用于 malformed 测试）。
        full = []
        for a in attempts:
            d = dict(a)
            if strict:
                d.setdefault("gate3_system_freeze_id", "2ec11a69b173")
                d.setdefault("gate3_dataset_freeze_id", "257fa0d0a6d6")
                d.setdefault("holdout_evaluation_set_id", "79a6bc0814a3")
                d.setdefault("actual_execution_source_commit", "f" * 40)
                d.setdefault("started_at", "2026-08-14T00:00:00+00:00")
            full.append(d)
        p = tmp_path / "ledger.json"
        p.write_text(json.dumps({
            "schema_version": "holdout_attempt_ledger_v1", "attempts": full,
        }, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def test_second_active_attempt_rejects(self, tmp_path):
        path = self._ledger(tmp_path, [{"attempt_id": "a1", "status": "running"}])
        with pytest.raises(RuntimeError):
            check_attempt_allowed(path)
        with pytest.raises(RuntimeError):
            atomic_create_attempt(path, _holdout_config(tmp_path))

    def test_completed_attempt_rejects(self, tmp_path):
        path = self._ledger(tmp_path, [{"attempt_id": "a1", "status": "completed"}])
        with pytest.raises(RuntimeError):
            check_attempt_allowed(path)

    def test_failed_system_rejects_rerun(self, tmp_path):
        path = self._ledger(tmp_path, [{"attempt_id": "a1", "status": "failed_system"}])
        with pytest.raises(RuntimeError):
            check_attempt_allowed(path)

    def test_invalid_infrastructure_no_auto_rerun(self, tmp_path):
        path = self._ledger(tmp_path, [
            {"attempt_id": "a1", "status": "invalid_infrastructure"}])
        with pytest.raises(RuntimeError):
            check_attempt_allowed(path)

    def test_existing_prepared_rejects(self, tmp_path):
        path = self._ledger(tmp_path, [{"attempt_id": "a1", "status": "prepared"}])
        with pytest.raises(RuntimeError):
            check_attempt_allowed(path)
        with pytest.raises(RuntimeError):
            atomic_create_attempt(path, _holdout_config(tmp_path))

    def test_consecutive_create_second_rejects(self, tmp_path):
        path = str(tmp_path / "ledger.json")
        atomic_create_attempt(path, _holdout_config(tmp_path))
        with pytest.raises(RuntimeError):
            atomic_create_attempt(path, _holdout_config(tmp_path))
        ledger = read_attempt_ledger(path)
        assert len(ledger["attempts"]) == 1

    def test_unknown_status_fail_closed(self, tmp_path):
        path = self._ledger(tmp_path, [{"attempt_id": "a1", "status": "bogus"}])
        with pytest.raises(ValueError):
            read_attempt_ledger(path)

    def test_malformed_attempt_fail_closed(self, tmp_path):
        path = self._ledger(tmp_path, [{"attempt_id": "a1"}], strict=False)
        with pytest.raises(ValueError):
            read_attempt_ledger(path)

    def test_attempts_not_list_fail_closed(self, tmp_path):
        p = tmp_path / "ledger.json"
        p.write_text(json.dumps({"schema_version": "holdout_attempt_ledger_v1",
                                 "attempts": "not_a_list"}, ensure_ascii=False),
                     encoding="utf-8")
        with pytest.raises(ValueError):
            read_attempt_ledger(str(p))

    def test_existing_exclusive_lock_rejects(self, tmp_path):
        path = str(tmp_path / "ledger.json")
        Path(path + ".lock").write_text("", encoding="utf-8")
        with pytest.raises(RuntimeError):
            atomic_create_attempt(path, _holdout_config(tmp_path))

    def test_started_at_real_utc(self, tmp_path):
        from datetime import datetime
        path = str(tmp_path / "ledger.json")
        attempt = atomic_create_attempt(path, _holdout_config(tmp_path))
        parsed = datetime.fromisoformat(attempt["started_at"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() is not None

    def test_empty_ledger_allows_first_attempt(self, tmp_path):
        path = str(tmp_path / "ledger.json")
        check_attempt_allowed(path)
        cfg = _holdout_config(tmp_path)
        attempt = atomic_create_attempt(path, cfg)
        assert attempt["status"] == "prepared"
        assert attempt["gate3_system_freeze_id"] == "2ec11a69b173"
        assert attempt["actual_execution_source_commit"] == DEV_COMMIT
        assert attempt["started_at"] is not None
        ledger = read_attempt_ledger(path)
        assert len(ledger["attempts"]) == 1
        assert not Path(path + ".lock").exists()  # 正常完成释放锁


class TestGoldIsolation:
    def test_generation_case_strips_secret_sentinel(self, tmp_path):
        from evaluation.gate3.e2e import GenerationCase, load_generation_cases
        import dataclasses
        sentinel = "SECRET_GOLD_SENTINEL_09A"
        dev = tmp_path / "h.jsonl"
        dev.write_text(json.dumps({
            "schema_version": "gate3_case_v1", "case_id": "h1",
            "query": "holdout question",
            "query_type": "fact", "answerability": "answerable",
            "decomposition_expected": "forbidden", "retrieval_required": True,
            "evidence_obligations": [{"obligation_id": "o1", "description": sentinel,
                                      "relevant_files": ["a.md"], "required": True}],
            "relevant_files": ["a.md"], "tags": ["fact"],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        cases = load_generation_cases(str(dev))
        assert len(cases) == 1
        gc = cases[0]
        blob = json.dumps({f.name: getattr(gc, f.name)
                           for f in dataclasses.fields(GenerationCase)},
                          ensure_ascii=False)
        assert sentinel not in blob
        assert gc.case_id == "h1" and gc.query == "holdout question"


class TestDevIdentityCompatibility:
    def test_dev_run_id_and_identity_unchanged(self):
        # 09A e2e.py 只做 split-agnostic 抽取，Gate3E2EConfig 身份不变（锁定向量）。
        cfg = _dev_config()
        assert cfg.run_id == "9df3c2ea44c8"
        canon = json.dumps(cfg.identity_payload(), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert hashlib.sha256(canon).hexdigest() == (
            "9df3c2ea44c8dfaeb950d07cfaa447b89a12c901c5e6be4aaed64538da344d99"
        )


# ---------------------------------------------------------------------------
# 09B：正式执行器（synthetic sealed + fake chain）
# ---------------------------------------------------------------------------


def _synthetic_holdout_text():
    lines = []
    for i in range(1, 13):
        cid = f"h{i:02d}"
        lines.append(json.dumps({
            "schema_version": "gate3_case_v1", "case_id": cid,
            "query": f"question {cid}",
            "query_type": "fact", "answerability": "answerable",
            "decomposition_expected": "forbidden", "retrieval_required": True,
            "evidence_obligations": [{
                "obligation_id": "o1",
                "description": "SECRET_GOLD_SENTINEL_09B" + cid,
                "relevant_files": ["a.md"], "required": True,
            }],
            "relevant_files": ["a.md"], "tags": ["fact"],
        }, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def _synthetic_manifest(holdout_text, eval_id="79a6bc0814a3", case_count=12,
                        sha=None):
    return {
        "schema_version": "gate3_holdout_private_manifest_v1",
        "gate3_dataset_freeze_id": "257fa0d0a6d6",
        "holdout_evaluation_set_id": eval_id,
        "case_count": case_count,
        "holdout_jsonl_sha256": sha or hashlib.sha256(
            holdout_text.encode("utf-8")).hexdigest(),
        "holdout_jsonl_file": "gate3_holdout_v1.jsonl",
    }


def _fake_gen(cases, formal_config, out_dir):
    return {"case_count": len(cases), "cases": [c.case_id for c in cases],
            "formal_holdout_run_id": formal_config.formal_holdout_run_id}


def _fake_gen_sentinel(cases, formal_config, out_dir):
    for c in cases:
        assert "SECRET_GOLD_SENTINEL" not in c.case_id
        assert "SECRET_GOLD_SENTINEL" not in c.query
    return _fake_gen(cases, formal_config, out_dir)


def _fake_gen_failures(cases, formal_config, out_dir):
    return {"case_count": len(cases),
            "failed_cases": [c.case_id for c in cases[:2]],
            "failed_count": 2}


class TestExecutor:
    def _run(self, tmp_path, *, sealed_read_fn, run_generation_fn=_fake_gen,
             output_root=None, ledger_path=None, run_evaluation_fn=None):
        return execute_holdout(
            _holdout_config(tmp_path),
            repo=str(_clean_git_repo(tmp_path)),
            freeze_json_path=_freeze(tmp_path),
            output_root=str(output_root or tmp_path / "out"),
            attempt_ledger_path=str(ledger_path or tmp_path / "ledger.json"),
            sealed_read_fn=sealed_read_fn,
            run_generation_fn=run_generation_fn,
            run_evaluation_fn=run_evaluation_fn,
        )

    def test_attempt_created_before_sealed_read(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"

        def sealed_read():
            # 执行到 sealed 读取时，attempt 必须已创建为 prepared
            l = read_attempt_ledger(str(ledger))
            assert len(l["attempts"]) == 1
            assert l["attempts"][0]["status"] == "prepared"
            return manifest, holdout_text

        result = self._run(tmp_path, sealed_read_fn=sealed_read,
                           ledger_path=ledger)
        assert result["status"] == "completed"
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == "completed"

    def test_holdout_sha_mismatch_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text, sha="ab" * 32)
        ledger = tmp_path / "ledger.json"
        with pytest.raises(HoldoutInfrastructureFailure):
            self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      ledger_path=ledger)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"

    def test_evaluation_set_id_mismatch_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text, eval_id="0" * 12)
        with pytest.raises(HoldoutInfrastructureFailure):
            self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))

    def test_case_count_mismatch_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text, case_count=11)
        with pytest.raises(HoldoutInfrastructureFailure):
            self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))

    def test_duplicate_case_id_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        holdout_text += json.dumps({
            "schema_version": "gate3_case_v1", "case_id": "h01",
            "query": "dup", "query_type": "fact", "answerability": "answerable",
            "decomposition_expected": "forbidden", "retrieval_required": True,
            "evidence_obligations": [], "relevant_files": ["a.md"],
            "tags": ["fact"],
        }, ensure_ascii=False) + "\n"
        manifest = _synthetic_manifest(holdout_text, case_count=13)
        with pytest.raises(HoldoutInfrastructureFailure):
            self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))

    def test_generation_sentinel_not_leak(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        result = self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                           run_generation_fn=_fake_gen_sentinel)
        assert result["status"] == "completed"

    def test_formal_run_id_includes_holdout_sha(self, tmp_path):
        from dataclasses import replace
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        result = self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))
        formal = replace(_holdout_config(tmp_path),
                         holdout_jsonl_sha256=result["holdout_jsonl_sha256"])
        assert result["formal_holdout_run_id"] == formal.formal_holdout_run_id
        assert result["formal_holdout_run_id"] != result["preflight_holdout_run_id"]
        assert "holdout_jsonl_sha256" in formal.formal_identity_payload()

    def test_actual_source_commit_in_identity(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        result = self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))
        assert len(result["actual_execution_source_commit"]) == 40

    def test_freeze_id_in_identity(self, tmp_path):
        cfg = _holdout_config(tmp_path)
        assert cfg.identity_payload()["gate3_system_freeze_id"] == "2ec11a69b173"

    def test_output_not_overwritable(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"
        with pytest.raises(FileExistsError):
            self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      output_root=out, ledger_path=ledger)
        assert not ledger.exists()

    def test_system_case_failure_still_completed(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"
        result = self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                           run_generation_fn=_fake_gen_failures,
                           ledger_path=ledger)
        assert result["status"] == "completed"
        assert result["generation_output"]["failed_count"] == 2
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == "completed"

    def test_infrastructure_exception_terminal_state(self, tmp_path):
        ledger = tmp_path / "ledger.json"

        def boom():
            raise HoldoutInfrastructureFailure("manifest 损坏")

        with pytest.raises(HoldoutInfrastructureFailure):
            self._run(tmp_path, sealed_read_fn=boom, ledger_path=ledger)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"
        with pytest.raises(RuntimeError):
            self._run(tmp_path, sealed_read_fn=boom, ledger_path=ledger)

    def test_second_execution_after_terminal_rejected(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"
        self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                  ledger_path=ledger)
        with pytest.raises(RuntimeError):
            self._run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      ledger_path=ledger)
