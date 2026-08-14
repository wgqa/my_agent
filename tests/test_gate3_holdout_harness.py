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
import types
from pathlib import Path

import pytest

from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.e2e import (
    GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    Gate3E2EConfig,
)
from evaluation.gate3.holdout import (
    EXPECTED_HOLDOUT_JSONL_SHA256,
    EXPECTED_PRIVATE_MANIFEST_SHA256,
    HoldoutInfrastructureFailure,
    _parse_generation_cases_from_holdout,
    assert_no_forbidden_overrides,
    atomic_create_attempt,
    bind_attempt_formal_identity,
    build_holdout_config_from_freeze,
    check_attempt_allowed,
    execute_holdout,
    preflight_holdout,
    read_attempt_ledger,
    read_real_sealed_inputs,
    run_holdout_evaluation,
    run_holdout_generation,
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


def _exec_run(tmp_path, *, sealed_read_fn, run_generation_fn=_fake_gen,
              output_root=None, ledger_path=None, run_evaluation_fn=None):
    """TestExecutor / TestRealWiring 共用：以真实 clean-repo HEAD 绑定 config 后执行。"""
    repo = _clean_git_repo(tmp_path)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    return execute_holdout(
        _holdout_config(tmp_path, actual_commit=head),
        repo=str(repo),
        freeze_json_path=_freeze(tmp_path),
        output_root=str(output_root or tmp_path / "out"),
        attempt_ledger_path=str(ledger_path or tmp_path / "ledger.json"),
        sealed_read_fn=sealed_read_fn,
        run_generation_fn=run_generation_fn,
        run_evaluation_fn=run_evaluation_fn,
    )


class TestExecutor:
    def _run(self, tmp_path, *, sealed_read_fn, run_generation_fn=_fake_gen,
             output_root=None, ledger_path=None, run_evaluation_fn=None):
        return _exec_run(
            tmp_path, sealed_read_fn=sealed_read_fn,
            run_generation_fn=run_generation_fn, output_root=output_root,
            ledger_path=ledger_path, run_evaluation_fn=run_evaluation_fn,
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

        result = _exec_run(tmp_path, sealed_read_fn=sealed_read,
                           ledger_path=ledger)
        assert result["status"] == "completed"
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == "completed"

    def test_holdout_sha_mismatch_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text, sha="ab" * 32)
        ledger = tmp_path / "ledger.json"
        with pytest.raises(HoldoutInfrastructureFailure):
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      ledger_path=ledger)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"

    def test_evaluation_set_id_mismatch_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text, eval_id="0" * 12)
        with pytest.raises(HoldoutInfrastructureFailure):
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))

    def test_case_count_mismatch_fails(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text, case_count=11)
        with pytest.raises(HoldoutInfrastructureFailure):
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))

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
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))

    def test_generation_sentinel_not_leak(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        result = _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                           run_generation_fn=_fake_gen_sentinel)
        assert result["status"] == "completed"

    def test_formal_run_id_includes_holdout_sha(self, tmp_path):
        from dataclasses import replace
        repo = _clean_git_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        result = _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))
        formal = replace(_holdout_config(tmp_path, actual_commit=head),
                         holdout_jsonl_sha256=result["holdout_jsonl_sha256"])
        assert result["formal_holdout_run_id"] == formal.formal_holdout_run_id
        assert result["formal_holdout_run_id"] != result["preflight_holdout_run_id"]
        assert "holdout_jsonl_sha256" in formal.formal_identity_payload()

    def test_actual_source_commit_in_identity(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        result = _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text))
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
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      output_root=out, ledger_path=ledger)
        assert not ledger.exists()

    def test_system_case_failure_still_completed(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"
        result = _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
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
            _exec_run(tmp_path, sealed_read_fn=boom, ledger_path=ledger)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"
        with pytest.raises(RuntimeError):
            _exec_run(tmp_path, sealed_read_fn=boom, ledger_path=ledger)

    def test_second_execution_after_terminal_rejected(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"
        _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                  ledger_path=ledger)
        with pytest.raises(RuntimeError):
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      ledger_path=ledger)


# ---------------------------------------------------------------------------
# 09B-R1：真实 wiring（synthetic sealed + fake chain 写全 8 个正式 Artifact）
# ---------------------------------------------------------------------------


def _fake_gen_artifacts(cases, config, out_dir):
    """fake 生成链：真实落盘 4 个 generation Artifact（不含任何 Gold）。"""
    out = Path(out_dir)
    out.mkdir(parents=True)
    run_cfg = config.to_dict()
    run_cfg["formal_holdout_run_id"] = config.formal_holdout_run_id
    run_cfg["holdout_jsonl_sha256"] = config.holdout_jsonl_sha256
    (out / "run_config.json").write_text(
        json.dumps(run_cfg, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (out / "index_manifest.json").write_text(json.dumps({
        "schema_version": "gate3_e2e_index_manifest_v1",
        "corpus_id": "x", "index_sha256": "ab" * 32,
        "corpus_entries": [], "index_entries": [],
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    case_lines = "\n".join(json.dumps({
        "case_id": c.case_id, "query": c.query, "status": "completed",
        "error_code": None, "plan_id": "x" * 12,
        "plan": {"query_type": "fact", "action": "direct",
                 "reason_code": None, "subquery_count": 0},
        "route": "direct", "retrieval_call_count": 1,
        "candidate_canonical_paths": [], "retrieved_canonical_paths": [],
        "evidence_count": 1, "fallback_used": False, "failure_code": None,
        "answer": "synthetic answer [C1]", "cited_citation_ids": [1],
        "evidence_citation_ids": [1],
    }, ensure_ascii=False) for c in cases)
    (out / "case_results.jsonl").write_text(case_lines + "\n", encoding="utf-8")
    cited_lines = "\n".join(json.dumps({
        "case_id": c.case_id,
        "items": [{"citation_id": "[C1]", "source_name": "s.md",
                   "canonical_path": "s.md", "content": "synthetic evidence"}],
    }, ensure_ascii=False) for c in cases)
    (out / "cited_evidence.jsonl").write_text(cited_lines + "\n", encoding="utf-8")
    return {"case_count": len(cases),
            "formal_holdout_run_id": config.formal_holdout_run_id}


def _fake_eval_artifacts(gen_output, config, out_dir):
    """fake evaluation：真实落盘 4 个 evaluation Artifact。"""
    out = Path(out_dir)
    n = gen_output["case_count"]
    judgments = "\n".join(json.dumps({
        "case_id": f"h{i:02d}",
        "judge_output": {"judge_status": "ok",
                         "obligation_coverage": {"o1": "covered"},
                         "unsupported_material_claims": []},
    }, ensure_ascii=False) for i in range(1, n + 1))
    (out / "answer_judgments.jsonl").write_text(judgments + "\n", encoding="utf-8")
    metrics = {"schema_version": "gate3_e2e_metrics_v1",
               "deterministic": {}, "answer": {}, "case_count": n}
    (out / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (out / "comparison_report.md").write_text("# Holdout report\n", encoding="utf-8")
    result = {
        "schema_version": "gate3_e2e_result_v1",
        "formal_holdout_run_id": config.formal_holdout_run_id,
        "holdout_run_id": config.holdout_run_id,
        "config": config.to_dict(),
        "metrics": metrics,
    }
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {"case_count": n}


class TestRealWiring:
    def test_read_real_sealed_inputs_only_config_paths(self, tmp_path):
        from dataclasses import replace
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        sealed = tmp_path / "sealed"
        sealed.mkdir()
        (sealed / "manifest.json").write_bytes(
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        (sealed / "holdout.jsonl").write_bytes(holdout_text.encode("utf-8"))
        (sealed / "decoy.json").write_text("not referenced", encoding="utf-8")
        manifest_sha = hashlib.sha256(
            (sealed / "manifest.json").read_bytes()).hexdigest()
        holdout_sha = hashlib.sha256(holdout_text.encode("utf-8")).hexdigest()
        cfg = replace(_holdout_config(tmp_path),
                      holdout_jsonl_path=str(sealed / "holdout.jsonl"),
                      private_manifest_path=str(sealed / "manifest.json"),
                      expected_private_manifest_sha256=manifest_sha,
                      expected_holdout_jsonl_sha256=holdout_sha)
        got_manifest, got_text = read_real_sealed_inputs(cfg)
        assert got_manifest == manifest
        assert got_text == holdout_text

    def test_read_real_sealed_inputs_missing_file_infra(self, tmp_path):
        from dataclasses import replace
        cfg = replace(_holdout_config(tmp_path),
                      holdout_jsonl_path=str(tmp_path / "no.jsonl"),
                      private_manifest_path=str(tmp_path / "no.json"))
        with pytest.raises(HoldoutInfrastructureFailure):
            read_real_sealed_inputs(cfg)

    def test_full_fake_integration_8_artifacts_no_gold_leak(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"
        out = tmp_path / "out"
        result = _exec_run(
            tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
            run_generation_fn=_fake_gen_artifacts,
            run_evaluation_fn=_fake_eval_artifacts,
            output_root=out, ledger_path=ledger,
        )
        assert result["status"] == "completed"
        expected = ("run_config.json", "index_manifest.json", "case_results.jsonl",
                    "cited_evidence.jsonl", "answer_judgments.jsonl",
                    "metrics.json", "comparison_report.md", "result.json")
        for name in expected:
            assert (out / name).is_file(), f"缺少正式 Artifact: {name}"
        gen_blob = "\n".join((out / n).read_text("utf-8") for n in
                             ("run_config.json", "index_manifest.json",
                              "case_results.jsonl", "cited_evidence.jsonl"))
        assert "SECRET_GOLD_SENTINEL" not in gen_blob
        run_cfg = json.loads((out / "run_config.json").read_text("utf-8"))
        res = json.loads((out / "result.json").read_text("utf-8"))
        assert run_cfg["formal_holdout_run_id"] == result["formal_holdout_run_id"]
        assert run_cfg["holdout_jsonl_sha256"] == result["holdout_jsonl_sha256"]
        assert res["formal_holdout_run_id"] == result["formal_holdout_run_id"]
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == "completed"

    def test_wrong_actual_head_no_attempt(self, tmp_path):
        repo = _clean_git_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        wrong_head = ("f" if head[0] != "f" else "a") + head[1:]
        ledger = tmp_path / "ledger.json"
        out = tmp_path / "out"
        with pytest.raises(RuntimeError):
            execute_holdout(
                _holdout_config(tmp_path, actual_commit=wrong_head),
                repo=str(repo), freeze_json_path=_freeze(tmp_path),
                output_root=str(out), attempt_ledger_path=str(ledger),
                sealed_read_fn=lambda: (None, None), run_generation_fn=_fake_gen)
        assert not ledger.exists()
        assert not out.exists()

    def test_wrong_freeze_no_attempt(self, tmp_path):
        repo = _clean_git_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        bad = tmp_path / "bad_freeze.json"
        freeze = _freeze_json()
        freeze["gate3_system_freeze_id"] = "0" * 12
        bad.write_text(json.dumps(freeze, ensure_ascii=False), encoding="utf-8")
        ledger = tmp_path / "ledger.json"
        out = tmp_path / "out"
        with pytest.raises(ValueError):
            execute_holdout(
                _holdout_config(tmp_path, actual_commit=head),
                repo=str(repo), freeze_json_path=str(bad),
                output_root=str(out), attempt_ledger_path=str(ledger),
                sealed_read_fn=lambda: (None, None), run_generation_fn=_fake_gen)
        assert not ledger.exists()
        assert not out.exists()

    def test_manifest_wrong_dataset_freeze_invalid_infra(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        manifest["gate3_dataset_freeze_id"] = "0" * 12
        ledger = tmp_path / "ledger.json"
        with pytest.raises(HoldoutInfrastructureFailure):
            _exec_run(tmp_path, sealed_read_fn=lambda: (manifest, holdout_text),
                      ledger_path=ledger)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"

    def test_running_ledger_entry_binds_formal_identity(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        ledger = tmp_path / "ledger.json"

        def gen_checks_running(cases, config, out_dir):
            entry = read_attempt_ledger(str(ledger))["attempts"][0]
            assert entry["status"] == "running"
            assert entry.get("formal_holdout_run_id") == \
                config.formal_holdout_run_id
            assert entry.get("holdout_jsonl_sha256") == \
                config.holdout_jsonl_sha256
            return _fake_gen(cases, config, out_dir)

        result = _exec_run(tmp_path,
                           sealed_read_fn=lambda: (manifest, holdout_text),
                           run_generation_fn=gen_checks_running, ledger_path=ledger)
        assert result["status"] == "completed"
        entry = read_attempt_ledger(str(ledger))["attempts"][0]
        assert entry["status"] == "completed"
        assert entry["formal_holdout_run_id"] == result["formal_holdout_run_id"]

    def test_formal_identity_cannot_rebind(self, tmp_path):
        path = str(tmp_path / "ledger.json")
        cfg = _holdout_config(tmp_path)
        attempt = atomic_create_attempt(path, cfg)
        aid = attempt["attempt_id"]
        bind_attempt_formal_identity(path, aid, formal_holdout_run_id="a" * 12,
                                     holdout_jsonl_sha256="b" * 64)
        with pytest.raises(RuntimeError):
            bind_attempt_formal_identity(path, aid, formal_holdout_run_id="c" * 12,
                                         holdout_jsonl_sha256="d" * 64)

    def test_cli_execute_auth_missing_zero_sealed_read(self, tmp_path, monkeypatch):
        import scripts.run_gate3_e2e_holdout as cli
        monkeypatch.delenv("HOLDOUT_EXECUTION_AUTHORIZED", raising=False)
        calls = []

        def spy(config):
            calls.append(1)
            return read_real_sealed_inputs(config)

        monkeypatch.setattr(cli, "read_real_sealed_inputs", spy)
        out = tmp_path / "out"
        ledger = tmp_path / "ledger.json"
        args = [
            "--execute",
            "--repo", str(Path.cwd()),
            "--freeze-json", _freeze(tmp_path),
            "--holdout-jsonl", str(tmp_path / "no_such_holdout.jsonl"),
            "--private-manifest", str(tmp_path / "no_such_manifest.json"),
            "--frozen-index-manifest", "m.json",
            "--corpus-root", "c",
            "--output-root", str(out),
            "--attempt-ledger", str(ledger),
        ]
        with pytest.raises(SystemExit):
            cli.main(args)
        assert calls == []
        assert not out.exists()
        assert not ledger.exists()

    def test_cli_execute_wires_real_adapters(self, tmp_path, monkeypatch):
        import scripts.run_gate3_e2e_holdout as cli
        monkeypatch.setenv("HOLDOUT_EXECUTION_AUTHORIZED", "1")
        captured = {}

        def fake_execute(config, **kwargs):
            captured.update(kwargs)
            return {"status": "not_run", "formal_holdout_run_id": "a" * 12}

        monkeypatch.setattr(cli, "execute_holdout", fake_execute)
        out = tmp_path / "out"
        args = [
            "--execute",
            "--repo", str(Path.cwd()),
            "--freeze-json", _freeze(tmp_path),
            "--holdout-jsonl", str(tmp_path / "h.jsonl"),
            "--private-manifest", str(tmp_path / "p.json"),
            "--frozen-index-manifest", "m.json",
            "--corpus-root", "c",
            "--output-root", str(out),
            "--attempt-ledger", str(tmp_path / "l.json"),
        ]
        cli.main(args)
        assert captured.get("sealed_read_fn") is not None
        assert captured.get("run_generation_fn") is run_holdout_generation
        assert captured.get("run_evaluation_fn") is run_holdout_evaluation
        assert not out.exists()


# ---------------------------------------------------------------------------
# 09B-R2：FINAL-INTEGRITY（公开冻结 bytes 绑定 + evaluation SHA guard +
# zero-obligation judgment；全部 synthetic/public fixture）
# ---------------------------------------------------------------------------


def _obligation(oid, path="a.md"):
    return {"obligation_id": oid, "description": f"desc-{oid}",
            "relevant_files": [path], "required": True}


def _frozen_manifest(tmp_path, relative_paths):
    p = tmp_path / "index_manifest.json"
    p.write_text(json.dumps({
        "schema_version": "gate3_e2e_index_manifest_v1",
        "corpus_entries": [{"relative_path": r} for r in relative_paths],
    }, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _holdout_case_line(case_id, *, obligations, answerability="answerable"):
    """合法 gate3_case_v1 行（answerable 带 obligation；unanswerable 零 obligation）。"""
    if answerability == "answerable":
        query_type = "fact"
        retrieval_required = True
        relevant_files = sorted({p for o in obligations
                                 for p in o.get("relevant_files", [])})
    else:
        query_type = "unanswerable_or_no_retrieval"
        retrieval_required = (answerability == "unanswerable")
        relevant_files = []
    return json.dumps({
        "schema_version": "gate3_case_v1",
        "case_id": case_id,
        "query": f"question {case_id}",
        "query_type": query_type,
        "answerability": answerability,
        "decomposition_expected": "forbidden",
        "retrieval_required": retrieval_required,
        "evidence_obligations": obligations,
        "relevant_files": relevant_files,
        "tags": ["fact"],
    }, ensure_ascii=False)


def _build_eval_fixture(tmp_path, *, holdout_cases, records):
    """合成 corpus + frozen index manifest + holdout jsonl + run_dir 生成/eval Artifact。"""
    from dataclasses import replace
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("# a\ncontent-a\n", encoding="utf-8")
    manifest_path = _frozen_manifest(tmp_path, ["a.md"])
    holdout_lines = [
        _holdout_case_line(c["case_id"],
                           obligations=c.get("obligations", []),
                           answerability=c.get(
                               "answerability", "answerable"
                               if c.get("obligations") else "unanswerable"))
        for c in holdout_cases
    ]
    holdout_text = "\n".join(holdout_lines) + "\n"
    holdout_path = tmp_path / "holdout.jsonl"
    # write_bytes（不做换行翻译）：磁盘 bytes 与 holdout_sha 逐字节一致
    holdout_path.write_bytes(holdout_text.encode("utf-8"))

    run_dir = tmp_path / "run_dir"
    run_dir.mkdir()
    case_lines = []
    cited_lines = []
    for r in records:
        rec = {
            "case_id": r["case_id"], "query": f"question {r['case_id']}",
            "status": r.get("status", "completed"),
            "error_code": r.get("error_code"),
            "plan_id": "x" * 12,
            "plan": {"query_type": "fact", "action": "direct",
                     "reason_code": None, "subquery_count": 0},
            "route": "direct", "retrieval_call_count": 1,
            "candidate_canonical_paths": ["a.md"],
            "retrieved_canonical_paths": ["a.md"],
            "evidence_count": 1, "fallback_used": False,
            "failure_code": r.get("failure_code"),
            "answer": r.get("answer", ""),
            "cited_citation_ids": [1] if r.get("answer") else [],
            "evidence_citation_ids": [1],
        }
        case_lines.append(json.dumps(rec, ensure_ascii=False))
        cited_lines.append(json.dumps({"case_id": r["case_id"], "items": []},
                                      ensure_ascii=False))
    (run_dir / "case_results.jsonl").write_text(
        "\n".join(case_lines) + "\n", encoding="utf-8")
    (run_dir / "cited_evidence.jsonl").write_text(
        "\n".join(cited_lines) + "\n", encoding="utf-8")

    holdout_sha = hashlib.sha256(holdout_text.encode("utf-8")).hexdigest()
    config = replace(_holdout_config(tmp_path),
                     corpus_root=str(corpus),
                     frozen_index_manifest_path=manifest_path,
                     holdout_jsonl_path=str(holdout_path),
                     holdout_jsonl_sha256=holdout_sha,
                     holdout_case_count=len(holdout_cases))
    return config, run_dir, holdout_path


class _FakeJudgeClient:
    """AnswerJudge 注入的 fake client：返回固定 covered judge JSON。"""

    def __init__(self):
        self.calls = 0

    @property
    def chat(self):
        return _FakeChat(self)


class _FakeChat:
    def __init__(self, judge):
        self.completions = _FakeCompletions(judge)


class _FakeCompletions:
    def __init__(self, judge):
        self._judge = judge

    def create(self, **kwargs):
        self._judge.calls += 1
        content = ('{"obligation_coverage": {"o1": "covered"}, '
                   '"unsupported_material_claims": []}')
        return types.SimpleNamespace(choices=[
            types.SimpleNamespace(message=types.SimpleNamespace(content=content))])


class TestFinalIntegrity:
    def _real_read_config(self, tmp_path, holdout_text, manifest,
                          expected_holdout_sha=None, expected_manifest_sha=None,
                          actual_commit=DEV_COMMIT):
        """写入 synthetic sealed，构建 config（expected 冻结 SHA 可覆盖）。"""
        from dataclasses import replace
        sealed = tmp_path / "sealed"
        sealed.mkdir()
        (sealed / "holdout.jsonl").write_bytes(holdout_text.encode("utf-8"))
        (sealed / "manifest.json").write_bytes(
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        manifest_sha = hashlib.sha256(
            (sealed / "manifest.json").read_bytes()).hexdigest()
        holdout_sha = hashlib.sha256(holdout_text.encode("utf-8")).hexdigest()
        return replace(_holdout_config(tmp_path, actual_commit=actual_commit),
                       holdout_jsonl_path=str(sealed / "holdout.jsonl"),
                       private_manifest_path=str(sealed / "manifest.json"),
                       expected_private_manifest_sha256=(
                           expected_manifest_sha or manifest_sha),
                       expected_holdout_jsonl_sha256=(
                           expected_holdout_sha or holdout_sha))

    def _exec_repo(self, tmp_path):
        repo = _clean_git_repo(tmp_path)
        head = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        return repo, head

    def test_holdout_sha_mismatch_public_frozen_reject(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        repo, head = self._exec_repo(tmp_path)
        # manifest 与 holdout 自洽（expected manifest SHA = 实际），但 expected
        # holdout SHA 用公开冻结 00bfcac2（合成 ≠ 公开 → reject）
        cfg = self._real_read_config(
            tmp_path, holdout_text, manifest,
            expected_holdout_sha=EXPECTED_HOLDOUT_JSONL_SHA256,
            actual_commit=head)
        ledger = tmp_path / "ledger.json"
        with pytest.raises(HoldoutInfrastructureFailure):
            execute_holdout(cfg, repo=str(repo), freeze_json_path=_freeze(tmp_path),
                            output_root=str(tmp_path / "out"),
                            attempt_ledger_path=str(ledger),
                            sealed_read_fn=lambda: read_real_sealed_inputs(cfg),
                            run_generation_fn=_fake_gen)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"

    def test_private_manifest_raw_sha_mismatch_reject(self, tmp_path):
        holdout_text = _synthetic_holdout_text()
        manifest = _synthetic_manifest(holdout_text)
        repo, head = self._exec_repo(tmp_path)
        cfg = self._real_read_config(
            tmp_path, holdout_text, manifest,
            expected_manifest_sha=EXPECTED_PRIVATE_MANIFEST_SHA256,
            actual_commit=head)
        ledger = tmp_path / "ledger.json"
        with pytest.raises(HoldoutInfrastructureFailure):
            execute_holdout(cfg, repo=str(repo), freeze_json_path=_freeze(tmp_path),
                            output_root=str(tmp_path / "out"),
                            attempt_ledger_path=str(ledger),
                            sealed_read_fn=lambda: read_real_sealed_inputs(cfg),
                            run_generation_fn=_fake_gen)
        assert read_attempt_ledger(str(ledger))["attempts"][0]["status"] == \
            "invalid_infrastructure"

    def test_corpus_byte_change_rejects_no_attempt(self, tmp_path, monkeypatch):
        from dataclasses import replace
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-09br2-corpus")
        repo, head = self._exec_repo(tmp_path)
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "a.md").write_text("# a\ncontent-a\n", encoding="utf-8")
        (corpus / "b.md").write_text("# b\ncontent-b\n", encoding="utf-8")
        relative_paths = ["a.md", "b.md"]
        c0 = ExperimentCorpus.build(str(corpus), relative_paths)
        manifest_path = _frozen_manifest(tmp_path, relative_paths)
        # corpus 某文件改 1 byte → corpus_id 变化 → reject
        (corpus / "a.md").write_text("# a\ncontent-A\n", encoding="utf-8")
        cfg = replace(_holdout_config(tmp_path, actual_commit=head),
                      corpus_root=str(corpus),
                      frozen_index_manifest_path=manifest_path,
                      expected_corpus_id=c0.corpus_id,
                      expected_corpus_file_count=2)
        ledger = tmp_path / "ledger.json"
        out = tmp_path / "out"
        sealed_calls = []

        def spy():
            sealed_calls.append(1)
            return (None, None)

        with pytest.raises(RuntimeError):
            execute_holdout(cfg, repo=str(repo), freeze_json_path=_freeze(tmp_path),
                            output_root=str(out), attempt_ledger_path=str(ledger),
                            sealed_read_fn=spy,
                            run_generation_fn=run_holdout_generation)
        assert not ledger.exists()
        assert not out.exists()
        assert sealed_calls == []

    def test_corpus_file_count_mismatch_rejects(self, tmp_path, monkeypatch):
        from dataclasses import replace
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-09br2-count")
        repo, head = self._exec_repo(tmp_path)
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "a.md").write_text("# a\n", encoding="utf-8")
        # frozen manifest 列 3 个文件，但 expected_corpus_file_count=2
        manifest_path = _frozen_manifest(tmp_path, ["a.md", "b.md", "c.md"])
        cfg = replace(_holdout_config(tmp_path, actual_commit=head),
                      corpus_root=str(corpus),
                      frozen_index_manifest_path=manifest_path,
                      expected_corpus_id="870e5864df67",
                      expected_corpus_file_count=2)
        ledger = tmp_path / "ledger.json"
        out = tmp_path / "out"
        sealed_calls = []

        def spy():
            sealed_calls.append(1)
            return (None, None)

        with pytest.raises(RuntimeError):
            execute_holdout(cfg, repo=str(repo), freeze_json_path=_freeze(tmp_path),
                            output_root=str(out), attempt_ledger_path=str(ledger),
                            sealed_read_fn=spy,
                            run_generation_fn=run_holdout_generation)
        assert not ledger.exists()
        assert not out.exists()
        assert sealed_calls == []

    def test_missing_api_key_no_attempt_no_sealed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        repo, head = self._exec_repo(tmp_path)
        cfg = _holdout_config(tmp_path, actual_commit=head)
        ledger = tmp_path / "ledger.json"
        out = tmp_path / "out"
        sealed_calls = []

        def spy():
            sealed_calls.append(1)
            return (None, None)

        with pytest.raises(RuntimeError):
            execute_holdout(cfg, repo=str(repo), freeze_json_path=_freeze(tmp_path),
                            output_root=str(out), attempt_ledger_path=str(ledger),
                            sealed_read_fn=spy,
                            run_generation_fn=run_holdout_generation)
        assert not ledger.exists()
        assert not out.exists()
        assert sealed_calls == []

    def test_holdout_changed_between_gen_eval_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-09br2-eval")
        cases = [
            {"case_id": f"g3q5{i:02d}", "obligations": [_obligation("o1")],
             "status": "completed", "answer": "answer"}
            for i in range(1, 13)
        ]
        config, run_dir, holdout_path = _build_eval_fixture(
            tmp_path, holdout_cases=cases, records=cases)
        with holdout_path.open("a", encoding="utf-8") as f:
            f.write("\n")  # Generation 后 Holdout 被改动（多 1 字节）→ SHA guard
        with pytest.raises(HoldoutInfrastructureFailure):
            run_holdout_evaluation({}, config, str(run_dir),
                                   judge_client=_FakeJudgeClient())

    def test_evaluation_case_id_set_mismatch_rejects(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-09br2-eval")
        records = [
            {"case_id": f"g3q5{i:02d}", "obligations": [_obligation("o1")],
             "status": "completed", "answer": "answer"}
            for i in range(1, 13)
        ]
        # holdout 集合平移一位（数量一致但集合不同）→ reject
        holdout_cases = [
            {"case_id": f"g3q5{i:02d}", "obligations": [_obligation("o1")],
             "answerability": "answerable"}
            for i in range(2, 14)
        ]
        config, run_dir, _ = _build_eval_fixture(
            tmp_path, holdout_cases=holdout_cases, records=records)
        with pytest.raises(HoldoutInfrastructureFailure):
            run_holdout_evaluation({}, config, str(run_dir),
                                   judge_client=_FakeJudgeClient())

    def test_zero_obligation_judgment_not_required(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-09br2-eval")
        zero_case = {"case_id": "g3q599", "obligations": [],
                     "answerability": "unanswerable", "status": "completed",
                     "answer": "irrelevant"}
        answerable = [
            {"case_id": f"g3q5{i:02d}", "obligations": [_obligation("o1")],
             "status": "completed", "answer": "answer"}
            for i in range(1, 12)
        ]
        records = answerable + [zero_case]
        holdout_cases = [
            {"case_id": c["case_id"],
             "obligations": c.get("obligations", []),
             "answerability": c.get("answerability", "answerable"
                                    if c.get("obligations") else "unanswerable")}
            for c in records
        ]
        config, run_dir, _ = _build_eval_fixture(
            tmp_path, holdout_cases=holdout_cases, records=records)
        fake = _FakeJudgeClient()
        run_holdout_evaluation({}, config, str(run_dir), judge_client=fake)
        judgments = [json.loads(l) for l in
                     (run_dir / "answer_judgments.jsonl").read_text("utf-8").splitlines()
                     if l.strip()]
        by_case = {j["case_id"]: j for j in judgments}
        assert by_case["g3q599"]["judge_output"]["judge_status"] == "not_required"
        assert by_case["g3q599"]["judge_output"]["reason"] == "zero_obligation"
        assert fake.calls == 11  # zero-obligation 不调 Judge

    def test_answerable_no_answer_judgment_not_generated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-09br2-eval")
        no_answer = {"case_id": "g3q598", "obligations": [_obligation("o1")],
                     "status": "failed", "failure_code": "GENERATION_FAILED",
                     "error_code": "GENERATION_FAILED", "answer": ""}
        answerable = [
            {"case_id": f"g3q5{i:02d}", "obligations": [_obligation("o1")],
             "status": "completed", "answer": "answer"}
            for i in range(1, 12)
        ]
        records = answerable + [no_answer]
        holdout_cases = [
            {"case_id": c["case_id"], "obligations": c.get("obligations", []),
             "answerability": "answerable"}
            for c in records
        ]
        config, run_dir, _ = _build_eval_fixture(
            tmp_path, holdout_cases=holdout_cases, records=records)
        fake = _FakeJudgeClient()
        run_holdout_evaluation({}, config, str(run_dir), judge_client=fake)
        judgments = [json.loads(l) for l in
                     (run_dir / "answer_judgments.jsonl").read_text("utf-8").splitlines()
                     if l.strip()]
        by_case = {j["case_id"]: j for j in judgments}
        assert by_case["g3q598"]["judge_output"]["judge_status"] == "not_generated"
        assert fake.calls == 11
