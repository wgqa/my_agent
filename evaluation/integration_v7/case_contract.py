"""Offline contract and identity validator for ARCH-EVAL-08A.

This module freezes evaluation inputs and execution preconditions.  It never
creates an Agent, invokes a provider, opens a Holdout, or produces a product
result.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.conversation_context import (
    CONTEXT_MAX_MESSAGES,
    CONTEXT_TOKEN_BUDGET,
    ContextMessage,
    RESOLVER_MAX_OUTPUT_TOKENS,
    RESOLVER_MAX_RETRIES,
    RESOLVER_PROMPT_VERSION,
)
from core.chunker.token_counter import TokenCounter
from core.query_planning import (
    PLANNER_MAX_OUTPUT_TOKENS,
    PLANNER_MAX_RETRIES,
    PLANNER_PROMPT_SHA256,
    PLANNER_PROMPT_VERSION,
)
from core.adaptive_retrieval import ADAPTIVE_RETRIEVAL_POLICY_VERSION
from core.agent_runtime.evidence import SUBQUERY_RRF_MERGE_V2, DEFAULT_MERGE_RRF_K
from core.engineering_requirements import ROUTER_VERSION
from core.engineering_retrieval import MAX_EVIDENCE_ITEMS, MAX_RETRIEVAL_CALLS, RETRIEVAL_TOP_K
from core.tool_agent.decision_prompt import (
    ACTION_REPAIR_PROMPT_SHA256,
    ACTION_REPAIR_PROMPT_VERSION,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_MAX_OUTPUT_TOKENS,
    compute_toolset_sha256,
    max_parse_repairs_for_profile,
    max_output_tokens_for_profile,
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
from core.tool_agent.runtime import _PROJECT_CODE_SUFFIXES
from core.tool_agent.runtime_models import ToolAgentBudget
from core.tool_agent.tools.test_discovery import is_test_path


PACKAGE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_ROOT / "protocol_manifest_v1.json"
DEV_DATASET_PATH = PACKAGE_ROOT / "integration_dev_v1.jsonl"
HOLDOUT_DATASET_PATH = PACKAGE_ROOT / "integration_holdout_v1.jsonl"
GOLD_PROOF_AUDIT_PATH = PACKAGE_ROOT / "gold_proof_audit_v1.jsonl"
HISTORICAL_G12_PATH = PACKAGE_ROOT.parent / "gate12" / "final_benchmark_v1.jsonl"

CASE_SCHEMA_VERSION = "integration_v7_case_v1"
PROTOCOL_SCHEMA_VERSION = "integration_v7_protocol_manifest_v1"
PROTOCOL_VERSION = "v7_architecture_integration_evaluation_v1"
METRIC_SCHEMA_VERSION = "integration_v7_metrics_v1"
MANUAL_RUBRIC_VERSION = "integration_v7_manual_rubric_v1"
GOLD_PROOF_AUDIT_SCHEMA_VERSION = "integration_v7_gold_proof_audit_v1"
DEV_SPLIT = "integration_dev"
HOLDOUT_SPLIT = "integration_holdout"

SYSTEM_A_COMMIT = "0eef8ef9d6decdaa10efebe04087b06611654670"
SYSTEM_B_COMMIT = "385b7795eafde7c114efc382e95c0d18ec273f54"
CORPUS_SOURCE_COMMIT = "179f18e812ad63c36c5569de8e86c5ff9a931cb5"
TARGET_PROJECT_COMMIT = SYSTEM_B_COMMIT
TARGET_PROJECT_ID = "my_agent"

TASK_FAMILIES = (
    "knowledge_only",
    "repo_only",
    "theory_code",
    "context_followup",
    "change_test",
    "docs_code",
    "diagnosis",
    "decomposed_knowledge",
    "insufficient_refusal",
)
EXPECTED_CASE_COUNTS = {DEV_SPLIT: 18, HOLDOUT_SPLIT: 9}
EXPECTED_FAMILY_COUNTS = {family: {DEV_SPLIT: 2, HOLDOUT_SPLIT: 1} for family in TASK_FAMILIES}

PUBLIC_EVIDENCE_KINDS = frozenset(
    {"knowledge", "project_code", "project_doc", "project_change", "project_test"}
)
TOOLS = frozenset(
    {
        CALCULATOR_SPEC.name,
        CHANGED_FILES_SPEC.name,
        CODE_SEARCH_SPEC.name,
        FIND_TESTS_SPEC.name,
        GIT_DIFF_SPEC.name,
        KNOWLEDGE_SEARCH_SPEC.name,
        READ_PROJECT_CONTEXT_SPEC.name,
    }
)
TOOLSET_NAMES = (
    "calculator",
    "changed_files",
    "code_search",
    "find_tests",
    "git_diff",
    "knowledge_search",
    "read_project_context",
)
SYSTEM_A_DYNAMIC_TOOL_NAMES = TOOLSET_NAMES
SYSTEM_B_DYNAMIC_TOOL_NAMES = tuple(name for name in TOOLSET_NAMES if name != "knowledge_search")
KNOWLEDGE_FAMILIES = frozenset({"knowledge_only", "theory_code", "decomposed_knowledge"})
CONTEXT_FAMILIES = frozenset({"context_followup"})
CHANGE_TEST_FAMILIES = frozenset({"change_test"})
PROJECT_EVIDENCE_KINDS = frozenset(
    {"project_code", "project_doc", "project_change", "project_test"}
)
_DIFFICULTIES = frozenset({"basic", "intermediate", "complex", "adversarial"})
_OUTCOMES = frozenset({"answerable", "refusal"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CASE_ID_RE = re.compile(r"^v7[dh][0-9]{3}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_WHITESPACE_RE = re.compile(r"\s+")
_ABSOLUTE_PATH_IN_TEXT_RE = re.compile(r"(?i)(?:\b[A-Z]:[\\/]|(?:^|[\r\n])/(?:[^/\r\n]|/))")
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "cot",
        "full_prompt",
        "private_cot",
        "private_reasoning",
        "raw_model_output",
        "raw_provider_response",
    }
)
_CASE_FIELDS = frozenset(
    {
        "schema_version",
        "case_id",
        "split",
        "task_family",
        "difficulty",
        "question",
        "conversation_context",
        "current_question",
        "expected_standalone_intent",
        "project_id",
        "project_source_commit",
        "gold_obligations",
        "source_proofs",
        "knowledge_gold_sources",
        "knowledge_probe_query",
        "decomposition_facets",
        "required_evidence_groups",
        "required_tools",
        "required_tools_by_system",
        "forbidden_tools",
        "min_distinct_project_code_paths",
        "expected_outcome",
        "base_ref",
        "head_ref",
        "accepted_test_paths",
        "independence_note",
    }
)
_REQUIRED_CASE_FIELDS = frozenset(
    {
        "schema_version",
        "case_id",
        "split",
        "task_family",
        "difficulty",
        "question",
        "conversation_context",
        "project_id",
        "project_source_commit",
        "gold_obligations",
        "source_proofs",
        "knowledge_gold_sources",
        "knowledge_probe_query",
        "required_evidence_groups",
        "required_tools",
        "required_tools_by_system",
        "forbidden_tools",
        "min_distinct_project_code_paths",
        "expected_outcome",
        "independence_note",
    }
)


class ProtocolViolation(ValueError):
    """Raised when frozen evaluation input or provenance is invalid."""


class HoldoutExecutionDenied(ProtocolViolation):
    """Raised when a Holdout execution lacks explicit frozen confirmation."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalise_question(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip()).casefold()


def _require_text(value: object, label: str, *, max_chars: int = 4000) -> str:
    if type(value) is not str or not value.strip():
        raise ProtocolViolation(f"{label} must be a non-empty string")
    if len(value) > max_chars:
        raise ProtocolViolation(f"{label} exceeds {max_chars} characters")
    if "\x00" in value or any(ord(char) < 32 and char not in "\n\t\r" for char in value):
        raise ProtocolViolation(f"{label} contains control characters")
    return value


def _require_sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a full 40-character lowercase SHA")
    return value


def _safe_relative_path(value: object, label: str) -> str:
    value = _require_text(value, label, max_chars=500)
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        "\\" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or value.startswith("/")
        or any(part in ("", ".", "..") for part in posix.parts)
    ):
        raise ProtocolViolation(f"{label} must be a repo-relative POSIX path")
    return posix.as_posix()


def _proof_cases(cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if cases is not None:
        return cases
    return load_cases(DEV_DATASET_PATH) + load_cases(HOLDOUT_DATASET_PATH)


def _resolve_source_anchor(text: str, anchor: str, label: str) -> None:
    """Resolve a deterministic line or literal-text anchor in frozen source."""

    if anchor.startswith("line:"):
        raw_line = anchor.removeprefix("line:")
        if not raw_line.isdigit() or int(raw_line) < 1:
            raise ProtocolViolation(f"{label} has an invalid line anchor")
        line_number = int(raw_line)
        lines = text.splitlines()
        if line_number > len(lines) or not lines[line_number - 1].strip():
            raise ProtocolViolation(f"{label} line anchor does not resolve")
        return
    if anchor not in text:
        raise ProtocolViolation(f"{label} text anchor does not resolve")


def _validate_source_excerpt(text: str, anchor: str, excerpt: object, label: str) -> None:
    """Require a short, exact source excerpt located at the declared anchor."""

    excerpt = _require_text(excerpt, f"{label}.source_excerpt", max_chars=300)
    if _ABSOLUTE_PATH_IN_TEXT_RE.search(excerpt):
        raise ProtocolViolation(f"{label}.source_excerpt must not contain an absolute path")
    _resolve_source_anchor(text, anchor, f"{label}.anchor")
    if excerpt not in text:
        raise ProtocolViolation(f"{label}.source_excerpt does not exist in frozen source")
    if anchor.startswith("line:"):
        line_number = int(anchor.removeprefix("line:"))
        first_excerpt_line = next(
            (line for line in excerpt.splitlines() if line.strip()),
            "",
        ).strip()
        source_line = text.splitlines()[line_number - 1]
        if not first_excerpt_line or first_excerpt_line not in source_line:
            raise ProtocolViolation(
                f"{label}.source_excerpt is not located at its line anchor"
            )
    elif anchor not in excerpt and excerpt not in anchor:
        raise ProtocolViolation(
            f"{label}.source_excerpt is not located at its text anchor"
        )


def _proof_source_path(root: Path, relative_path: str, label: str) -> Path:
    safe_path = _safe_relative_path(relative_path, label)
    resolved_root = root.resolve()
    resolved_path = (resolved_root / safe_path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} escapes the frozen source root") from exc
    return resolved_path


def _walk_forbidden(value: object, path: str = "case") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _SECRET_KEYS:
                raise ProtocolViolation(f"{path} contains forbidden secret/reasoning field {key!r}")
            _walk_forbidden(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if re.search(r"(?i)(sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,})", value):
            raise ProtocolViolation(f"{path} contains a credential-like value")


def _validate_context(case: Mapping[str, Any]) -> None:
    family = case["task_family"]
    history = case["conversation_context"]
    if isinstance(history, (str, bytes)) or not isinstance(history, list):
        raise ProtocolViolation("conversation_context must be a list")
    if len(history) > CONTEXT_MAX_MESSAGES:
        raise ProtocolViolation("conversation_context exceeds the G8 six-message bound")
    token_counter = TokenCounter()
    token_total = 0
    for index, raw in enumerate(history):
        if not isinstance(raw, Mapping):
            raise ProtocolViolation(f"conversation_context[{index}] must be an object")
        message = ContextMessage(role=raw.get("role"), content=raw.get("content"))
        token_total += token_counter.count(message.content)
    if token_total > CONTEXT_TOKEN_BUDGET:
        raise ProtocolViolation("conversation_context exceeds the G8 token budget")
    if family in CONTEXT_FAMILIES:
        current_question = _require_text(case.get("current_question"), "current_question")
        if current_question != case["question"]:
            raise ProtocolViolation("context case question must equal current_question")
        _require_text(case.get("expected_standalone_intent"), "expected_standalone_intent")
        if not history:
            raise ProtocolViolation("context_followup requires non-empty conversation_context")
    else:
        if history or "current_question" in case or "expected_standalone_intent" in case:
            raise ProtocolViolation("non-context case must not carry conversation context fields")


def _validate_obligations(case: Mapping[str, Any]) -> set[str]:
    obligations = case["gold_obligations"]
    if not isinstance(obligations, list) or not obligations:
        raise ProtocolViolation("gold_obligations must be a non-empty list")
    ids: set[str] = set()
    for index, item in enumerate(obligations):
        if not isinstance(item, Mapping):
            raise ProtocolViolation(f"gold_obligations[{index}] must be an object")
        obligation_id = _require_text(item.get("id"), f"gold_obligations[{index}].id", max_chars=32)
        if not re.fullmatch(r"O[1-9][0-9]*", obligation_id) or obligation_id in ids:
            raise ProtocolViolation("gold obligation IDs must be unique O1/O2/... values")
        ids.add(obligation_id)
        _require_text(item.get("claim"), f"gold_obligations[{index}].claim", max_chars=800)
    return ids


def _validate_proofs(case: Mapping[str, Any], obligation_ids: set[str]) -> set[tuple[str, str, str]]:
    proofs = case["source_proofs"]
    if not isinstance(proofs, list) or not proofs:
        raise ProtocolViolation("source_proofs must be a non-empty list")
    identities: set[tuple[str, str, str]] = set()
    covered: set[str] = set()
    for index, proof in enumerate(proofs):
        if not isinstance(proof, Mapping):
            raise ProtocolViolation(f"source_proofs[{index}] must be an object")
        kind = proof.get("kind")
        if kind not in PUBLIC_EVIDENCE_KINDS:
            raise ProtocolViolation(f"source_proofs[{index}].kind is not a public evidence kind")
        relative_path = _safe_relative_path(proof.get("relative_path"), f"source_proofs[{index}].relative_path")
        anchor = _require_text(proof.get("anchor"), f"source_proofs[{index}].anchor", max_chars=300)
        _require_text(proof.get("source_excerpt"), f"source_proofs[{index}].source_excerpt", max_chars=300)
        _require_text(proof.get("bounded_proof"), f"source_proofs[{index}].bounded_proof", max_chars=1200)
        proof_ids = proof.get("obligation_ids")
        if not isinstance(proof_ids, list) or not proof_ids or any(item not in obligation_ids for item in proof_ids):
            raise ProtocolViolation(f"source_proofs[{index}].obligation_ids references an unknown obligation")
        identity = (kind, relative_path, anchor)
        if identity in identities:
            raise ProtocolViolation("source-proof identity is duplicated within a case")
        identities.add(identity)
        covered.update(proof_ids)
    if covered != obligation_ids:
        raise ProtocolViolation("every gold obligation must have a source proof")
    return identities


def _runtime_project_path_kind(relative_path: str) -> str:
    """Mirror ToolAgentRuntime's read-project-context evidence classifier."""

    if is_test_path(relative_path):
        return "project_test"
    if PurePosixPath(relative_path).suffix.lower() in _PROJECT_CODE_SUFFIXES:
        return "project_code"
    return "project_doc"


def validate_case_gold_coherence(case: Mapping[str, Any]) -> None:
    """Validate that Gold, evidence groups, and path contracts describe one case."""

    if not isinstance(case, Mapping):
        raise ProtocolViolation("case Gold coherence input must be an object")
    proofs = case.get("source_proofs")
    if not isinstance(proofs, list) or not proofs:
        raise ProtocolViolation("case Gold coherence requires source_proofs")

    proof_kinds: set[str] = set()
    knowledge_proof_paths: set[str] = set()
    code_paths: set[str] = set()
    proof_obligation_ids: dict[str, set[str]] = {}
    for index, proof in enumerate(proofs):
        if not isinstance(proof, Mapping):
            raise ProtocolViolation(f"source_proofs[{index}] must be an object")
        kind = proof.get("kind")
        if kind not in PUBLIC_EVIDENCE_KINDS:
            raise ProtocolViolation(f"source_proofs[{index}].kind is invalid")
        relative_path = _safe_relative_path(
            proof.get("relative_path"),
            f"source_proofs[{index}].relative_path",
        )
        runtime_kind = _runtime_project_path_kind(relative_path)
        if runtime_kind == "project_test" and kind != "project_test":
            raise ProtocolViolation(
                f"source_proofs[{index}] test path must be classified as project_test"
            )
        if kind == "project_test" and runtime_kind != "project_test":
            raise ProtocolViolation(
                f"source_proofs[{index}] project_test path is not a test path"
            )
        if kind == "project_code" and runtime_kind != "project_code":
            raise ProtocolViolation(
                f"source_proofs[{index}] project_code path is not runtime project_code"
            )
        if kind == "project_doc" and runtime_kind != "project_doc":
            raise ProtocolViolation(
                f"source_proofs[{index}] project_doc path is an obvious source/test path"
            )
        proof_kinds.add(kind)
        if kind == "knowledge":
            knowledge_proof_paths.add(relative_path)
        if kind == "project_code":
            code_paths.add(relative_path)
        obligation_ids = proof.get("obligation_ids")
        if not isinstance(obligation_ids, list) or not obligation_ids:
            raise ProtocolViolation(
                f"source_proofs[{index}].obligation_ids must be non-empty"
            )
        proof_obligation_ids[kind] = proof_obligation_ids.get(kind, set()) | set(obligation_ids)

    declared_knowledge_paths = case.get("knowledge_gold_sources")
    if not isinstance(declared_knowledge_paths, list):
        raise ProtocolViolation("knowledge_gold_sources must be a list")
    normalized_knowledge_paths = {
        _safe_relative_path(item, "knowledge_gold_sources")
        for item in declared_knowledge_paths
    }
    if len(normalized_knowledge_paths) != len(declared_knowledge_paths):
        raise ProtocolViolation("knowledge_gold_sources contains a duplicate path")
    if normalized_knowledge_paths != knowledge_proof_paths:
        raise ProtocolViolation(
            "knowledge_gold_sources must exactly match knowledge proof paths"
        )

    groups = case.get("required_evidence_groups")
    if not isinstance(groups, list):
        raise ProtocolViolation("required_evidence_groups must be a list")
    for index, group in enumerate(groups):
        if not isinstance(group, list) or not group:
            raise ProtocolViolation(
                f"required_evidence_groups[{index}] must be non-empty"
            )
        if not any(kind in proof_kinds for kind in group):
            raise ProtocolViolation(
                f"required_evidence_groups[{index}] has no Gold proof support"
            )

    min_paths = case.get("min_distinct_project_code_paths")
    if type(min_paths) is not int or min_paths < 0:
        raise ProtocolViolation("min_distinct_project_code_paths must be a non-negative int")
    if len(code_paths) < min_paths:
        raise ProtocolViolation(
            "Gold project_code paths do not satisfy min_distinct_project_code_paths"
        )

    if case.get("task_family") == "theory_code":
        obligation_ids = {
            item.get("id")
            for item in case.get("gold_obligations", [])
            if isinstance(item, Mapping)
        }
        if not knowledge_proof_paths:
            raise ProtocolViolation("theory_code requires a knowledge Gold proof")
        project_proof_ids = set().union(
            *(proof_obligation_ids.get(kind, set()) for kind in ("project_code", "project_doc"))
        )
        if not project_proof_ids:
            raise ProtocolViolation(
                "theory_code requires a project_code or project_doc Gold proof"
            )
        if not proof_obligation_ids.get("knowledge"):
            raise ProtocolViolation("theory_code knowledge proof must map to an obligation")
        if not proof_obligation_ids.get("knowledge") & obligation_ids:
            raise ProtocolViolation("theory_code knowledge proof maps outside Gold obligations")
        if not project_proof_ids & obligation_ids:
            raise ProtocolViolation("theory_code project proof must map to an obligation")


def _validate_string_list(value: object, label: str, *, allowed: set[str] | frozenset[str]) -> list[str]:
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise ProtocolViolation(f"{label} must be a list of strings")
    if len(set(value)) != len(value) or any(item not in allowed for item in value):
        raise ProtocolViolation(f"{label} contains duplicates or unsupported values")
    return value


def required_tools_for_system(case: Mapping[str, Any], system: str) -> list[str]:
    """Return only the dynamic ToolAgent obligations for one system contract."""

    if system not in {"A", "B"}:
        raise ProtocolViolation("system must be A or B")
    mapping = case.get("required_tools_by_system")
    if not isinstance(mapping, Mapping):
        raise ProtocolViolation("required_tools_by_system must be an object")
    tools = mapping.get(system)
    allowed = TOOLS if system == "A" else TOOLS - {KNOWLEDGE_SEARCH_SPEC.name}
    return _validate_string_list(tools, f"required_tools_by_system.{system}", allowed=allowed)


def compute_tool_coverage(case: Mapping[str, Any], system: str, observed_tools: list[str] | tuple[str, ...] | set[str]) -> float:
    """Compute coverage against one system's dynamic-tool contract only."""

    required = set(required_tools_for_system(case, system))
    observed = set(_validate_string_list(list(observed_tools), "observed_tools", allowed=TOOLS))
    if not required:
        return 1.0
    return len(required & observed) / len(required)


def compute_task_completion(case: Mapping[str, Any], terminal_state: Mapping[str, Any]) -> bool:
    """Use runtime/business terminal state; semantic Gold remains manual."""

    if not isinstance(terminal_state, Mapping):
        raise ProtocolViolation("terminal_state must be an object")
    status = terminal_state.get("status")
    if status not in {"completed", "refused", "failed"}:
        raise ProtocolViolation("terminal_state.status must be completed, refused, or failed")
    expected = case.get("expected_outcome")
    if expected not in _OUTCOMES:
        raise ProtocolViolation("case expected_outcome is invalid")
    return (expected == "answerable" and status == "completed") or (
        expected == "refusal" and status == "refused"
    )


def compute_required_evidence_coverage(case: Mapping[str, Any], satisfied_groups: list[bool] | tuple[bool, ...]) -> float:
    """Return satisfied required groups / total groups, with no Gold-obligation inference."""

    groups = case.get("required_evidence_groups")
    if not isinstance(groups, list) or not isinstance(satisfied_groups, (list, tuple)):
        raise ProtocolViolation("required evidence coverage inputs must be lists")
    if len(groups) != len(satisfied_groups):
        raise ProtocolViolation("one satisfaction value is required for every evidence group")
    if any(type(value) is not bool for value in satisfied_groups):
        raise ProtocolViolation("evidence group satisfaction values must be booleans")
    if not groups:
        return 1.0
    return sum(satisfied_groups) / len(groups)


def compute_premature_finalization(case: Mapping[str, Any], finalization_state: Mapping[str, Any]) -> bool:
    """Detect finalization before typed/evidence state is satisfied."""

    if not isinstance(finalization_state, Mapping):
        raise ProtocolViolation("finalization_state must be an object")
    finalized = finalization_state.get("finalized")
    if type(finalized) is not bool:
        raise ProtocolViolation("finalization_state.finalized must be a boolean")
    if not finalized:
        return False
    required_satisfied = finalization_state.get("required_evidence_satisfied", True)
    typed_satisfied = finalization_state.get("typed_requirement_satisfied", True)
    if type(required_satisfied) is not bool or type(typed_satisfied) is not bool:
        raise ProtocolViolation("finalization satisfaction state must be boolean")
    return not (required_satisfied and typed_satisfied)


def compute_refusal_correctness(case: Mapping[str, Any], terminal_state: Mapping[str, Any]) -> bool:
    """Compare expected outcome with terminal answer/refusal state only."""

    return compute_task_completion(case, terminal_state)


def validate_case(case: Mapping[str, Any], *, line_number: int = 0) -> set[tuple[str, str, str]]:
    if not isinstance(case, Mapping):
        raise ProtocolViolation(f"case line {line_number} must be an object")
    extra = set(case) - _CASE_FIELDS
    missing = _REQUIRED_CASE_FIELDS - set(case)
    if extra:
        raise ProtocolViolation(f"case line {line_number} has unknown fields: {sorted(extra)}")
    if missing:
        raise ProtocolViolation(f"case line {line_number} is missing fields: {sorted(missing)}")
    if case["schema_version"] != CASE_SCHEMA_VERSION:
        raise ProtocolViolation("case schema_version mismatch")
    case_id = case["case_id"]
    if type(case_id) is not str or _CASE_ID_RE.fullmatch(case_id) is None:
        raise ProtocolViolation("case_id must match v7dNNN or v7hNNN")
    split = case["split"]
    if split not in EXPECTED_CASE_COUNTS:
        raise ProtocolViolation("case split is not integration_dev or integration_holdout")
    if (case_id.startswith("v7d") and split != DEV_SPLIT) or (case_id.startswith("v7h") and split != HOLDOUT_SPLIT):
        raise ProtocolViolation("case_id prefix and split disagree")
    family = case["task_family"]
    if family not in TASK_FAMILIES:
        raise ProtocolViolation("unknown task_family")
    if case["difficulty"] not in _DIFFICULTIES:
        raise ProtocolViolation("unknown difficulty")
    question = _require_text(case["question"], "question")
    if question != question.strip():
        raise ProtocolViolation("question must not have leading/trailing whitespace")
    if case["project_id"] != TARGET_PROJECT_ID:
        raise ProtocolViolation("project_id must be my_agent")
    if case["project_source_commit"] != TARGET_PROJECT_COMMIT:
        raise ProtocolViolation("project_source_commit must equal the frozen target snapshot")
    _validate_context(case)
    obligation_ids = _validate_obligations(case)
    proof_identities = _validate_proofs(case, obligation_ids)

    knowledge_sources = case["knowledge_gold_sources"]
    if not isinstance(knowledge_sources, list):
        raise ProtocolViolation("knowledge_gold_sources must be a list")
    knowledge_sources = [_safe_relative_path(item, "knowledge_gold_sources") for item in knowledge_sources]
    probe = case["knowledge_probe_query"]
    if family in KNOWLEDGE_FAMILIES:
        if not knowledge_sources or probe is None:
            raise ProtocolViolation("knowledge family requires knowledge_gold_sources and knowledge_probe_query")
        _require_text(probe, "knowledge_probe_query", max_chars=500)
    elif knowledge_sources or probe is not None:
        raise ProtocolViolation("non-knowledge case must not carry knowledge gold fields")

    facets = case.get("decomposition_facets")
    if family == "decomposed_knowledge":
        if not isinstance(facets, list) or not 2 <= len(facets) <= 3 or len(set(facets)) != len(facets):
            raise ProtocolViolation("decomposed_knowledge requires two or three unique decomposition_facets")
        for facet in facets:
            _require_text(facet, "decomposition_facets item", max_chars=200)
    elif facets is not None:
        raise ProtocolViolation("decomposition_facets is only valid for decomposed_knowledge")

    groups = case["required_evidence_groups"]
    if not isinstance(groups, list):
        raise ProtocolViolation("required_evidence_groups must be a list")
    normalized_groups: list[tuple[str, ...]] = []
    for group in groups:
        if not isinstance(group, list) or not group or any(item not in PUBLIC_EVIDENCE_KINDS for item in group):
            raise ProtocolViolation("required_evidence_groups contains an invalid group")
        if len(set(group)) != len(group):
            raise ProtocolViolation("required_evidence_groups contains a duplicate kind")
        if tuple(group) in normalized_groups:
            raise ProtocolViolation("required_evidence_groups contains a duplicate group")
        normalized_groups.append(tuple(group))
    if case["expected_outcome"] not in _OUTCOMES:
        raise ProtocolViolation("expected_outcome must be answerable or refusal")
    if case["expected_outcome"] == "refusal" and normalized_groups:
        raise ProtocolViolation("insufficient_refusal must not claim answer evidence obligations")
    if case["expected_outcome"] == "answerable" and not normalized_groups:
        raise ProtocolViolation("answerable case requires required_evidence_groups")

    required_tools = _validate_string_list(case["required_tools"], "required_tools", allowed=TOOLS)
    required_tools_a = required_tools_for_system(case, "A")
    required_tools_b = required_tools_for_system(case, "B")
    common_tools = [tool for tool in required_tools_a if tool in required_tools_b]
    if required_tools != common_tools:
        raise ProtocolViolation(
            "required_tools must contain only obligations common to both system contracts"
        )
    forbidden_tools = _validate_string_list(case["forbidden_tools"], "forbidden_tools", allowed=TOOLS)
    if set(required_tools_a + required_tools_b) & set(forbidden_tools):
        raise ProtocolViolation("required_tools and forbidden_tools overlap")
    min_paths = case["min_distinct_project_code_paths"]
    if type(min_paths) is not int or min_paths < 0 or min_paths > 5:
        raise ProtocolViolation("min_distinct_project_code_paths must be an int from 0 to 5")
    if family in {"repo_only", "theory_code", "docs_code", "diagnosis"} and min_paths < 1:
        raise ProtocolViolation("project-evidence family requires at least one project-code path")
    if family == "diagnosis" and min_paths < 2:
        raise ProtocolViolation("diagnosis requires cross-file project evidence")
    validate_case_gold_coherence(case)

    change_fields = {"base_ref", "head_ref", "accepted_test_paths"}
    if family in CHANGE_TEST_FAMILIES:
        if not all(field in case for field in change_fields):
            raise ProtocolViolation("change_test requires base_ref, head_ref, and accepted_test_paths")
        base_ref = _require_sha(case["base_ref"], "base_ref")
        head_ref = _require_sha(case["head_ref"], "head_ref")
        if base_ref == head_ref:
            raise ProtocolViolation("change_test base_ref and head_ref must differ")
        accepted = case["accepted_test_paths"]
        if not isinstance(accepted, list) or not accepted:
            raise ProtocolViolation("accepted_test_paths must be a non-empty list")
        for path in accepted:
            _safe_relative_path(path, "accepted_test_paths")
    elif any(field in case for field in change_fields):
        raise ProtocolViolation("change/test fields are only valid for change_test")

    _require_text(case["independence_note"], "independence_note", max_chars=1200)
    if split == HOLDOUT_SPLIT:
        note = case["independence_note"].casefold()
        for required_word in ("dev", "g11", "g12"):
            if required_word not in note:
                raise ProtocolViolation("every Holdout case needs Dev/G11/G12 independence_note coverage")
    _walk_forbidden(case)
    return proof_identities


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise ProtocolViolation(f"dataset is missing: {path}")
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ProtocolViolation(f"dataset line {line_number} is blank")
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProtocolViolation(f"dataset line {line_number} is not valid JSON") from exc
            validate_case(item, line_number=line_number)
            cases.append(dict(item))
    if not cases:
        raise ProtocolViolation("dataset must not be empty")
    return cases


def canonical_jsonl_sha256(path: str | Path) -> str:
    """Hash canonical JSON objects, independent of JSONL line endings."""

    cases = load_cases(path)
    canonical = b"\n".join(_canonical_json(case) for case in cases) + b"\n"
    return hashlib.sha256(canonical).hexdigest()


def _validate_dataset_pair(dev_cases: list[dict[str, Any]], holdout_cases: list[dict[str, Any]]) -> None:
    all_cases = dev_cases + holdout_cases
    if len(dev_cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT] or len(holdout_cases) != EXPECTED_CASE_COUNTS[HOLDOUT_SPLIT]:
        raise ProtocolViolation("dataset counts must be exactly 18 Dev and 9 Holdout cases")
    counts = Counter((case["task_family"], case["split"]) for case in all_cases)
    for family in TASK_FAMILIES:
        for split, expected in EXPECTED_FAMILY_COUNTS[family].items():
            if counts[(family, split)] != expected:
                raise ProtocolViolation(f"{family}/{split} count must be {expected}")
    case_ids = [case["case_id"] for case in all_cases]
    if len(set(case_ids)) != len(case_ids):
        raise ProtocolViolation("case IDs must be globally unique")
    questions = [case["question"] for case in all_cases]
    normalized_questions = [_normalise_question(question) for question in questions]
    if len(set(questions)) != len(questions) or len(set(normalized_questions)) != len(questions):
        raise ProtocolViolation("questions and normalized questions must be globally unique")
    proof_identities: set[tuple[str, str, str]] = set()
    for case in all_cases:
        identities = _validate_proofs(case, {item["id"] for item in case["gold_obligations"]})
        collision = proof_identities & identities
        if collision:
            raise ProtocolViolation(f"exact source-proof identity collision: {sorted(collision)}")
        proof_identities.update(identities)
    change_pairs: set[tuple[str, str]] = set()
    change_heads: set[str] = set()
    for case in all_cases:
        if case["task_family"] == "change_test":
            pair = (case["base_ref"], case["head_ref"])
            if pair in change_pairs or case["head_ref"] in change_heads:
                raise ProtocolViolation("change_test cases must use distinct historical change ranges")
            change_pairs.add(pair)
            change_heads.add(case["head_ref"])
    context_signatures: set[str] = set()
    for case in all_cases:
        if case["task_family"] == "context_followup":
            signature = _normalise_question(json.dumps(case["conversation_context"], ensure_ascii=False, sort_keys=True))
            if signature in context_signatures:
                raise ProtocolViolation("context cases must use distinct follow-up dependencies")
            context_signatures.add(signature)


def _historical_g12_questions_and_proofs() -> tuple[set[str], set[tuple[str, str, str]]]:
    if not HISTORICAL_G12_PATH.is_file():
        raise ProtocolViolation("historical G12 final dataset is unavailable")
    questions: set[str] = set()
    proofs: set[tuple[str, str, str]] = set()
    with HISTORICAL_G12_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            questions.add(_normalise_question(item["question"]))
            for proof in item.get("source_proofs", []):
                proofs.add((proof.get("kind"), proof.get("relative_path"), proof.get("anchor")))
    return questions, proofs


def validate_target_project_binding(binding: Mapping[str, Any], *, expected_commit: str = TARGET_PROJECT_COMMIT) -> None:
    if not isinstance(binding, Mapping):
        raise ProtocolViolation("target project binding must be an object")
    if binding.get("project_id") != TARGET_PROJECT_ID:
        raise ProtocolViolation("target project project_id mismatch")
    if binding.get("source_commit") != expected_commit:
        raise ProtocolViolation("target project source SHA mismatch")
    if binding.get("dirty") is not False:
        raise ProtocolViolation("target project must be tracked-clean")
    if binding.get("binding_source") != "ENGINEERING_PROJECT_ROOT":
        raise ProtocolViolation("target project binding source mismatch")
    path = binding.get("path")
    if path is not None:
        raise ProtocolViolation("target project path must not enter the public protocol artifact")


def validate_target_project_checkout(
    root: str | Path,
    *,
    expected_commit: str = TARGET_PROJECT_COMMIT,
) -> None:
    """Fail closed unless a read-only checkout is present at the frozen SHA."""

    checkout = Path(root)
    if not checkout.is_dir():
        raise ProtocolViolation("target project checkout is missing")
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProtocolViolation("target project checkout cannot be inspected") from exc
    if revision.returncode != 0 or revision.stdout.strip() != expected_commit:
        raise ProtocolViolation("target project checkout SHA does not match the frozen target snapshot")
    if status.returncode != 0:
        raise ProtocolViolation("target project checkout status cannot be inspected")
    if status.stdout.strip():
        raise ProtocolViolation("target project checkout must be tracked-clean")


def _validate_frozen_git_checkout(
    root: str | Path,
    *,
    expected_commit: str,
    label: str,
    allow_untracked: bool = False,
) -> Path:
    checkout = Path(root)
    if not checkout.is_dir():
        raise ProtocolViolation(f"{label} checkout is missing")
    _require_sha(expected_commit, f"{label} expected SHA")
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=checkout,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProtocolViolation(f"{label} checkout cannot be inspected") from exc
    if revision.returncode != 0 or revision.stdout.strip() != expected_commit:
        raise ProtocolViolation(f"{label} checkout SHA does not match the frozen source")
    if status.returncode != 0:
        raise ProtocolViolation(f"{label} checkout status cannot be inspected")
    status_lines = [line for line in status.stdout.splitlines() if line.strip()]
    if allow_untracked:
        if any(not line.startswith("?? ") for line in status_lines):
            raise ProtocolViolation(f"{label} checkout has tracked source changes")
    elif status_lines:
        raise ProtocolViolation(f"{label} checkout must be tracked-clean")
    return checkout


def _validate_source_proof_files(
    cases: list[dict[str, Any]],
    *,
    source_root: Path,
    proof_kinds: set[str],
    source_label: str,
    git_checkout: Path,
) -> None:
    def git_show(revision: str, repo_relative_path: str, label: str) -> str:
        try:
            shown = subprocess.run(
                ["git", "show", f"{revision}:{repo_relative_path}"],
                cwd=git_checkout,
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProtocolViolation(f"{label} source provenance cannot be inspected") from exc
        if shown.returncode != 0:
            raise ProtocolViolation(f"{label} source file is not present in the frozen commit")
        try:
            return shown.stdout.decode("utf-8")
        except UnicodeError as exc:
            raise ProtocolViolation(f"{label} source file is unreadable") from exc

    def changed_paths(base_ref: str, head_ref: str, label: str) -> set[str]:
        _require_sha(base_ref, f"{label}.base_ref")
        _require_sha(head_ref, f"{label}.head_ref")
        try:
            changed = subprocess.run(
                ["git", "diff", "--name-only", base_ref, head_ref, "--"],
                cwd=git_checkout,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProtocolViolation(f"{label} change range cannot be inspected") from exc
        if changed.returncode != 0:
            raise ProtocolViolation(f"{label} change range is invalid")
        return {line.strip().replace("\\", "/") for line in changed.stdout.splitlines() if line.strip()}

    def added_lines(base_ref: str, head_ref: str, relative_path: str, label: str) -> set[str]:
        try:
            diff = subprocess.run(
                ["git", "diff", "--unified=0", base_ref, head_ref, "--", relative_path],
                cwd=git_checkout,
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProtocolViolation(f"{label} change excerpt cannot be inspected") from exc
        if diff.returncode != 0:
            raise ProtocolViolation(f"{label} change range is invalid")
        try:
            diff_text = diff.stdout.decode("utf-8")
        except UnicodeError as exc:
            raise ProtocolViolation(f"{label} change diff is unreadable") from exc
        return {
            line[1:].rstrip("\r")
            for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        }

    for case in cases:
        for index, proof in enumerate(case["source_proofs"]):
            if proof["kind"] not in proof_kinds:
                continue
            label = f"{source_label} proof {case['case_id']}[{index}]"
            source_path = _proof_source_path(source_root, proof["relative_path"], f"{label}.relative_path")
            if not source_path.is_file():
                raise ProtocolViolation(f"{label} source file is missing")
            try:
                repo_relative_path = source_path.resolve().relative_to(git_checkout.resolve()).as_posix()
            except ValueError as exc:
                raise ProtocolViolation(f"{label} source path escapes the checkout") from exc
            revision = "HEAD"
            if proof["kind"] == "project_change":
                base_ref = case.get("base_ref")
                head_ref = case.get("head_ref")
                if not isinstance(base_ref, str) or not isinstance(head_ref, str):
                    raise ProtocolViolation(f"{label} requires base_ref and head_ref")
                if repo_relative_path not in changed_paths(base_ref, head_ref, label):
                    raise ProtocolViolation(
                        f"{label} path is not present in git diff base_ref..head_ref"
                    )
                revision = head_ref
                added = added_lines(base_ref, head_ref, repo_relative_path, label)
                excerpt_value = proof.get("source_excerpt")
                if not isinstance(excerpt_value, str):
                    raise ProtocolViolation(f"{label}.source_excerpt is missing")
                excerpt_lines = [line for line in excerpt_value.splitlines() if line.strip()]
                if not excerpt_lines or any(line.rstrip("\r") not in added for line in excerpt_lines):
                    raise ProtocolViolation(
                        f"{label}.source_excerpt is not a head-side changed line"
                    )
            elif proof["kind"] == "project_test":
                accepted = case.get("accepted_test_paths")
                change_test_contract = case.get("task_family") in CHANGE_TEST_FAMILIES or any(
                    field in case for field in ("base_ref", "head_ref", "accepted_test_paths")
                )
                if change_test_contract and (
                    not isinstance(accepted, list) or repo_relative_path not in accepted
                ):
                    raise ProtocolViolation(
                        f"{label} test path is not in accepted_test_paths"
                    )
                head_ref = case.get("head_ref") or case.get("project_source_commit")
                if not isinstance(head_ref, str):
                    raise ProtocolViolation(f"{label} requires head_ref or project_source_commit")
                _require_sha(head_ref, f"{label}.head_ref")
                revision = head_ref
            source_text = git_show(revision, repo_relative_path, label)
            _validate_source_excerpt(source_text, proof["anchor"], proof.get("source_excerpt"), label)


def validate_project_source_proofs(
    target_checkout: str | Path,
    *,
    expected_commit: str = TARGET_PROJECT_COMMIT,
    cases: list[dict[str, Any]] | None = None,
) -> None:
    """Audit every project proof against an exact clean frozen target checkout."""

    checkout = _validate_frozen_git_checkout(
        target_checkout,
        expected_commit=expected_commit,
        label="target project",
    )
    _validate_source_proof_files(
        _proof_cases(cases),
        source_root=checkout,
        proof_kinds={"project_code", "project_doc", "project_change", "project_test"},
        source_label="project",
        git_checkout=checkout,
    )


def validate_knowledge_source_proofs(
    corpus_checkout: str | Path,
    *,
    expected_commit: str = CORPUS_SOURCE_COMMIT,
    cases: list[dict[str, Any]] | None = None,
) -> None:
    """Audit every knowledge proof against the frozen agent_data checkout."""

    checkout = _validate_frozen_git_checkout(
        corpus_checkout,
        expected_commit=expected_commit,
        label="knowledge corpus",
        allow_untracked=True,
    )
    manifest_corpus_path = Path(load_protocol_manifest()["corpus_identity"]["path"])
    candidate_root = checkout / manifest_corpus_path
    source_root = candidate_root if candidate_root.is_dir() else checkout
    if not source_root.is_dir():
        raise ProtocolViolation("knowledge corpus source root is missing")
    _validate_source_proof_files(
        _proof_cases(cases),
        source_root=source_root,
        proof_kinds={"knowledge"},
        source_label="knowledge",
        git_checkout=checkout,
    )


_GOLD_PROOF_AUDIT_FIELDS = frozenset(
    {
        "case_id",
        "obligation_id",
        "proof_kind",
        "relative_path",
        "anchor",
        "source_excerpt",
        "review_decision",
        "review_note",
    }
)


def load_gold_proof_audit(
    path: str | Path = GOLD_PROOF_AUDIT_PATH,
) -> list[dict[str, Any]]:
    """Load the human semantic-provenance review, never a result artifact."""

    audit_path = Path(path)
    if not audit_path.is_file():
        raise ProtocolViolation(f"Gold proof audit is missing: {audit_path}")
    records: list[dict[str, Any]] = []
    with audit_path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ProtocolViolation(f"Gold proof audit line {line_number} is blank")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProtocolViolation(
                    f"Gold proof audit line {line_number} is not valid JSON"
                ) from exc
            if not isinstance(record, Mapping):
                raise ProtocolViolation(f"Gold proof audit line {line_number} must be an object")
            if set(record) != _GOLD_PROOF_AUDIT_FIELDS:
                raise ProtocolViolation(
                    f"Gold proof audit line {line_number} has invalid fields"
                )
            _require_text(record.get("case_id"), "gold proof audit case_id", max_chars=32)
            _require_text(record.get("obligation_id"), "gold proof audit obligation_id", max_chars=32)
            if record.get("proof_kind") not in PUBLIC_EVIDENCE_KINDS:
                raise ProtocolViolation("Gold proof audit proof_kind is invalid")
            _safe_relative_path(record.get("relative_path"), "gold proof audit relative_path")
            _require_text(record.get("anchor"), "gold proof audit anchor", max_chars=300)
            _require_text(record.get("source_excerpt"), "gold proof audit source_excerpt", max_chars=300)
            if record.get("review_decision") not in {"ACCEPT", "REVISE"}:
                raise ProtocolViolation("Gold proof audit review_decision is invalid")
            _require_text(record.get("review_note"), "gold proof audit review_note", max_chars=1200)
            _walk_forbidden(record)
            records.append(dict(record))
    if not records:
        raise ProtocolViolation("Gold proof audit must not be empty")
    return records


def validate_gold_proof_audit(
    cases: list[dict[str, Any]] | None = None,
    *,
    audit_path: str | Path = GOLD_PROOF_AUDIT_PATH,
) -> None:
    """Require one independently reviewable ACCEPT record for every Gold proof."""

    expected: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for case in _proof_cases(cases):
        for proof in case["source_proofs"]:
            for obligation_id in proof["obligation_ids"]:
                key = (
                    case["case_id"],
                    obligation_id,
                    proof["kind"],
                    proof["relative_path"],
                    proof["anchor"],
                )
                if key in expected:
                    raise ProtocolViolation("Gold proof audit key is duplicated by dataset proofs")
                expected[key] = {
                    "case_id": case["case_id"],
                    "obligation_id": obligation_id,
                    "proof_kind": proof["kind"],
                    "relative_path": proof["relative_path"],
                    "anchor": proof["anchor"],
                    "source_excerpt": proof["source_excerpt"],
                }
    records = load_gold_proof_audit(audit_path)
    seen: set[tuple[str, str, str, str, str]] = set()
    for record in records:
        key = (
            record["case_id"],
            record["obligation_id"],
            record["proof_kind"],
            record["relative_path"],
            record["anchor"],
        )
        if key in seen:
            raise ProtocolViolation("Gold proof audit contains a duplicate record")
        seen.add(key)
        if key not in expected:
            raise ProtocolViolation("Gold proof audit does not match dataset proofs")
        if record["source_excerpt"] != expected[key]["source_excerpt"]:
            raise ProtocolViolation("Gold proof audit source_excerpt does not match dataset proof")
        if record["review_decision"] != "ACCEPT":
            raise ProtocolViolation(
                "Gold proof audit is not closed: every record requires independent ACCEPT"
            )
    if seen != set(expected):
        raise ProtocolViolation("Gold proof audit is missing a dataset proof record")


def validate_corpus_identity(observed: Mapping[str, Any], expected: Mapping[str, Any] | None = None) -> None:
    if not isinstance(observed, Mapping):
        raise ProtocolViolation("corpus identity must be an object")
    expected = expected or load_protocol_manifest()["corpus_identity"]
    if not isinstance(expected, Mapping):
        raise ProtocolViolation("expected corpus identity must be an object")
    required = (
        "repository",
        "source_commit",
        "path",
        "corpus_id",
        "file_count",
        "chunk_count",
        "retrieval_strategy",
        "manifest_experiment_id",
    )
    for field in required:
        if observed.get(field) != expected.get(field):
            raise ProtocolViolation(f"corpus identity mismatch at {field}")


def load_protocol_manifest(path: str | Path = MANIFEST_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ProtocolViolation(f"protocol manifest is missing: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("protocol manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise ProtocolViolation("protocol manifest must be an object")
    return manifest


def _manifest_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(manifest)
    payload.pop("protocol_sha256", None)
    return payload


def _computed_protocol_sha256(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_manifest_payload(manifest))).hexdigest()


def _toolset_identity(names: tuple[str, ...]) -> dict[str, Any]:
    registry_specs = {
        CALCULATOR_SPEC.name: CALCULATOR_SPEC,
        CHANGED_FILES_SPEC.name: CHANGED_FILES_SPEC,
        CODE_SEARCH_SPEC.name: CODE_SEARCH_SPEC,
        FIND_TESTS_SPEC.name: FIND_TESTS_SPEC,
        GIT_DIFF_SPEC.name: GIT_DIFF_SPEC,
        KNOWLEDGE_SEARCH_SPEC.name: KNOWLEDGE_SEARCH_SPEC,
        READ_PROJECT_CONTEXT_SPEC.name: READ_PROJECT_CONTEXT_SPEC,
    }
    return {"names": list(names), "sha256": compute_toolset_sha256(tuple(registry_specs[name] for name in names))}


def _validate_system_a_toolset_identity(system_a: Mapping[str, Any]) -> None:
    toolset = system_a.get("toolset")
    if not isinstance(toolset, Mapping):
        raise ProtocolViolation("System A toolset identity must be an object")
    expected = _toolset_identity(SYSTEM_A_DYNAMIC_TOOL_NAMES)
    base = toolset.get("base_registry")
    effective = toolset.get("effective_dynamic_registry")
    if toolset.get("names") != expected["names"] or toolset.get("sha256") != expected["sha256"]:
        raise ProtocolViolation("System A base toolset identity drift")
    if base != expected or effective != expected:
        raise ProtocolViolation("System A effective toolset identity drift")


def _validate_current_system_b_identity(system_b: Mapping[str, Any]) -> None:
    if not isinstance(system_b, Mapping):
        raise ProtocolViolation("System B identity must be an object")
    budget = ToolAgentBudget()
    expected_budget = {
        "max_agent_iterations": budget.max_agent_iterations,
        "max_tool_calls": budget.max_tool_calls,
        "max_tool_errors": budget.max_tool_errors,
    }
    expected_base_toolset = _toolset_identity(SYSTEM_A_DYNAMIC_TOOL_NAMES)
    expected_effective_toolset = _toolset_identity(SYSTEM_B_DYNAMIC_TOOL_NAMES)
    checks = {
        "provider": FROZEN_TOOL_PROVIDER,
        "model": FROZEN_TOOL_MODEL,
        "engineering_prompt_version": ENGINEERING_DECISION_PROMPT_V2_PROFILE.version,
        "engineering_prompt_sha256": ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256,
        "repair_prompt_version": ACTION_REPAIR_PROMPT_VERSION,
        "repair_prompt_sha256": ACTION_REPAIR_PROMPT_SHA256,
        "max_parse_repairs": max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE),
        "max_output_tokens": max_output_tokens_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE),
        "budget": expected_budget,
        "toolset_sha256": expected_base_toolset["sha256"],
    }
    engineering_prompt = system_b.get("engineering_prompt")
    repair_prompt = system_b.get("repair_prompt")
    toolset = system_b.get("toolset")
    if not all(isinstance(value, Mapping) for value in (engineering_prompt, repair_prompt, toolset)):
        raise ProtocolViolation("System B prompt/repair/toolset identities must be objects")
    observed = {
        "provider": system_b.get("provider"),
        "model": system_b.get("model"),
        "engineering_prompt_version": engineering_prompt.get("version"),
        "engineering_prompt_sha256": engineering_prompt.get("sha256"),
        "repair_prompt_version": repair_prompt.get("version"),
        "repair_prompt_sha256": repair_prompt.get("sha256"),
        "max_parse_repairs": repair_prompt.get("max_parse_repairs"),
        "max_output_tokens": system_b.get("max_output_tokens"),
        "budget": system_b.get("budget"),
        "toolset_sha256": toolset.get("sha256"),
    }
    if observed != checks:
        raise ProtocolViolation(f"System B product identity drift: {observed!r} != {checks!r}")
    expected_planned_backend = {
        "component": "EngineeringRetrievalComponent",
        "capability": "knowledge_evidence",
        "strategy": "bm25",
        "top_k": RETRIEVAL_TOP_K,
        "max_planned_retrieval_calls": MAX_RETRIEVAL_CALLS,
    }
    if toolset.get("base_registry") != expected_base_toolset:
        raise ProtocolViolation("System B base toolset identity drift")
    if toolset.get("effective_dynamic_registry") != expected_effective_toolset:
        raise ProtocolViolation("System B effective dynamic toolset identity drift")
    if toolset.get("planned_knowledge_backend") != expected_planned_backend:
        raise ProtocolViolation("System B planned knowledge backend identity drift")

    planner = system_b.get("planner")
    adaptive_policy = system_b.get("adaptive_policy")
    planned_retrieval = system_b.get("planned_retrieval")
    verifier = system_b.get("evidence_verifier")
    context_resolver = system_b.get("context_resolver")
    requirement_router = system_b.get("requirement_router")
    if not all(
        isinstance(value, Mapping)
        for value in (planner, adaptive_policy, planned_retrieval, verifier, context_resolver, requirement_router)
    ):
        raise ProtocolViolation("System B component identities must be objects")
    component_checks = {
        "planner": {
            "prompt_version": PLANNER_PROMPT_VERSION,
            "prompt_sha256": PLANNER_PROMPT_SHA256,
            "user_payload_version": "planner_user_payload_v1",
            "max_output_tokens": PLANNER_MAX_OUTPUT_TOKENS,
            "network_retry": PLANNER_MAX_RETRIES,
        },
        "adaptive_policy": {"version": ADAPTIVE_RETRIEVAL_POLICY_VERSION},
        "planned_retrieval": {
            "top_k": RETRIEVAL_TOP_K,
            "max_planned_retrieval_calls": MAX_RETRIEVAL_CALLS,
            "max_evidence_items": MAX_EVIDENCE_ITEMS,
            "merge_policy": SUBQUERY_RRF_MERGE_V2,
            "rrf_k": DEFAULT_MERGE_RRF_K,
        },
        "evidence_verifier": {
            "module": "core/engineering_verification.py",
            "contract_class": "EngineeringVerificationResult",
            "source_commit": SYSTEM_B_COMMIT,
        },
        "context_resolver": {
            "prompt_version": RESOLVER_PROMPT_VERSION,
            "max_output_tokens": RESOLVER_MAX_OUTPUT_TOKENS,
            "network_retry": RESOLVER_MAX_RETRIES,
        },
        "requirement_router": {"version": ROUTER_VERSION},
    }
    component_values = {
        "planner": planner,
        "adaptive_policy": adaptive_policy,
        "planned_retrieval": planned_retrieval,
        "evidence_verifier": verifier,
        "context_resolver": context_resolver,
        "requirement_router": requirement_router,
    }
    for name, expected in component_checks.items():
        if dict(component_values[name]) != expected:
            raise ProtocolViolation(f"System B {name} identity drift")


def validate_protocol_manifest(path: str | Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = load_protocol_manifest(manifest_path)
    if manifest.get("schema_version") != PROTOCOL_SCHEMA_VERSION or manifest.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolViolation("protocol manifest schema/version mismatch")
    if manifest.get("protocol_sha256") != _computed_protocol_sha256(manifest):
        raise ProtocolViolation("protocol manifest SHA mismatch")
    if manifest.get("case_count") != 27:
        raise ProtocolViolation("protocol case_count must be 27")
    if manifest.get("system_a_commit") != SYSTEM_A_COMMIT or manifest.get("system_b_commit") != SYSTEM_B_COMMIT:
        raise ProtocolViolation("top-level System A/B commit identity drift")
    if manifest.get("target_project_commit") != TARGET_PROJECT_COMMIT:
        raise ProtocolViolation("top-level target project commit drift")
    if manifest.get("family_counts") != EXPECTED_FAMILY_COUNTS:
        raise ProtocolViolation("family count matrix drift")
    target = manifest.get("target_project")
    validate_target_project_binding(target)
    corpus = manifest.get("corpus_identity")
    validate_corpus_identity(corpus)
    systems = manifest.get("systems")
    if not isinstance(systems, Mapping) or set(systems) != {"A", "B"}:
        raise ProtocolViolation("protocol must contain exactly System A and System B")
    if not all(isinstance(systems[name], Mapping) for name in ("A", "B")):
        raise ProtocolViolation("System identities must be objects")
    if systems["A"].get("source_commit") != SYSTEM_A_COMMIT:
        raise ProtocolViolation("System A source commit drift")
    if systems["B"].get("source_commit") != SYSTEM_B_COMMIT:
        raise ProtocolViolation("System B source commit drift")
    _validate_system_a_toolset_identity(systems["A"])
    _validate_current_system_b_identity(systems["B"])
    if systems["A"].get("target_project_commit") != TARGET_PROJECT_COMMIT or systems["B"].get("target_project_commit") != TARGET_PROJECT_COMMIT:
        raise ProtocolViolation("A/B must bind the same target project commit")
    if systems["A"].get("corpus_identity") != systems["B"].get("corpus_identity"):
        raise ProtocolViolation("A/B corpus identities differ")
    tool_coverage = manifest.get("tool_coverage")
    if not isinstance(tool_coverage, Mapping):
        raise ProtocolViolation("tool coverage contract is missing")
    if tool_coverage.get("scope") != "system_contract_local":
        raise ProtocolViolation("tool coverage must be system-contract-local")
    if tool_coverage.get("knowledge_acquisition") != {
        "A": "knowledge_search",
        "B": "planned_retrieval",
    }:
        raise ProtocolViolation("knowledge acquisition tool mapping drift")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, Mapping) or set(datasets) != {DEV_SPLIT, HOLDOUT_SPLIT}:
        raise ProtocolViolation("protocol must contain exactly Dev and Holdout dataset entries")
    for split in (DEV_SPLIT, HOLDOUT_SPLIT):
        if not isinstance(datasets[split], Mapping):
            raise ProtocolViolation(f"{split} dataset manifest entry must be an object")
        if datasets[split].get("case_count") != EXPECTED_CASE_COUNTS[split]:
            raise ProtocolViolation(f"{split} dataset case count drift")
        if type(datasets[split].get("file")) is not str or Path(datasets[split]["file"]).name != datasets[split]["file"]:
            raise ProtocolViolation(f"{split} dataset file must be a local package filename")
    dev_path = manifest_path.parent / datasets[DEV_SPLIT]["file"]
    holdout_path = manifest_path.parent / datasets[HOLDOUT_SPLIT]["file"]
    dev_cases = load_cases(dev_path)
    holdout_cases = load_cases(holdout_path)
    _validate_dataset_pair(dev_cases, holdout_cases)
    for split, path in ((DEV_SPLIT, dev_path), (HOLDOUT_SPLIT, holdout_path)):
        if manifest["datasets"][split]["sha256"] != canonical_jsonl_sha256(path):
            raise ProtocolViolation(f"{split} dataset SHA mismatch")
    gold_audit = manifest.get("gold_proof_audit")
    if not isinstance(gold_audit, Mapping):
        raise ProtocolViolation("gold_proof_audit metadata is missing")
    audit_filename = gold_audit.get("file")
    if (
        type(audit_filename) is not str
        or Path(audit_filename).name != audit_filename
        or not audit_filename
    ):
        raise ProtocolViolation("gold_proof_audit file must be a local package filename")
    audit_path = manifest_path.parent / audit_filename
    audit_records = load_gold_proof_audit(audit_path)
    expected_audit_count = sum(
        len(proof["obligation_ids"])
        for case in dev_cases + holdout_cases
        for proof in case["source_proofs"]
    )
    if gold_audit.get("record_count") != expected_audit_count or len(audit_records) != expected_audit_count:
        raise ProtocolViolation("gold_proof_audit record count drift")
    if gold_audit.get("review_decision") != "PREPARED_ACCEPT_PENDING_INDEPENDENT_AUDIT":
        raise ProtocolViolation("gold_proof_audit review decision drift")
    required_audit_flags = (
        "agent_may_not_self_accept",
        "independent_final_acceptance_required",
        "semantic_entailment_is_not_automated",
    )
    if any(gold_audit.get(flag) is not True for flag in required_audit_flags):
        raise ProtocolViolation("gold_proof_audit independence boundary drift")
    validate_gold_proof_audit(cases=dev_cases + holdout_cases, audit_path=audit_path)
    expected_supersession_history = [
        {
            "revision": "R0",
            "protocol_sha256": "e440ed8c32b366e99980b3b3fbd01f4325978547b929fbd6e94adec48b791f42",
            "superseded_by": "R1",
            "product_run": False,
            "product_result": False,
        },
        {
            "revision": "R1",
            "protocol_sha256": "534c0a69c817125c23cf2b1d75d60df1c3cd65dacf13844ee4b654206e313d31",
            "superseded_by": "R2",
            "product_run": False,
            "product_result": False,
        },
        {
            "revision": "R2",
            "protocol_sha256": "c15d7cb9c9a363b52dd76182225ede4641637acfe85c6b67d9870fc26a9ec1f5",
            "superseded_by": "R3",
            "product_run": False,
            "product_result": False,
        },
        {
            "revision": "R3",
            "supersedes": "R2",
            "product_run": False,
            "product_result": False,
        },
    ]
    if manifest.get("supersession_history") != expected_supersession_history:
        raise ProtocolViolation("protocol supersession history drift")
    expected_case_coherence = {
        "validator": "validate_case_gold_coherence",
        "path_classification_source": "core.tool_agent.runtime",
        "required_evidence_groups_must_be_gold_backed": True,
        "min_distinct_project_code_paths_must_be_gold_backed": True,
        "theory_code_requires_bilateral_gold": True,
        "knowledge_sources_must_match_knowledge_proofs": True,
        "r3_reviewed_cases": [
            "v7d005",
            "v7d006",
            "v7d008",
            "v7d010",
            "v7d014",
            "v7h006",
            "v7h007",
        ],
    }
    if manifest.get("case_coherence") != expected_case_coherence:
        raise ProtocolViolation("case coherence contract metadata drift")
    historical_questions, historical_proofs = _historical_g12_questions_and_proofs()
    for case in dev_cases + holdout_cases:
        if _normalise_question(case["question"]) in historical_questions:
            raise ProtocolViolation(f"case {case['case_id']} overlaps a historical G12 question")
        identities = _validate_proofs(case, {item["id"] for item in case["gold_obligations"]})
        if identities & historical_proofs:
            raise ProtocolViolation(f"case {case['case_id']} reuses an exact G12 source proof identity")
    if manifest.get("metric_schema", {}).get("schema_version") != METRIC_SCHEMA_VERSION:
        raise ProtocolViolation("metric schema identity mismatch")
    if manifest.get("manual_rubric", {}).get("schema_version") != MANUAL_RUBRIC_VERSION:
        raise ProtocolViolation("manual rubric identity mismatch")
    return manifest


def assert_execution_allowed(split: str, *, confirm_frozen_candidate: str | None = None) -> None:
    """Allow Dev contract inspection; deny Holdout without exact confirmation."""

    if split == DEV_SPLIT:
        return
    if split != HOLDOUT_SPLIT:
        raise HoldoutExecutionDenied("unknown split is denied")
    manifest = load_protocol_manifest()
    expected = manifest["datasets"][HOLDOUT_SPLIT]["sha256"]
    if confirm_frozen_candidate != expected:
        raise HoldoutExecutionDenied(
            "Holdout is deny-by-default; require --split holdout and exact --confirm-frozen-candidate SHA"
        )
