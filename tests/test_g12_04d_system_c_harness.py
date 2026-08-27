from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import evaluation.gate12.system_c_contract as contract
from evaluation.gate12.baseline_contract import (
    BaselineContractError,
    InfrastructureFailure,
    build_request_payload,
    load_frozen_final_dataset,
    route_case,
)
from scripts import run_g12_system_c as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE12_DIR = REPO_ROOT / "evaluation" / "gate12"
SYSTEM_C_VALID_FORMAL_EVALUATOR_COMMIT = (
    "c2ca9bd5c52ab1b7f9e94e869cd716be53dce0e0"
)


def _case(case_id: str) -> dict[str, Any]:
    dataset = load_frozen_final_dataset(GATE12_DIR)
    return next(case for case in dataset["cases"] if case["case_id"] == case_id)


def _evidence(kind: str, path: str = "core/example.py", evidence_id: str = "E1") -> dict[str, Any]:
    if kind == "knowledge":
        return {
            "evidence_id": evidence_id,
            "kind": kind,
            "source_name": "tool-calling/overview.md",
            "chunk_id": "chunk-1",
            "score": 1.0,
            "rank": 1,
            "snippet": "bounded knowledge",
        }
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "path": path,
        "start_line": 1,
        "end_line": 3,
        "snippet": "def test_or_implementation():\n    assert True\n",
    }


def _response(
    *,
    status: str = "completed",
    answer: str | None = "bounded answer",
    reason_code: str | None = None,
    failure_code: str | None = None,
    trace: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "engineering_query_response_v1",
        "status": status,
        "answer": answer,
        "reason_code": reason_code,
        "failure_code": failure_code,
        "iterations_used": 2,
        "tool_calls_used": 1,
        "tool_errors_used": 0,
        "trace": trace or [],
        "evidence": evidence or [],
    }


def _normalize(case_id: str, response: dict[str, Any]) -> dict[str, Any]:
    case = _case(case_id)
    return contract.normalize_system_c_case(
        case,
        response,
        latency_ms=1,
        roots=[REPO_ROOT],
    )


def _automatic_metrics() -> dict[str, Any]:
    return {
        "case_count": 16,
        "evidence_sufficient_cases": 8,
        "premature_finalization_cases": 0,
        "refused_cases": 2,
        "failed_cases": 1,
        "provider_calls": 54,
        "tool_calls": 37,
        "iterations": 53,
        "forbidden_tool_calls": 0,
        "structured_parse_failure_cases": 0,
        "duplicate_tool_stops": 0,
        "budget_stops": 0,
        "guard_specific_refusal_count": 1,
        "change_project_test_evidence_cases": 2,
        "diagnosis_cross_file_shape_satisfied_cases": 2,
        "docs_bilateral_evidence_cases": 2,
        "by_task_family": {
            "Theory <-> Code": {"evidence_sufficient_cases": 2},
            "Change Impact <-> Test": {"evidence_sufficient_cases": 1},
            "Diagnosis / Config": {"evidence_sufficient_cases": 1},
            "Docs <-> Code": {"evidence_sufficient_cases": 1},
        },
    }


def _manual_metrics() -> dict[str, int]:
    return {
        "full_task_success_cases": 2,
        "partial_or_better_cases": 10,
        "claim_grounding_pass": 3,
        "claim_grounding_fail": 4,
    }


def _offline_preflight() -> dict[str, Any]:
    dataset = load_frozen_final_dataset(GATE12_DIR)
    product_identity = contract.validate_product_identity()
    product_identity["finalization_guard"] = "IMPLEMENTED / FROZEN"
    api_preflight = {
        project_id: {
            "endpoints": {"query": f"http://{project_id}.test/engineering/query"},
            "capabilities": {
                "schema_version": "capabilities_response_v1",
                "engineering_agent": True,
            },
            "knowledge": contract.KNOWLEDGE_STATUS,
            "public_project_identity": {
                "project_name": project_id,
                "source": "configured",
            },
            "runtime_binding_attestation": "operator_started_api_with_configured_project_root",
        }
        for project_id in ("my_agent", "pydantic_ai")
    }
    return {
        "roots": {
            "evaluator": REPO_ROOT,
            "my_agent": REPO_ROOT,
            "pydantic_ai": REPO_ROOT,
            "knowledge_corpus": REPO_ROOT,
        },
        "dataset": dataset,
        "acceptance_contract": contract.load_system_c_acceptance_contract(),
        "product": {
            "evaluator_commit": "a" * 40,
            "evaluator_commit_attestation": "locally_verified",
            "system_c_product_commit": contract.SYSTEM_C_PRODUCT_COMMIT,
            "system_c_product_commit_attestation": "locally_verified",
            "product_source_paths": ["core/", "api/", "demo/", "config.yaml"],
            "current_product_diff_clean": True,
            "allowed_intervention_paths": [],
            "observed_intervention_paths": [],
            "intervention_diff_summary": {"product_source_paths_clean": True},
            "product_identity": product_identity,
        },
        "project_validation": {
            "projects": {
                "my_agent": {
                    "checkout": {
                        "head": "465dd65e950e9c4a119820a5a27f558e74ad5892"
                    }
                },
                "pydantic_ai": {
                    "checkout": {
                        "head": "bfa8e9187b86aad7ec583665ab2743fadea458b1"
                    }
                },
            }
        },
        "api_preflight": api_preflight,
    }


def test_system_c_frozen_identities_and_acceptance_hash_are_exact():
    dataset = load_frozen_final_dataset(GATE12_DIR)
    acceptance = contract.load_system_c_acceptance_contract()

    assert len(dataset["cases"]) == 16
    assert dataset["identity"]["gate12_dataset_freeze_id"] == "gate12-v1-630fc8b527c2"
    assert contract.SYSTEM_C_PRODUCT_COMMIT == "65ee45eb52c45e95d2871aa9060416dabcd3d759"
    assert acceptance["acceptance_contract_sha256"] == contract.SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256
    assert acceptance["baseline"]["run_id"] == "g12-baseline-a-formal-20260825-195305"


def test_provider_plane_reclassification_record_is_immutable_and_explicit():
    record = json.loads(
        (GATE12_DIR / "system_c_invalid_run_v1.json").read_text(encoding="utf-8")
    )
    assert record["run_id"] == "g12-system-c-formal-20260826-173039"
    assert record["original_harness_classification"] == "VALID / MANUAL GOLD PENDING"
    assert record["reviewer_corrected_classification"] == "INVALID / PROVIDER-PLANE FAILURE"
    assert record["reason"]["failure_observation"] == (
        "16/16 cases returned ACTION_PROVIDER_ERROR on the first Decision"
    )
    assert record["reason"]["provider_calls"] == 16
    assert record["reason"]["iterations"] == 16
    assert record["reason"]["tool_calls"] == 0
    assert record["reason"]["guard_blocks"] == 0
    assert record["guard_intervention_reached"] is False
    assert record["formal_ab_conclusion"] == "NOT MEASURED"
    assert record["original_artifact_unchanged"] is True
    assert all(
        len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
        for digest in record["original_artifact_sha256"].values()
    )
    assert record["original_artifact_sha256"]["run_report.md"] == (
        "420f9c95b4ddac273078bc6a1a8bc51793f1bc2b82e34a294dd640e4d4a65d0e"
    )


def test_product_attestation_proves_exact_04c_intervention_paths(
    monkeypatch: pytest.MonkeyPatch,
):
    # G12-04D attests the historical Formal evaluator checkout. Post-G12
    # productization may change current HEAD and must not redefine the
    # frozen System C product attestation retroactively.
    formal_evaluator_commit = SYSTEM_C_VALID_FORMAL_EVALUATOR_COMMIT
    monkeypatch.setattr(
        contract,
        "validate_evaluator_checkout",
        lambda evaluator_commit, evaluator_git_root: (
            REPO_ROOT,
            formal_evaluator_commit,
        ),
    )
    attestation = contract.validate_system_c_product_attestation(
        evaluator_git_root=REPO_ROOT,
        evaluator_commit=formal_evaluator_commit,
    )
    assert attestation["current_product_diff_clean"] is True
    assert attestation["intervention_diff_summary"]["exact_allowed_product_intervention"] is True
    assert attestation["observed_intervention_paths"] == list(
        contract.SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS
    )


def test_product_attestation_rejects_product_surface_drift(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        contract,
        "validate_evaluator_checkout",
        lambda evaluator_commit, evaluator_git_root: (REPO_ROOT, "a" * 40),
    )

    def fake_git(*args: Any) -> subprocess.CompletedProcess[str]:
        if "--quiet" in args:
            return subprocess.CompletedProcess(args, 1, "", "")
        if "--name-only" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                "\n".join(contract.SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS),
                "",
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(contract, "_git", fake_git)
    with pytest.raises(BaselineContractError, match="product differs"):
        contract.validate_system_c_product_attestation(
            evaluator_git_root=REPO_ROOT,
            evaluator_commit="a" * 40,
        )


def test_request_payload_and_routing_exclude_evaluator_metadata():
    my_case = _case("g12q001")
    external_case = _case("g12q008")
    assert build_request_payload(my_case) == {"question": my_case["question"]}
    assert set(build_request_payload(my_case)) == {"question"}
    assert route_case(
        my_case,
        my_agent_url="http://a.test/engineering/query",
        pydantic_ai_url="http://b.test/engineering/query",
    ) == "http://a.test/engineering/query"
    assert route_case(
        external_case,
        my_agent_url="http://a.test/engineering/query",
        pydantic_ai_url="http://b.test/engineering/query",
    ) == "http://b.test/engineering/query"


def test_evaluator_shape_is_independent_of_product_router_result():
    result = _normalize(
        "g12q005",
        _response(
            evidence=[
                _evidence("project_change", "core/changed.py"),
                _evidence("project_test", "tests/test_changed.py", evidence_id="E2"),
            ]
        ),
    )
    assert result["evidence_sufficient"] is True
    assert result["evidence_kind_counts"] == {"project_change": 1, "project_test": 1}


def test_completed_with_insufficient_evaluator_shape_is_premature():
    result = _normalize("g12q005", _response(evidence=[_evidence("project_change")]))
    assert result["evidence_sufficient"] is False
    assert result["premature_finalization"] is True


def test_guard_block_recovery_requires_later_progress_completion_and_sufficiency():
    trace = [
        {
            "event_type": "finalization_guard_blocked",
            "guard_status": "blocked",
            "missing_evidence_groups": [["project_test"]],
            "distinct_project_code_paths": 0,
            "required_min_distinct_project_code_paths": 0,
        },
        {"event_type": "tool_observation", "tool_name": "read_project_context"},
    ]
    recovered = _normalize(
        "g12q005",
        _response(
            trace=trace,
            evidence=[
                _evidence("project_change"),
                _evidence("project_test", "tests/test_changed.py", evidence_id="E2"),
            ],
        ),
    )
    assert recovered["guard_block_count"] == 1
    assert recovered["guard_blocked"] is True
    assert recovered["guard_recovery_attempted"] is True
    assert recovered["guard_recovery_succeeded"] is True

    incomplete = _normalize(
        "g12q005",
        _response(trace=trace, evidence=[_evidence("project_change")]),
    )
    assert incomplete["guard_recovery_attempted"] is True
    assert incomplete["guard_recovery_succeeded"] is False


def test_guard_specific_refusal_is_counted_separately():
    result = _normalize(
        "g12q005",
        _response(
            status="refused",
            answer=None,
            reason_code="INSUFFICIENT_EVIDENCE_TO_FINALIZE",
            trace=[
                {
                    "event_type": "finalization_guard_blocked",
                    "guard_status": "blocked",
                    "missing_evidence_groups": [["project_test"]],
                    "distinct_project_code_paths": 0,
                    "required_min_distinct_project_code_paths": 0,
                }
            ],
        ),
    )
    assert result["guard_final_refusal"] is True
    assert result["guard_specific_refusal_count"] == 1
    assert result["premature_finalization"] is False
    assert contract.find_provider_plane_failures([result]) == []


def test_guard_trace_error_alone_does_not_make_a_specific_refusal():
    result = _normalize(
        "g12q005",
        _response(
            status="refused",
            answer=None,
            reason_code="INSUFFICIENT_INFORMATION",
            trace=[
                {
                    "event_type": "runtime_stopped",
                    "error_code": "INSUFFICIENT_EVIDENCE_TO_FINALIZE",
                }
            ],
        ),
    )
    assert result["guard_final_refusal"] is False
    assert result["guard_specific_refusal_count"] == 0


def test_guard_recovery_attempt_remains_true_when_a_later_block_has_no_activity():
    result = _normalize(
        "g12q005",
        _response(
            trace=[
                {
                    "event_type": "finalization_guard_blocked",
                    "guard_status": "blocked",
                    "missing_evidence_groups": [["project_test"]],
                    "distinct_project_code_paths": 0,
                    "required_min_distinct_project_code_paths": 0,
                },
                {"event_type": "tool_observation", "tool_name": "read_project_context"},
                {
                    "event_type": "finalization_guard_blocked",
                    "guard_status": "blocked",
                    "missing_evidence_groups": [["project_test"]],
                    "distinct_project_code_paths": 0,
                    "required_min_distinct_project_code_paths": 0,
                },
            ],
            evidence=[_evidence("project_change")],
        ),
    )
    assert result["guard_recovery_attempted"] is True
    assert result["guard_recovery_succeeded"] is False


def test_guard_recovery_requires_actual_missing_group_or_path_progress():
    result = _normalize(
        "g12q005",
        _response(
            trace=[
                {
                    "event_type": "finalization_guard_blocked",
                    "guard_status": "blocked",
                    "missing_evidence_groups": [],
                    "distinct_project_code_paths": 1,
                    "required_min_distinct_project_code_paths": 1,
                },
                {"event_type": "tool_observation", "tool_name": "read_project_context"},
            ],
            evidence=[_evidence("project_change"), _evidence("project_test", evidence_id="E2")],
        ),
    )
    assert result["evidence_sufficient"] is True
    assert result["guard_recovery_attempted"] is True
    assert result["guard_recovery_succeeded"] is False


def test_safe_trace_rejects_absolute_local_path():
    with pytest.raises(InfrastructureFailure, match="absolute local path"):
        contract.safe_system_c_trace(
            [{"event_type": "tool_observation", "tool_name": "C:\\private\\tool"}]
        )


def test_provider_calls_sum_each_decision_completed_event():
    result = _normalize(
        "g12q001",
        _response(
            trace=[
                {"event_type": "decision_completed", "provider_call_count": 1},
                {"event_type": "decision_completed", "provider_call_count": 2},
                {"event_type": "decision_completed", "provider_call_count": 1},
            ],
            evidence=[_evidence("knowledge"), _evidence("project_code")],
        ),
    )
    assert result["provider_call_count"] == 4


def test_parse_failure_code_is_counted_even_without_trace_category():
    result = _normalize(
        "g12q001",
        _response(status="failed", answer=None, failure_code="ACTION_PARSE_FAILED"),
    )
    metrics = contract.summarize_system_c_metrics(
        [contract.add_system_c_case_flags(result, _case("g12q001"))]
    )
    assert metrics["overall"]["structured_parse_failure_cases"] == 1


def test_safe_trace_rejects_question_prompt_and_unknown_fields():
    with pytest.raises(InfrastructureFailure):
        contract.safe_system_c_trace([{"event_type": "decision_completed", "question": "leak"}])
    with pytest.raises(InfrastructureFailure):
        contract.safe_system_c_trace([{"event_type": "decision_completed", "unknown": True}])
    with pytest.raises(InfrastructureFailure):
        contract.safe_system_c_trace([{"event_type": "decision_completed", "chain_of_thought": "secret"}])


def test_product_attestation_rejects_prompt_budget_or_registry_drift(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        contract,
        "validate_evaluator_checkout",
        lambda evaluator_commit, evaluator_git_root: (REPO_ROOT, "a" * 40),
    )
    def fake_git(*args: Any) -> subprocess.CompletedProcess[str]:
        output = "\n".join(contract.SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS)
        return subprocess.CompletedProcess(args, 0, output if "--name-only" in args else "", "")

    monkeypatch.setattr(contract, "_git", fake_git)
    monkeypatch.setattr(
        contract,
        "validate_product_identity",
        lambda: {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "prompt_version": "engineering_agent_decision_prompt_v3",
            "prompt_sha256": "0" * 64,
            "repair_prompt_version": "engineering_action_repair_prompt_v1",
            "repair_prompt_sha256": "958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636",
            "max_parse_repairs": 1,
            "max_output_tokens": 1200,
            "budget": {"max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2},
            "registry_size": 7,
            "provider_network_retries": 0,
        },
    )
    with pytest.raises(BaselineContractError, match="identity drift"):
        contract.validate_system_c_product_attestation(
            evaluator_git_root=REPO_ROOT,
            evaluator_commit="a" * 40,
        )


def test_system_c_metrics_report_change_diagnosis_docs_and_guard_slices():
    change = contract.add_system_c_case_flags(
        _normalize(
            "g12q005",
            _response(
                evidence=[
                    _evidence("project_change"),
                    _evidence("project_test", "tests/test_changed.py", evidence_id="E2"),
                ]
            ),
        ),
        _case("g12q005"),
    )
    diagnosis = contract.add_system_c_case_flags(
        _normalize(
            "g12q009",
            _response(
                evidence=[
                    _evidence("project_code", "core/a.py"),
                    _evidence("project_code", "core/b.py", evidence_id="E2"),
                ]
            ),
        ),
        _case("g12q009"),
    )
    docs = contract.add_system_c_case_flags(
        _normalize(
            "g12q013",
            _response(
                evidence=[
                    _evidence("project_doc", "docs/a.md"),
                    _evidence("project_code", "core/a.py", evidence_id="E2"),
                ]
            ),
        ),
        _case("g12q013"),
    )
    metrics = contract.summarize_system_c_metrics([change, diagnosis, docs])
    overall = metrics["overall"]
    assert overall["change_project_test_evidence_cases"] == 1
    assert overall["diagnosis_cross_file_shape_satisfied_cases"] == 1
    assert overall["docs_bilateral_evidence_cases"] == 1


def test_acceptance_is_pending_without_manual_gold_and_classifies_complete_runs():
    automatic = _automatic_metrics()
    pending = contract.evaluate_system_c_acceptance(automatic)
    assert pending["workflow_status"] == "VALID / MANUAL GOLD PENDING"
    assert pending["final_classification"] == "PENDING_MANUAL_REVIEW"
    assert pending["manual_metrics"]["full_task_success_cases"] == "NOT SCORED"

    complete = contract.evaluate_system_c_acceptance(automatic, _manual_metrics())
    assert complete["workflow_status"] == "VALID / MANUAL GOLD COMPLETE"
    assert complete["final_classification"] == "PASS"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("premature_finalization_cases", 1),
        ("change_project_test_evidence_cases", 1),
        ("diagnosis_cross_file_shape_satisfied_cases", 1),
        ("docs_bilateral_evidence_cases", 1),
        ("provider_calls", 73),
    ],
)
def test_acceptance_threshold_failures_are_not_silently_passed(field: str, value: int):
    automatic = _automatic_metrics()
    automatic[field] = value
    if field == "premature_finalization_cases":
        automatic["evidence_sufficient_cases"] = 8
    result = contract.evaluate_system_c_acceptance(automatic, _manual_metrics())
    assert result["final_classification"] in {"MIXED", "FAIL"}
    if field == "premature_finalization_cases":
        assert result["final_classification"] == "FAIL"


def test_acceptance_invalid_is_distinct_from_valid_fail():
    invalid = contract.evaluate_system_c_acceptance({}, invalid=True)
    assert invalid["final_classification"] == "INVALID"
    automatic = _automatic_metrics()
    automatic["severe_reliability_regression"] = True
    failed = contract.evaluate_system_c_acceptance(automatic, _manual_metrics())
    assert failed["final_classification"] == "FAIL"


@pytest.mark.parametrize(
    "failure_code",
    [
        "ACTION_PARSE_FAILED",
        "AGENT_DUPLICATE_TOOL_CALL",
        "AGENT_BUDGET_EXCEEDED",
    ],
)
def test_non_provider_failures_remain_valid_agent_outcomes(failure_code: str):
    result = _normalize(
        "g12q001",
        _response(status="failed", answer=None, failure_code=failure_code),
    )
    assert contract.is_provider_plane_failure(failure_code) is False
    assert contract.find_provider_plane_failures([result]) == []


@pytest.mark.parametrize("failure_code", ["ACTION_PROVIDER_ERROR", "ACTION_TIMEOUT"])
def test_http_200_provider_failure_invalidates_run(
    failure_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[str, str, Any]] = []

    def fake_client(method: str, url: str, payload: Any) -> runner.HttpReply:
        calls.append((method, url, payload))
        response = _response(status="failed", answer=None, failure_code=failure_code)
        response["iterations_used"] = 1
        response["tool_calls_used"] = 0
        response["trace"] = [
            {"event_type": "decision_completed", "provider_call_count": 1}
        ]
        return runner.HttpReply(status_code=200, payload=response)

    monkeypatch.setattr(runner, "run_preflight", lambda **kwargs: _offline_preflight())
    monkeypatch.setattr(runner, "_validate_output_root", lambda output_root, evaluator_root: tmp_path)
    output = runner.execute_system_c(
        client=fake_client,
        my_agent_url="http://my_agent.test/engineering/query",
        pydantic_ai_url="http://pydantic_ai.test/engineering/query",
        evaluator_git_root=REPO_ROOT,
        evaluator_commit="a" * 40,
        my_agent_root=REPO_ROOT,
        pydantic_ai_root=REPO_ROOT,
        corpus_root=REPO_ROOT,
        output_root=tmp_path,
        run_id=f"offline-provider-failure-{failure_code.lower()}",
    )

    assert len(calls) == 1
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    snapshot = json.loads((output / "acceptance_snapshot.json").read_text(encoding="utf-8"))
    invalidity = json.loads(
        (output / "provider_plane_failure.json").read_text(encoding="utf-8")
    )
    assert manifest["run_status"] == "INVALID / PROVIDER-PLANE FAILURE"
    assert manifest["final_classification"] == "INVALID"
    assert manifest["baseline_comparison"]["manual_task_success_comparison"] == "NOT MEASURED"
    assert summary["final_classification"] == "INVALID"
    assert summary["valid_for_system_c_acceptance"] is False
    assert snapshot["workflow_status"] == "INVALID / PROVIDER-PLANE FAILURE"
    assert snapshot["final_classification"] == "INVALID"
    assert snapshot["invalid_reason"] == "PROVIDER-PLANE FAILURE"
    assert invalidity["provider_plane_failure_codes"] == [failure_code]
    assert invalidity["attempted_case_count"] == 1
    assert invalidity["completed_case_count"] == 0
    assert invalidity["system_c_effect"] == "NOT MEASURED"
    assert invalidity["formal_ab_conclusion"] == "NOT MEASURED"
    assert invalidity["manual_gold"] == "NOT STARTED"
    assert "manual_review_template.jsonl" not in {path.name for path in output.iterdir()}


def test_provider_failure_preserves_partial_diagnostics_without_valid_conclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[str, str, Any]] = []
    first = _response(
        evidence=[_evidence("knowledge"), _evidence("project_code", evidence_id="E2")]
    )
    first["trace"] = [
        {"event_type": "decision_completed", "provider_call_count": 2}
    ]
    first["tool_calls_used"] = 1
    second = _response(status="failed", answer=None, failure_code="ACTION_PROVIDER_ERROR")
    second["iterations_used"] = 1
    second["tool_calls_used"] = 0
    second["trace"] = [
        {"event_type": "decision_completed", "provider_call_count": 1}
    ]
    responses = [first, second]

    def fake_client(method: str, url: str, payload: Any) -> runner.HttpReply:
        calls.append((method, url, payload))
        return runner.HttpReply(status_code=200, payload=responses[len(calls) - 1])

    monkeypatch.setattr(runner, "run_preflight", lambda **kwargs: _offline_preflight())
    monkeypatch.setattr(runner, "_validate_output_root", lambda output_root, evaluator_root: tmp_path)
    output = runner.execute_system_c(
        client=fake_client,
        my_agent_url="http://my_agent.test/engineering/query",
        pydantic_ai_url="http://pydantic_ai.test/engineering/query",
        evaluator_git_root=REPO_ROOT,
        evaluator_commit="a" * 40,
        my_agent_root=REPO_ROOT,
        pydantic_ai_root=REPO_ROOT,
        corpus_root=REPO_ROOT,
        output_root=tmp_path,
        run_id="offline-provider-partial-run",
    )

    assert len(calls) == 2
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    invalidity = manifest["invalidity"]
    results = [
        json.loads(line)
        for line in (output / "case_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(results) == 2
    assert results[0]["status"] == "completed"
    assert results[1]["failure_code"] == "ACTION_PROVIDER_ERROR"
    assert invalidity["attempted_case_count"] == 2
    assert invalidity["completed_case_count"] == 1
    assert invalidity["failed_case_ids"] == [results[1]["case_id"]]
    assert invalidity["cost_before_failure"] == {
        "provider_calls": 3,
        "tool_calls": 1,
        "iterations": 3,
    }
    assert summary["overall"]["provider_calls"] == 3
    assert summary["overall"]["tool_calls"] == 1
    assert summary["overall"]["iterations"] == 3
    assert manifest["final_classification"] == "INVALID"


def test_latency_major_regression_is_cost_diagnostic_not_invalid():
    automatic = _automatic_metrics()
    automatic["avg_latency_ms"] = 250.0
    automatic["baseline_avg_latency_ms"] = 100.0
    result = contract.evaluate_system_c_acceptance(automatic, _manual_metrics())
    assert result["final_classification"] == "FAIL"
    assert result["gates"]["latency_major_regression"] is False
    assert result["final_classification"] != "INVALID"


def test_guard_refusal_threshold_prevents_full_pass():
    automatic = _automatic_metrics()
    automatic["guard_specific_refusal_count"] = 5
    result = contract.evaluate_system_c_acceptance(automatic, _manual_metrics())
    assert result["final_classification"] == "MIXED"


def test_artifact_safety_rejects_local_paths_raw_provider_and_cot(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"answer": str(REPO_ROOT / "core" / "secret.py")}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe local path"):
        contract.validate_system_c_artifact_safety(tmp_path, [REPO_ROOT])

    bad.write_text(json.dumps({"raw_provider_response": "secret"}), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="forbidden sensitive field"):
        contract.validate_system_c_artifact_safety(tmp_path, [REPO_ROOT])

    bad.write_text(json.dumps({"chain_of_thought": "private"}), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="forbidden sensitive field"):
        contract.validate_system_c_artifact_safety(tmp_path, [REPO_ROOT])

    bad.write_text(json.dumps({"prompt": "system prompt"}), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="forbidden prompt"):
        contract.validate_system_c_artifact_safety(tmp_path, [REPO_ROOT])


def test_offline_fake_two_api_run_writes_pending_artifacts_and_routes_all_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    preflight = _offline_preflight()
    calls: list[tuple[str, str, Any]] = []

    def fake_client(method: str, url: str, payload: Any) -> runner.HttpReply:
        calls.append((method, url, payload))
        return runner.HttpReply(status_code=200, payload=_response())

    monkeypatch.setattr(runner, "run_preflight", lambda **kwargs: preflight)
    monkeypatch.setattr(runner, "_validate_output_root", lambda output_root, evaluator_root: tmp_path)
    output = runner.execute_system_c(
        client=fake_client,
        my_agent_url="http://my_agent.test/engineering/query",
        pydantic_ai_url="http://pydantic_ai.test/engineering/query",
        evaluator_git_root=REPO_ROOT,
        evaluator_commit="a" * 40,
        my_agent_root=REPO_ROOT,
        pydantic_ai_root=REPO_ROOT,
        corpus_root=REPO_ROOT,
        output_root=tmp_path,
        run_id="offline-system-c-run",
    )
    assert len(calls) == 16
    assert all(method == "POST" and set(payload or {}) == {"question"} for method, _, payload in calls)
    assert sum("my_agent.test" in url for _, url, _ in calls) == 8
    assert sum("pydantic_ai.test" in url for _, url, _ in calls) == 8
    assert {
        path.name for path in output.iterdir()
    } == {
        "manifest.json",
        "summary.json",
        "case_results.jsonl",
        "acceptance_snapshot.json",
        "manual_review_template.jsonl",
        "run_report.md",
    }
    snapshot = json.loads((output / "acceptance_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["final_classification"] == "PENDING_MANUAL_REVIEW"
    assert "by_task_family" in snapshot["automatic_metrics"]


def test_frozen_benchmark_files_have_no_worktree_diff():
    paths = [
        "evaluation/gate12/final_benchmark_v1.jsonl",
        "evaluation/gate12/final_benchmark_manifest_v1.json",
        "evaluation/gate12/reviewer_selection_v1.json",
        "evaluation/gate12/system_c_acceptance_contract_v1.json",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *paths],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""
