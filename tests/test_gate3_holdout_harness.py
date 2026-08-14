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
    assert_no_forbidden_overrides,
    atomic_create_attempt,
    build_holdout_config_from_freeze,
    check_attempt_allowed,
    preflight_holdout,
    read_attempt_ledger,
    validate_frozen_knobs,
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
            "attempts": [{"attempt_id": "x", "status": "completed"}],
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
    def _ledger(self, tmp_path, attempts):
        p = tmp_path / "ledger.json"
        p.write_text(json.dumps({
            "schema_version": "holdout_attempt_ledger_v1",
            "attempts": attempts,
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

    def test_empty_ledger_allows_first_attempt(self, tmp_path):
        path = str(tmp_path / "ledger.json")
        check_attempt_allowed(path)
        cfg = _holdout_config(tmp_path)
        attempt = atomic_create_attempt(path, cfg)
        assert attempt["status"] == "prepared"
        assert attempt["gate3_system_freeze_id"] == "2ec11a69b173"
        assert attempt["actual_execution_source_commit"] == DEV_COMMIT
        ledger = read_attempt_ledger(path)
        assert len(ledger["attempts"]) == 1


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
