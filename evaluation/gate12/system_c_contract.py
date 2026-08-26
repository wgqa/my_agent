"""Evaluator-only contract for the G12 System C benchmark.

This module measures the public response shape produced by System C.  It does
not route product requirements, inspect answer semantics, or score Manual
Gold.  Frozen case metadata is used only on the evaluator side to calculate
the structural evidence gates defined by the 04A contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.gate12.baseline_contract import (
    BaselineContractError,
    InfrastructureFailure,
    KNOWLEDGE_STATUS,
    PUBLIC_EVIDENCE_KINDS,
    PRODUCT_BASELINE_COMMIT,
    sanitize_for_artifact,
    validate_baseline_artifact_safety,
    validate_engineering_response,
    validate_product_identity,
)
from scripts.run_g11_05_docs_code_consistency import validate_evaluator_checkout


GATE12_DIR = Path(__file__).resolve().parent
SYSTEM_C_WORKFLOW_ID = "g12-system-c-evaluation-v1"
SYSTEM_C_MANIFEST_SCHEMA = "g12_system_c_manifest_v1"
SYSTEM_C_PRODUCT_COMMIT = "65ee45eb52c45e95d2871aa9060416dabcd3d759"
SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS = (
    "api/app.py",
    "core/engineering_agent.py",
    "core/engineering_requirements.py",
    "core/tool_agent/__init__.py",
    "core/tool_agent/runtime.py",
    "core/tool_agent/runtime_models.py",
)
SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256 = (
    "5a9d190dcb585a29097fac206c14aa0f31c27d178d8fe0cae8d72b1b8c17bb8f"
)

SYSTEM_C_BASELINE_METRICS = {
    "case_count": 16,
    "full_task_success_pass": 2,
    "full_task_success_partial": 8,
    "full_task_success_fail": 6,
    "strict_full_task_success_rate": 0.125,
    "partial_or_better_cases": 10,
    "partial_or_better_rate": 0.625,
    "evidence_sufficiency_cases": 2,
    "premature_finalization_cases": 12,
    "claim_grounding_pass": 1,
    "claim_grounding_partial": 8,
    "claim_grounding_fail": 7,
    "evidence_coverage_full": 1,
    "evidence_coverage_partial": 8,
    "evidence_coverage_none": 7,
    "provider_calls": 54,
    "tool_calls": 37,
    "iterations": 53,
    "forbidden_tool_calls": 0,
    "structured_parse_failure_cases": 1,
    "duplicate_tool_stops": 1,
    "budget_stops": 0,
    "refused_cases": 1,
    "failed_cases": 1,
}

_TRACE_EVENT_TYPES = frozenset(
    {
        "decision_completed",
        "tool_call_created",
        "tool_observation",
        "finalization_guard_blocked",
        "runtime_stopped",
    }
)
_PARSE_CATEGORIES = frozenset(
    {
        "EMPTY_OUTPUT",
        "OUTPUT_TRUNCATED",
        "INVALID_JSON",
        "DUPLICATE_KEY",
        "ACTION_SCHEMA_INVALID",
        "UNKNOWN_TOOL",
        "ARGUMENTS_SCHEMA_INVALID",
    }
)
_SAFE_TRACE_KEYS = frozenset(
    {
        "iteration",
        "event_type",
        "action_type",
        "tool_name",
        "call_id",
        "tool_status",
        "error_code",
        "iterations_used",
        "tool_calls_used",
        "tool_errors_used",
        "provider_call_count",
        "repair_attempted",
        "repair_succeeded",
        "parse_failure_category",
        "guard_status",
        "missing_evidence_groups",
        "distinct_project_code_paths",
        "required_min_distinct_project_code_paths",
    }
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/][^\s\"'<>]+|\\\\[^\\/\s\"'<>]+[\\/][^\\/\s\"'<>]+(?:[\\/][^\s\"'<>]+)?)"
)
_FORBIDDEN_TRACE_KEYS = frozenset(
    {
        "question",
        "answer",
        "task_family",
        "requirement_profile",
        "required_evidence_groups",
        "gold",
        "gold_obligations",
        "gold_source_paths",
        "prompt",
        "prompt_text",
        "reasoning",
        "thought",
        "chain_of_thought",
        "raw_output",
        "provider_response",
    }
)
_FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "question",
        "prompt",
        "prompt_text",
        "full_prompt",
        "reasoning",
        "thought",
        "chain_of_thought",
        "private_cot",
        "raw_output",
        "provider_response",
        "raw_provider_response",
    }
)


def load_system_c_acceptance_contract() -> dict[str, Any]:
    """Load the immutable 04A contract and verify its self-attested hash."""

    path = GATE12_DIR / "system_c_acceptance_contract_v1.json"
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineContractError("System C acceptance contract cannot be loaded") from exc
    if not isinstance(contract, dict):
        raise BaselineContractError("System C acceptance contract must be an object")
    payload = {
        key: value for key, value in contract.items() if key != "acceptance_contract_sha256"
    }
    observed = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if contract.get("acceptance_contract_sha256") != observed:
        raise BaselineContractError("System C acceptance contract hash mismatch")
    if observed != SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256:
        raise BaselineContractError("System C acceptance contract identity drift")
    return contract


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _full_sha(value: object, label: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise BaselineContractError(f"{label} must be a full 40-character SHA")
    return value.lower()


def validate_system_c_product_attestation(
    *,
    evaluator_git_root: str | Path,
    evaluator_commit: str,
    system_c_product_commit: str = SYSTEM_C_PRODUCT_COMMIT,
) -> dict[str, Any]:
    """Bind the evaluator to the frozen 04C product while allowing evaluator files."""

    evaluator_root, normalized_evaluator = validate_evaluator_checkout(
        evaluator_commit, evaluator_git_root=evaluator_git_root
    )
    product_commit = _full_sha(system_c_product_commit, "system_c_product_commit")
    if product_commit != SYSTEM_C_PRODUCT_COMMIT:
        raise BaselineContractError("System C product commit is not frozen")
    if product_commit == PRODUCT_BASELINE_COMMIT:
        raise BaselineContractError("System C product commit must include the frozen Guard")
    exists = _git(evaluator_root, "cat-file", "-e", f"{product_commit}^{{commit}}")
    if exists.returncode != 0:
        raise BaselineContractError("System C product commit is unavailable")
    baseline_exists = _git(
        evaluator_root, "cat-file", "-e", f"{PRODUCT_BASELINE_COMMIT}^{{commit}}"
    )
    if baseline_exists.returncode != 0:
        raise BaselineContractError("product baseline commit is unavailable")
    intervention = _git(
        evaluator_root,
        "diff",
        "--name-only",
        PRODUCT_BASELINE_COMMIT,
        product_commit,
        "--",
        "core",
        "api",
        "demo",
        "config.yaml",
    )
    if intervention.returncode != 0:
        raise BaselineContractError("could not inspect System C intervention diff")
    intervention_paths = tuple(
        line.replace("\\", "/") for line in intervention.stdout.splitlines() if line
    )
    if set(intervention_paths) != set(SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS):
        raise BaselineContractError("System C product intervention paths drifted")
    product_paths = ("core", "api", "demo", "config.yaml")
    product_diff = _git(
        evaluator_root,
        "diff",
        "--quiet",
        product_commit,
        normalized_evaluator,
        "--",
        *product_paths,
    )
    if product_diff.returncode == 1:
        raise BaselineContractError("current product differs from frozen System C commit")
    if product_diff.returncode != 0:
        raise BaselineContractError("could not verify current product diff")
    changed = _git(
        evaluator_root,
        "diff",
        "--name-only",
        product_commit,
        normalized_evaluator,
    )
    if changed.returncode != 0:
        raise BaselineContractError("could not inspect evaluator intervention paths")
    observed_paths = [line.replace("\\", "/") for line in changed.stdout.splitlines() if line]
    identity = validate_product_identity()
    expected_identity = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "prompt_version": "engineering_agent_decision_prompt_v2",
        "prompt_sha256": "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107",
        "repair_prompt_version": "engineering_action_repair_prompt_v1",
        "repair_prompt_sha256": "958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636",
        "max_parse_repairs": 1,
        "max_output_tokens": 1200,
        "budget": {"max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2},
        "registry_size": 7,
        "provider_network_retries": 0,
    }
    if any(identity.get(key) != value for key, value in expected_identity.items()):
        raise BaselineContractError("System C product identity drift")
    identity["finalization_guard"] = "IMPLEMENTED / FROZEN"
    return {
        "evaluator_commit": normalized_evaluator,
        "evaluator_commit_attestation": "operator_declared_and_locally_verified_checkout",
        "system_c_product_commit": product_commit,
        "system_c_product_commit_attestation": "locally_verified_product_source_and_frozen_guard_commit",
        "product_source_paths": ["core/", "api/", "demo/", "config.yaml"],
        "current_product_diff_clean": True,
        "allowed_intervention_paths": list(SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS),
        "observed_intervention_paths": list(intervention_paths),
        "evaluator_paths_since_system_c_product": observed_paths,
        "intervention_diff_summary": {
            "baseline_product_commit": PRODUCT_BASELINE_COMMIT,
            "system_c_product_commit": product_commit,
            "allowed_product_paths": list(SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS),
            "observed_product_paths": list(intervention_paths),
            "exact_allowed_product_intervention": True,
            "product_source_paths_clean": True,
            "tracked_paths_changed_since_product_commit": len(observed_paths),
        },
        "product_identity": identity,
    }


def _validate_safe_trace_event(event: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(event) - _SAFE_TRACE_KEYS
    if unknown or set(event) & _FORBIDDEN_TRACE_KEYS:
        raise InfrastructureFailure("trace contains an unsafe or unknown field")
    event_type = event.get("event_type")
    if event_type not in _TRACE_EVENT_TYPES:
        raise InfrastructureFailure("trace contains an invalid event type")
    for key in (
        "iteration",
        "iterations_used",
        "tool_calls_used",
        "tool_errors_used",
    ):
        if key in event and (type(event[key]) is not int or event[key] < 0):
            raise InfrastructureFailure("trace contains an invalid usage counter")
    if "provider_call_count" in event and (
        type(event["provider_call_count"]) is not int
        or event["provider_call_count"] < 0
    ):
        raise InfrastructureFailure("trace contains an invalid provider counter")
    for key in ("repair_attempted", "repair_succeeded"):
        if key in event and type(event[key]) is not bool:
            raise InfrastructureFailure("trace contains an invalid repair flag")
    if event.get("repair_succeeded") is True and event.get("repair_attempted") is not True:
        raise InfrastructureFailure("trace repair success lacks repair attempt")
    if "parse_failure_category" in event and event["parse_failure_category"] not in _PARSE_CATEGORIES:
        raise InfrastructureFailure("trace contains an invalid parse category")
    for key in ("tool_name", "tool_status", "action_type", "error_code", "call_id"):
        if key in event and event[key] is not None and type(event[key]) is not str:
            raise InfrastructureFailure("trace contains an invalid string field")
        if key in event and type(event.get(key)) is str and _ABSOLUTE_PATH_RE.search(event[key]):
            raise InfrastructureFailure("trace contains an absolute local path")
    if event_type == "finalization_guard_blocked":
        if event.get("guard_status") != "blocked":
            raise InfrastructureFailure("Guard trace event must be blocked")
        groups = event.get("missing_evidence_groups", [])
        if isinstance(groups, (str, bytes)) or not isinstance(groups, list):
            raise InfrastructureFailure("Guard trace missing groups are invalid")
        for group in groups:
            if isinstance(group, (str, bytes)) or not isinstance(group, list) or not group:
                raise InfrastructureFailure("Guard trace evidence group is invalid")
            if any(kind not in PUBLIC_EVIDENCE_KINDS for kind in group):
                raise InfrastructureFailure("Guard trace contains an invalid evidence kind")
        for key in ("distinct_project_code_paths", "required_min_distinct_project_code_paths"):
            if key in event and (type(event[key]) is not int or event[key] < 0):
                raise InfrastructureFailure("Guard trace path count is invalid")
    elif any(
        key in event
        for key in (
            "guard_status",
            "missing_evidence_groups",
            "distinct_project_code_paths",
            "required_min_distinct_project_code_paths",
        )
    ):
        raise InfrastructureFailure("Guard fields are only valid on Guard events")
    return copy.deepcopy(dict(event))


def safe_system_c_trace(trace: object) -> list[dict[str, Any]]:
    """Validate and copy the public 04C trace without retaining model text."""

    if not isinstance(trace, list):
        raise InfrastructureFailure("engineering trace must be a list")
    return [_validate_safe_trace_event(event) if isinstance(event, Mapping) else _invalid_trace() for event in trace]


def _invalid_trace() -> dict[str, Any]:
    raise InfrastructureFailure("engineering trace event must be an object")


def _tool_sequence(trace: Iterable[Mapping[str, Any]]) -> list[str]:
    return [
        event["tool_name"]
        for event in trace
        if event.get("event_type") == "tool_observation"
        and type(event.get("tool_name")) is str
    ]


def _trace_aggregation(trace: list[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = [event for event in trace if event.get("event_type") == "decision_completed"]
    provider_counts = [
        event["provider_call_count"]
        for event in decisions
        if type(event.get("provider_call_count")) is int
        and event["provider_call_count"] >= 0
    ]
    guard_indexes = [
        index for index, event in enumerate(trace) if event.get("event_type") == "finalization_guard_blocked"
    ]
    later_activity = any(
        event.get("event_type") in {"tool_call_created", "tool_observation"}
        for guard_index in guard_indexes
        for index, event in enumerate(trace)
        if index > guard_index
    )
    return {
        "provider_call_count": sum(provider_counts),
        "repair_attempted": any(event.get("repair_attempted") is True for event in decisions),
        "repair_succeeded": any(event.get("repair_succeeded") is True for event in decisions),
        "initial_parse_categories": [
            event["parse_failure_category"]
            for event in decisions
            if type(event.get("parse_failure_category")) is str
        ],
        "guard_block_count": len(guard_indexes),
        "guard_blocked": bool(guard_indexes),
        "guard_later_activity": later_activity,
    }


def _evidence_counts(evidence: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(
        item.get("kind")
        for item in evidence
        if isinstance(item, Mapping) and item.get("kind") in PUBLIC_EVIDENCE_KINDS
    )
    return dict(sorted(counts.items()))


def _evidence_paths(
    evidence: Iterable[Mapping[str, Any]], *, kind: str = "project_code"
) -> set[str]:
    return {
        item["path"].replace("\\", "/")
        for item in evidence
        if isinstance(item, Mapping)
        and item.get("kind") == kind
        and type(item.get("path")) is str
    }


def _structural_progress(
    trace: list[Mapping[str, Any]],
    *,
    missing_evidence_groups: Iterable[Iterable[str]],
    distinct_project_code_paths: int,
    evidence_sufficient: bool,
    final_evidence_kinds: Iterable[str] = (),
    final_evidence_paths: Iterable[str] = (),
) -> bool:
    """Detect evidence progress after a Guard block using trace-local facts."""

    blocks = [
        event
        for event in trace
        if event.get("event_type") == "finalization_guard_blocked"
    ]
    if not blocks:
        return False
    current_missing = {tuple(group) for group in missing_evidence_groups}
    final_kinds = set(final_evidence_kinds)
    final_paths = set(final_evidence_paths)
    for block in blocks:
        block_index = max(
            position
            for position, event in enumerate(trace)
            if event is block
        )
        later = trace[block_index + 1 :]
        if not any(event.get("event_type") in {"tool_call_created", "tool_observation"} for event in later):
            continue
        previous_missing = {
            tuple(group) for group in block.get("missing_evidence_groups", [])
        }
        previous_paths = block.get("distinct_project_code_paths")
        if any(
            group not in current_missing
            and any(kind in final_kinds for kind in group)
            for group in previous_missing
        ):
            return True
        if type(previous_paths) is int and (
            distinct_project_code_paths > previous_paths
            or len(final_paths) > previous_paths
        ):
            return True
    return False


def normalize_system_c_case(
    case: Mapping[str, Any],
    response: object,
    *,
    latency_ms: float,
    roots: Iterable[Path],
) -> dict[str, Any]:
    """Normalize one valid HTTP-200 outcome and compute evaluator-side facts."""

    response = validate_engineering_response(response)
    raw_trace = safe_system_c_trace(response["trace"])
    raw_evidence = response["evidence"]
    shape_counts = _evidence_counts(raw_evidence)
    code_paths = _evidence_paths(raw_evidence)
    missing_groups = [
        list(group)
        for group in case["required_evidence_groups"]
        if not any(shape_counts.get(kind, 0) >= 1 for kind in group)
    ]
    cross_file_satisfied = (
        len(code_paths) >= case["min_distinct_project_code_paths"]
        if case["requires_cross_file"]
        else True
    )
    evidence_sufficient = not missing_groups and cross_file_satisfied
    trace = sanitize_for_artifact(raw_trace, roots)
    evidence = sanitize_for_artifact(raw_evidence, roots)
    sequence = _tool_sequence(raw_trace)
    required_tools = list(case.get("required_tools", []))
    forbidden_tools = list(case.get("forbidden_tools", []))
    required_coverage = {tool: tool in sequence for tool in required_tools}
    forbidden_calls = [tool for tool in sequence if tool in forbidden_tools]
    aggregation = _trace_aggregation(raw_trace)
    status = response["status"]
    guard_final_refusal = (
        status == "refused"
        and response.get("reason_code") == "INSUFFICIENT_EVIDENCE_TO_FINALIZE"
    )
    progress = _structural_progress(
        raw_trace,
        missing_evidence_groups=missing_groups,
        distinct_project_code_paths=len(code_paths),
        evidence_sufficient=evidence_sufficient,
        final_evidence_kinds=shape_counts,
        final_evidence_paths=code_paths,
    )
    recovery_attempted = aggregation["guard_blocked"] and aggregation["guard_later_activity"]
    recovery_succeeded = (
        aggregation["guard_blocked"]
        and progress
        and status == "completed"
        and evidence_sufficient
    )
    premature = status == "completed" and not evidence_sufficient
    trace_codes = {
        event.get("error_code") for event in raw_trace if type(event.get("error_code")) is str
    }
    failure_code = response.get("failure_code")
    layers: list[str] = []
    if aggregation["initial_parse_categories"] or failure_code == "ACTION_PARSE_FAILED":
        layers.append("L1 Transport / Parsing")
    if (
        failure_code in {"AGENT_DUPLICATE_TOOL_CALL", "AGENT_BUDGET_EXCEEDED", "AGENT_TOOL_ERROR_LIMIT"}
        or trace_codes & {"AGENT_DUPLICATE_TOOL_CALL", "AGENT_BUDGET_EXCEEDED"}
        or forbidden_calls
    ):
        layers.append("L2 Planning / Tool-loop")
    if premature or guard_final_refusal:
        layers.append("L3 Evidence Acquisition")
    return {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "project_id": case["project_id"],
        "source_candidate_id": case["source_candidate_id"],
        "source_candidate_sha256": case["source_candidate_sha256"],
        "status": status,
        "answer": sanitize_for_artifact(response.get("answer"), roots),
        "reason_code": sanitize_for_artifact(response.get("reason_code"), roots),
        "failure_code": sanitize_for_artifact(failure_code, roots),
        "iterations_used": response["iterations_used"],
        "tool_calls_used": response["tool_calls_used"],
        "tool_errors_used": response["tool_errors_used"],
        "safe_trace": trace,
        "tool_sequence": sequence,
        "public_evidence": evidence,
        "latency_ms": round(float(latency_ms), 2),
        "evidence_kind_counts": shape_counts,
        "final_evidence_kinds": sorted(shape_counts),
        "final_evidence_paths": sorted(
            {
                item["path"].replace("\\", "/")
                for item in raw_evidence
                if isinstance(item, Mapping)
                and item.get("kind") in {
                    "project_code",
                    "project_doc",
                    "project_change",
                    "project_test",
                }
                and type(item.get("path")) is str
            }
        ),
        "distinct_project_code_paths": len(code_paths),
        "evidence_sufficient": evidence_sufficient,
        "missing_evidence_groups": missing_groups,
        "cross_file_shape_satisfied": cross_file_satisfied,
        "required_tool_coverage": required_coverage,
        "forbidden_tool_calls": forbidden_calls,
        "non_required_tool_calls": [tool for tool in sequence if tool not in required_tools],
        "premature_finalization": premature,
        "provider_call_count": aggregation["provider_call_count"],
        "repair_attempted": aggregation["repair_attempted"],
        "repair_succeeded": aggregation["repair_succeeded"],
        "initial_parse_categories": aggregation["initial_parse_categories"],
        "duplicate_tool_stop": (
            failure_code == "AGENT_DUPLICATE_TOOL_CALL"
            or "AGENT_DUPLICATE_TOOL_CALL" in trace_codes
        ),
        "budget_stop": (
            failure_code == "AGENT_BUDGET_EXCEEDED"
            or "AGENT_BUDGET_EXCEEDED" in trace_codes
        ),
        "guard_block_count": aggregation["guard_block_count"],
        "guard_blocked": aggregation["guard_blocked"],
        "guard_recovery_attempted": recovery_attempted,
        "guard_recovery_succeeded": recovery_succeeded,
        "guard_final_refusal": guard_final_refusal,
        "guard_specific_refusal_count": int(guard_final_refusal),
        "structural_failure_layers": layers,
    }


def _metrics_for_cases(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(cases)
    sequence_total = sum(len(item.get("tool_sequence", [])) for item in cases)
    required_total = sum(len(item.get("required_tool_coverage", {})) for item in cases)
    required_hits = sum(
        sum(value is True for value in item.get("required_tool_coverage", {}).values())
        for item in cases
    )
    forbidden_calls = sum(len(item.get("forbidden_tool_calls", [])) for item in cases)
    kinds = Counter(
        kind
        for item in cases
        for kind, value in item.get("evidence_kind_counts", {}).items()
        if value >= 1
    )
    applicable_cross = [item for item in cases if item.get("_requires_cross_file") is True]
    change_cases = [item for item in cases if item.get("task_family") == "Change Impact <-> Test"]
    diagnosis_cross = [
        item
        for item in cases
        if item.get("task_family") == "Diagnosis / Config"
        and item.get("_requires_cross_file") is True
    ]
    docs_cases = [item for item in cases if item.get("task_family") == "Docs <-> Code"]
    provider_total = sum(item.get("provider_call_count", 0) for item in cases)
    tool_total = sum(item.get("tool_calls_used", 0) for item in cases)
    iteration_total = sum(item.get("iterations_used", 0) for item in cases)
    result: dict[str, Any] = {
        "case_count": count,
        "completed_cases": sum(item.get("status") == "completed" for item in cases),
        "refused_cases": sum(item.get("status") == "refused" for item in cases),
        "failed_cases": sum(item.get("status") == "failed" for item in cases),
        "completion_rate": 0,
        "refusal_rate": 0,
        "failure_rate": 0,
        "evidence_sufficient_cases": sum(item.get("evidence_sufficient") is True for item in cases),
        "evidence_sufficiency_rate": 0,
        "premature_finalization_cases": sum(
            item.get("premature_finalization") is True for item in cases
        ),
        "premature_finalization_rate": 0,
        "required_tool_complete_cases": sum(
            all(item.get("required_tool_coverage", {}).values()) for item in cases
        ),
        "required_tool_coverage_rate": required_hits / required_total if required_total else 0,
        "forbidden_tool_calls": forbidden_calls,
        "forbidden_tool_call_rate": forbidden_calls / sequence_total if sequence_total else 0,
        "non_required_tool_calls": sum(len(item.get("non_required_tool_calls", [])) for item in cases),
        "evidence_kind_coverage": dict(sorted(kinds.items())),
        "cross_file_applicable_cases": len(applicable_cross),
        "cross_file_shape_satisfied_cases": sum(
            item.get("cross_file_shape_satisfied") is True for item in applicable_cross
        ),
        "cross_file_shape_rate": (
            sum(item.get("cross_file_shape_satisfied") is True for item in applicable_cross)
            / len(applicable_cross)
            if applicable_cross
            else 0
        ),
        "provider_calls_total": provider_total,
        "provider_calls": provider_total,
        "tool_calls_total": tool_total,
        "tool_calls": tool_total,
        "iterations_total": iteration_total,
        "iterations": iteration_total,
        "tool_errors_total": sum(item.get("tool_errors_used", 0) for item in cases),
        "avg_provider_calls": provider_total / count if count else 0,
        "avg_tool_calls": tool_total / count if count else 0,
        "avg_iterations": iteration_total / count if count else 0,
        "latency_ms_total": round(sum(item.get("latency_ms", 0) for item in cases), 2),
        "avg_latency_ms": round(
            sum(item.get("latency_ms", 0) for item in cases) / count, 2
        )
        if count
        else 0,
        "structured_parse_failure_cases": sum(
            bool(item.get("initial_parse_categories"))
            or "L1 Transport / Parsing" in item.get("structural_failure_layers", [])
            for item in cases
        ),
        "repair_attempted_cases": sum(item.get("repair_attempted") is True for item in cases),
        "repair_succeeded_cases": sum(item.get("repair_succeeded") is True for item in cases),
        "duplicate_tool_stop_cases": sum(item.get("duplicate_tool_stop") is True for item in cases),
        "duplicate_tool_stops": sum(item.get("duplicate_tool_stop") is True for item in cases),
        "budget_stop_cases": sum(item.get("budget_stop") is True for item in cases),
        "budget_stops": sum(item.get("budget_stop") is True for item in cases),
        "guard_block_count": sum(item.get("guard_block_count", 0) for item in cases),
        "guard_blocked_cases": sum(item.get("guard_blocked") is True for item in cases),
        "guard_recovery_attempted_cases": sum(
            item.get("guard_recovery_attempted") is True for item in cases
        ),
        "guard_recovery_succeeded_cases": sum(
            item.get("guard_recovery_succeeded") is True for item in cases
        ),
        "guard_final_refusal_cases": sum(item.get("guard_final_refusal") is True for item in cases),
        "guard_specific_refusal_count": sum(
            item.get("guard_specific_refusal_count", 0) for item in cases
        ),
        "forbidden_tool_calls_rate": forbidden_calls / sequence_total if sequence_total else 0,
        "change_project_test_evidence_cases": sum(
            item.get("evidence_kind_counts", {}).get("project_test", 0) >= 1
            for item in change_cases
        ),
        "diagnosis_cross_file_shape_satisfied_cases": sum(
            item.get("cross_file_shape_satisfied") is True for item in diagnosis_cross
        ),
        "diagnosis_cross_file_shape_applicable_cases": len(diagnosis_cross),
        "docs_bilateral_evidence_cases": sum(
            item.get("evidence_kind_counts", {}).get("project_doc", 0) >= 1
            and item.get("evidence_kind_counts", {}).get("project_code", 0) >= 1
            for item in docs_cases
        ),
        "l1_transport_parsing_cases": sum(
            "L1 Transport / Parsing" in item.get("structural_failure_layers", [])
            for item in cases
        ),
        "l2_planning_tool_loop_cases": sum(
            "L2 Planning / Tool-loop" in item.get("structural_failure_layers", [])
            for item in cases
        ),
        "l3_evidence_acquisition_cases": sum(
            "L3 Evidence Acquisition" in item.get("structural_failure_layers", [])
            for item in cases
        ),
    }
    result["completion_rate"] = result["completed_cases"] / count if count else 0
    result["refusal_rate"] = result["refused_cases"] / count if count else 0
    result["failure_rate"] = result["failed_cases"] / count if count else 0
    result["evidence_sufficiency_rate"] = result["evidence_sufficient_cases"] / count if count else 0
    result["premature_finalization_rate"] = result["premature_finalization_cases"] / count if count else 0
    return result


def summarize_system_c_metrics(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Return automatic metrics while keeping Manual Gold explicitly unscored."""

    enriched = []
    for item in cases:
        copied = dict(item)
        copied["_requires_cross_file"] = bool(copied.get("_requires_cross_file", False))
        enriched.append(copied)
    by_family = {
        family: _metrics_for_cases([item for item in enriched if item["task_family"] == family])
        for family in sorted({item["task_family"] for item in enriched})
    }
    by_repository = {
        project: _metrics_for_cases([item for item in enriched if item["project_id"] == project])
        for project in sorted({item["project_id"] for item in enriched})
    }
    overall = _metrics_for_cases(enriched)
    overall["family_evidence_sufficiency"] = {
        family: values["evidence_sufficient_cases"] for family, values in by_family.items()
    }
    return {
        "automatic_scope": "STRUCTURAL ONLY / L4 REASONING AND MANUAL GOLD NOT AUTO SCORED",
        "overall": overall,
        "by_task_family": by_family,
        "by_repository": by_repository,
        "manual_only_metrics": {
            "full_task_success": "NOT SCORED",
            "partial_or_better": "NOT SCORED",
            "evidence_coverage": "NOT SCORED",
            "evidence_correctness": "NOT SCORED",
            "claim_grounding": "NOT SCORED",
            "remediation_correctness": "NOT SCORED",
            "docs_semantic_label_correctness": "NOT SCORED",
        },
    }


def _metric(values: Mapping[str, Any], *keys: str, default: Any = 0) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    return default


def _manual_values(
    metrics: Mapping[str, Any], manual_metrics: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    source: Mapping[str, Any] | None = manual_metrics
    if source is None:
        if all(
            any(name in metrics for name in names)
            for names in (
                ("full_task_success_cases", "task_success_pass", "full_task_success_pass"),
                ("partial_or_better_cases", "task_success_partial_or_better", "partial_or_better"),
                ("claim_grounding_pass", "claim_grounding_pass_cases"),
                ("claim_grounding_fail", "claim_grounding_fail_cases"),
            )
        ):
            source = metrics
    if source is None:
        for key in ("manual_metrics", "manual", "manual_gold"):
            value = metrics.get(key)
            if isinstance(value, Mapping) and any(
                isinstance(item, int) and not isinstance(item, bool) for item in value.values()
            ):
                source = value
                break
    if source is None:
        return None
    aliases = {
        "full_task_success_cases": (
            "full_task_success_cases",
            "task_success_pass",
            "full_task_success_pass",
        ),
        "partial_or_better_cases": (
            "partial_or_better_cases",
            "task_success_partial_or_better",
            "partial_or_better",
        ),
        "claim_grounding_pass": (
            "claim_grounding_pass",
            "claim_grounding_pass_cases",
        ),
        "claim_grounding_fail": (
            "claim_grounding_fail",
            "claim_grounding_fail_cases",
        ),
    }
    result: dict[str, Any] = {}
    for target, names in aliases.items():
        value = _metric(source, *names, default=None)
        if type(value) is not int or value < 0:
            return None
        result[target] = value
    return result


def _family_value(overall: Mapping[str, Any], family: str) -> int:
    family_map = overall.get("family_evidence_sufficiency")
    if isinstance(family_map, Mapping):
        value = family_map.get(family)
        if type(value) is int:
            return value
    by_family = overall.get("by_task_family")
    if isinstance(by_family, Mapping) and isinstance(by_family.get(family), Mapping):
        value = _metric(
            by_family[family],
            "evidence_sufficient_cases",
            "evidence_sufficiency_cases",
            "evidence_sufficiency",
            default=None,
        )
        if type(value) is int and not isinstance(value, bool):
            return value
    return 0


def _acceptance_gates(
    automatic: Mapping[str, Any],
    manual: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, bool]:
    primary = contract["primary_thresholds"]
    grounding = contract["grounding_thresholds"]
    outcome = contract["outcome_thresholds"]
    cost = contract["cost_thresholds"]
    reliability = contract["reliability_thresholds"]
    family_thresholds = primary["family_evidence_sufficiency_min"]
    family_gate = all(
        _family_value(automatic, family) >= minimum
        for family, minimum in family_thresholds.items()
    )
    premature = _metric(
        automatic,
        "premature_finalization_cases",
        "premature_finalizations",
        "premature_finalization_count",
    )
    evidence = _metric(
        automatic,
        "evidence_sufficient_cases",
        "evidence_sufficiency_cases",
        "evidence_sufficiency",
    )
    refused = _metric(automatic, "refused_cases", "refusal_cases")
    failed = _metric(automatic, "failed_cases", "failure_cases")
    guard_refusals = _metric(
        automatic,
        "guard_specific_refusal_count",
        "guard_specific_refusals",
        "guard_final_refusal_cases",
    )
    provider_calls = _metric(automatic, "provider_calls", "provider_calls_total")
    tool_calls = _metric(automatic, "tool_calls", "tool_calls_total")
    iterations = _metric(automatic, "iterations", "iterations_total")
    forbidden = _metric(automatic, "forbidden_tool_calls", "forbidden_tool_call_count")
    parse_failures = _metric(
        automatic,
        "structured_parse_failure_cases",
        "parse_failure_cases",
    )
    duplicate_stops = _metric(
        automatic,
        "duplicate_tool_stops",
        "duplicate_tool_stop_cases",
    )
    budget_stops = _metric(automatic, "budget_stops", "budget_stop_cases")
    change_test = _metric(
        automatic,
        "change_project_test_evidence_cases",
        "change_project_test_cases",
        "change_project_test",
    )
    diagnosis_cross_file = _metric(
        automatic,
        "diagnosis_cross_file_shape_satisfied_cases",
        "diagnosis_cross_file_shape_cases",
        "diagnosis_cross_file_cases",
    )
    docs_bilateral = _metric(
        automatic,
        "docs_bilateral_evidence_cases",
        "docs_bilateral_cases",
        "docs_bilateral",
    )
    severe_refusal = bool(automatic.get("severe_refusal_collapse", False)) or (
        _metric(automatic, "case_count") > 0
        and refused >= _metric(automatic, "case_count")
    )
    latency_major = bool(
        automatic.get("latency_major_regression", False)
        or automatic.get("average_latency_major_regression", False)
    )
    baseline_latency = automatic.get("baseline_avg_latency_ms")
    average_latency = automatic.get("avg_latency_ms")
    if (
        not latency_major
        and type(baseline_latency) in (int, float)
        and type(average_latency) in (int, float)
        and baseline_latency > 0
    ):
        latency_major = average_latency > (
            float(baseline_latency)
            * float(cost["average_latency_major_regression_factor"])
        )
    severe_cost = bool(automatic.get("severe_cost_regression", False)) or latency_major
    severe_reliability = bool(automatic.get("severe_reliability_regression", False))
    return {
        "premature_zero": premature
        == primary["premature_finalization_cases_max"],
        "evidence_primary": evidence
        >= primary["evidence_sufficiency_cases_min"],
        "evidence_fail_floor": evidence >= 6,
        "family_evidence": family_gate,
        "change_project_test": change_test >= primary["change_project_test_evidence_min"],
        "diagnosis_cross_file": diagnosis_cross_file
        >= primary["diagnosis_cross_file_shape_cases_min"],
        "docs_bilateral": docs_bilateral >= primary["docs_bilateral_evidence_cases_min"],
        "full_task_success": manual["full_task_success_cases"] >= primary["full_task_success_cases_min"],
        "partial_or_better": manual["partial_or_better_cases"] >= primary["partial_or_better_cases_min"],
        "grounding_pass": manual["claim_grounding_pass"] >= grounding["claim_grounding_pass_cases_min"],
        "grounding_fail": manual["claim_grounding_fail"] <= grounding["claim_grounding_fail_cases_max"],
        "refusal_limit": refused <= outcome["refused_cases_max"],
        "guard_refusal_limit": guard_refusals
        <= outcome["guard_specific_insufficient_evidence_refusals_max"],
        "failure_limit": failed <= outcome["failed_cases_max"],
        "provider_cost": provider_calls <= cost["provider_calls_max"],
        "tool_cost": tool_calls <= cost["tool_calls_max"],
        "iteration_cost": iterations <= cost["iterations_max"],
        "forbidden_zero": forbidden <= reliability["forbidden_tool_calls_max"],
        "parse_limit": parse_failures <= reliability["structured_parse_failure_cases_max"],
        "duplicate_limit": duplicate_stops <= reliability["duplicate_tool_stops_max"],
        "budget_limit": budget_stops <= reliability["budget_stops_max"],
        "latency_major_regression": not latency_major,
        "no_severe_refusal": not severe_refusal,
        "no_severe_cost": not severe_cost,
        "no_severe_reliability": not severe_reliability,
    }


def evaluate_system_c_acceptance(
    metrics: Mapping[str, Any],
    manual_metrics: Mapping[str, Any] | None = None,
    *,
    invalid: bool = False,
) -> dict[str, Any]:
    """Classify a run, requiring Manual Gold before PASS/MIXED/FAIL."""

    contract = load_system_c_acceptance_contract()
    automatic = dict(metrics.get("overall", metrics)) if isinstance(metrics, Mapping) else {}
    if isinstance(metrics.get("by_task_family"), Mapping):
        automatic["by_task_family"] = metrics["by_task_family"]
    if isinstance(metrics.get("family_evidence_sufficiency"), Mapping):
        automatic["family_evidence_sufficiency"] = metrics["family_evidence_sufficiency"]
    if isinstance(metrics.get("by_repository"), Mapping):
        automatic["by_repository"] = metrics["by_repository"]
    if isinstance(metrics.get("automatic_scope"), str):
        automatic["automatic_scope"] = metrics["automatic_scope"]
    manual = _manual_values(metrics, manual_metrics)
    frozen_thresholds = {
        key: contract[key]
        for key in (
            "primary_thresholds",
            "grounding_thresholds",
            "outcome_thresholds",
            "cost_thresholds",
            "reliability_thresholds",
            "guard_invariants",
        )
    }
    if invalid:
        return {
            "schema_version": "g12_system_c_acceptance_snapshot_v1",
            "acceptance_contract_sha256": SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256,
            "workflow_status": "INVALID / INFRASTRUCTURE FAILURE",
            "final_classification": "INVALID",
            "frozen_thresholds": frozen_thresholds,
            "automatic_metrics": automatic,
            "manual_metrics": manual or "NOT PRODUCED",
        }
    if manual is None:
        return {
            "schema_version": "g12_system_c_acceptance_snapshot_v1",
            "acceptance_contract_sha256": SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256,
            "workflow_status": "VALID / MANUAL GOLD PENDING",
            "final_classification": "PENDING_MANUAL_REVIEW",
            "frozen_thresholds": frozen_thresholds,
            "automatic_metrics": automatic,
            "manual_metrics": {
                "full_task_success_cases": "NOT SCORED",
                "partial_or_better_cases": "NOT SCORED",
                "evidence_coverage": "NOT SCORED",
                "evidence_correctness": "NOT SCORED",
                "claim_grounding": "NOT SCORED",
                "remediation_correctness": "NOT SCORED",
                "docs_semantic_label_correctness": "NOT SCORED",
            },
            "automatic_guard_metrics": {
                "premature_finalization_cases": automatic.get("premature_finalization_cases", 0),
                "evidence_sufficient_cases": automatic.get("evidence_sufficient_cases", 0),
                "guard_block_count": automatic.get("guard_block_count", 0),
            },
        }
    gates = _acceptance_gates(automatic, manual, contract)
    fail_floor = (
        not gates["premature_zero"]
        or not gates["evidence_fail_floor"]
        or not gates["full_task_success"]
        or not gates["no_severe_refusal"]
        or not gates["no_severe_cost"]
        or not gates["no_severe_reliability"]
    )
    pass_gate_names = (
        "premature_zero",
        "evidence_primary",
        "family_evidence",
        "change_project_test",
        "diagnosis_cross_file",
        "docs_bilateral",
        "full_task_success",
        "partial_or_better",
        "grounding_pass",
        "grounding_fail",
        "refusal_limit",
        "guard_refusal_limit",
        "failure_limit",
        "provider_cost",
        "tool_cost",
        "iteration_cost",
        "forbidden_zero",
        "parse_limit",
        "duplicate_limit",
        "budget_limit",
        "no_severe_refusal",
        "no_severe_cost",
        "no_severe_reliability",
    )
    if fail_floor:
        classification = "FAIL"
    elif all(gates[name] for name in pass_gate_names):
        classification = "PASS"
    else:
        classification = "MIXED"
    return {
        "schema_version": "g12_system_c_acceptance_snapshot_v1",
        "acceptance_contract_sha256": SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256,
        "workflow_status": "VALID / MANUAL GOLD COMPLETE",
        "final_classification": classification,
        "frozen_thresholds": frozen_thresholds,
        "automatic_metrics": automatic,
        "manual_metrics": manual,
        "gates": gates,
    }


def build_acceptance_snapshot(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Build a pending snapshot from the full summary, including family slices."""

    return evaluate_system_c_acceptance(metrics)


def build_system_c_manual_review_entry(
    case: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    evidence_references = []
    for item in result.get("public_evidence", []):
        if not isinstance(item, Mapping):
            continue
        evidence_references.append(
            {
                key: item[key]
                for key in ("evidence_id", "kind", "path", "source_name")
                if key in item
            }
        )
    return {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "project_id": case["project_id"],
        "gold_obligations": case["gold_obligations"],
        "gold_source_proofs": case["source_proofs"],
        "agent_final_answer": result.get("answer"),
        "agent_evidence_references": evidence_references,
        "automatic_structural_metrics": {
            "evidence_sufficient": result.get("evidence_sufficient"),
            "premature_finalization": result.get("premature_finalization"),
            "guard_block_count": result.get("guard_block_count", 0),
            "guard_recovery_succeeded": result.get("guard_recovery_succeeded", False),
        },
        "task_success": "NOT SCORED",
        "evidence_coverage": "NOT SCORED",
        "evidence_correctness": "NOT SCORED",
        "claim_grounding": "NOT SCORED",
        "remediation_correctness": "NOT SCORED",
        "docs_semantic_label_correctness": "NOT SCORED",
        "review_notes": "",
    }


def _reject_system_c_artifact_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is str and key.casefold() in _FORBIDDEN_ARTIFACT_KEYS:
                raise BaselineContractError(
                    "System C artifact contains a forbidden prompt or sensitive field"
                )
            if key == "safe_trace" and isinstance(item, list):
                safe_system_c_trace(item)
            _reject_system_c_artifact_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_system_c_artifact_fields(item)


def _reject_system_c_markdown_fields(text: str) -> None:
    """Apply the same sensitive-key rules to JSON embedded in Markdown."""

    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        opening = re.fullmatch(
            r"[ \t]*(?P<fence>`{3,})[ \t]*(?P<info>[^\r\n]*)",
            lines[index].rstrip("\r\n"),
        )
        if opening is None or opening.group("info").strip().casefold() != "json":
            index += 1
            continue
        fence = opening.group("fence")
        closing_index = next(
            (
                cursor
                for cursor in range(index + 1, len(lines))
                if re.fullmatch(
                    rf"[ \t]*`{{{len(fence)},}}[ \t]*",
                    lines[cursor].rstrip("\r\n"),
                )
            ),
            None,
        )
        if closing_index is None:
            index += 1
            continue
        try:
            payload = json.loads("".join(lines[index + 1 : closing_index]))
        except json.JSONDecodeError:
            index = closing_index + 1
            continue
        _reject_system_c_artifact_fields(payload)
        index = closing_index + 1


def validate_system_c_artifact_safety(
    output: Path, roots: Iterable[Path]
) -> None:
    """Validate both local-root secrecy and System C trace/artifact semantics."""

    root_list = list(roots)
    validate_baseline_artifact_safety(output, root_list)
    for path in sorted(output.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        if path.suffix.lower() == ".json":
            documents = [json.loads(path.read_text(encoding="utf-8"))]
        else:
            documents = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        for document in documents:
            _reject_system_c_artifact_fields(document)
    for path in sorted(output.iterdir()):
        if path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
            _reject_system_c_markdown_fields(path.read_text(encoding="utf-8"))


def add_system_c_case_flags(
    result: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    copied = dict(result)
    copied["_requires_cross_file"] = bool(case["requires_cross_file"])
    return copied


__all__ = [
    "GATE12_DIR",
    "SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256",
    "SYSTEM_C_ALLOWED_PRODUCT_INTERVENTION_PATHS",
    "SYSTEM_C_BASELINE_METRICS",
    "SYSTEM_C_MANIFEST_SCHEMA",
    "SYSTEM_C_PRODUCT_COMMIT",
    "SYSTEM_C_WORKFLOW_ID",
    "_evidence_counts",
    "_evidence_paths",
    "_metrics_for_cases",
    "_structural_progress",
    "_tool_sequence",
    "_trace_aggregation",
    "_validate_safe_trace_event",
    "add_system_c_case_flags",
    "build_acceptance_snapshot",
    "build_system_c_manual_review_entry",
    "evaluate_system_c_acceptance",
    "load_system_c_acceptance_contract",
    "normalize_system_c_case",
    "safe_system_c_trace",
    "summarize_system_c_metrics",
    "validate_system_c_artifact_safety",
    "validate_system_c_product_attestation",
]
