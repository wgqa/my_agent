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
from core.tool_agent.runtime_models import ToolAgentBudget


PACKAGE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = PACKAGE_ROOT / "protocol_manifest_v1.json"
DEV_DATASET_PATH = PACKAGE_ROOT / "integration_dev_v1.jsonl"
HOLDOUT_DATASET_PATH = PACKAGE_ROOT / "integration_holdout_v1.jsonl"
HISTORICAL_G12_PATH = PACKAGE_ROOT.parent / "gate12" / "final_benchmark_v1.jsonl"

CASE_SCHEMA_VERSION = "integration_v7_case_v1"
PROTOCOL_SCHEMA_VERSION = "integration_v7_protocol_manifest_v1"
PROTOCOL_VERSION = "v7_architecture_integration_evaluation_v1"
METRIC_SCHEMA_VERSION = "integration_v7_metrics_v1"
MANUAL_RUBRIC_VERSION = "integration_v7_manual_rubric_v1"
DEV_SPLIT = "integration_dev"
HOLDOUT_SPLIT = "integration_holdout"

SYSTEM_A_COMMIT = "0eef8ef9d6decdaa10efebe04087b06611654670"
SYSTEM_B_COMMIT = "385b7795eafde7c114efc382e95c0d18ec273f54"
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
KNOWLEDGE_FAMILIES = frozenset({"knowledge_only", "theory_code", "decomposed_knowledge"})
CONTEXT_FAMILIES = frozenset({"context_followup"})
CHANGE_TEST_FAMILIES = frozenset({"change_test"})
_DIFFICULTIES = frozenset({"basic", "intermediate", "complex", "adversarial"})
_OUTCOMES = frozenset({"answerable", "refusal"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CASE_ID_RE = re.compile(r"^v7[dh][0-9]{3}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_WHITESPACE_RE = re.compile(r"\s+")
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


def _validate_string_list(value: object, label: str, *, allowed: set[str] | frozenset[str]) -> list[str]:
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise ProtocolViolation(f"{label} must be a list of strings")
    if len(set(value)) != len(value) or any(item not in allowed for item in value):
        raise ProtocolViolation(f"{label} contains duplicates or unsupported values")
    return value


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
        normalized_groups.append(tuple(group))
    if case["expected_outcome"] not in _OUTCOMES:
        raise ProtocolViolation("expected_outcome must be answerable or refusal")
    if case["expected_outcome"] == "refusal" and normalized_groups:
        raise ProtocolViolation("insufficient_refusal must not claim answer evidence obligations")
    if case["expected_outcome"] == "answerable" and not normalized_groups:
        raise ProtocolViolation("answerable case requires required_evidence_groups")

    required_tools = _validate_string_list(case["required_tools"], "required_tools", allowed=TOOLS)
    forbidden_tools = _validate_string_list(case["forbidden_tools"], "forbidden_tools", allowed=TOOLS)
    if set(required_tools) & set(forbidden_tools):
        raise ProtocolViolation("required_tools and forbidden_tools overlap")
    min_paths = case["min_distinct_project_code_paths"]
    if type(min_paths) is not int or min_paths < 0 or min_paths > 5:
        raise ProtocolViolation("min_distinct_project_code_paths must be an int from 0 to 5")
    if family in {"repo_only", "theory_code", "docs_code", "diagnosis", "change_test"} and min_paths < 1:
        raise ProtocolViolation("project-evidence family requires at least one project-code path")
    if family == "diagnosis" and min_paths < 2:
        raise ProtocolViolation("diagnosis requires cross-file project evidence")

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


def _validate_current_system_b_identity(system_b: Mapping[str, Any]) -> None:
    if not isinstance(system_b, Mapping):
        raise ProtocolViolation("System B identity must be an object")
    budget = ToolAgentBudget()
    expected_budget = {
        "max_agent_iterations": budget.max_agent_iterations,
        "max_tool_calls": budget.max_tool_calls,
        "max_tool_errors": budget.max_tool_errors,
    }
    registry_specs = (
        CALCULATOR_SPEC,
        CHANGED_FILES_SPEC,
        CODE_SEARCH_SPEC,
        FIND_TESTS_SPEC,
        GIT_DIFF_SPEC,
        KNOWLEDGE_SEARCH_SPEC,
        READ_PROJECT_CONTEXT_SPEC,
    )
    expected_toolset = compute_toolset_sha256(registry_specs)
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
        "toolset_sha256": expected_toolset,
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
    _validate_current_system_b_identity(systems["B"])
    if systems["A"].get("target_project_commit") != TARGET_PROJECT_COMMIT or systems["B"].get("target_project_commit") != TARGET_PROJECT_COMMIT:
        raise ProtocolViolation("A/B must bind the same target project commit")
    if systems["A"].get("corpus_identity") != systems["B"].get("corpus_identity"):
        raise ProtocolViolation("A/B corpus identities differ")
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
