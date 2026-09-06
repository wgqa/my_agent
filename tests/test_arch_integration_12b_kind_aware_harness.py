"""Provider-free contract tests for ARCH-INTEGRATION-12B."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
from core.tool_agent.default_tools import CODE_SEARCH_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_VERSION
from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    TARGET_PROJECT_COMMIT,
    HoldoutExecutionDenied,
    ProtocolViolation,
    load_protocol_manifest,
    validate_protocol_manifest,
)
from evaluation.integration_v7.kind_aware_candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_RUNTIME_LABEL,
    CANDIDATE_SYSTEM_LABEL,
    DECISION_PROMPT_PROFILE_SELECTOR,
    DEFAULT_OUTPUT_DIR,
    EXPECTED_ARTIFACT_KIND_VALUES,
    LEGACY_DEV_RESULTS_DIR,
    PREVIOUS_CANDIDATE_RESULTS_DIRS,
    KindAwareCandidateRunConfig,
    _assert_independent_output,
    _probe_candidate_contract,
    build_kind_aware_candidate_manifest,
    build_kind_aware_candidate_run_plan,
    build_kind_aware_candidate_worker_job,
    run_kind_aware_candidate_dev,
    validate_kind_aware_candidate_checkouts,
    validate_kind_aware_candidate_identities,
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
    _select_decision_prompt_profile,
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


def test_kind_aware_plan_is_exactly_18_dev_runs_and_holdout_is_denied():
    plan = build_kind_aware_candidate_run_plan(_cases())
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert {item["system"] for item in plan} == {CANDIDATE_SYSTEM_LABEL}
    assert {item["worker_system"] for item in plan} == {"B"}
    assert {item["runtime_variant"] for item in plan} == {CANDIDATE_RUNTIME_LABEL}
    assert {item["decision_prompt_profile_selector"] for item in plan} == {
        UNIFIED_DECISION_PROMPT_SELECTOR
    }
    assert {item["decision_prompt_profile"] for item in plan} == {
        ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version
    }
    with pytest.raises(HoldoutExecutionDenied):
        build_kind_aware_candidate_run_plan(_cases(), HOLDOUT_SPLIT)


def test_candidate_job_binds_unified_v1_and_separate_checkout_inputs():
    cases = _cases()
    item = build_kind_aware_candidate_run_plan(cases)[0]
    job = build_kind_aware_candidate_worker_job(
        cases[0],
        plan_item=item,
        candidate_root=Path("runtime_candidate"),
        target_root=Path("target_project"),
        corpus_root=Path("corpus"),
    )
    assert job["system"] == "B"
    assert job["system_root"] == "runtime_candidate"
    assert job["target_root"] == "target_project"
    assert job["decision_prompt_profile_selector"] == DECISION_PROMPT_PROFILE_SELECTOR
    assert item["decision_prompt_sha256"] == ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256
    validate_kind_aware_candidate_checkouts(
        Path("runtime_candidate"),
        Path("target_project"),
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
    )
    with pytest.raises(RunnerPreflightError):
        validate_kind_aware_candidate_checkouts(
            Path("same"),
            Path("same"),
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
        )


def test_candidate_checkout_probe_binds_unified_v1_and_code_search_v5():
    candidate_root = REPO_ROOT.parent / ".arch_eval_12b_test_candidate"
    add = subprocess.run(
        ["git", "worktree", "add", "--detach", str(candidate_root), CANDIDATE_RUNTIME_COMMIT],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert add.returncode == 0, add.stderr
    try:
        contract = _probe_candidate_contract(candidate_root)
        assert contract["prompt_profile"] == {
            "version": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
            "sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
        }
        assert contract["code_search"] == {
            "tool": "code_search",
            "version": "code_search_v5",
            "spec_version": "code_search_v5",
            "artifact_kind": {
                "optional": True,
                "values": list(EXPECTED_ARTIFACT_KIND_VALUES),
            },
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


def test_worker_selector_and_live_contract_are_unified_v1_and_v5():
    assert _select_decision_prompt_profile({"system": "B"}) is not ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
    assert _select_decision_prompt_profile(
        {"system": "B", "decision_prompt_profile_selector": UNIFIED_DECISION_PROMPT_SELECTOR}
    ) is ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
    assert CODE_SEARCH_VERSION == "code_search_v5"
    assert CODE_SEARCH_SPEC.version == "code_search_v5"
    artifact_kind = CODE_SEARCH_SPEC.input_schema["properties"]["artifact_kind"]
    assert "artifact_kind" not in CODE_SEARCH_SPEC.input_schema["required"]
    assert artifact_kind["enum"] == list(EXPECTED_ARTIFACT_KIND_VALUES)


def test_all_previous_result_directories_are_protected_and_fresh_output_is_independent(tmp_path):
    protected = (LEGACY_DEV_RESULTS_DIR,) + PREVIOUS_CANDIDATE_RESULTS_DIRS
    for result_dir in protected:
        with pytest.raises(RunnerPreflightError):
            _assert_independent_output(result_dir)
    fresh = tmp_path / "dev_candidate_6cd1_v1"
    _assert_independent_output(fresh)
    assert DEFAULT_OUTPUT_DIR.resolve() not in {path.resolve() for path in protected}


def test_manifest_records_candidate_repo_tool_and_frozen_bindings(tmp_path):
    protocol = validate_protocol_manifest()
    plan = build_kind_aware_candidate_run_plan(_cases())
    code_search_contract = {
        "tool": CODE_SEARCH_SPEC.name,
        "version": CODE_SEARCH_SPEC.version,
        "spec_version": CODE_SEARCH_SPEC.version,
        "artifact_kind": {
            "optional": "artifact_kind" not in CODE_SEARCH_SPEC.input_schema["required"],
            "values": list(CODE_SEARCH_SPEC.input_schema["properties"]["artifact_kind"]["enum"]),
        },
        "prompt_profile": {
            "version": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
            "sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
        },
    }
    manifest = build_kind_aware_candidate_manifest(
        manifest=protocol,
        config=KindAwareCandidateRunConfig(
            corpus_checkout=Path("corpus"),
            output_dir=tmp_path / "dev_candidate_6cd1_v1",
            provider=FROZEN_PROVIDER,
            model=FROZEN_MODEL,
        ),
        plan=plan,
        raw_runs=[],
        corpus_identity=protocol["corpus_identity"],
        code_search_contract=code_search_contract,
        timestamp="20260906T000000Z",
    )
    assert manifest["candidate_runtime"]["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert manifest["candidate_runtime"]["runtime_variant"] == CANDIDATE_RUNTIME_LABEL
    assert manifest["candidate_runtime"]["decision_prompt_profile"] == ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version
    assert manifest["candidate_runtime"]["decision_prompt_sha256"] == ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256
    assert manifest["target_project"]["source_sha"] == TARGET_PROJECT_COMMIT
    assert manifest["corpus_identity"]["source_commit"] == protocol["corpus_identity"]["source_commit"] == CORPUS_SOURCE_COMMIT
    assert manifest["protocol"]["sha256"] == FROZEN_PROTOCOL_SHA
    assert manifest["dataset"] == {
        "split": DEV_SPLIT,
        "case_count": EXPECTED_CASE_COUNTS[DEV_SPLIT],
        "sha256": protocol["datasets"][DEV_SPLIT]["sha256"],
    }
    assert manifest["repo_tool_contract"]["version"] == "code_search_v5"
    assert manifest["repo_tool_contract"]["artifact_kind"] == {
        "optional": True,
        "values": list(EXPECTED_ARTIFACT_KIND_VALUES),
    }
    assert manifest["expected_candidate_runs"] == 18
    assert manifest["holdout"] == "NOT_RUN / DENY"
    assert manifest["automatic_metrics_only"] is True
    assert set(manifest["protected_result_directories"]) == {
        "evaluation/integration_v7/results/dev_v1",
        "evaluation/integration_v7/results/dev_candidate_e374_v1",
        "evaluation/integration_v7/results/dev_candidate_0abdb_v1",
        "evaluation/integration_v7/results/dev_candidate_d001_v1",
    }


def test_candidate_identity_validation_requires_unified_v1_v5_and_frozen_bindings():
    validate_kind_aware_candidate_identities(
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
        corpus_head=CORPUS_SOURCE_COMMIT,
        protocol_sha=FROZEN_PROTOCOL_SHA,
        prompt_profile_version=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
        prompt_profile_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
        code_search_version="code_search_v5",
        artifact_kind_optional=True,
        artifact_kind_values=EXPECTED_ARTIFACT_KIND_VALUES,
    )
    with pytest.raises(RunnerPreflightError):
        validate_kind_aware_candidate_identities(
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
            corpus_head=CORPUS_SOURCE_COMMIT,
            protocol_sha=FROZEN_PROTOCOL_SHA,
            prompt_profile_version="engineering_agent_decision_prompt_unified_v2",
            prompt_profile_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
            code_search_version="code_search_v5",
            artifact_kind_optional=True,
            artifact_kind_values=EXPECTED_ARTIFACT_KIND_VALUES,
        )
    with pytest.raises(RunnerPreflightError):
        validate_kind_aware_candidate_identities(
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
            corpus_head=CORPUS_SOURCE_COMMIT,
            protocol_sha=FROZEN_PROTOCOL_SHA,
            prompt_profile_version=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
            prompt_profile_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
            code_search_version="code_search_v4",
            artifact_kind_optional=True,
            artifact_kind_values=EXPECTED_ARTIFACT_KIND_VALUES,
        )


def test_runner_is_one_pass_dev_only_and_safe_artifacts_are_preserved():
    source = inspect.getsource(run_kind_aware_candidate_dev)
    assert source.count("_invoke_kind_aware_candidate_worker(") == 1
    assert source.count("for item in plan:") == 1
    assert "HOLDOUT_DATASET_PATH" not in source
    assert "system_a" not in source.lower()
    safe = safe_artifact({"answer": r"C:\private\repo sk-123456789012345"})
    assert "C:\\private" not in repr(safe)
    assert "sk-123456789012345" not in repr(safe)
    with pytest.raises(RunnerPreflightError):
        safe_artifact({"raw_provider_response": "must not serialize"})


def test_candidate_runner_does_not_redefine_frozen_dataset_or_target_identity():
    module_source = Path(
        "evaluation/integration_v7/kind_aware_candidate_runner.py"
    ).read_text(encoding="utf-8")
    assert "385b7795eafde7c114efc382" not in module_source
    assert "179f18e812ad63c36c5569de8e86c5ff9a931cb5" not in module_source
    assert "integration_dev_v1.jsonl" not in module_source
    assert "gold_proof" not in module_source.lower()
