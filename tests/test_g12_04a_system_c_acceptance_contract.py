"""Deterministic checks for the frozen G12 System C acceptance contract."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "evaluation" / "gate12" / "system_c_acceptance_contract_v1.json"


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _canonical_payload(contract: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in contract.items() if key != "acceptance_contract_sha256"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _classify(contract: dict[str, Any], metrics: dict[str, Any], *, invalid: bool = False) -> str:
    if invalid:
        return "INVALID"
    primary = contract["primary_thresholds"]
    grounding = contract["grounding_thresholds"]
    outcome = contract["outcome_thresholds"]
    cost = contract["cost_thresholds"]
    reliability = contract["reliability_thresholds"]
    premature = metrics["premature_finalization_cases"]
    evidence = metrics["evidence_sufficiency_cases"]
    full = metrics["full_task_success_cases"]
    severe_collapse = metrics.get("severe_refusal_collapse", False)
    severe_cost = metrics.get("severe_cost_regression", False)
    severe_reliability = metrics.get("severe_reliability_regression", False)
    if (
        premature > primary["premature_finalization_cases_max"]
        or evidence < 6
        or full < primary["full_task_success_cases_min"]
        or severe_collapse
        or severe_cost
        or severe_reliability
    ):
        return "FAIL"
    pass_gates = (
        evidence >= primary["evidence_sufficiency_cases_min"]
        and full >= primary["full_task_success_cases_min"]
        and metrics["partial_or_better_cases"] >= primary["partial_or_better_cases_min"]
        and metrics["claim_grounding_pass"] >= grounding["claim_grounding_pass_cases_min"]
        and metrics["claim_grounding_fail"] <= grounding["claim_grounding_fail_cases_max"]
        and metrics["refused_cases"] <= outcome["refused_cases_max"]
        and metrics["failed_cases"] <= outcome["failed_cases_max"]
        and metrics["provider_calls"] <= cost["provider_calls_max"]
        and metrics["tool_calls"] <= cost["tool_calls_max"]
        and metrics["iterations"] <= cost["iterations_max"]
        and metrics["forbidden_tool_calls"] <= reliability["forbidden_tool_calls_max"]
        and metrics["structured_parse_failure_cases"] <= reliability["structured_parse_failure_cases_max"]
        and metrics["duplicate_tool_stops"] <= reliability["duplicate_tool_stops_max"]
        and metrics["budget_stops"] <= reliability["budget_stops_max"]
    )
    if pass_gates:
        return "PASS"
    if premature == 0 and evidence >= 6 and not severe_collapse and not severe_cost and not severe_reliability:
        return "MIXED"
    return "FAIL"


def _passing_metrics() -> dict[str, Any]:
    return {
        "premature_finalization_cases": 0,
        "evidence_sufficiency_cases": 8,
        "full_task_success_cases": 2,
        "partial_or_better_cases": 9,
        "claim_grounding_pass": 3,
        "claim_grounding_fail": 5,
        "refused_cases": 5,
        "failed_cases": 2,
        "provider_calls": 72,
        "tool_calls": 52,
        "iterations": 72,
        "forbidden_tool_calls": 0,
        "structured_parse_failure_cases": 1,
        "duplicate_tool_stops": 1,
        "budget_stops": 2,
    }


def test_contract_hash_and_baseline_identity_are_exact():
    contract = _load_contract()
    expected_hash = hashlib.sha256(_canonical_payload(contract)).hexdigest()
    assert contract["acceptance_contract_sha256"] == expected_hash
    assert contract["baseline"]["run_id"] == "g12-baseline-a-formal-20260825-195305"
    assert contract["baseline"]["dataset_freeze_id"] == "gate12-v1-630fc8b527c2"
    assert contract["baseline"]["product_baseline_commit"] == "0a1f42e8ee0320486dbd0ddc01400e1e19150501"
    assert contract["baseline"]["metrics"]["provider_calls"] == 54
    assert contract["baseline"]["metrics"]["tool_calls"] == 37
    assert contract["baseline"]["metrics"]["iterations"] == 53


def test_system_c_intervention_and_product_controls_are_frozen():
    contract = _load_contract()
    controls = contract["system_c_required_controls"]
    assert controls["intervention"] == [
        "deterministic typed Evidence Requirement",
        "system-level Finalization Guard",
    ]
    assert controls["prompt_version"] == "engineering_agent_decision_prompt_v2"
    assert controls["prompt_sha256"] == "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
    assert controls["max_output_tokens"] == 1200
    assert controls["budget"] == {"max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2}
    assert controls["toolset"] == [
        "calculator", "code_search", "read_project_context", "knowledge_search",
        "changed_files", "git_diff", "find_tests",
    ]
    assert controls["registry_size"] == 7
    assert controls["project_snapshots"] == {
        "my_agent": "465dd65e950e9c4a119820a5a27f558e74ad5892",
        "pydantic_ai": "bfa8e9187b86aad7ec583665ab2743fadea458b1",
    }
    assert controls["formal_request_fields"] == ["question"]
    assert controls["knowledge_corpus"] == {
        "corpus_id": "870e5864df67",
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": "dbc497c796d5",
    }
    assert controls["gold_metadata_injected"] is False
    assert controls["task_family_hint_injected"] is False


def test_primary_family_transfer_and_utility_thresholds_are_frozen():
    thresholds = _load_contract()["primary_thresholds"]
    assert thresholds["premature_finalization_cases_max"] == 0
    assert thresholds["evidence_sufficiency_cases_min"] == 8
    assert thresholds["family_evidence_sufficiency_min"] == {
        "Theory <-> Code": 2,
        "Change Impact <-> Test": 1,
        "Diagnosis / Config": 1,
        "Docs <-> Code": 1,
    }
    assert thresholds["change_project_test_evidence_min"] == 2
    assert thresholds["diagnosis_cross_file_shape_cases_min"] == 2
    assert thresholds["diagnosis_cross_file_shape_denominator"] == 3
    assert thresholds["docs_bilateral_evidence_cases_min"] == 2
    assert thresholds["full_task_success_cases_min"] == 2
    assert thresholds["partial_or_better_cases_min"] == 9


def test_grounding_outcome_cost_and_reliability_thresholds_are_frozen():
    contract = _load_contract()
    assert contract["grounding_thresholds"] == {
        "claim_grounding_pass_cases_min": 3,
        "claim_grounding_fail_cases_max": 5,
    }
    assert contract["outcome_thresholds"] == {
        "refused_cases_max": 5,
        "guard_specific_insufficient_evidence_refusals_max": 4,
        "failed_cases_max": 2,
        "always_refuse_is_success": False,
    }
    assert contract["cost_thresholds"]["provider_calls_max"] == 72
    assert contract["cost_thresholds"]["tool_calls_max"] == 52
    assert contract["cost_thresholds"]["iterations_max"] == 72
    assert contract["cost_thresholds"]["average_latency_major_regression_factor"] == 2.0
    assert contract["cost_thresholds"]["latency_alone_invalidates_run"] is False
    assert contract["reliability_thresholds"] == {
        "forbidden_tool_calls_max": 0,
        "structured_parse_failure_cases_max": 1,
        "duplicate_tool_stops_max": 1,
        "budget_stops_max": 2,
        "hard_budget": {"max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2},
        "registry_size": 7,
    }


def test_requirement_source_and_anti_leakage_contract_is_generic():
    contract = _load_contract()
    integrity = contract["requirement_source_integrity"]
    assert integrity["source"] == "product/system-side generic bounded logic"
    assert integrity["evaluator_gold_is_not_requirement_source"] is True
    assert integrity["generic_task_semantics_only"] is True
    assert set(integrity["forbidden_request_fields"]) == {
        "case_id",
        "task_family",
        "required_evidence_groups",
        "requires_cross_file",
        "min_distinct_project_code_paths",
        "gold_obligations",
        "gold_source_paths",
        "source_candidate_id",
    }
    assert all(contract["anti_leakage_rules"].values())
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert re.search(r"g12q\d{3}", text) is None
    assert ".py" not in text
    assert "docs/" not in text
    assert "tests/" not in text


def test_classification_precedence_is_deterministic_for_synthetic_metrics():
    contract = _load_contract()
    assert _classify(contract, _passing_metrics()) == "PASS"

    mixed = _passing_metrics()
    mixed["evidence_sufficiency_cases"] = 6
    assert _classify(contract, mixed) == "MIXED"

    fail = _passing_metrics()
    fail["premature_finalization_cases"] = 1
    assert _classify(contract, fail) == "FAIL"

    assert _classify(contract, _passing_metrics(), invalid=True) == "INVALID"
    assert contract["classification_rules"]["precedence"] == ["INVALID", "FAIL", "PASS", "MIXED"]


def test_tradeoff_controls_and_formal_policy_are_frozen():
    contract = _load_contract()
    assert contract["guard_invariants"] == {
        "completed_with_insufficient_evidence_max": 0,
        "premature_finalization_is_correctness_gate": True,
        "guard_must_not_always_refuse": True,
    }
    assert contract["q004_q006_tradeoff_audit"] == {
        "required": True,
        "purpose": "audit shape sufficiency against semantic task success and prevent an always-refuse interpretation",
        "baseline_shape_sufficient_but_partial": True,
        "baseline_shape_insufficient_but_pass": True,
    }
    assert contract["formal_policy"]["system_c_formal_status"] == "NOT RUN"
    assert contract["formal_policy"]["official_run_policy"] == "one complete benchmark run; no cherry-picking individual cases"
    assert contract["formal_policy"]["previous_invalid_runs_retained"] is True
