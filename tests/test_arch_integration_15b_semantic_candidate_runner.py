"""Provider-free contracts for ARCH-INTEGRATION-15B."""

from __future__ import annotations

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
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROTOCOL_SHA,
    FROZEN_PROVIDER,
    REPO_ROOT,
    RunnerPreflightError,
)
from evaluation.integration_v7.semantic_candidate_runner import (
    ARTIFACT_FILES,
    CANDIDATE_RUNTIME_COMMIT,
    DEFAULT_OUTPUT_DIR,
    EXPECTED_DEV_DATASET_SHA,
    PROTECTED_RESULT_DIRS,
    RUNNER_SCHEMA_VERSION,
    SemanticCandidateRunConfig,
    _assert_independent_output,
    _automatic_score_record,
    _current_harness_worker_path,
    _safe_diagnostic_record,
    _semantic_run_record,
    _write_result_package,
    assert_dev_only,
    build_semantic_manifest,
    build_semantic_run_plan,
    build_semantic_summary,
    build_semantic_worker_job,
    run_semantic_candidate_dev,
    validate_checkout_separation,
    validate_semantic_identities,
)
from evaluation.integration_v7.semantic_evaluation_artifact import (
    SEMANTIC_EVALUATION_ARTIFACT_VERSION,
)


def _cases():
    return load_cases(DEV_DATASET_PATH)


def _valid_payload():
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
            {"type": "evidence_added", "kind": "project_code", "path": "core/tool_agent/runtime.py"},
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


def test_plan_is_exactly_18_unique_dev_cases_and_denies_holdout():
    plan = build_semantic_run_plan(_cases())
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert len({item["case_id"] for item in plan}) == 18
    assert {item["system"] for item in plan} == {"B_kind_aware_recovery_candidate"}
    assert {item["worker_system"] for item in plan} == {"B"}
    with pytest.raises(HoldoutExecutionDenied):
        build_semantic_run_plan(_cases(), HOLDOUT_SPLIT)
    with pytest.raises(HoldoutExecutionDenied):
        assert_dev_only("not_a_split")


def test_worker_is_current_harness_while_job_product_root_is_candidate_checkout():
    plan = build_semantic_run_plan(_cases())
    candidate_root = Path("candidate_6d7e58f")
    target_root = Path("target_385b")
    job = build_semantic_worker_job(
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


def test_all_frozen_product_identities_and_harness_identity_fail_closed_on_drift():
    protocol = validate_protocol_manifest()
    kwargs = {
        "candidate_head": CANDIDATE_RUNTIME_COMMIT,
        "target_head": TARGET_PROJECT_COMMIT,
        "corpus_head": CORPUS_SOURCE_COMMIT,
        "protocol_sha": FROZEN_PROTOCOL_SHA,
        "dev_sha": EXPECTED_DEV_DATASET_SHA,
        "prompt_version": ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
        "prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
        "provider": FROZEN_PROVIDER,
        "model": FROZEN_MODEL,
        "harness_head": "a" * 40,
    }
    assert protocol["datasets"][DEV_SPLIT]["sha256"] == EXPECTED_DEV_DATASET_SHA
    validate_semantic_identities(**kwargs)
    for field, wrong_value in (
        ("candidate_head", "0" * 40),
        ("target_head", "0" * 40),
        ("corpus_head", "0" * 40),
        ("protocol_sha", "0" * 64),
        ("dev_sha", "0" * 64),
        ("prompt_version", "wrong"),
        ("prompt_sha256", "0" * 64),
        ("provider", "opencode"),
        ("model", "other-model"),
        ("harness_head", "not-a-sha"),
    ):
        broken = {**kwargs, field: wrong_value}
        with pytest.raises(RunnerPreflightError):
            validate_semantic_identities(**broken)
    with pytest.raises(RunnerPreflightError):
        validate_checkout_separation(
            Path("same"), Path("same"), candidate_head=CANDIDATE_RUNTIME_COMMIT, target_head=TARGET_PROJECT_COMMIT
        )


def test_valid_and_invalid_worker_payloads_produce_one_semantic_artifact_each():
    case = _cases()[0]
    valid = _semantic_run_record(case, _valid_payload())
    invalid = _semantic_run_record(case, _invalid_payload())
    assert valid["semantic_evaluation_availability"] == "AVAILABLE"
    assert valid["final"]["answer"] == "A bounded final answer for semantic review."
    assert invalid["semantic_evaluation_availability"] == "NOT_APPLICABLE_INVALID_RUN"
    assert invalid["final"] is None
    plan = build_semantic_run_plan(_cases())
    rows = [_semantic_run_record(case, _valid_payload()) for case in _cases()]
    assert len(rows) == len(plan) == 18
    assert [row["case_id"] for row in rows] == [item["case_id"] for item in plan]


def test_automatic_metrics_are_computed_only_for_valid_payloads():
    case = _cases()[0]
    plan = build_semantic_run_plan(_cases())
    valid = _automatic_score_record(case, plan[0], _valid_payload())
    invalid = _automatic_score_record(case, plan[0], _invalid_payload())
    assert valid["automatic_metrics"]
    assert invalid["automatic_metrics"] == {}


def test_diagnostic_record_preserves_safe_activity_without_answer_or_raw_provider_fields():
    case = _cases()[0]
    plan = build_semantic_run_plan(_cases())
    payload = _valid_payload()
    payload["raw_provider_response"] = "DO_NOT_PERSIST"
    # The accepted 14A diagnostic projector intentionally excludes this field.
    diagnostic = _safe_diagnostic_record(case, plan[0], payload)
    serialized = repr(diagnostic).lower()
    assert diagnostic["activity"][0]["target"]["artifact_kind"] == "project_code"
    for forbidden in ("answer", "raw_provider_response", "provider", "prompt", "arguments"):
        assert forbidden not in serialized


def test_manifest_separates_product_candidate_from_current_evaluation_harness():
    protocol = validate_protocol_manifest()
    plan = build_semantic_run_plan(_cases())
    manifest = build_semantic_manifest(
        protocol=protocol,
        config=SemanticCandidateRunConfig(corpus_checkout=Path("corpus")),
        plan=plan,
        diagnostic_runs=[_safe_diagnostic_record(_cases()[0], plan[0], _valid_payload())],
        harness_head="b" * 40,
        corpus_identity={"corpus_id": "870e5864df67"},
        timestamp="20260907T000000Z",
    )
    assert manifest["candidate_runtime"]["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert manifest["evaluation_harness"] == {
        "source_commit": "b" * 40,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "semantic_artifact_schema_version": SEMANTIC_EVALUATION_ARTIFACT_VERSION,
        "worker_schema_version": "integration_v7_real_dev_worker_v1",
    }
    assert manifest["relationship_to_14a"] == "NEW_VERSIONED_EVALUATION_RUN_NOT_HISTORICAL_REPAIR"
    assert manifest["retry_policy"] == "NO_RETRY"
    assert manifest["system_a"] == "NOT_RUN"
    assert manifest["holdout"] == "NOT_RUN / DENY"
    assert manifest["semantic_scoring"] == manifest["manual_scoring"] == "NOT_DONE"
    assert manifest["artifact_files"] == list(ARTIFACT_FILES)


def test_summary_has_descriptive_only_counts_and_no_semantic_score():
    case = _cases()[0]
    plan = build_semantic_run_plan(_cases())
    diagnostic = _safe_diagnostic_record(case, plan[0], _valid_payload())
    semantic = _semantic_run_record(case, _valid_payload())
    score = _automatic_score_record(case, plan[0], _valid_payload())
    summary = build_semantic_summary([diagnostic], [semantic], [score])
    assert summary["run_counts"] == {"expected": 18, "observed": 1, "valid": 1, "invalid": 0}
    assert summary["semantic_artifact_counts"] == {
        "available": 1,
        "not_applicable_invalid": 0,
    }
    assert summary["terminal_counts"] == {"completed": 1, "refused": 0, "failed": 0}
    assert summary["semantic_scoring"] == summary["manual_scoring"] == "NOT_DONE"
    assert "semantic_correctness" not in repr(summary)


def test_historical_outputs_and_nonempty_15b_output_are_protected(tmp_path: Path):
    for path in PROTECTED_RESULT_DIRS:
        with pytest.raises(RunnerPreflightError):
            _assert_independent_output(path)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "prior.json").write_text("prior\n", encoding="utf-8")
    with pytest.raises(RunnerPreflightError):
        _assert_independent_output(occupied)
    _assert_independent_output(tmp_path / "empty")
    assert DEFAULT_OUTPUT_DIR.resolve() not in {path.resolve() for path in PROTECTED_RESULT_DIRS}


def test_writer_creates_exactly_the_configured_safe_file_set(tmp_path: Path):
    case = _cases()[0]
    plan = build_semantic_run_plan(_cases())
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
    semantic_rows = [json.loads(line) for line in (tmp_path / "semantic_runs.jsonl").read_text(encoding="utf-8").splitlines()]
    diagnostic_rows = [json.loads(line) for line in (tmp_path / "diagnostic_runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert semantic_rows[0]["final"]["answer"]
    assert "answer" not in repr(diagnostic_rows).lower()


def test_runner_has_one_current_harness_worker_invocation_per_case_without_provider_execution():
    source = inspect.getsource(run_semantic_candidate_dev)
    assert source.count("_invoke_current_harness_worker(") == 1
    assert source.count("semantic_runs.append(") == 1
    assert source.count("for item in plan:") == 1
    assert "retry" not in source.lower()
    assert "HOLDOUT_DATASET_PATH" not in source
    assert "semantic_score" not in source
