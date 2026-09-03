"""Provider-free contract tests for ARCH-INTEGRATION-11B."""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
)
from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    TARGET_PROJECT_COMMIT,
    HoldoutExecutionDenied,
    load_cases,
    validate_protocol_manifest,
)
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROVIDER,
    FROZEN_PROTOCOL_SHA,
    REPO_ROOT,
    RunnerPreflightError,
    safe_artifact,
)
from evaluation.integration_v7.runner_worker import (
    UNIFIED_DECISION_PROMPT_SELECTOR,
    UNIFIED_V2_DECISION_PROMPT_SELECTOR,
    _select_decision_prompt_profile,
)
from evaluation.integration_v7.unified_v2_candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_RUNTIME_LABEL,
    CANDIDATE_SYSTEM_LABEL,
    DECISION_PROMPT_PROFILE_SELECTOR,
    DEFAULT_OUTPUT_DIR,
    LEGACY_DEV_RESULTS_DIR,
    PREVIOUS_CANDIDATE_RESULTS_DIRS,
    UnifiedV2CandidateRunConfig,
    _assert_independent_output,
    build_unified_v2_candidate_manifest,
    build_unified_v2_candidate_run_plan,
    build_unified_v2_candidate_worker_job,
    run_unified_v2_candidate_dev,
    validate_unified_v2_candidate_checkouts,
    validate_unified_v2_candidate_identities,
)


def _cases(count: int = EXPECTED_CASE_COUNTS[DEV_SPLIT]) -> list[dict]:
    return [
        {
            "case_id": f"v7d{index:03d}",
            "split": DEV_SPLIT,
            "task_family": "knowledge_only",
            "question": f"question {index}",
            "conversation_context": [],
        }
        for index in range(1, count + 1)
    ]


def test_unified_v2_plan_is_exactly_18_dev_runs_and_holdout_is_denied():
    plan = build_unified_v2_candidate_run_plan(_cases())
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert {item["system"] for item in plan} == {CANDIDATE_SYSTEM_LABEL}
    assert {item["worker_system"] for item in plan} == {"B"}
    assert {item["decision_prompt_profile_selector"] for item in plan} == {
        DECISION_PROMPT_PROFILE_SELECTOR
    }
    assert {item["decision_prompt_profile"] for item in plan} == {
        ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version
    }
    with pytest.raises(HoldoutExecutionDenied):
        build_unified_v2_candidate_run_plan(_cases(), HOLDOUT_SPLIT)


def test_candidate_job_binds_unified_v2_selector_and_keeps_checkouts_separate():
    case = _cases()[0]
    item = build_unified_v2_candidate_run_plan(_cases())[0]
    job = build_unified_v2_candidate_worker_job(
        case,
        plan_item=item,
        candidate_root=Path("runtime_candidate"),
        target_root=Path("target_project"),
        corpus_root=Path("corpus"),
    )
    assert job["system"] == "B"
    assert job["system_root"] == "runtime_candidate"
    assert job["target_root"] == "target_project"
    assert job["decision_prompt_profile_selector"] == DECISION_PROMPT_PROFILE_SELECTOR
    assert item["decision_prompt_sha256"] == ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256
    validate_unified_v2_candidate_checkouts(
        Path("runtime_candidate"),
        Path("target_project"),
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
    )
    with pytest.raises(RunnerPreflightError):
        validate_unified_v2_candidate_checkouts(
            Path("same"),
            Path("same"),
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
        )


def test_worker_selector_identity_matrix_is_fail_closed_and_does_not_drift():
    assert _select_decision_prompt_profile({"system": "B"}) is ENGINEERING_DECISION_PROMPT_V2_PROFILE
    assert _select_decision_prompt_profile({"system": "A"}) is ENGINEERING_DECISION_PROMPT_V2_PROFILE
    assert _select_decision_prompt_profile(
        {"system": "B", "decision_prompt_profile_selector": UNIFIED_DECISION_PROMPT_SELECTOR}
    ) is ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
    assert _select_decision_prompt_profile(
        {"system": "B", "decision_prompt_profile_selector": UNIFIED_V2_DECISION_PROMPT_SELECTOR}
    ) is ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE
    assert UNIFIED_V2_DECISION_PROMPT_SELECTOR == DECISION_PROMPT_PROFILE_SELECTOR
    with pytest.raises(ValueError):
        _select_decision_prompt_profile(
            {"system": "B", "decision_prompt_profile_selector": "unknown"}
        )
    with pytest.raises(ValueError):
        _select_decision_prompt_profile(
            {"system": "A", "decision_prompt_profile_selector": UNIFIED_V2_DECISION_PROMPT_SELECTOR}
        )


def test_unified_v2_selector_reimports_profile_from_candidate_checkout(tmp_path):
    """Exercise the same bootstrap used by the worker against candidate code."""

    candidate_root = tmp_path / "candidate"
    add = subprocess.run(
        ["git", "worktree", "add", "--detach", str(candidate_root), CANDIDATE_RUNTIME_COMMIT],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert add.returncode == 0, add.stderr
    try:
        worker_path = REPO_ROOT / "evaluation" / "integration_v7" / "runner_worker.py"
        probe = """
import importlib.util
import json
import sys
from pathlib import Path

worker_path = Path(sys.argv[1])
candidate_root = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("current_eval_worker", worker_path)
worker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(worker)
worker._bootstrap_system_imports(candidate_root)
profile = worker._select_decision_prompt_profile({
    "system": "B",
    "decision_prompt_profile_selector": "engineering_agent_decision_prompt_unified_v2",
})
print(json.dumps({"version": profile.version, "sha256": profile.sha256}))
"""
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(candidate_root)
        result = subprocess.run(
            [sys.executable, "-c", probe, str(worker_path), str(candidate_root)],
            cwd=candidate_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        identity = json.loads(result.stdout)
        assert identity == {
            "version": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version,
            "sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256,
        }
    finally:
        removed = subprocess.run(
            ["git", "worktree", "remove", "--force", str(candidate_root)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert removed.returncode == 0, removed.stderr


def test_all_previous_result_directories_are_protected_and_fresh_output_is_independent(tmp_path):
    protected = (LEGACY_DEV_RESULTS_DIR,) + PREVIOUS_CANDIDATE_RESULTS_DIRS
    for result_dir in protected:
        with pytest.raises(RunnerPreflightError):
            _assert_independent_output(result_dir)
    fresh = tmp_path / "dev_candidate_d001_v1"
    _assert_independent_output(fresh)
    assert DEFAULT_OUTPUT_DIR.resolve() not in {path.resolve() for path in protected}


def test_manifest_records_candidate_v2_target_corpus_protocol_dev_and_no_holdout(tmp_path):
    protocol = validate_protocol_manifest()
    plan = build_unified_v2_candidate_run_plan(_cases())
    manifest = build_unified_v2_candidate_manifest(
        manifest=protocol,
        config=UnifiedV2CandidateRunConfig(
            corpus_checkout=Path("corpus"),
            output_dir=tmp_path / "dev_candidate_d001_v1",
            provider=FROZEN_PROVIDER,
            model=FROZEN_MODEL,
        ),
        plan=plan,
        raw_runs=[],
        corpus_identity=protocol["corpus_identity"],
        timestamp="20260903T000000Z",
    )
    candidate = manifest["candidate_runtime"]
    assert candidate["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert candidate["system_identity"] == CANDIDATE_SYSTEM_LABEL
    assert candidate["decision_prompt_profile"] == ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version
    assert candidate["decision_prompt_sha256"] == ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256
    assert manifest["target_project"]["source_sha"] == TARGET_PROJECT_COMMIT
    assert manifest["corpus_identity"]["source_commit"] == protocol["corpus_identity"]["source_commit"]
    assert manifest["protocol"]["sha256"] == FROZEN_PROTOCOL_SHA
    assert manifest["dataset"] == {
        "split": DEV_SPLIT,
        "case_count": EXPECTED_CASE_COUNTS[DEV_SPLIT],
        "sha256": protocol["datasets"][DEV_SPLIT]["sha256"],
    }
    assert manifest["expected_candidate_runs"] == 18
    assert manifest["holdout"] == "NOT_RUN / DENY"
    assert manifest["frozen_system_identity_preserved"]["system_a_08b"] == "not executed"
    assert manifest["automatic_metrics_only"] is True
    assert "evaluation/integration_v7/results/dev_v1" in manifest["protected_result_directories"]
    assert "evaluation/integration_v7/results/dev_candidate_0abdb_v1" in manifest[
        "protected_result_directories"
    ]


def test_candidate_identity_validation_requires_v2_profile_and_frozen_bindings():
    validate_unified_v2_candidate_identities(
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
        corpus_head=CORPUS_SOURCE_COMMIT,
        protocol_sha=FROZEN_PROTOCOL_SHA,
        prompt_profile_version=ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version,
        prompt_profile_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256,
    )
    with pytest.raises(RunnerPreflightError):
        validate_unified_v2_candidate_identities(
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
            corpus_head=CORPUS_SOURCE_COMMIT,
            protocol_sha=FROZEN_PROTOCOL_SHA,
            prompt_profile_version=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
            prompt_profile_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
        )


def test_safe_artifact_and_runner_are_no_retry_no_holdout_automatic_only():
    safe = safe_artifact({"answer": r"C:\private\repo sk-123456789012345"})
    assert "C:\\private" not in repr(safe)
    assert "sk-123456789012345" not in repr(safe)
    with pytest.raises(RunnerPreflightError):
        safe_artifact({"raw_provider_response": "must not serialize"})

    source = inspect.getsource(run_unified_v2_candidate_dev)
    assert source.count("_invoke_unified_v2_candidate_worker(") == 1
    assert source.count("for item in plan:") == 1
    assert "HOLDOUT_DATASET_PATH" not in source
    assert "system_a" not in source.lower()


def test_runner_uses_frozen_dataset_contract_without_redefining_dev_or_target_sha():
    source = inspect.getsource(run_unified_v2_candidate_dev)
    module_source = Path(
        "evaluation/integration_v7/unified_v2_candidate_runner.py"
    ).read_text(encoding="utf-8")
    cases = load_cases(Path("evaluation/integration_v7/integration_dev_v1.jsonl"))
    assert len(cases) == EXPECTED_CASE_COUNTS[DEV_SPLIT]
    assert "integration_dev_v1.jsonl" not in source
    assert "385b7795eafde7c114efc382" not in module_source
    assert "EXPECTED_DEV_DATASET_SHA" not in module_source
