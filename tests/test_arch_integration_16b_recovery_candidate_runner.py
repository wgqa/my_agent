"""Provider-free contracts for ARCH-INTEGRATION-16B."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
)
from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
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
from evaluation.integration_v7.recovery_repair_candidate_runner import (
    ARTIFACT_FILES,
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_SYSTEM_LABEL,
    DEFAULT_OUTPUT_DIR,
    EXPECTED_DEV_DATASET_SHA,
    FROZEN_RECOVERY_REPAIR_PROMPT_SHA256,
    PROTECTED_RESULT_DIRS,
    RECOVERY_REPAIR_PROMPT_VERSION,
    RUNNER_SCHEMA_VERSION,
    RUNTIME_VARIANT,
    RecoveryRepairCandidateRunConfig,
    _assert_independent_output,
    _automatic_score_record,
    _current_harness_worker_path,
    _invoke_current_harness_worker,
    _safe_diagnostic_record,
    _semantic_run_record,
    _write_result_package,
    assert_dev_only,
    build_recovery_manifest,
    build_recovery_run_plan,
    build_recovery_summary,
    build_recovery_worker_job,
    project_decision_repair_observability,
    run_recovery_repair_candidate_dev,
    validate_checkout_separation,
    validate_recovery_identities,
)
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROTOCOL_SHA,
    FROZEN_PROVIDER,
    REPO_ROOT,
    RunnerPreflightError,
)
from evaluation.integration_v7.semantic_candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT as FIFTEEN_B_CANDIDATE_RUNTIME_COMMIT,
    RUNNER_SCHEMA_VERSION as FIFTEEN_B_RUNNER_SCHEMA_VERSION,
)
from evaluation.integration_v7.semantic_evaluation_artifact import (
    SEMANTIC_EVALUATION_ARTIFACT_VERSION,
)


def _cases():
    return load_cases(DEV_DATASET_PATH)


def _decision_event(
    iteration,
    *,
    action_type="tool_call",
    call_count=1,
    attempted=False,
    succeeded=False,
    category=None,
):
    return {
        "iteration": iteration,
        "event_type": "decision_completed",
        "action_type": action_type,
        "provider_call_count": call_count,
        "repair_attempted": attempted,
        "repair_succeeded": succeeded,
        "parse_failure_category": category,
    }


def _valid_payload(trace=None):
    return {
        "execution_validity": "VALID",
        "infrastructure_code": None,
        "result": {
            "status": "completed",
            "answer": "A bounded final answer for semantic review.",
            "reason_code": None,
            "failure_code": None,
            "iterations_used": 2,
            "tool_calls_used": 1,
            "trace": (
                trace
                if trace is not None
                else [_decision_event(1)]
            ),
            "evidence": [
                {
                    "evidence_id": "E1",
                    "kind": "project_code",
                    "path": "core/tool_agent/runtime.py",
                    "start_line": 10,
                    "end_line": 12,
                    "snippet": "bounded public snippet",
                }
            ],
        },
        "requirement_state": {
            "satisfied": True,
            "missing_evidence_groups": [],
            "evidence_kind_counts": {
                "knowledge": 0,
                "project_code": 1,
                "project_doc": 0,
                "project_change": 0,
                "project_test": 0,
            },
            "distinct_project_code_paths": 1,
            "required_min_distinct_project_code_paths": 0,
        },
        "requirement_contract_match": True,
        "context": {
            "input_mode": "question_only",
            "resolver_used": False,
            "resolver_fallback": False,
            "resolved_input": None,
            "resolution_correct": None,
        },
        "tool_sequence": ["code_search", "read_project_context"],
        "activity": [
            {
                "type": "activity",
                "tool_name": "code_search",
                "state": "started",
                "target": {"artifact_kind": "project_code"},
            },
            {
                "type": "evidence_added",
                "kind": "project_code",
                "path": "core/tool_agent/runtime.py",
            },
        ],
        "retrieval": {},
        "timing": {},
        "llm_calls_context": 0,
        "llm_calls_planner": 0,
        "llm_calls_toolagent_decision": 1,
        "llm_calls_repair": 0,
    }


def _invalid_payload():
    return {
        "execution_validity": "INVALID",
        "infrastructure_code": "worker_process_failure",
    }


def test_plan_is_exactly_18_unique_dev_cases_system_b_only():
    plan = build_recovery_run_plan(_cases())
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert len({item["case_id"] for item in plan}) == 18
    assert [item["case_id"] for item in plan] == [
        case["case_id"] for case in _cases()
    ]
    assert {item["system"] for item in plan} == {CANDIDATE_SYSTEM_LABEL}
    assert {item["worker_system"] for item in plan} == {"B"}
    assert CANDIDATE_SYSTEM_LABEL == "B_kind_aware_recovery_repair_candidate"
    assert RUNTIME_VARIANT == "unified_kind_aware_recovery_repair_candidate"
    assert "A" not in {item["worker_system"] for item in plan}


def test_holdout_and_non_dev_scopes_fail_closed():
    with pytest.raises(HoldoutExecutionDenied):
        build_recovery_run_plan(_cases(), HOLDOUT_SPLIT)
    with pytest.raises(HoldoutExecutionDenied):
        assert_dev_only("not_a_split")


def test_candidate_commit_is_exactly_the_16a_product_commit():
    assert CANDIDATE_RUNTIME_COMMIT == "09c92746cea2699cb544e999c2b6feda88e43969"


def test_all_frozen_identities_fail_closed_on_drift():
    protocol = validate_protocol_manifest()
    kwargs = {
        "candidate_head": CANDIDATE_RUNTIME_COMMIT,
        "target_head": TARGET_PROJECT_COMMIT,
        "corpus_head": CORPUS_SOURCE_COMMIT,
        "protocol_sha": FROZEN_PROTOCOL_SHA,
        "dev_sha": EXPECTED_DEV_DATASET_SHA,
        "prompt_version": ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
        "prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
        "recovery_repair_prompt_version": RECOVERY_REPAIR_PROMPT_VERSION,
        "recovery_repair_prompt_sha256": FROZEN_RECOVERY_REPAIR_PROMPT_SHA256,
        "provider": FROZEN_PROVIDER,
        "model": FROZEN_MODEL,
        "harness_head": "a" * 40,
    }
    assert protocol["datasets"][DEV_SPLIT]["sha256"] == EXPECTED_DEV_DATASET_SHA
    validate_recovery_identities(**kwargs)
    for field, wrong_value in (
        ("candidate_head", "0" * 40),
        ("target_head", "0" * 40),
        ("corpus_head", "0" * 40),
        ("protocol_sha", "0" * 64),
        ("dev_sha", "0" * 64),
        ("prompt_version", "wrong"),
        ("prompt_sha256", "0" * 64),
        ("recovery_repair_prompt_version", "wrong"),
        ("recovery_repair_prompt_sha256", "0" * 64),
        ("provider", "opencode"),
        ("model", "other-model"),
        ("harness_head", "not-a-sha"),
    ):
        broken = {**kwargs, field: wrong_value}
        with pytest.raises(RunnerPreflightError):
            validate_recovery_identities(**broken)
    with pytest.raises(RunnerPreflightError):
        validate_checkout_separation(
            Path("same"),
            Path("same"),
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
        )


def test_recovery_repair_identity_is_frozen_provenance_not_current_product():
    # The 16B candidate evaluation keeps the historical 09c9274 repair
    # identity even though ARCH-PROD-16C rolled the current Product back.
    assert RECOVERY_REPAIR_PROMPT_VERSION == (
        "engineering_recovery_action_repair_prompt_v1"
    )
    assert FROZEN_RECOVERY_REPAIR_PROMPT_SHA256 == (
        "b4890280e4ec8fa76e31865698c24b751356350c20b1d32f05cd9720124e1013"
    )
    decision_prompt = importlib.import_module("core.tool_agent.decision_prompt")
    for symbol in (
        "ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION",
        "ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256",
        "ENGINEERING_RECOVERY_REPAIR_ENABLED_PROFILE_VERSIONS",
    ):
        assert not hasattr(decision_prompt, symbol), symbol
    assert (
        ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256
        == "de7a0eeb4beaea5ed93e0e4196f55b5253f73408c3e5216379aba0d8a7abd85f"
    )
    assert CANDIDATE_RUNTIME_COMMIT == "09c92746cea2699cb544e999c2b6feda88e43969"


def test_worker_is_current_harness_while_job_product_root_is_candidate_checkout():
    plan = build_recovery_run_plan(_cases())
    candidate_root = Path("candidate_09c9274")
    target_root = Path("target_385b")
    job = build_recovery_worker_job(
        _cases()[0],
        plan_item=plan[0],
        candidate_root=candidate_root,
        target_root=target_root,
        corpus_root=Path("corpus_agent_data"),
    )
    worker = _current_harness_worker_path(REPO_ROOT)
    assert worker == REPO_ROOT / "evaluation" / "integration_v7" / "runner_worker.py"
    assert worker != candidate_root / "evaluation" / "integration_v7" / "runner_worker.py"
    assert job["system_root"] == str(candidate_root)
    assert job["system"] == "B"
    assert job["decision_prompt_profile_selector"] == (
        "engineering_agent_decision_prompt_unified_kind_aware_v1"
    )


def test_historical_15b_runner_is_unmodified_and_not_an_execution_path():
    assert FIFTEEN_B_CANDIDATE_RUNTIME_COMMIT == "6d7e58f1e8c1f2bdaab091c453855b6eee53036b"
    assert FIFTEEN_B_RUNNER_SCHEMA_VERSION == "integration_v7_semantic_candidate_runner_v1"
    runner_source = inspect.getsource(
        __import__(
            "evaluation.integration_v7.recovery_repair_candidate_runner",
            fromlist=[""],
        )
    )
    assert "semantic_candidate_runner" not in runner_source
    assert "run_semantic_candidate_dev" not in runner_source
    assert inspect.getsource(run_recovery_repair_candidate_dev).count(
        "_invoke_current_harness_worker("
    ) == 1


def test_normal_decision_classifies_as_none():
    observability = project_decision_repair_observability(
        [_decision_event(1)], run_validity="VALID"
    )
    assert observability == {
        "availability": "AVAILABLE",
        "decision_count": 1,
        "provider_calls_total": 1,
        "recovery_repair_attempts": 0,
        "recovery_repair_successes": 0,
        "parse_repair_attempts": 0,
        "parse_repair_successes": 0,
        "recovery_repair_attempt_iterations": [],
        "recovery_repair_success_iterations": [],
    }


def test_parse_repair_classifies_as_parse_and_counts_success():
    trace = [
        _decision_event(
            1, attempted=True, succeeded=True, category="INVALID_JSON", call_count=2
        ),
    ]
    observability = project_decision_repair_observability(trace, run_validity="VALID")
    assert observability["parse_repair_attempts"] == 1
    assert observability["parse_repair_successes"] == 1
    assert observability["recovery_repair_attempts"] == 0
    assert observability["provider_calls_total"] == 2


def test_recovery_repair_classifies_and_records_iterations():
    trace = [
        _decision_event(
            1, attempted=True, succeeded=True, call_count=2
        ),
        _decision_event(2),
        _decision_event(3, action_type="final_answer"),
    ]
    observability = project_decision_repair_observability(trace, run_validity="VALID")
    assert observability["decision_count"] == 3
    assert observability["provider_calls_total"] == 4
    assert observability["recovery_repair_attempts"] == 1
    assert observability["recovery_repair_successes"] == 1
    assert observability["recovery_repair_attempt_iterations"] == [1]
    assert observability["recovery_repair_success_iterations"] == [1]


def test_recovery_repair_failure_counts_attempt_without_success():
    trace = [
        _decision_event(
            2,
            action_type="refuse",
            attempted=True,
            succeeded=False,
            call_count=2,
        ),
    ]
    observability = project_decision_repair_observability(trace, run_validity="VALID")
    assert observability["recovery_repair_attempts"] == 1
    assert observability["recovery_repair_successes"] == 0
    assert observability["recovery_repair_attempt_iterations"] == [2]
    assert observability["recovery_repair_success_iterations"] == []


def test_invalid_run_keeps_not_applicable_observability():
    observability = project_decision_repair_observability(None, run_validity="INVALID")
    assert observability == {"availability": "NOT_APPLICABLE_INVALID_RUN"}
    diagnostic = _safe_diagnostic_record(_cases()[0], build_recovery_run_plan(_cases())[0], _invalid_payload())
    assert diagnostic["decision_repair_observability"] == {
        "availability": "NOT_APPLICABLE_INVALID_RUN"
    }


@pytest.mark.parametrize(
    "trace",
    [
        # missing provider_call_count
        [
            {
                "iteration": 1,
                "event_type": "decision_completed",
                "action_type": "tool_call",
                "repair_attempted": False,
                "repair_succeeded": False,
                "parse_failure_category": None,
            }
        ],
        # out-of-range provider_call_count
        [_decision_event(1, call_count=3)],
        # non-bool repair metadata
        [{**_decision_event(1), "repair_attempted": "no"}],
        [{**_decision_event(1), "repair_succeeded": None}],
        # succeeded without attempted
        [_decision_event(1, attempted=False, succeeded=True)],
        # attempted without second call
        [_decision_event(1, attempted=True, call_count=1)],
        # unsafe parse category
        [{**_decision_event(1), "parse_failure_category": "MYSTERY"}],
        # missing iteration
        [{**_decision_event(1), "iteration": 0}],
        # no decision events at all
        [{"iteration": 1, "event_type": "tool_observation"}],
    ],
)
def test_malformed_valid_repair_metadata_fails_closed(trace):
    with pytest.raises(RunnerPreflightError):
        project_decision_repair_observability(trace, run_validity="VALID")
    with pytest.raises(RunnerPreflightError):
        project_decision_repair_observability(None, run_validity="VALID")


def test_diagnostic_record_keeps_identity_and_repair_facts_without_answers():
    case = _cases()[0]
    plan = build_recovery_run_plan(_cases())
    payload = _valid_payload()
    payload["raw_provider_response"] = "DO_NOT_PERSIST"
    diagnostic = _safe_diagnostic_record(case, plan[0], payload)
    assert diagnostic["system"] == CANDIDATE_SYSTEM_LABEL
    assert diagnostic["runtime_variant"] == RUNTIME_VARIANT
    assert diagnostic["candidate_runtime_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert diagnostic["worker_system"] == "B"
    assert diagnostic["decision_repair_observability"]["availability"] == "AVAILABLE"
    assert diagnostic["decision_repair_observability"]["decision_count"] == 1
    serialized = repr(diagnostic).lower()
    # "provider" legitimately appears only inside the bounded count key
    # provider_calls_total; no raw provider output, answer, prompt, or
    # argument is persisted.
    for forbidden in ("answer", "raw_provider_response", "prompt", "arguments", "observation"):
        assert forbidden not in serialized
    assert "provider_calls_total" in diagnostic["decision_repair_observability"]
    assert "provider" not in diagnostic
    assert "provider" not in diagnostic["decision_repair_observability"]


def test_semantic_records_still_use_the_frozen_15a_projector():
    case = _cases()[0]
    valid = _semantic_run_record(case, _valid_payload())
    invalid = _semantic_run_record(case, _invalid_payload())
    assert valid["schema_version"] == SEMANTIC_EVALUATION_ARTIFACT_VERSION
    assert valid["semantic_evaluation_availability"] == "AVAILABLE"
    assert valid["final"]["answer"] == "A bounded final answer for semantic review."
    assert invalid["semantic_evaluation_availability"] == "NOT_APPLICABLE_INVALID_RUN"
    assert invalid["final"] is None
    plan = build_recovery_run_plan(_cases())
    rows = [_semantic_run_record(case, _valid_payload()) for case in _cases()]
    assert len(rows) == len(plan) == 18
    assert [row["case_id"] for row in rows] == [item["case_id"] for item in plan]
    assert "repair_attempted" not in repr(valid)


def test_automatic_metrics_are_computed_only_for_valid_payloads():
    case = _cases()[0]
    plan = build_recovery_run_plan(_cases())
    valid = _automatic_score_record(case, plan[0], _valid_payload())
    invalid = _automatic_score_record(case, plan[0], _invalid_payload())
    assert valid["automatic_metrics"]
    assert invalid["automatic_metrics"] == {}
    assert valid["system"] == CANDIDATE_SYSTEM_LABEL


def test_summary_aggregates_repair_observability_and_stays_descriptive():
    case = _cases()[0]
    plan = build_recovery_run_plan(_cases())
    recovery_payload = _valid_payload(
        trace=[
            _decision_event(1, attempted=True, succeeded=True, call_count=2),
            _decision_event(2),
        ]
    )
    plain_payload = _valid_payload()
    diagnostic_runs = [
        _safe_diagnostic_record(case, plan[0], recovery_payload),
        _safe_diagnostic_record(_cases()[1], plan[1], plain_payload),
    ]
    semantic_runs = [
        _semantic_run_record(_cases()[0], recovery_payload),
        _semantic_run_record(_cases()[1], plain_payload),
    ]
    automatic_scores = [
        _automatic_score_record(_cases()[0], plan[0], recovery_payload),
        _automatic_score_record(_cases()[1], plan[1], plain_payload),
    ]
    summary = build_recovery_summary(diagnostic_runs, semantic_runs, automatic_scores)
    assert summary["schema_version"] == RUNNER_SCHEMA_VERSION
    assert summary["run_counts"] == {"expected": 18, "observed": 2, "valid": 2, "invalid": 0}
    assert summary["recovery_repair_observability"] == {
        "available_valid_cases": 2,
        "cases_with_recovery_repair_attempt": [case["case_id"]],
        "cases_with_recovery_repair_success": [case["case_id"]],
        "recovery_repair_attempted_decisions": 1,
        "recovery_repair_successful_decisions": 1,
        "recovery_repair_failed_decisions": 0,
        "parse_repair_attempted_decisions": 0,
        "parse_repair_successful_decisions": 0,
        "provider_calls_total": 4,
    }
    assert summary["semantic_scoring"] == summary["manual_scoring"] == "NOT_DONE"
    assert "effectiveness" not in repr(summary).lower()
    assert "semantic_correctness" not in repr(summary)

    empty = build_recovery_summary([], [], [])
    assert empty["recovery_repair_observability"] == {
        "available_valid_cases": 0,
        "cases_with_recovery_repair_attempt": [],
        "cases_with_recovery_repair_success": [],
        "recovery_repair_attempted_decisions": 0,
        "recovery_repair_successful_decisions": 0,
        "recovery_repair_failed_decisions": 0,
        "parse_repair_attempted_decisions": 0,
        "parse_repair_successful_decisions": 0,
        "provider_calls_total": 0,
    }


def test_manifest_separates_candidate_main_prompt_repair_and_harness():
    protocol = validate_protocol_manifest()
    plan = build_recovery_run_plan(_cases())
    diagnostic_runs = [
        _safe_diagnostic_record(case, item, _valid_payload())
        for case, item in zip(_cases(), plan)
    ]
    manifest = build_recovery_manifest(
        protocol=protocol,
        config=RecoveryRepairCandidateRunConfig(corpus_checkout=Path("corpus")),
        plan=plan,
        diagnostic_runs=diagnostic_runs,
        harness_head="b" * 40,
        corpus_identity={"corpus_id": "870e5864df67"},
        timestamp="20260907T000000Z",
    )
    candidate = manifest["candidate_runtime"]
    assert candidate["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert candidate["system_identity"] == CANDIDATE_SYSTEM_LABEL
    assert candidate["runtime_variant"] == RUNTIME_VARIANT
    assert candidate["decision_prompt_profile"] == (
        "engineering_agent_decision_prompt_unified_kind_aware_v1"
    )
    assert candidate["decision_prompt_sha256"] == (
        "de7a0eeb4beaea5ed93e0e4196f55b5253f73408c3e5216379aba0d8a7abd85f"
    )
    assert candidate["recovery_action_repair"] == {
        "enabled": True,
        "prompt_version": "engineering_recovery_action_repair_prompt_v1",
        "prompt_sha256": "b4890280e4ec8fa76e31865698c24b751356350c20b1d32f05cd9720124e1013",
    }
    assert manifest["evaluation_harness"] == {
        "source_commit": "b" * 40,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "semantic_artifact_schema_version": SEMANTIC_EVALUATION_ARTIFACT_VERSION,
        "worker_schema_version": "integration_v7_real_dev_worker_v1",
    }
    # Identity fields are distinct keys: the candidate commit is a frozen
    # constant while the harness commit is the actual clean HEAD; the two may
    # coincide numerically in a 16B execution but never share semantics.
    assert manifest["candidate_runtime"]["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert manifest["evaluation_harness"]["source_commit"] == "b" * 40
    assert manifest["target_project"]["source_sha"] == TARGET_PROJECT_COMMIT
    assert manifest["relationship_to_15b"] == (
        "NEW_PRODUCT_CANDIDATE_EVALUATION_RUN_NOT_15B_RERUN_NOT_HISTORICAL_REPAIR"
    )
    assert manifest["retry_policy"] == "NO_RETRY"
    assert manifest["system_a"] == "NOT_RUN"
    assert manifest["holdout"] == "NOT_RUN / DENY"
    assert manifest["semantic_scoring"] == manifest["manual_scoring"] == "NOT_DONE"
    assert manifest["expected_runs"] == manifest["observed_runs"] == 18
    assert manifest["valid_runs"] == 18
    assert manifest["invalid_runs"] == 0
    assert manifest["case_ids"] == [item["case_id"] for item in plan]


def test_historical_outputs_and_nonempty_16b_output_are_protected(tmp_path: Path):
    for path in PROTECTED_RESULT_DIRS:
        assert (REPO_ROOT / "evaluation" / "integration_v7" / "results").resolve() in path.resolve().parents
        with pytest.raises(RunnerPreflightError):
            _assert_independent_output(path)
    assert str(PROTECTED_RESULT_DIRS[-1]).replace("\\", "/").endswith(
        "evaluation/integration_v7/results/dev_semantic_15b_6d7e58f_v1"
    )
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "prior.json").write_text("prior\n", encoding="utf-8")
    with pytest.raises(RunnerPreflightError):
        _assert_independent_output(occupied)
    _assert_independent_output(tmp_path / "empty")
    assert DEFAULT_OUTPUT_DIR.name == "dev_semantic_16b_09c9274_v1"
    assert DEFAULT_OUTPUT_DIR.resolve() not in {path.resolve() for path in PROTECTED_RESULT_DIRS}


def test_writer_creates_exactly_the_configured_safe_file_set(tmp_path: Path):
    case = _cases()[0]
    plan = build_recovery_run_plan(_cases())
    diagnostic = _safe_diagnostic_record(case, plan[0], _valid_payload())
    semantic = _semantic_run_record(case, _valid_payload())
    score = _automatic_score_record(case, plan[0], _valid_payload())
    _write_result_package(
        tmp_path,
        manifest={"schema_version": RUNNER_SCHEMA_VERSION},
        diagnostic_runs=[diagnostic],
        semantic_runs=[semantic],
        automatic_scores=[score],
    )
    assert {path.name for path in tmp_path.iterdir()} == set(ARTIFACT_FILES)
    assert set(ARTIFACT_FILES) == {
        "run_manifest.json",
        "diagnostic_runs.jsonl",
        "semantic_runs.jsonl",
        "automatic_scores.jsonl",
        "summary.json",
    }
    semantic_rows = [
        json.loads(line)
        for line in (tmp_path / "semantic_runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    diagnostic_rows = [
        json.loads(line)
        for line in (tmp_path / "diagnostic_runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert semantic_rows[0]["final"]["answer"]
    assert "repair_attempted" not in repr(semantic_rows)
    assert diagnostic_rows[0]["decision_repair_observability"]["availability"] == "AVAILABLE"


def test_worker_invocation_is_never_executed_by_the_test_suite():
    source = inspect.getsource(_invoke_current_harness_worker)
    assert "subprocess.run" in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "openai" not in source.lower()
    run_source = inspect.getsource(run_recovery_repair_candidate_dev)
    assert run_source.count("for item in plan:") == 1
    assert "semantic_runs.append(" in run_source
    assert "retry" not in run_source.lower()
    assert "HOLDOUT_DATASET_PATH" not in run_source
    assert "semantic_score" not in run_source
    plan_source = inspect.getsource(build_recovery_run_plan)
    assert "HOLDOUT_SPLIT" not in plan_source
