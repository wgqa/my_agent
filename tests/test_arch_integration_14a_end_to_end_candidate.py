"""Provider-free contracts for ARCH-INTEGRATION-14A."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
)
from core.tool_agent.runtime_models import ToolAgentBudget
from core.unified_engineering_runtime import UnifiedEngineeringRuntime
from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    TARGET_PROJECT_COMMIT,
    HoldoutExecutionDenied,
    ProtocolViolation,
    load_cases,
    validate_protocol_manifest,
)
from evaluation.integration_v7.end_to_end_candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_SYSTEM_LABEL,
    DECISION_PROMPT_PROFILE_SELECTOR,
    DEFAULT_OUTPUT_DIR,
    PROTECTED_RESULT_DIRS,
    RUNTIME_VARIANT,
    WORKER_SYSTEM,
    EndToEndCandidateRunConfig,
    _assert_independent_output,
    _safe_raw_record,
    build_end_to_end_run_plan,
    build_end_to_end_summary,
    build_end_to_end_worker_job,
    run_end_to_end_candidate,
    validate_end_to_end_identities,
)
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROTOCOL_SHA,
    FROZEN_PROVIDER,
    RunnerPreflightError,
)
from evaluation.integration_v7.runner_worker import (
    UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR,
)


def _cases():
    return load_cases(DEV_DATASET_PATH)


def test_plan_is_exactly_18_frozen_dev_cases_once_each():
    plan = build_end_to_end_run_plan(_cases())
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert len({item["case_id"] for item in plan}) == 18
    assert {item["system"] for item in plan} == {CANDIDATE_SYSTEM_LABEL}
    assert {item["worker_system"] for item in plan} == {WORKER_SYSTEM}
    assert {item["runtime_variant"] for item in plan} == {RUNTIME_VARIANT}
    assert {item["decision_prompt_profile_selector"] for item in plan} == {
        DECISION_PROMPT_PROFILE_SELECTOR
    }
    assert {item["decision_prompt_profile"] for item in plan} == {
        ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version
    }
    with pytest.raises(HoldoutExecutionDenied):
        build_end_to_end_run_plan(_cases(), HOLDOUT_SPLIT)


def test_worker_job_binds_candidate_b_and_kind_aware_profile_with_separate_inputs():
    cases = _cases()
    plan = build_end_to_end_run_plan(cases)
    job = build_end_to_end_worker_job(
        cases[0],
        plan_item=plan[0],
        candidate_root=Path("candidate_checkout"),
        target_root=Path("target_checkout"),
        corpus_root=Path("corpus_candidate"),
    )
    assert job["system"] == "B"
    assert job["system_root"] == "candidate_checkout"
    assert job["target_root"] == "target_checkout"
    assert job["decision_prompt_profile_selector"] == (
        "engineering_agent_decision_prompt_unified_kind_aware_v1"
    )
    assert "api_key" not in repr(job).lower()
    assert "opencode" not in repr(job).lower()


def test_candidate_identity_and_frozen_inputs_are_exact():
    protocol = validate_protocol_manifest()
    assert FROZEN_PROVIDER == "deepseek"
    assert FROZEN_MODEL == "deepseek-chat"
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_kind_aware_v1"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256 == (
        "de7a0eeb4beaea5ed93e0e4196f55b5253f73408c3e5216379aba0d8a7abd85f"
    )
    validate_end_to_end_identities(
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
        corpus_head=protocol["corpus_identity"]["source_commit"],
        protocol_sha=FROZEN_PROTOCOL_SHA,
        dev_sha=protocol["datasets"][DEV_SPLIT]["sha256"],
        prompt_version=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
        prompt_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
        provider=FROZEN_PROVIDER,
        model=FROZEN_MODEL,
    )
    with pytest.raises(RunnerPreflightError):
        validate_end_to_end_identities(
            candidate_head="0" * 40,
            target_head=TARGET_PROJECT_COMMIT,
            corpus_head=protocol["corpus_identity"]["source_commit"],
            protocol_sha=FROZEN_PROTOCOL_SHA,
            dev_sha=protocol["datasets"][DEV_SPLIT]["sha256"],
            prompt_version=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
            prompt_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
            provider=FROZEN_PROVIDER,
            model=FROZEN_MODEL,
        )


def test_safe_raw_record_and_descriptive_summary_preserve_only_public_state():
    case = _cases()[0]
    plan = build_end_to_end_run_plan(_cases())
    activity = [
        {
            "type": "activity",
            "tool_name": "code_search",
            "state": "started",
            "target": {"artifact_kind": "project_code", "query": "runtime"},
        },
        {
            "type": "activity",
            "tool_name": "code_search",
            "state": "completed",
            "result_summary": {"top_paths": ["core/runtime.py"]},
        },
        {
            "type": "activity",
            "tool_name": "read_project_context",
            "state": "completed",
            "target": {"path": "core/runtime.py"},
            "evidence_ids_added": ["E1"],
        },
    ]
    raw = _safe_raw_record(
        case,
        plan[0],
        {
            "execution_validity": "VALID",
            "activity": activity,
            "requirement_state": {"missing_evidence_groups": []},
            "tool_sequence": ["code_search", "read_project_context"],
            "result": {
                "status": "completed",
                "reason_code": None,
                "failure_code": None,
                "tool_calls_used": 2,
                "iterations_used": 3,
                "evidence": [{"kind": "project_code", "path": "core/runtime.py"}],
                "answer": "must not persist",
            },
            "raw_provider_response": "must not persist",
        },
    )
    assert raw["missing_evidence_groups"] == []
    assert raw["activity"] == activity
    assert raw["final"]["evidence_kinds"] == ["project_code"]
    assert raw["tool_sequence"] == ["code_search", "read_project_context"]
    assert raw["tool_calls"] == 2
    assert raw["iterations"] == 3
    serialized = repr(raw).lower()
    for forbidden in ("answer", "raw_provider_response", "prompt", "observation", "arguments"):
        assert forbidden not in serialized

    summary = build_end_to_end_summary([raw], [{"run_validity": "VALID", "automatic_metrics": {}}])
    assert summary["descriptive_counts"]["code_search_calls"] == 1
    assert summary["descriptive_counts"]["code_search_with_project_code"] == 1
    assert summary["descriptive_counts"]["project_code_evidence_cases"] == 1
    assert summary["descriptive_counts"]["completed_cases"] == 1


def test_runner_is_one_pass_and_historical_results_are_protected(tmp_path):
    source = inspect.getsource(run_end_to_end_candidate)
    assert source.count("_invoke_end_to_end_worker(") == 1
    assert source.count("for item in plan:") == 1
    assert "HOLDOUT_DATASET_PATH" not in source
    for result_dir in PROTECTED_RESULT_DIRS:
        with pytest.raises(RunnerPreflightError):
            _assert_independent_output(result_dir)
    _assert_independent_output(tmp_path / "fresh_output")
    assert DEFAULT_OUTPUT_DIR.resolve() not in {path.resolve() for path in PROTECTED_RESULT_DIRS}


def test_formal_runtime_boundaries_and_profile_selector_are_unchanged():
    assert DECISION_PROMPT_PROFILE_SELECTOR == UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR
    source = inspect.getsource(UnifiedEngineeringRuntime.run)
    assert 'disabled_tools=("knowledge_search",)' in source
    assert source.count("self._execution_adapter.run(") == 1
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
