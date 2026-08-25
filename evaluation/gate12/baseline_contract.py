"""Frozen structural contract for the G12 Baseline A evaluator.

This module is evaluator infrastructure.  It never decides whether an answer
is semantically correct and never changes Engineering product behavior.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from core.tool_agent.decision_prompt import (
    ACTION_REPAIR_PROMPT_SHA256,
    ACTION_REPAIR_PROMPT_VERSION,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_MAX_OUTPUT_TOKENS,
    max_output_tokens_for_profile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.default_tools import (
    CALCULATOR_SPEC,
    CHANGED_FILES_SPEC,
    CODE_SEARCH_SPEC,
    FIND_TESTS_SPEC,
    GIT_DIFF_SPEC,
    KNOWLEDGE_SEARCH_SPEC,
    READ_PROJECT_CONTEXT_SPEC,
)
from core.tool_agent.integration import FROZEN_TOOL_MODEL, FROZEN_TOOL_PROVIDER
from core.tool_agent.runtime_models import ToolAgentBudget
from evaluation.gate12.candidate_contract import (
    CandidateContractError,
    file_sha256,
    load_json,
    load_jsonl,
    validate_manifest as validate_candidate_manifest,
    validate_pool,
)
from evaluation.gate12.final_contract import (
    FINAL_CASE_MAPPING,
    validate_final_benchmark,
    validate_final_manifest,
)
from scripts.run_g11_03_change_impact import (
    SAFE_TRACE_KEYS,
    _sanitize_for_artifact as _sanitize_single_root,
    _tool_sequence,
    validate_artifact_safety as _validate_single_root_artifact_safety,
)
from scripts.run_g11_05_docs_code_consistency import validate_evaluator_checkout


GATE12_DATASET_FREEZE_ID = "gate12-v1-630fc8b527c2"
FINAL_BENCHMARK_SHA256 = "630fc8b527c22d3e7afc4f4288788524f5dfb52f5ed6ade13ec050abc35f215f"
REVIEWER_SELECTION_SHA256 = "53d93f34a43a3de62a159fc0c8029062ec9390f1d2dfc5cab6d67589b8d98d18"
CANDIDATE_POOL_SHA256 = "d3d217066b72deaaa6bb9f0f20a84b1e97940f16214d96b8f614ed14dd3935b8"
REPOSITORY_MANIFEST_SHA256 = "392279dc0348723ddfebef4eefb1fa269f7b4d67a534c63a4de2344a5571ba43"
PRODUCT_BASELINE_COMMIT = "0a1f42e8ee0320486dbd0ddc01400e1e19150501"
MY_AGENT_COMMIT = "465dd65e950e9c4a119820a5a27f558e74ad5892"
PYDANTIC_AI_COMMIT = "bfa8e9187b86aad7ec583665ab2743fadea458b1"
BASELINE_A_FORMAL_RUN_ID = "g12-baseline-a-formal-20260825-195305"
BASELINE_A_EVALUATOR_COMMIT = "f0852af1a339c72616b69c4ffdbdd6059c42bf5b"
BASELINE_A_CASE_RESULTS_SHA256 = "3db5b4af578eaa48852f39ff89ea898bf2e5bd7629b70f936f387263ab5d7ce0"
BASELINE_A_MANUAL_TEMPLATE_SHA256 = "3eab10fa8279cd3ba132dbe3dcd0bc2d3e5971cca20d8d2a675db46d7b83085f"
BASELINE_A_FORMAL_MANIFEST_SHA256 = "663a33e428fcf88fcd8e2661d2cdb607b947c3ff25f12def67bc2c67a928f7c3"
ENGINEERING_RESPONSE_SCHEMA = "engineering_query_response_v1"
KNOWLEDGE_STATUS = {
    "schema_version": "engineering_knowledge_status_v1",
    "ready": True,
    "verified": True,
    "corpus_id": "870e5864df67",
    "file_count": 37,
    "chunk_count": 215,
    "retrieval_strategy": "bm25",
    "manifest_experiment_id": "dbc497c796d5",
}
VALID_AGENT_STATUSES = frozenset({"completed", "refused", "failed"})
PUBLIC_EVIDENCE_KINDS = frozenset(
    {"knowledge", "project_code", "project_doc", "project_change", "project_test"}
)
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_ARTIFACT_FIELDS = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "cot",
        "full_prompt",
        "messages",
        "model_reasoning",
        "private_cot",
        "private_reasoning",
        "prompt_text",
        "provider_response",
        "raw_model_output",
        "raw_output",
        "raw_provider_response",
    }
)


class BaselineContractError(ValueError):
    """Raised when frozen Baseline A provenance or structural rules drift."""


class InfrastructureFailure(RuntimeError):
    """An HTTP or response-schema problem that invalidates a formal run."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True, encoding="utf-8"
    )


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or not _SHA_RE.fullmatch(value):
        raise BaselineContractError(f"{label} must be a full 40-character SHA")
    return value


def validate_run_id(value: object) -> str:
    if type(value) is not str or not _RUN_ID_RE.fullmatch(value):
        raise BaselineContractError("run_id must be a bounded path-safe identifier")
    return value


def _gate12_paths(gate12_dir: str | Path) -> dict[str, Path]:
    root = Path(gate12_dir)
    return {
        "registry": root / "repositories_v1.json",
        "candidate_pool": root / "candidate_pool_v1.jsonl",
        "candidate_manifest": root / "candidate_pool_manifest_v1.json",
        "final_benchmark": root / "final_benchmark_v1.jsonl",
        "final_manifest": root / "final_benchmark_manifest_v1.json",
        "selection": root / "reviewer_selection_v1.json",
    }


def validate_frozen_dataset_identity(
    final_manifest: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
    *,
    final_benchmark_sha256: str,
    reviewer_selection_sha256: str,
    repository_manifest_sha256: str,
) -> None:
    """Check the immutable G12-02B dataset identity before any API request."""

    expected = {
        "gate12_dataset_freeze_id": GATE12_DATASET_FREEZE_ID,
        "final_benchmark_jsonl_sha256": FINAL_BENCHMARK_SHA256,
        "reviewer_selection_sha256": REVIEWER_SELECTION_SHA256,
        "candidate_pool_sha256": CANDIDATE_POOL_SHA256,
        "repository_manifest_sha256": REPOSITORY_MANIFEST_SHA256,
    }
    observed = {
        "gate12_dataset_freeze_id": final_manifest.get("gate12_dataset_freeze_id"),
        "final_benchmark_jsonl_sha256": final_benchmark_sha256,
        "reviewer_selection_sha256": reviewer_selection_sha256,
        "candidate_pool_sha256": candidate_manifest.get("candidate_pool_sha256"),
        "repository_manifest_sha256": repository_manifest_sha256,
    }
    if observed != expected:
        raise BaselineContractError("frozen G12 dataset identity mismatch")


def load_frozen_final_dataset(gate12_dir: str | Path) -> dict[str, Any]:
    """Load and fully validate the immutable 16-case dataset on disk."""

    paths = _gate12_paths(gate12_dir)
    registry_document = load_json(paths["registry"])
    repositories = registry_document.get("repositories")
    if not isinstance(repositories, dict):
        raise BaselineContractError("repository registry has no repositories map")
    candidates = load_jsonl(paths["candidate_pool"])
    candidate_manifest = load_json(paths["candidate_manifest"])
    cases = load_jsonl(paths["final_benchmark"])
    final_manifest = load_json(paths["final_manifest"])
    selection = load_json(paths["selection"])
    try:
        validate_pool(candidates, repositories)
        validate_candidate_manifest(
            candidate_manifest, candidates, paths["registry"], paths["candidate_pool"]
        )
        validate_final_benchmark(cases, candidates, repositories, candidate_manifest, selection)
        validate_final_manifest(
            final_manifest,
            cases,
            final_benchmark_path=paths["final_benchmark"],
            reviewer_selection_path=paths["selection"],
            candidate_manifest=candidate_manifest,
            repository_manifest_path=paths["registry"],
        )
    except CandidateContractError as exc:
        raise BaselineContractError("frozen G12 final dataset contract failed") from exc
    final_benchmark_sha = file_sha256(paths["final_benchmark"])
    selection_sha = file_sha256(paths["selection"])
    registry_sha = file_sha256(paths["registry"])
    validate_frozen_dataset_identity(
        final_manifest,
        candidate_manifest,
        final_benchmark_sha256=final_benchmark_sha,
        reviewer_selection_sha256=selection_sha,
        repository_manifest_sha256=registry_sha,
    )
    if [(case["case_id"], case["source_candidate_id"]) for case in cases] != list(FINAL_CASE_MAPPING):
        raise BaselineContractError("final case identity mapping drift")
    return {
        "cases": cases,
        "repositories": repositories,
        "candidate_manifest": candidate_manifest,
        "final_manifest": final_manifest,
        "selection": selection,
        "identity": {
            "gate12_dataset_freeze_id": GATE12_DATASET_FREEZE_ID,
            "final_benchmark_sha256": final_benchmark_sha,
            "reviewer_selection_sha256": selection_sha,
            "candidate_pool_sha256": candidate_manifest["candidate_pool_sha256"],
            "repository_manifest_sha256": registry_sha,
        },
    }


def validate_distinct_roots(
    evaluator_root: str | Path,
    my_agent_root: str | Path,
    pydantic_ai_root: str | Path,
    corpus_root: str | Path,
) -> dict[str, Path]:
    roots = {
        "evaluator": Path(evaluator_root).resolve(),
        "my_agent": Path(my_agent_root).resolve(),
        "pydantic_ai": Path(pydantic_ai_root).resolve(),
        "knowledge_corpus": Path(corpus_root).resolve(),
    }
    if any(not root.is_dir() for root in roots.values()):
        raise BaselineContractError("all evaluator, project, and corpus roots must be directories")
    if len({roots["evaluator"], roots["my_agent"], roots["pydantic_ai"]}) != 3:
        raise BaselineContractError("evaluator, my_agent, and pydantic_ai must use distinct roots")
    return roots


def validate_product_identity() -> dict[str, Any]:
    """Read frozen production identities from current product imports."""

    budget = ToolAgentBudget()
    registry_names = {
        CALCULATOR_SPEC.name,
        CODE_SEARCH_SPEC.name,
        READ_PROJECT_CONTEXT_SPEC.name,
        KNOWLEDGE_SEARCH_SPEC.name,
        CHANGED_FILES_SPEC.name,
        GIT_DIFF_SPEC.name,
        FIND_TESTS_SPEC.name,
    }
    expected_budget = {
        "max_agent_iterations": 5,
        "max_tool_calls": 4,
        "max_tool_errors": 2,
    }
    actual_budget = {
        "max_agent_iterations": budget.max_agent_iterations,
        "max_tool_calls": budget.max_tool_calls,
        "max_tool_errors": budget.max_tool_errors,
    }
    if (
        FROZEN_TOOL_PROVIDER != "deepseek"
        or FROZEN_TOOL_MODEL != "deepseek-chat"
        or ENGINEERING_DECISION_PROMPT_V2_PROFILE.version
        != "engineering_agent_decision_prompt_v2"
        or ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256
        != "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
        or ACTION_REPAIR_PROMPT_VERSION != "engineering_action_repair_prompt_v1"
        or ACTION_REPAIR_PROMPT_SHA256
        != "958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636"
        or max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE) != 1
        or max_output_tokens_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE) != 1200
        or ENGINEERING_MAX_OUTPUT_TOKENS != 1200
        or actual_budget != expected_budget
        or len(registry_names) != 7
    ):
        raise BaselineContractError("current production identity differs from frozen Baseline A")
    return {
        "provider": FROZEN_TOOL_PROVIDER,
        "model": FROZEN_TOOL_MODEL,
        "prompt_version": ENGINEERING_DECISION_PROMPT_V2_PROFILE.version,
        "prompt_sha256": ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256,
        "repair_prompt_version": ACTION_REPAIR_PROMPT_VERSION,
        "repair_prompt_sha256": ACTION_REPAIR_PROMPT_SHA256,
        "max_parse_repairs": 1,
        "max_output_tokens": 1200,
        "budget": expected_budget,
        "registry_size": len(registry_names),
        "provider_network_retries": 0,
        "finalization_guard": "NOT IMPLEMENTED",
    }


def validate_product_baseline_attestation(
    *,
    evaluator_git_root: str | Path,
    evaluator_commit: str,
    product_baseline_commit: str,
) -> dict[str, Any]:
    """Require tracked-clean evaluator state and no production-source drift."""

    evaluator_root, normalized_evaluator_commit = validate_evaluator_checkout(
        evaluator_commit, evaluator_git_root=evaluator_git_root
    )
    product_baseline_commit = _require_sha(product_baseline_commit, "product_baseline_commit")
    if product_baseline_commit != PRODUCT_BASELINE_COMMIT:
        raise BaselineContractError("Baseline A must use the frozen product baseline commit")
    exists = _git(evaluator_root, "cat-file", "-e", f"{product_baseline_commit}^{{commit}}")
    if exists.returncode != 0:
        raise BaselineContractError("product baseline commit is not available in evaluator checkout")
    product_diff = _git(
        evaluator_root,
        "diff",
        "--quiet",
        product_baseline_commit,
        normalized_evaluator_commit,
        "--",
        "core",
        "api",
        "demo",
        "config.yaml",
    )
    if product_diff.returncode == 1:
        raise BaselineContractError("production source differs from frozen product baseline")
    if product_diff.returncode != 0:
        raise BaselineContractError("could not verify production baseline source diff")
    return {
        "evaluator_commit": normalized_evaluator_commit,
        "evaluator_commit_attestation": "operator_declared_and_locally_verified_checkout",
        "product_baseline_commit": product_baseline_commit,
        "product_source_paths": ["core/", "api/", "demo/", "config.yaml"],
        "product_source_diff_clean": True,
        "product_identity": validate_product_identity(),
    }


def derive_api_urls(query_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(query_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BaselineContractError("query endpoint must be an absolute HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BaselineContractError("query endpoint must not contain credentials, query, or fragment")
    suffix = "/engineering/query"
    path = parsed.path.rstrip("/")
    if not path.endswith(suffix):
        raise BaselineContractError("query endpoint must end with /engineering/query")
    base_path = path[: -len(suffix)]

    def endpoint(suffix_path: str) -> str:
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, base_path + suffix_path, "", ""))

    return {
        "query": endpoint("/engineering/query"),
        "capabilities": endpoint("/capabilities"),
        "knowledge": endpoint("/engineering/knowledge"),
        "project": endpoint("/project"),
    }


def validate_api_preflight(
    *,
    get_json: Callable[[str], Mapping[str, Any]],
    query_url: str,
    project_root: str | Path,
) -> dict[str, Any]:
    """Validate public API readiness without claiming a Git-SHA API proof."""

    urls = derive_api_urls(query_url)
    capabilities = get_json(urls["capabilities"])
    if capabilities.get("schema_version") != "capabilities_response_v1":
        raise InfrastructureFailure("capabilities response schema mismatch")
    features = capabilities.get("features")
    if not isinstance(features, Mapping) or features.get("engineering_agent") is not True:
        raise InfrastructureFailure("capabilities engineering_agent is not true")
    knowledge = get_json(urls["knowledge"])
    if {key: knowledge.get(key) for key in KNOWLEDGE_STATUS} != KNOWLEDGE_STATUS:
        raise InfrastructureFailure("engineering knowledge endpoint identity mismatch")
    project = get_json(urls["project"])
    expected_project = Path(project_root).resolve().name
    if project.get("source") != "configured" or project.get("project_name") != expected_project:
        raise InfrastructureFailure("project endpoint is not truthfully bound to configured project root")
    return {
        "endpoints": urls,
        "capabilities": {"schema_version": capabilities["schema_version"], "engineering_agent": True},
        "knowledge": dict(KNOWLEDGE_STATUS),
        "public_project_identity": {"project_name": expected_project, "source": "configured"},
        "runtime_binding_attestation": (
            "operator_started_api_with_configured_project_root; /project provides public "
            "identity only and does not cryptographically attest the checkout commit"
        ),
    }


def build_request_payload(case: Mapping[str, Any]) -> dict[str, str]:
    """Return the only evaluator-to-model payload allowed for Baseline A."""

    question = case.get("question")
    if type(question) is not str or not question.strip():
        raise BaselineContractError("frozen case question is invalid")
    return {"question": question}


def route_case(case: Mapping[str, Any], *, my_agent_url: str, pydantic_ai_url: str) -> str:
    project_id = case.get("project_id")
    if project_id == "my_agent":
        return derive_api_urls(my_agent_url)["query"]
    if project_id == "pydantic_ai":
        return derive_api_urls(pydantic_ai_url)["query"]
    raise BaselineContractError("final case has an unknown project routing identity")


def validate_engineering_response(response: object) -> dict[str, Any]:
    """Validate the public API response shape; invalid responses are infra failures."""

    if not isinstance(response, dict):
        raise InfrastructureFailure("engineering query response must be a JSON object")
    expected_keys = {
        "schema_version", "status", "answer", "reason_code", "failure_code",
        "iterations_used", "tool_calls_used", "tool_errors_used", "trace", "evidence",
    }
    if set(response) != expected_keys or response.get("schema_version") != ENGINEERING_RESPONSE_SCHEMA:
        raise InfrastructureFailure("engineering query response schema mismatch")
    if response.get("status") not in VALID_AGENT_STATUSES:
        raise InfrastructureFailure("engineering query response has invalid agent status")
    for field in ("iterations_used", "tool_calls_used", "tool_errors_used"):
        value = response.get(field)
        if type(value) is not int or isinstance(value, bool) or value < 0:
            raise InfrastructureFailure("engineering query response has invalid usage counter")
    for field in ("answer", "reason_code", "failure_code"):
        value = response.get(field)
        if value is not None and type(value) is not str:
            raise InfrastructureFailure("engineering query response has invalid terminal field")
    if response["status"] == "completed" and (not isinstance(response["answer"], str) or not response["answer"].strip()):
        raise InfrastructureFailure("completed response must contain a final answer")
    if not isinstance(response.get("trace"), list) or not all(isinstance(item, dict) for item in response["trace"]):
        raise InfrastructureFailure("engineering query response trace is invalid")
    if not isinstance(response.get("evidence"), list) or not all(isinstance(item, dict) for item in response["evidence"]):
        raise InfrastructureFailure("engineering query response evidence is invalid")
    for item in response["evidence"]:
        kind = item.get("kind")
        if kind not in PUBLIC_EVIDENCE_KINDS or type(item.get("evidence_id")) is not str:
            raise InfrastructureFailure("engineering query response evidence schema is invalid")
        if kind == "knowledge":
            if type(item.get("source_name")) is not str or type(item.get("snippet")) is not str:
                raise InfrastructureFailure("knowledge evidence schema is invalid")
        elif type(item.get("path")) is not str or type(item.get("snippet")) is not str:
            raise InfrastructureFailure("project evidence schema is invalid")
    return response


def _safe_trace(trace: object) -> list[dict[str, Any]]:
    if not isinstance(trace, list):
        return []
    return [
        {key: event[key] for key in SAFE_TRACE_KEYS if key in event}
        for event in trace
        if isinstance(event, dict)
    ]


def _trace_aggregation(trace: list[dict[str, Any]]) -> dict[str, Any]:
    decision_events = [event for event in trace if event.get("event_type") == "decision_completed"]
    decision_call_counts = [
        event["provider_call_count"]
        for event in decision_events
        if type(event.get("provider_call_count")) is int
        and not isinstance(event.get("provider_call_count"), bool)
        and event["provider_call_count"] >= 0
    ]
    parse_categories = [
        event["parse_failure_category"]
        for event in decision_events
        if type(event.get("parse_failure_category")) is str
    ]
    return {
        # Each decision_completed event carries one decision's local call
        # metadata: 1 for a normal decision, 2 when that decision used repair.
        # Summing events preserves the case-level provider-call count.
        "provider_call_count": sum(decision_call_counts),
        "repair_attempted": any(event.get("repair_attempted") is True for event in decision_events),
        "repair_succeeded": any(event.get("repair_succeeded") is True for event in decision_events),
        "initial_parse_categories": parse_categories,
    }


def evaluate_evidence_shape(case: Mapping[str, Any], evidence: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    evidence_list = list(evidence)
    counts = Counter(
        item.get("kind") for item in evidence_list if item.get("kind") in PUBLIC_EVIDENCE_KINDS
    )
    missing_groups = [
        list(group)
        for group in case["required_evidence_groups"]
        if not any(counts.get(kind, 0) >= 1 for kind in group)
    ]
    code_paths = {
        item["path"]
        for item in evidence_list
        if item.get("kind") == "project_code" and type(item.get("path")) is str
    }
    requires_cross_file = case["requires_cross_file"]
    cross_file_satisfied = (
        len(code_paths) >= case["min_distinct_project_code_paths"] if requires_cross_file else True
    )
    return {
        "evidence_kind_counts": dict(sorted(counts.items())),
        "distinct_project_code_paths": len(code_paths),
        "evidence_sufficient": not missing_groups and cross_file_satisfied,
        "missing_evidence_groups": missing_groups,
        "cross_file_shape_satisfied": cross_file_satisfied,
    }


def normalize_case_result(
    case: Mapping[str, Any], response: object, *, latency_ms: float, roots: Iterable[Path]
) -> dict[str, Any]:
    """Normalize one valid HTTP 200 Agent outcome into structural diagnostics."""

    response = validate_engineering_response(response)
    raw_trace = _safe_trace(response["trace"])
    trace = sanitize_for_artifact(raw_trace, roots)
    raw_evidence = response["evidence"]
    evidence = sanitize_for_artifact(raw_evidence, roots)
    shape = evaluate_evidence_shape(case, raw_evidence)
    sequence = _tool_sequence(trace)
    required = list(case["required_tools"])
    forbidden = list(case["forbidden_tools"])
    required_coverage = {tool: tool in sequence for tool in required}
    forbidden_calls = [tool for tool in sequence if tool in forbidden]
    aggregation = _trace_aggregation(trace)
    status = response["status"]
    premature = status == "completed" and not shape["evidence_sufficient"]
    trace_codes = {
        event.get("error_code")
        for event in trace
        if isinstance(event.get("error_code"), str)
    }
    failure_code = response["failure_code"]
    layers: list[str] = []
    if failure_code == "ACTION_PARSE_FAILED" or aggregation["initial_parse_categories"]:
        layers.append("L1 Transport / Parsing")
    if (
        failure_code in {"AGENT_DUPLICATE_TOOL_CALL", "AGENT_BUDGET_EXCEEDED", "AGENT_TOOL_ERROR_LIMIT"}
        or trace_codes & {"AGENT_DUPLICATE_TOOL_CALL", "AGENT_BUDGET_EXCEEDED"}
        or forbidden_calls
    ):
        layers.append("L2 Planning / Tool-loop")
    if premature:
        layers.append("L3 Evidence Acquisition")
    return {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "project_id": case["project_id"],
        "source_candidate_id": case["source_candidate_id"],
        "source_candidate_sha256": case["source_candidate_sha256"],
        "status": status,
        "answer": sanitize_for_artifact(response["answer"], roots),
        "reason_code": sanitize_for_artifact(response["reason_code"], roots),
        "failure_code": sanitize_for_artifact(failure_code, roots),
        "iterations_used": response["iterations_used"],
        "tool_calls_used": response["tool_calls_used"],
        "tool_errors_used": response["tool_errors_used"],
        "safe_trace": trace,
        "tool_sequence": sequence,
        "public_evidence": evidence,
        "latency_ms": round(float(latency_ms), 2),
        **shape,
        "required_tool_coverage": required_coverage,
        "forbidden_tool_calls": forbidden_calls,
        "non_required_tool_calls": [tool for tool in sequence if tool not in required],
        "premature_finalization": premature,
        "provider_call_count": aggregation["provider_call_count"],
        "repair_attempted": aggregation["repair_attempted"],
        "repair_succeeded": aggregation["repair_succeeded"],
        "initial_parse_categories": aggregation["initial_parse_categories"],
        "duplicate_tool_stop": (
            failure_code == "AGENT_DUPLICATE_TOOL_CALL" or "AGENT_DUPLICATE_TOOL_CALL" in trace_codes
        ),
        "budget_stop": (
            failure_code == "AGENT_BUDGET_EXCEEDED" or "AGENT_BUDGET_EXCEEDED" in trace_codes
        ),
        "structural_failure_layers": layers,
    }


def _metrics_for_cases(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(cases)
    sequence_total = sum(len(item.get("tool_sequence", [])) for item in cases)
    required_total = sum(len(item.get("required_tool_coverage", {})) for item in cases)
    required_hits = sum(
        sum(value is True for value in item.get("required_tool_coverage", {}).values()) for item in cases
    )
    evidence_coverage = Counter(
        kind
        for item in cases
        for kind in item.get("evidence_kind_counts", {})
    )
    # Only cases whose frozen contract requires the additional rule are applicable.
    applicable_cross_file = [
        item for item in cases if item.get("_requires_cross_file") is True
    ]
    forbidden_calls = sum(len(item.get("forbidden_tool_calls", [])) for item in cases)
    result = {
        "case_count": count,
        "completed_cases": sum(item.get("status") == "completed" for item in cases),
        "refused_cases": sum(item.get("status") == "refused" for item in cases),
        "failed_cases": sum(item.get("status") == "failed" for item in cases),
        "evidence_sufficient_cases": sum(item.get("evidence_sufficient") is True for item in cases),
        "premature_finalization_cases": sum(item.get("premature_finalization") is True for item in cases),
        "required_tool_complete_cases": sum(
            all(item.get("required_tool_coverage", {}).values()) for item in cases
        ),
        "required_tool_coverage_rate": required_hits / required_total if required_total else 0,
        "forbidden_tool_calls": forbidden_calls,
        "forbidden_tool_call_rate": forbidden_calls / sequence_total if sequence_total else 0,
        "non_required_tool_calls": sum(len(item.get("non_required_tool_calls", [])) for item in cases),
        "evidence_kind_coverage": dict(sorted(evidence_coverage.items())),
        "cross_file_applicable_cases": len(applicable_cross_file),
        "cross_file_shape_satisfied_cases": sum(
            item.get("cross_file_shape_satisfied") is True for item in applicable_cross_file
        ),
        "provider_calls_total": sum(item.get("provider_call_count", 0) for item in cases),
        "tool_calls_total": sum(item.get("tool_calls_used", 0) for item in cases),
        "iterations_total": sum(item.get("iterations_used", 0) for item in cases),
        "tool_errors_total": sum(item.get("tool_errors_used", 0) for item in cases),
        "latency_ms_total": round(sum(item.get("latency_ms", 0) for item in cases), 2),
        "structured_parse_failure_cases": sum(
            "L1 Transport / Parsing" in item.get("structural_failure_layers", []) for item in cases
        ),
        "repair_attempted_cases": sum(item.get("repair_attempted") is True for item in cases),
        "repair_succeeded_cases": sum(item.get("repair_succeeded") is True for item in cases),
        "duplicate_tool_stop_cases": sum(item.get("duplicate_tool_stop") is True for item in cases),
        "budget_stop_cases": sum(item.get("budget_stop") is True for item in cases),
        "l1_transport_parsing_cases": sum(
            "L1 Transport / Parsing" in item.get("structural_failure_layers", []) for item in cases
        ),
        "l2_planning_tool_loop_cases": sum(
            "L2 Planning / Tool-loop" in item.get("structural_failure_layers", []) for item in cases
        ),
        "l3_evidence_acquisition_cases": sum(
            "L3 Evidence Acquisition" in item.get("structural_failure_layers", []) for item in cases
        ),
    }
    result.update(
        {
            "completion_rate": result["completed_cases"] / count if count else 0,
            "refusal_rate": result["refused_cases"] / count if count else 0,
            "failure_rate": result["failed_cases"] / count if count else 0,
            "evidence_sufficiency_rate": result["evidence_sufficient_cases"] / count if count else 0,
            "premature_finalization_rate": result["premature_finalization_cases"] / count if count else 0,
            "cross_file_shape_rate": (
                result["cross_file_shape_satisfied_cases"] / result["cross_file_applicable_cases"]
                if result["cross_file_applicable_cases"] else 0
            ),
            "avg_provider_calls": result["provider_calls_total"] / count if count else 0,
            "avg_tool_calls": result["tool_calls_total"] / count if count else 0,
            "avg_iterations": result["iterations_total"] / count if count else 0,
            "avg_tool_errors": result["tool_errors_total"] / count if count else 0,
            "avg_latency_ms": result["latency_ms_total"] / count if count else 0,
        }
    )
    return result


def summarize_structural_metrics(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Produce only automatic structural measurements, never Manual Gold scores."""

    enriched = []
    for item in cases:
        copied = dict(item)
        copied["_requires_cross_file"] = copied.get("_requires_cross_file", False)
        enriched.append(copied)
    return {
        "automatic_scope": "STRUCTURAL ONLY / L4 REASONING AND MANUAL GOLD NOT AUTO SCORED",
        "overall": _metrics_for_cases(enriched),
        "by_task_family": {
            family: _metrics_for_cases([item for item in enriched if item["task_family"] == family])
            for family in sorted({item["task_family"] for item in enriched})
        },
        "by_repository": {
            project_id: _metrics_for_cases([item for item in enriched if item["project_id"] == project_id])
            for project_id in sorted({item["project_id"] for item in enriched})
        },
        "manual_only_metrics": {
            "task_success": "NOT AUTO SCORED",
            "evidence_coverage": "NOT AUTO SCORED",
            "evidence_correctness": "NOT AUTO SCORED",
            "claim_grounding": "NOT AUTO SCORED",
            "remediation_correctness": "NOT AUTO SCORED",
            "docs_semantic_label_correctness": "NOT AUTO SCORED",
        },
    }


def add_case_contract_flags(
    result: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep frozen cross-file applicability available to aggregate metrics."""

    copied = dict(result)
    copied["_requires_cross_file"] = case["requires_cross_file"]
    return copied


def build_manual_review_entry(case: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    evidence_references = []
    for item in result.get("public_evidence", []):
        if not isinstance(item, dict):
            continue
        reference = {key: item[key] for key in ("evidence_id", "kind", "path", "source_name") if key in item}
        evidence_references.append(reference)
    return {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "project_id": case["project_id"],
        "gold_obligations": case["gold_obligations"],
        "gold_source_proofs": case["source_proofs"],
        "agent_final_answer": result.get("answer"),
        "agent_evidence_references": evidence_references,
        "task_success": "NOT SCORED",
        "evidence_coverage": "NOT SCORED",
        "evidence_correctness": "NOT SCORED",
        "claim_grounding": "NOT SCORED",
        "review_notes": "",
    }


def sanitize_for_artifact(value: Any, roots: Iterable[Path]) -> Any:
    sanitized = value
    for root in roots:
        sanitized = _sanitize_single_root(sanitized, root)
    return sanitized


def _reject_sensitive_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is str and key.casefold() in _FORBIDDEN_ARTIFACT_FIELDS:
                raise BaselineContractError("artifact contains a forbidden sensitive field")
            _reject_sensitive_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_fields(item)


def _reject_markdown_json_fence_sensitive_fields(text: str) -> None:
    """Apply sensitive-field rules to structured Markdown report sections."""

    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        opening = re.fullmatch(r"[ \t]*(?P<fence>`{3,})[ \t]*(?P<info>[^\r\n]*)", lines[index].rstrip("\r\n"))
        if opening is None or opening.group("info").strip().casefold() != "json":
            index += 1
            continue
        fence = opening.group("fence")
        closing_index = None
        for cursor in range(index + 1, len(lines)):
            if re.fullmatch(rf"[ \t]*`{{{len(fence)},}}[ \t]*", lines[cursor].rstrip("\r\n")):
                closing_index = cursor
                break
        if closing_index is None:
            raise BaselineContractError("artifact contains an incomplete JSON Markdown fence")
        try:
            _reject_sensitive_fields(json.loads("".join(lines[index + 1 : closing_index])))
        except json.JSONDecodeError as exc:
            raise BaselineContractError("artifact contains invalid JSON Markdown fence") from exc
        index = closing_index + 1


def validate_baseline_artifact_safety(output: Path, roots: Iterable[Path]) -> None:
    """Apply existing semantic path safety plus Baseline A sensitive-field bans."""

    root_list = list(roots)
    for root in root_list:
        _validate_single_root_artifact_safety(output, root)
    for path in sorted(output.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            _reject_sensitive_fields(json.loads(path.read_text(encoding="utf-8")))
        elif path.suffix.lower() == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    _reject_sensitive_fields(json.loads(line))
        elif path.suffix.lower() in {".md", ".markdown"}:
            _reject_markdown_json_fence_sensitive_fields(path.read_text(encoding="utf-8"))


__all__ = [
    "BASELINE_A_CASE_RESULTS_SHA256", "BASELINE_A_EVALUATOR_COMMIT",
    "BASELINE_A_FORMAL_MANIFEST_SHA256", "BASELINE_A_FORMAL_RUN_ID",
    "BASELINE_A_MANUAL_TEMPLATE_SHA256", "BaselineContractError", "CANDIDATE_POOL_SHA256", "ENGINEERING_RESPONSE_SCHEMA",
    "FINAL_BENCHMARK_SHA256", "GATE12_DATASET_FREEZE_ID", "InfrastructureFailure",
    "KNOWLEDGE_STATUS", "MY_AGENT_COMMIT", "PRODUCT_BASELINE_COMMIT", "PYDANTIC_AI_COMMIT",
    "REPOSITORY_MANIFEST_SHA256", "REVIEWER_SELECTION_SHA256", "add_case_contract_flags",
    "build_manual_review_entry", "build_request_payload", "derive_api_urls", "evaluate_evidence_shape",
    "load_frozen_final_dataset", "normalize_case_result", "route_case", "sanitize_for_artifact",
    "summarize_structural_metrics", "validate_api_preflight", "validate_baseline_artifact_safety",
    "validate_distinct_roots", "validate_engineering_response", "validate_frozen_dataset_identity",
    "validate_product_baseline_attestation", "validate_product_identity", "validate_run_id",
]
