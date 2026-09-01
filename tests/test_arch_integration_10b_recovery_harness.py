"""Provider-free ARCH-INTEGRATION-10B recovery harness tests."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
)
from core.tool_agent.runtime_models import ToolAgentBudget
from core.tool_agent.runtime_models import DecisionControlState
from core.unified_engineering_runtime import UnifiedEngineeringRuntime
from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    TARGET_PROJECT_COMMIT,
    HoldoutExecutionDenied,
    load_cases,
    validate_protocol_manifest,
)
from evaluation.integration_v7.recovery_candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_RUNTIME_LABEL,
    CANDIDATE_SYSTEM_LABEL,
    DEFAULT_OUTPUT_DIR,
    DECISION_PROMPT_PROFILE_SELECTOR,
    LEGACY_DEV_RESULTS_DIR,
    PREVIOUS_CANDIDATE_RESULTS_DIR,
    RecoveryCandidateRunConfig,
    RunnerPreflightError,
    _assert_independent_output,
    build_recovery_candidate_manifest,
    build_recovery_candidate_run_plan,
    build_recovery_candidate_worker_job,
    safe_artifact,
    assert_recovery_candidate_scope,
    validate_recovery_candidate_checkouts,
    validate_recovery_candidate_identities,
)
from evaluation.integration_v7.runner_worker import (
    _select_decision_prompt_profile,
)


def _cases(count: int = 18) -> list[dict]:
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


def test_recovery_plan_is_exactly_18_dev_only_b_double_prime_runs():
    cases = _cases()
    plan = build_recovery_candidate_run_plan(cases)
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert [item["case_id"] for item in plan] == [case["case_id"] for case in cases]
    assert {item["system"] for item in plan} == {CANDIDATE_SYSTEM_LABEL}
    assert {item["worker_system"] for item in plan} == {"B"}
    assert {
        item["decision_prompt_profile_selector"] for item in plan
    } == {DECISION_PROMPT_PROFILE_SELECTOR}
    with pytest.raises(HoldoutExecutionDenied):
        assert_recovery_candidate_scope(HOLDOUT_SPLIT)
    with pytest.raises(HoldoutExecutionDenied):
        build_recovery_candidate_run_plan(cases, HOLDOUT_SPLIT)


def test_candidate_worker_explicitly_selects_unified_profile_and_old_default_is_v2():
    case = _cases(18)[0]
    item = build_recovery_candidate_run_plan(_cases())[0]
    job = build_recovery_candidate_worker_job(
        case,
        plan_item=item,
        candidate_root=Path("candidate"),
        target_root=Path("target"),
        corpus_root=Path("corpus"),
    )
    assert job["system"] == "B"
    assert job["decision_prompt_profile_selector"] == DECISION_PROMPT_PROFILE_SELECTOR
    assert _select_decision_prompt_profile(job) is ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
    assert _select_decision_prompt_profile({"system": "B"}) is ENGINEERING_DECISION_PROMPT_V2_PROFILE
    assert _select_decision_prompt_profile({"system": "A"}) is ENGINEERING_DECISION_PROMPT_V2_PROFILE
    with pytest.raises(ValueError):
        _select_decision_prompt_profile(
            {"system": "B", "decision_prompt_profile_selector": "unknown"}
        )
    with pytest.raises(ValueError):
        _select_decision_prompt_profile(
            {
                "system": "A",
                "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
            }
        )


def test_candidate_and_target_checkouts_are_separate_and_exact():
    validate_recovery_candidate_checkouts(
        Path("candidate"),
        Path("target"),
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
    )
    with pytest.raises(RunnerPreflightError):
        validate_recovery_candidate_checkouts(
            Path("candidate"),
            Path("candidate"),
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
        )
    validate_recovery_candidate_identities(
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
        corpus_head="179f18e812ad63c36c5569de8e86c5ff9a931cb5",
        protocol_sha="281dba7b098535fd508971bfdd98d53ae188c8efa204b5c1fa929c3a40d6a40d",
    )


def test_old_dev_and_e374_candidate_result_directories_are_protected(tmp_path):
    with pytest.raises(RunnerPreflightError):
        _assert_independent_output(LEGACY_DEV_RESULTS_DIR)
    with pytest.raises(RunnerPreflightError):
        _assert_independent_output(PREVIOUS_CANDIDATE_RESULTS_DIR)
    fresh = tmp_path / "dev_candidate_0abdb_v1"
    _assert_independent_output(fresh)
    assert DEFAULT_OUTPUT_DIR.resolve() not in {
        LEGACY_DEV_RESULTS_DIR.resolve(),
        PREVIOUS_CANDIDATE_RESULTS_DIR.resolve(),
    }
    assert not fresh.exists()

    safe = safe_artifact({"answer": r"C:\private\repo sk-123456789012345"})
    assert "C:\\private" not in repr(safe)
    assert "sk-123456789012345" not in repr(safe)
    with pytest.raises(RunnerPreflightError):
        safe_artifact({"raw_provider_response": "must not serialize"})


def test_candidate_manifest_records_candidate_prompt_target_corpus_protocol_and_scope(tmp_path):
    protocol = validate_protocol_manifest()
    plan = build_recovery_candidate_run_plan(_cases())
    manifest = build_recovery_candidate_manifest(
        manifest=protocol,
        config=RecoveryCandidateRunConfig(
            corpus_checkout=Path("corpus"),
            output_dir=tmp_path / "dev_candidate_0abdb_v1",
        ),
        plan=plan,
        raw_runs=[],
        corpus_identity={
            "corpus_id": "870e5864df67",
            "file_count": 37,
            "chunk_count": 215,
            "retrieval_strategy": "bm25",
            "manifest_experiment_id": "dbc497c796d5",
            "verified": True,
        },
        timestamp="20260901T000000Z",
    )
    assert manifest["candidate_runtime"]["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert manifest["candidate_runtime"]["label"] == CANDIDATE_RUNTIME_LABEL
    assert manifest["candidate_runtime"]["system_identity"] == CANDIDATE_SYSTEM_LABEL
    assert manifest["candidate_runtime"]["decision_prompt_profile"] == (
        ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version
    )
    assert manifest["target_project"]["source_sha"] == TARGET_PROJECT_COMMIT
    assert manifest["corpus_identity"]["source_commit"] == (
        "179f18e812ad63c36c5569de8e86c5ff9a931cb5"
    )
    assert manifest["corpus_identity"]["corpus_id"] == "870e5864df67"
    assert manifest["protocol"]["sha256"] == protocol["protocol_sha256"]
    assert manifest["dataset"] == {
        "split": DEV_SPLIT,
        "case_count": 18,
        "sha256": protocol["datasets"][DEV_SPLIT]["sha256"],
    }
    assert manifest["expected_candidate_runs"] == 18
    assert manifest["holdout"] == "NOT_RUN / DENY"
    assert manifest["automatic_metrics_only"] is True


def test_runtime_control_and_budget_contracts_remain_single_and_unchanged():
    source = inspect.getsource(UnifiedEngineeringRuntime.run)
    assert 'disabled_tools=("knowledge_search",)' in source
    assert "enforce_evidence_acquisition=True" in source
    assert source.count("self._execution_adapter.run(") == 1
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
    assert DecisionControlState(5, 0, 0, False, True).must_terminate is True
