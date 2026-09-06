"""Provider-free contracts for ARCH-INTEGRATION-12D."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    DEV_SPLIT,
    HOLDOUT_SPLIT,
    TARGET_PROJECT_COMMIT,
    HoldoutExecutionDenied,
    ProtocolViolation,
    load_cases,
    validate_protocol_manifest,
)
from evaluation.integration_v7.repo_acquisition_diagnostic_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_SYSTEM,
    DECISION_PROMPT_PROFILE_SELECTOR,
    DIAGNOSTIC_CASE_IDS,
    PROTECTED_RESULT_DIRS,
    RUNTIME_VARIANT,
    RepoAcquisitionDiagnosticConfig,
    _assert_independent_output,
    _diagnostic_raw_record,
    build_diagnostic_manifest,
    build_diagnostic_run_plan,
    build_diagnostic_worker_job,
    run_repo_acquisition_diagnostic,
    validate_diagnostic_checkouts,
)
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROTOCOL_SHA,
    FROZEN_PROVIDER,
    RunnerPreflightError,
)
from evaluation.integration_v7.runner_worker import UNIFIED_DECISION_PROMPT_SELECTOR


def _real_plan():
    cases = load_cases(DEV_DATASET_PATH)
    return cases, build_diagnostic_run_plan(cases)


def test_plan_is_exactly_three_fixed_dev_cases_once_each():
    cases, plan = _real_plan()
    assert DIAGNOSTIC_CASE_IDS == ("v7d003", "v7d012", "v7d014")
    assert tuple(item["case_id"] for item in plan) == DIAGNOSTIC_CASE_IDS
    assert [item["run_order"] for item in plan] == [1, 2, 3]
    assert len({item["case_id"] for item in plan}) == len(plan) == 3
    assert {item["system"] for item in plan} == {"B"}
    assert {item["runtime_variant"] for item in plan} == {RUNTIME_VARIANT}
    assert all(
        next(case for case in cases if case["case_id"] == item["case_id"])["split"]
        == DEV_SPLIT
        for item in plan
    )


def test_holdout_and_system_a_have_no_execution_path():
    cases = load_cases(DEV_DATASET_PATH)
    with pytest.raises(HoldoutExecutionDenied):
        build_diagnostic_run_plan(cases, HOLDOUT_SPLIT)

    item = build_diagnostic_run_plan(cases)[0]
    item["system"] = "A"
    with pytest.raises(ProtocolViolation):
        build_diagnostic_worker_job(
            cases[2],
            plan_item=item,
            candidate_root=Path("candidate"),
            target_root=Path("target"),
            corpus_root=Path("corpus"),
        )


def test_identity_is_exact_deepseek_unified_v1_candidate():
    assert CANDIDATE_RUNTIME_COMMIT == "1a26428d64c724cad42b8ed331b9fdef65d1e9d7"
    assert CANDIDATE_SYSTEM == "B"
    assert FROZEN_PROVIDER == "deepseek"
    assert FROZEN_MODEL == "deepseek-chat"
    assert DECISION_PROMPT_PROFILE_SELECTOR == UNIFIED_DECISION_PROMPT_SELECTOR
    assert DECISION_PROMPT_PROFILE_SELECTOR == "engineering_agent_decision_prompt_unified_v1"
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version == (
        DECISION_PROMPT_PROFILE_SELECTOR
    )


def test_worker_job_uses_isolated_inputs_without_provider_port_or_key():
    cases, plan = _real_plan()
    by_id = {case["case_id"]: case for case in cases}
    job = build_diagnostic_worker_job(
        by_id[plan[0]["case_id"]],
        plan_item=plan[0],
        candidate_root=Path("candidate"),
        target_root=Path("target"),
        corpus_root=Path("corpus"),
    )
    assert job["system"] == "B"
    assert job["system_root"] == "candidate"
    assert job["target_root"] == "target"
    assert job["decision_prompt_profile_selector"] == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    serialized = repr(job).lower()
    assert "api_key" not in serialized
    assert "opencode" not in serialized
    assert "provider_config" not in serialized

    validate_diagnostic_checkouts(
        Path("candidate"),
        Path("target"),
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
    )
    with pytest.raises(RunnerPreflightError):
        validate_diagnostic_checkouts(
            Path("same"),
            Path("same"),
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
        )


def test_raw_record_persists_bounded_safe_activity_and_minimal_final():
    cases, plan = _real_plan()
    case = next(case for case in cases if case["case_id"] == "v7d003")
    activity = [
        {
            "type": "activity",
            "tool_name": "code_search",
            "state": "started",
            "target": {"query": "runtime", "artifact_kind": "project_code"},
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
    raw = _diagnostic_raw_record(
        case,
        plan[0],
        {
            "execution_validity": "VALID",
            "activity": activity + activity * 30,
            "result": {
                "status": "completed",
                "reason_code": None,
                "failure_code": None,
                "evidence": [
                    {"evidence_id": "E1", "kind": "project_code", "snippet": "omit"}
                ],
                "answer": "must not persist",
            },
            "raw_provider_response": "must not persist",
        },
    )
    assert len(raw["activity"]) == 64
    assert raw["activity"][0]["target"]["artifact_kind"] == "project_code"
    assert raw["activity"][1]["result_summary"]["top_paths"] == ["core/runtime.py"]
    assert raw["activity"][2]["evidence_ids_added"] == ["E1"]
    assert raw["final"] == {
        "status": "completed",
        "reason_code": None,
        "failure_code": None,
        "evidence_kinds": ["project_code"],
    }
    serialized = repr(raw).lower()
    for forbidden in (
        "answer",
        "snippet",
        "raw_provider_response",
        "prompt",
        "arguments",
        "observation",
        "secret",
    ):
        assert forbidden not in serialized


def test_manifest_records_frozen_identity_no_retry_and_no_holdout(tmp_path):
    protocol = validate_protocol_manifest()
    _, plan = _real_plan()
    manifest = build_diagnostic_manifest(
        protocol=protocol,
        config=RepoAcquisitionDiagnosticConfig(
            corpus_checkout=Path("corpus"), output_dir=tmp_path / "result"
        ),
        plan=plan,
        raw_runs=[],
        corpus_identity=protocol["corpus_identity"],
        timestamp="20260906T000000Z",
    )
    assert manifest["case_ids"] == list(DIAGNOSTIC_CASE_IDS)
    assert manifest["provider"] == {"name": "deepseek", "model": "deepseek-chat"}
    assert manifest["candidate_runtime"]["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert manifest["candidate_runtime"]["system"] == "B"
    assert manifest["candidate_runtime"]["decision_prompt_profile"] == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    assert manifest["protocol"]["sha256"] == FROZEN_PROTOCOL_SHA
    assert manifest["expected_runs"] == 3
    assert manifest["retry_policy"] == "NO_RETRY"
    assert manifest["system_a"] == "NOT_RUN"
    assert manifest["holdout"] == "NOT_RUN / DENY"


def test_runner_has_one_worker_invocation_and_protects_existing_results(tmp_path):
    source = inspect.getsource(run_repo_acquisition_diagnostic)
    assert source.count("_invoke_diagnostic_worker(") == 1
    assert source.count("for item in plan:") == 1
    assert "HOLDOUT_DATASET_PATH" not in source
    assert "while " not in source

    for protected in PROTECTED_RESULT_DIRS:
        with pytest.raises(RunnerPreflightError):
            _assert_independent_output(protected)
    fresh = tmp_path / "dev_diag_12d_1a26428_v1"
    _assert_independent_output(fresh)
