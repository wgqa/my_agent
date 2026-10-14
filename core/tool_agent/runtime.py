"""G4-RUNTIME-05：Bounded Tool Agent Loop。

第一次把 Decision Provider → AgentAction → ToolCall → ToolExecutor →
ToolObservation 接成 Decision → Action → Observation → Decision 的有界
循环。硬预算（5/4/2）由 ToolAgentBudget 系统控制，LLM 无权修改；完全
重复 ToolCall 去重、连续失败重复阻止、最后一次 Decision 不再执行 Tool
（AGENT_BUDGET_EXCEEDED）。Tool Observation 是"不可信事实"，以
DecisionContextItem 反馈给模型，但绝不作为系统指令。本模块不调用真实 LLM。
"""

from __future__ import annotations

import json
import hashlib
import inspect
import re
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable

from core.engineering_requirements import (
    EngineeringEvidenceRequirement,
    EvidenceRequirementState,
    evaluate_evidence_requirement,
)
from core.engineering_verification import (
    ANSWER_EVIDENCE_REFERENCE_INCOMPLETE,
    ANSWER_EVIDENCE_REFERENCE_INVALID,
    ANSWER_EVIDENCE_REFERENCE_MISSING,
    INVALID_CITATION_REFERENCE,
)
from core.tool_agent.activity import (
    ActivityEvent,
    EvidenceAddedActivity,
    RunStartedActivity,
    VerificationBlockedActivity,
    build_tool_activity_event,
)
from core.tool_agent.actions import (
    ACTION_PARSE_FAILED,
    ACTION_PROVIDER_ERROR,
    ACTION_TIMEOUT,
    AgentDecisionOutcome,
    ChangedFilesFinalizationAction,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from core.tool_agent.changed_files_typed_finalization import (
    ChangedFilesExecution,
    ChangedFilesSelectorOutcome,
    finalize_changed_files_typed,
)
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import AGENT_BUDGET_EXCEEDED, ToolCall, json_deep_copy
from core.tool_agent.project_files import (
    PROJECT_CODE_SUFFIXES as _PROJECT_CODE_SUFFIXES,  # Legacy evaluation import.
    classify_project_evidence_path,
)
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime_models import (
    AGENT_DUPLICATE_TOOL_CALL,
    AGENT_TOOL_ERROR_LIMIT,
    ENGINEERING_RUN_CANCELLED,
    ENGINEERING_RUN_DEADLINE_EXCEEDED,
    INSUFFICIENT_EVIDENCE_TO_FINALIZE,
    AgentDecisionProvider,
    DecisionControlState,
    DecisionContextItem,
    DecisionEvidenceReference,
    EngineeringEvidence,
    KnowledgeEvidence,
    RuntimeTraceEvent,
    ToolResultEvidence,
    ToolAgentBudget,
    ToolAgentExecutionMetrics,
    ToolAgentRunResult,
)
from core.tool_agent.source_excerpt import project_context_fragments, project_context_snippet
from core.tool_agent.tools.code_search import MAX_MATCHES as CODE_SEARCH_MAX_MATCHES

PublicEvidence = EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence

_EVIDENCE_PRODUCER_TOOLS = {
    "knowledge": ("knowledge_search",),
    "project_change": ("git_diff",),
    "project_code": ("read_project_context",),
    "project_doc": ("read_project_context",),
    "project_test": ("read_project_context",),
}


def _canonical_call(tool_name: str, arguments) -> tuple[str, str]:
    """tool_name + canonical JSON(arguments) 作为逻辑 ToolCall 身份（不含 call_id）。"""
    canonical = json.dumps(
        json_deep_copy(arguments),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (tool_name, canonical)


def _normalize_initial_context(value: object) -> tuple[DecisionContextItem, ...]:
    """Validate the trusted context seed without accepting arbitrary dicts."""

    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise TypeError("initial_context 必须是 DecisionContextItem 序列")
    items = tuple(value)
    if any(type(item) is not DecisionContextItem for item in items):
        raise TypeError("initial_context 必须全部是 DecisionContextItem")
    return items


def _evidence_identity(
    item: EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence,
) -> tuple:
    if isinstance(item, KnowledgeEvidence):
        return (
            "knowledge",
            item.source_name,
            item.chunk_id if item.chunk_id is not None else item.snippet,
        )
    if isinstance(item, ToolResultEvidence):
        return (
            "tool_result",
            item.tool_name,
            item.tool_version,
            item.call_id,
            item.arguments_sha256,
            item.result_sha256,
            item.scope,
        )
    return (item.kind, item.path, item.start_line, item.end_line)


def _normalize_initial_evidence(
    value: object,
) -> tuple[EngineeringEvidence | KnowledgeEvidence, ...]:
    """Validate, deduplicate, and deterministically number trusted evidence."""

    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise TypeError("initial_evidence 必须是 EngineeringEvidence 序列")
    normalized: list[EngineeringEvidence | KnowledgeEvidence] = []
    seen_identities: set[tuple] = set()
    seen_ids: set[str] = set()
    for item in value:
        if type(item) not in (EngineeringEvidence, KnowledgeEvidence):
            raise TypeError(
                "initial_evidence 必须全部是 EngineeringEvidence 或 KnowledgeEvidence"
            )
        identity = _evidence_identity(item)
        if identity in seen_identities:
            continue
        if item.evidence_id in seen_ids:
            raise ValueError("initial_evidence 的 evidence_id 不得重复")
        seen_identities.add(identity)
        seen_ids.add(item.evidence_id)
        normalized.append(replace(item, evidence_id=f"E{len(normalized) + 1}"))
    return tuple(normalized)


def _normalize_disabled_tools(
    value: object,
    registry: ToolRegistry,
) -> frozenset[str]:
    """Validate a run-scoped Tool filter and reject unknown Tool names."""

    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Collection):
        raise TypeError("disabled_tools 必须是 Tool 名称集合")
    names = tuple(value)
    if any(type(name) is not str or not name.strip() for name in names):
        raise TypeError("disabled_tools 必须全部是非空字符串")
    if len(set(names)) != len(names):
        raise ValueError("disabled_tools 不得包含重复 Tool")
    unknown = sorted(set(names) - {spec.name for spec in registry.list_specs()})
    if unknown:
        raise ValueError(f"disabled_tools 含未注册 Tool: {unknown!r}")
    return frozenset(names)


def _evidence_from_project_context(observation) -> EngineeringEvidence | None:
    """Convert one successful context read into bounded public evidence.

    The executor has already validated the Tool output schema. The defensive
    checks here keep the runtime fail-closed if a future handler violates that
    contract: malformed observations never become API-visible evidence.
    """
    if observation.status != "ok" or observation.tool_name != "read_project_context":
        return None
    result = observation.result
    if type(result) is not dict:
        return None
    path = result.get("path")
    start_line = result.get("start_line")
    end_line = result.get("end_line")
    snippet = project_context_snippet(result)
    if snippet is None:
        return None
    try:
        kind = classify_project_evidence_path(path)
        return EngineeringEvidence(
            evidence_id="E1",
            kind=kind,
            path=path,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
        )
    except (TypeError, ValueError):
        return None


def _evidence_from_project_context_regions(observation) -> tuple[EngineeringEvidence, ...]:
    """One public source per actual Reader region, preserving legacy reads."""
    if observation.status != "ok" or observation.tool_name != "read_project_context" or type(observation.result) is not dict:
        return ()
    evidence = []
    for fragment in project_context_fragments(observation.result):
        item = _evidence_from_project_context(replace(observation, result=fragment))
        if item is None:
            return ()
        evidence.append(item)
    return tuple(evidence)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_repo_path(value: object) -> bool:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or "\\" in value
        or any(ord(char) < 32 for char in value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        return False
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    return not (
        windows_path.is_absolute()
        or windows_path.drive
        or posix_path.is_absolute()
        or any(part in (".", "..") for part in windows_path.parts)
        or any(part in (".", "..") for part in posix_path.parts)
    )


def _make_tool_result_evidence(
    observation,
    arguments: Mapping,
    tool_version: str,
    *,
    kind: str,
    granularity: str,
    completeness: str,
    scope: str,
    scope_paths: tuple[str, ...],
    path: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    status_entries: tuple[tuple[str, str, str | None], ...] = (),
    candidate_reasons: tuple[str, ...] = (),
) -> ToolResultEvidence | None:
    complete_empty_status_list = (
        granularity == "status_list"
        and completeness == "complete"
        and not status_entries
    )
    if (
        observation.status != "ok"
        or observation.tool_name not in {"code_search", "changed_files", "find_tests", "git_diff"}
        or type(tool_version) is not str
        or not tool_version.strip()
        or not isinstance(arguments, Mapping)
        or type(observation.result) is not dict
        or type(observation.call_id) is not str
        or not observation.call_id.strip()
        or (not scope_paths and not complete_empty_status_list)
        or any(not _safe_repo_path(item) for item in scope_paths)
    ):
        return None
    try:
        return ToolResultEvidence(
            evidence_id="E1",
            kind=kind,
            tool_name=observation.tool_name,
            call_id=observation.call_id,
            tool_version=tool_version,
            arguments_json=_canonical_json(arguments),
            arguments_sha256=_sha256_json(arguments),
            result_sha256=_sha256_json(observation.result),
            granularity=granularity,
            completeness=completeness,
            scope=scope,
            scope_paths=scope_paths,
            path=path,
            start_line=start_line,
            end_line=end_line,
            status_entries=status_entries,
            candidate_reasons=candidate_reasons,
        )
    except (TypeError, ValueError):
        return None


def _evidence_from_code_search(observation, arguments: Mapping, tool_version: str) -> tuple[ToolResultEvidence, ...]:
    """Convert literal search hits to locator-only, never source-body Evidence."""
    if observation.status != "ok" or observation.tool_name != "code_search":
        return ()
    result = observation.result
    if type(result) is not dict or type(result.get("matches")) is not list:
        return ()
    requested_kind = arguments.get("artifact_kind", "any")
    if requested_kind not in {"any", "project_code", "project_doc", "project_test"}:
        return ()
    evidence: list[ToolResultEvidence] = []
    completeness = "partial" if len(result["matches"]) >= CODE_SEARCH_MAX_MATCHES else "complete"
    for match in result["matches"]:
        if type(match) is not dict:
            return ()
        path, line, text = match.get("path"), match.get("line"), match.get("text")
        if (
            not _safe_repo_path(path)
            or type(line) is not int
            or isinstance(line, bool)
            or line < 1
            or type(text) is not str
            or not text
        ):
            return ()
        try:
            kind = classify_project_evidence_path(path)
        except (TypeError, ValueError):
            return ()
        if requested_kind != "any" and kind != requested_kind:
            return ()
        item = _make_tool_result_evidence(
            observation,
            arguments,
            tool_version,
            kind=kind,
            granularity="locator",
            completeness=completeness,
            scope=f"literal search hit at {path}:{line}",
            scope_paths=(path,),
            path=path,
            start_line=line,
            end_line=line,
        )
        if item is None:
            return ()
        evidence.append(item)
    return tuple(evidence)


def _evidence_from_changed_files(observation, arguments: Mapping, tool_version: str) -> ToolResultEvidence | None:
    """Keep a changed_files inventory as a status list, never as diff/source."""
    if observation.status != "ok" or observation.tool_name != "changed_files":
        return None
    result = observation.result
    if type(result) is not dict or type(result.get("changes")) is not list:
        return None
    changes = result["changes"]
    paths: list[str] = []
    status_entries: list[tuple[str, str, str | None]] = []
    seen_change_paths: set[str] = set()
    for change in changes:
        if (
            type(change) is not dict
            or not _safe_repo_path(change.get("path"))
            or type(change.get("status")) is not str
            or change.get("status") not in {"modified", "added", "deleted", "renamed", "untracked"}
        ):
            return None
        path = change["path"]
        status = change["status"]
        if path in seen_change_paths:
            return None
        seen_change_paths.add(path)
        paths.append(path)
        old_path = change.get("old_path")
        if status == "renamed":
            if old_path is None or not _safe_repo_path(old_path) or old_path == path:
                return None
            paths.append(old_path)
        elif old_path is not None:
            return None
        status_entries.append((path, status, old_path))
    returned = result.get("returned_count")
    total = result.get("total_count")
    truncated = result.get("truncated")
    omitted = result.get("omitted_sensitive_count")
    if (
        type(returned) is not int or isinstance(returned, bool)
        or type(total) is not int or isinstance(total, bool)
        or type(truncated) is not bool
        or type(omitted) is not int or isinstance(omitted, bool)
        or returned != len(changes)
    ):
        return None
    complete = not truncated and omitted == 0 and total == returned
    if not paths and not (complete and not changes):
        return None
    scope_args = {
        key: arguments.get(key)
        for key in ("mode", "base_ref", "head_ref")
        if key in arguments
    }
    return _make_tool_result_evidence(
        observation,
        arguments,
        tool_version,
        kind="project_change",
        granularity="status_list",
        completeness="complete" if complete else "partial",
        scope=_canonical_json(scope_args),
        scope_paths=tuple(dict.fromkeys(paths)),
        status_entries=tuple(status_entries),
    )


def _evidence_from_find_tests(observation, arguments: Mapping, tool_version: str) -> tuple[ToolResultEvidence, ...]:
    """Keep find_tests output at candidate granularity, not test-body evidence."""
    if observation.status != "ok" or observation.tool_name != "find_tests":
        return ()
    result = observation.result
    source_path = arguments.get("path")
    candidates = result.get("candidates") if type(result) is dict else None
    if not _safe_repo_path(source_path) or type(candidates) is not list:
        return ()
    returned = result.get("returned_count")
    truncated = result.get("truncated")
    omitted = result.get("omitted_sensitive_count")
    if (
        type(returned) is not int or isinstance(returned, bool)
        or type(truncated) is not bool
        or type(omitted) is not int or isinstance(omitted, bool)
        or returned != len(candidates)
    ):
        return ()
    completeness = "complete" if not truncated and omitted == 0 else "partial"
    evidence: list[ToolResultEvidence] = []
    for candidate in candidates:
        if type(candidate) is not dict:
            return ()
        path, line, reasons = candidate.get("path"), candidate.get("line"), candidate.get("reasons")
        if (
            not _safe_repo_path(path)
            or type(line) is not int
            or isinstance(line, bool)
            or line < 1
            or type(reasons) is not list
            or not reasons
            or any(
                type(reason) is not str
                or reason not in {"mirrored_path", "filename_match", "content_reference"}
                for reason in reasons
            )
            or len(set(reasons)) != len(reasons)
        ):
            return ()
        item = _make_tool_result_evidence(
            observation,
            arguments,
            tool_version,
            kind="project_test",
            granularity="candidate",
            completeness=completeness,
            scope=f"candidate {path}:{line} for {source_path}",
            scope_paths=tuple(dict.fromkeys((source_path, path))),
            path=path,
            start_line=line,
            end_line=line,
            candidate_reasons=tuple(reasons),
        )
        if item is None:
            return ()
        evidence.append(item)
    return tuple(evidence)


def _evidence_from_tool_result(observation, call, tool_version: str | None) -> tuple[ToolResultEvidence, ...]:
    if (
        observation.status != "ok"
        or observation.call_id != call.call_id
        or observation.tool_name != call.tool_name
        or type(tool_version) is not str
    ):
        return ()
    arguments = call.arguments_copy()
    if call.tool_name == "code_search":
        return _evidence_from_code_search(observation, arguments, tool_version)
    if call.tool_name == "changed_files":
        item = _evidence_from_changed_files(observation, arguments, tool_version)
        return (item,) if item is not None else ()
    if call.tool_name == "find_tests":
        return _evidence_from_find_tests(observation, arguments, tool_version)
    if call.tool_name == "git_diff":
        result = observation.result
        path = result.get("path") if type(result) is dict else None
        start_line = result.get("start_line") if type(result) is dict else None
        end_line = result.get("end_line") if type(result) is dict else None
        truncated = result.get("truncated") if type(result) is dict else None
        if (
            not _safe_repo_path(path)
            or type(start_line) is not int or isinstance(start_line, bool) or start_line < 1
            or type(end_line) is not int or isinstance(end_line, bool) or end_line < start_line
            or type(result.get("diff")) is not str or not result.get("diff")
            or type(truncated) is not bool
        ):
            return ()
        item = _make_tool_result_evidence(
            observation,
            arguments,
            tool_version,
            kind="project_change",
            granularity="diff",
            completeness="partial" if truncated else "complete",
            scope=f"{result.get('mode')} diff for {path}",
            scope_paths=(path,),
            path=path,
            start_line=start_line,
            end_line=end_line,
        )
        return (item,) if item is not None else ()
    return ()


def _evidence_from_knowledge_search(observation) -> tuple[KnowledgeEvidence, ...]:
    """Convert only valid matches from one successful knowledge observation."""

    if observation.status != "ok" or observation.tool_name != "knowledge_search":
        return ()
    result = observation.result
    if type(result) is not dict or type(result.get("matches")) is not list:
        return ()
    evidence: list[KnowledgeEvidence] = []
    for match in result["matches"]:
        if type(match) is not dict:
            continue
        try:
            evidence.append(
                KnowledgeEvidence(
                    evidence_id="E1",
                    kind="knowledge",
                    source_name=match.get("source_name"),
                    chunk_id=match.get("chunk_id"),
                    score=match.get("score"),
                    rank=match.get("rank"),
                    snippet=match.get("snippet"),
                )
            )
        except (TypeError, ValueError):
            # Invalid backend data is not public evidence.
            continue
    return tuple(evidence)


def _evidence_fingerprint(
    evidence: list[PublicEvidence],
) -> tuple[tuple]:
    """Return an order-independent identity fingerprint without content."""

    identities: list[tuple] = []
    for item in evidence:
        if isinstance(item, KnowledgeEvidence):
            identities.append(
                (
                    "knowledge",
                    item.source_name,
                    item.chunk_id if item.chunk_id is not None else item.rank,
                )
            )
        elif isinstance(item, ToolResultEvidence):
            identities.append(_evidence_identity(item))
        else:
            identities.append(
                (item.kind, item.path, item.start_line, item.end_line)
            )
    return tuple(sorted(identities, key=repr))


def _missing_evidence_kinds(
    requirement: EngineeringEvidenceRequirement,
    state: EvidenceRequirementState,
) -> frozenset[str]:
    """Find producer kinds without pretending that a path shortfall is a group miss."""

    kinds = {
        kind
        for group in state.missing_evidence_groups
        for kind in group
    }
    if (
        not kinds
        and state.distinct_project_code_paths
        < requirement.min_distinct_project_code_paths
    ):
        kinds.add("project_code")
    return frozenset(kinds)


def _recovery_is_feasible(
    registry: ToolRegistry,
    requirement: EngineeringEvidenceRequirement,
    state: EvidenceRequirementState,
    *,
    iterations: int,
    tool_calls: int,
    tool_errors: int,
    budget: ToolAgentBudget,
) -> bool:
    """Check whether the next Decision can still execute a producer Tool."""

    # The last Decision cannot execute a Tool: the next iteration must be
    # strictly before the hard iteration cap.
    if iterations + 1 >= budget.max_agent_iterations:
        return False
    if tool_calls >= budget.max_tool_calls or tool_errors >= budget.max_tool_errors:
        return False
    for kind in _missing_evidence_kinds(requirement, state):
        if any(tool_name in registry for tool_name in _EVIDENCE_PRODUCER_TOOLS[kind]):
            return True
    return False


def _evidence_reference_catalog(
    evidence: list[PublicEvidence],
) -> tuple[DecisionEvidenceReference, ...]:
    """Deterministic metadata-only E-ID catalog of current public evidence."""

    refs: list[DecisionEvidenceReference] = []
    for item in evidence:
        if isinstance(item, ToolResultEvidence):
            refs.append(
                DecisionEvidenceReference(
                    evidence_id=item.evidence_id,
                    kind=item.kind,
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    granularity=item.granularity,
                    completeness=item.completeness,
                    tool_name=item.tool_name,
                    call_id=item.call_id,
                    tool_version=item.tool_version,
                    arguments_sha256=item.arguments_sha256,
                    result_sha256=item.result_sha256,
                    scope=item.scope,
                    scope_paths=item.scope_paths,
                    requirement_eligible=item.requirement_eligible,
                )
            )
        elif isinstance(item, KnowledgeEvidence):
            refs.append(
                DecisionEvidenceReference(
                    evidence_id=item.evidence_id,
                    kind=item.kind,
                    source_name=item.source_name,
                    chunk_id=item.chunk_id,
                    rank=item.rank,
                )
            )
        else:
            refs.append(
                DecisionEvidenceReference(
                    evidence_id=item.evidence_id,
                    kind=item.kind,
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    granularity=("diff" if item.kind == "project_change" else "source_body"),
                    completeness="unknown",
                )
            )
    return tuple(refs)


def _run_finalization_verifier(
    verifier,
    evidence: list[PublicEvidence],
    proposed_answer: str | None,
):
    """Run the one trusted Engineering verification seam, fail-fast on drift."""

    verify = getattr(verifier, "verify", None)
    if not callable(verify):
        raise TypeError("finalization_verifier 必须提供 verify 方法")
    result = verify(tuple(evidence), proposed_answer)
    from core.engineering_verification import EngineeringVerificationResult

    if not isinstance(result, EngineeringVerificationResult):
        raise TypeError(
            "finalization_verifier.verify 必须返回 EngineeringVerificationResult"
        )
    return result


_TYPED_SELECTOR_BINDING_BLOCKERS = frozenset(
    {
        INVALID_CITATION_REFERENCE,
        ANSWER_EVIDENCE_REFERENCE_MISSING,
        ANSWER_EVIDENCE_REFERENCE_INCOMPLETE,
        ANSWER_EVIDENCE_REFERENCE_INVALID,
    }
)


def _typed_selector_is_applicable(verification) -> bool:
    """Only replace a failed text binding when all existing hard checks pass."""

    reasons = tuple(getattr(verification, "insufficiency_reasons", ()))
    return (
        not verification.can_finalize
        and verification.retrieval_can_generate
        and verification.evidence_requirement_satisfied
        and bool(reasons)
        and set(reasons).issubset(_TYPED_SELECTOR_BINDING_BLOCKERS)
    )


_EVIDENCE_CITATION_LIKE = re.compile(r"\[\s*E[^\]\r\n]*\]")
_EVIDENCE_ID = re.compile(r"E[1-9][0-9]*")


def _lightweight_open_answer_check(finalization_verifier, evidence, answer: str, *, context=()) -> str | None:
    """Check current-run sources and hard requirements without legacy Binding.

    This intentionally does not test whether each natural-language claim is
    entailed by its cited source. It only checks the existing retrieval and
    Requirement obligations plus citation identity against this Run's
    Evidence objects.
    """
    if finalization_verifier is None:
        return "FINALIZATION_VERIFIER_REQUIRED"
    contract = getattr(finalization_verifier, "task_contract", None)
    if contract is not None and contract.operation == "file_status":
        return "TASK_REQUIRES_TYPED_FINALIZATION"
    verification = _run_finalization_verifier(
        finalization_verifier, evidence, None
    )
    if not verification.retrieval_can_generate:
        return "RETRIEVAL_NOT_SATISFIED"
    if not verification.evidence_requirement_satisfied:
        if contract is not None:
            material_error = contract.material_error(contract.scoped_evidence(evidence))
            if material_error is not None:
                return material_error
        return "EXISTING_REQUIREMENT_NOT_SATISFIED"

    citations = _EVIDENCE_CITATION_LIKE.findall(answer)
    available_ids = {
        getattr(item, "evidence_id", None)
        for item in evidence
        if type(getattr(item, "evidence_id", None)) is str
    }
    if any(
        not _EVIDENCE_ID.fullmatch(token.strip()[1:-1].strip())
        or token.strip()[1:-1].strip() not in available_ids
        for token in citations
    ):
        return "INVALID_CURRENT_RUN_EVIDENCE_REFERENCE"
    if evidence and not citations:
        return "CURRENT_RUN_EVIDENCE_REFERENCE_MISSING"
    if contract is not None:
        cited_ids = {token.strip()[1:-1].strip() for token in citations}
        selected = tuple(item for item in evidence if item.evidence_id in cited_ids)
        if contract.scoped_evidence(selected) != selected:
            return "TASK_CITATION_SCOPE_MISMATCH"
        selected_verification = _run_finalization_verifier(finalization_verifier, selected, None)
        if not selected_verification.evidence_requirement_satisfied:
            return "TASK_REQUIRED_MATERIAL_NOT_CITED"
        source_error = contract.source_context_error(context, selected)
        if source_error is not None:
            return source_error
    return None


class _ExecutionUsage:
    """Accumulate provider-reported usage from Decision and selector metadata.

    No second metering system: usage comes from the provider outcomes. Calls
    that did not report usage simply do not contribute, and a token total is
    ``None`` when no call reported that token kind.
    """

    def __init__(self) -> None:
        self.decision_llm_calls = 0
        self.selector_llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.selector_latency_ms = 0.0
        self.selector_latency_seen = False
        self.input_seen = False
        self.output_seen = False

    def record(self, call_metadata) -> None:
        if call_metadata is None:
            return
        self.decision_llm_calls += call_metadata.call_count
        if call_metadata.input_tokens is not None:
            self.input_tokens += call_metadata.input_tokens
            self.input_seen = True
        if call_metadata.output_tokens is not None:
            self.output_tokens += call_metadata.output_tokens
            self.output_seen = True

    def record_selector(self, outcome: ChangedFilesSelectorOutcome) -> None:
        self.selector_llm_calls += outcome.call_metadata.call_count
        self.selector_latency_ms += outcome.call_metadata.latency_ms
        self.selector_latency_seen = True
        if outcome.call_metadata.input_tokens is not None:
            self.input_tokens += outcome.call_metadata.input_tokens
            self.input_seen = True
        if outcome.call_metadata.output_tokens is not None:
            self.output_tokens += outcome.call_metadata.output_tokens
            self.output_seen = True


def _attach_execution_metrics(
    result: ToolAgentRunResult,
    *,
    elapsed_ms: int,
    usage: "_ExecutionUsage",
) -> ToolAgentRunResult:
    metrics = ToolAgentExecutionMetrics(
        elapsed_ms=elapsed_ms,
        decision_llm_calls=usage.decision_llm_calls,
        selector_llm_calls=usage.selector_llm_calls,
        input_tokens=usage.input_tokens if usage.input_seen else None,
        output_tokens=usage.output_tokens if usage.output_seen else None,
        selector_latency_ms=(
            usage.selector_latency_ms if usage.selector_latency_seen else None
        ),
    )
    return replace(result, execution=metrics)


class ToolAgentRuntime:
    """Bounded Decision → Tool → Observation execution component。

    During Unified Engineering migration it enforces the existing 5/4/2
    hard limits, but it is not a second Agent/controller or logical budget
    owner.  Unified Runtime may opt into first-decision evidence acquisition
    enforcement; that policy remains inside this same bounded loop.

    Executor 固定为 ToolExecutor(registry)：Decision 与执行始终绑定同一个
    registry，杜绝 "模型看到的能力" 与 "系统实际执行的能力" 分裂。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        provider: AgentDecisionProvider,
        budget: ToolAgentBudget | None = None,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry 必须是 ToolRegistry")
        if not isinstance(provider, AgentDecisionProvider) or not callable(
            getattr(provider, "decide", None)
        ):
            raise TypeError("provider 必须实现 AgentDecisionProvider（含 decide）")
        if budget is None:
            budget = ToolAgentBudget()
        elif type(budget) is not ToolAgentBudget:
            raise TypeError(
                "budget 必须是 ToolAgentBudget 或 None（不接受 duck typing / dict / bool / 自定义对象）"
            )
        self._registry = registry
        self._provider = provider
        self._executor = ToolExecutor(registry)
        self._budget = budget

    def run(
        self,
        user_query: str,
        *,
        evidence_requirement: EngineeringEvidenceRequirement | None = None,
        initial_context: Sequence[DecisionContextItem] = (),
        initial_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence] = (),
        disabled_tools: Collection[str] = (),
        finalization_verifier=None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
        enforce_evidence_acquisition: bool = False,
        finalization_strategy: str = "legacy",
        deadline_seconds: float | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ToolAgentRunResult:
        """One bounded run with product lifecycle governance.

        ``deadline_seconds`` is a system-owned cooperative deadline and
        ``cancel_requested`` a disconnect/cancellation probe; both are only
        checked at safe boundaries (before each Decision and before each
        Tool execution) and never preempt in-flight provider or tool work.
        The returned result carries a safe execution summary aggregated from
        the existing per-decision call metadata.
        """

        if deadline_seconds is not None and (
            type(deadline_seconds) not in (int, float)
            or isinstance(deadline_seconds, bool)
            or deadline_seconds <= 0
        ):
            raise ValueError("deadline_seconds 必须是正数或 None")
        if cancel_requested is not None and not callable(cancel_requested):
            raise TypeError("cancel_requested 必须可调用或 None")
        usage = _ExecutionUsage()
        deadline_at = (
            time.monotonic() + float(deadline_seconds)
            if deadline_seconds is not None
            else None
        )
        started = time.monotonic()
        result = self._run_bounded(
            user_query,
            evidence_requirement=evidence_requirement,
            initial_context=initial_context,
            initial_evidence=initial_evidence,
            disabled_tools=disabled_tools,
            finalization_verifier=finalization_verifier,
            trace_sink=trace_sink,
            activity_sink=activity_sink,
            enforce_evidence_acquisition=enforce_evidence_acquisition,
            finalization_strategy=finalization_strategy,
            usage=usage,
            deadline_at=deadline_at,
            cancel_requested=cancel_requested,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return _attach_execution_metrics(result, elapsed_ms=elapsed_ms, usage=usage)

    def _run_bounded(
        self,
        user_query: str,
        *,
        evidence_requirement: EngineeringEvidenceRequirement | None = None,
        initial_context: Sequence[DecisionContextItem] = (),
        initial_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence] = (),
        disabled_tools: Collection[str] = (),
        finalization_verifier=None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
        enforce_evidence_acquisition: bool = False,
        finalization_strategy: str = "legacy",
        usage: _ExecutionUsage,
        deadline_at: float | None,
        cancel_requested: Callable[[], bool] | None,
    ) -> ToolAgentRunResult:
        if type(user_query) is not str or not user_query.strip():
            raise ValueError("user_query 必须是非空字符串")
        if evidence_requirement is not None and not isinstance(
            evidence_requirement, EngineeringEvidenceRequirement
        ):
            raise TypeError(
                "evidence_requirement 必须是 EngineeringEvidenceRequirement 或 None"
            )
        if finalization_verifier is not None and not callable(
            getattr(finalization_verifier, "verify", None)
        ):
            raise TypeError("finalization_verifier 必须提供 verify 方法")
        if type(enforce_evidence_acquisition) is not bool:
            raise TypeError("enforce_evidence_acquisition 必须是 bool")
        if finalization_strategy not in ("legacy", "direct_hybrid"):
            raise ValueError("finalization_strategy 必须是 legacy 或 direct_hybrid")
        seed_context = _normalize_initial_context(initial_context)
        seed_evidence = _normalize_initial_evidence(initial_evidence)
        disabled = _normalize_disabled_tools(disabled_tools, self._registry)
        run_registry = (
            self._registry if not disabled else self._registry.without(disabled)
        )
        executor = self._executor if not disabled else ToolExecutor(run_registry)
        context: list[DecisionContextItem] = list(seed_context)
        executed: set[tuple[str, str]] = set()
        iterations = 0
        tool_calls = 0
        tool_errors = 0
        trace: list[RuntimeTraceEvent] = []
        evidence: list[PublicEvidence] = list(seed_evidence)
        seen_evidence: set[tuple] = {
            _evidence_identity(item) for item in seed_evidence
        }
        changed_files_executions: list[ChangedFilesExecution] = []
        changed_files_source_failed = False
        changed_files_selector_attempted = False
        task_contract = getattr(finalization_verifier, "task_contract", None)
        last_blocked_fingerprint: tuple[tuple] | None = None
        recovery_control_active = False
        activity_number = 0

        self._record_activity(
            RunStartedActivity(available_tool_count=len(run_registry)),
            activity_sink,
        )
        for item in seed_evidence:
            evidence_activity = EvidenceAddedActivity.try_from_public_evidence(item)
            if evidence_activity is not None:
                self._record_activity(evidence_activity, activity_sink)

        while True:
            # PRODUCT-ENGINEERING-24B lifecycle boundary: cooperative cancel
            # and the system deadline are evaluated before any new Decision
            # or Tool work is started; in-flight work is never preempted.
            if cancel_requested is not None and cancel_requested():
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    ENGINEERING_RUN_CANCELLED,
                    trace_sink,
                )
            if deadline_at is not None and time.monotonic() >= deadline_at:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    ENGINEERING_RUN_DEADLINE_EXCEEDED,
                    trace_sink,
                )
            iterations += 1
            if iterations > self._budget.max_agent_iterations:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                    trace_sink,
                )

            if finalization_verifier is None:
                guard_state = (
                    evaluate_evidence_requirement(evidence_requirement, evidence)
                    if evidence_requirement is not None
                    else None
                )
            else:
                current_verification = _run_finalization_verifier(
                    finalization_verifier,
                    evidence,
                    None,
                )
                guard_state = current_verification.evidence_requirement_state
            if guard_state is None or guard_state.satisfied:
                recovery_control_active = False
            elif enforce_evidence_acquisition:
                # Unified Runtime exposes the missing Project Evidence
                # requirement from the first decision, including when the
                # seed already contains Knowledge Evidence.  Legacy direct
                # ToolAgent runs retain their historical delayed guard.
                recovery_control_active = True
            control_state = DecisionControlState(
                iteration=iterations,
                remaining_iterations=self._budget.max_agent_iterations - iterations,
                remaining_tool_calls=self._budget.max_tool_calls - tool_calls,
                tool_call_allowed=(
                    iterations < self._budget.max_agent_iterations
                    and tool_calls < self._budget.max_tool_calls
                ),
                must_terminate=(
                    iterations >= self._budget.max_agent_iterations
                    or tool_calls >= self._budget.max_tool_calls
                ),
                finalization_blocked=(
                    True
                    if recovery_control_active and guard_state is not None
                    else None
                ),
                missing_evidence_groups=(
                    guard_state.missing_evidence_groups
                    if recovery_control_active and guard_state is not None
                    else ()
                ),
                current_distinct_project_code_paths=(
                    guard_state.distinct_project_code_paths
                    if recovery_control_active and guard_state is not None
                    else None
                ),
                required_min_distinct_project_code_paths=(
                    guard_state.required_min_distinct_project_code_paths
                    if recovery_control_active and guard_state is not None
                    else None
                ),
                available_evidence_refs=_evidence_reference_catalog(evidence),
                citation_required_evidence_groups=(
                    evidence_requirement.required_evidence_groups
                    if evidence_requirement is not None
                    else ()
                ),
                citation_required_min_distinct_project_code_paths=(
                    evidence_requirement.min_distinct_project_code_paths
                    if evidence_requirement is not None
                    else 0
                ),
                finalization_strategy=(
                    "direct_hybrid" if finalization_strategy == "direct_hybrid" else None
                ),
                task_contract=task_contract,
                task_contract_missing_material=(
                    task_contract.material_error(task_contract.scoped_evidence(evidence))
                    if task_contract is not None else None),
            )
            outcome = self._decide(
                run_registry,
                user_query,
                context=tuple(context),
                control_state=control_state,
            )
            if not isinstance(outcome, AgentDecisionOutcome):
                # Provider 违反 Protocol 属于程序契约错误，fail-fast
                raise TypeError("provider.decide 必须返回 AgentDecisionOutcome")
            usage.record(outcome.call_metadata)
            self._record_trace(
                trace,
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="decision_completed",
                    action_type=outcome.action.action if outcome.action is not None else None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    provider_call_count=(
                        outcome.call_metadata.call_count
                        if outcome.call_metadata is not None
                        else None
                    ),
                    repair_attempted=(
                        outcome.call_metadata.repair_attempted
                        if outcome.call_metadata is not None
                        else None
                    ),
                    repair_succeeded=(
                        outcome.call_metadata.repair_succeeded
                        if outcome.call_metadata is not None
                        else None
                    ),
                    parse_failure_category=(
                        outcome.call_metadata.initial_parse_category
                        if outcome.call_metadata is not None
                        else None
                    ),
                ),
                trace_sink,
            )

            if outcome.failure_code is not None:
                self._append_terminal(
                    trace,
                    iterations,
                    tool_calls,
                    tool_errors,
                    outcome.failure_code,
                    trace_sink,
                )
                return ToolAgentRunResult(
                    status="failed",
                    answer=None,
                    reason_code=None,
                    failure_code=outcome.failure_code,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                    evidence=tuple(evidence),
                )

            action = outcome.action
            if isinstance(action, ChangedFilesFinalizationAction):
                if (
                    finalization_strategy != "direct_hybrid"
                    or finalization_verifier is None
                    or len(changed_files_executions) != 1
                ):
                    return self._hard_stop(
                        trace,
                        evidence,
                        iterations,
                        tool_calls,
                        tool_errors,
                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                        trace_sink,
                    )
                typed_result = finalize_changed_files_typed(
                    action.as_selector(),
                    execution=changed_files_executions[0],
                    current_public_evidence=tuple(evidence),
                    finalization_verifier=finalization_verifier,
                    **({"task_contract": task_contract} if task_contract is not None else {}),
                )
                if (not typed_result.protocol_valid or not typed_result.source_valid
                        or (typed_result.error_code or "").startswith("TASK_")):
                    return self._hard_stop(
                        trace,
                        evidence,
                        iterations,
                        tool_calls,
                        tool_errors,
                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                        trace_sink,
                        trace_code=typed_result.error_code if task_contract is not None else None,
                    )
                if typed_result.accepted:
                    self._append_terminal(
                        trace, iterations, tool_calls, tool_errors, None, trace_sink
                    )
                    return ToolAgentRunResult(
                        status="completed",
                        answer=typed_result.rendered_answer,
                        reason_code=None,
                        failure_code=None,
                        iterations_used=iterations,
                        tool_calls_used=tool_calls,
                        tool_errors_used=tool_errors,
                        trace=tuple(trace),
                        evidence=tuple(evidence),
                    )

                # A valid Typed choice that lacks the frozen Requirement may
                # continue through the same bounded evidence-acquisition loop.
                current = _run_finalization_verifier(
                    finalization_verifier, evidence, None
                )
                state = current.evidence_requirement_state
                if (
                    not current.recovery_allowed
                    or not _recovery_is_feasible(
                        run_registry,
                        evidence_requirement,
                        state,
                        iterations=iterations,
                        tool_calls=tool_calls,
                        tool_errors=tool_errors,
                        budget=self._budget,
                    )
                ):
                    return self._hard_stop(
                        trace,
                        evidence,
                        iterations,
                        tool_calls,
                        tool_errors,
                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                        trace_sink,
                    )
                fingerprint = _evidence_fingerprint(evidence)
                if (
                    last_blocked_fingerprint is not None
                    and fingerprint == last_blocked_fingerprint
                ):
                    return self._hard_stop(
                        trace,
                        evidence,
                        iterations,
                        tool_calls,
                        tool_errors,
                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                        trace_sink,
                    )
                self._record_trace(
                    trace,
                    RuntimeTraceEvent(
                        iteration=iterations,
                        event_type="finalization_guard_blocked",
                        guard_status="blocked",
                        missing_evidence_groups=state.missing_evidence_groups,
                        distinct_project_code_paths=state.distinct_project_code_paths,
                        required_min_distinct_project_code_paths=(
                            state.required_min_distinct_project_code_paths
                        ),
                        iterations_used=iterations,
                        tool_calls_used=tool_calls,
                        tool_errors_used=tool_errors,
                    ),
                    trace_sink,
                )
                self._record_activity(
                    VerificationBlockedActivity(
                        iteration=iterations,
                        missing_evidence_kinds=tuple(
                            sorted(current.missing_evidence_kinds)
                        ),
                    ),
                    activity_sink,
                )
                last_blocked_fingerprint = fingerprint
                recovery_control_active = True
                continue

            if isinstance(action, FinalAnswerAction):
                if finalization_strategy == "direct_hybrid":
                    error_code = _lightweight_open_answer_check(
                        finalization_verifier, evidence, action.answer,
                        **({"context": tuple(context)} if task_contract is not None else {}),
                    )
                    if error_code is not None:
                        return self._hard_stop(
                            trace,
                            evidence,
                            iterations,
                            tool_calls,
                            tool_errors,
                            INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                            trace_sink,
                            trace_code=error_code if task_contract is not None else None,
                        )
                    self._append_terminal(
                        trace, iterations, tool_calls, tool_errors, None, trace_sink
                    )
                    return ToolAgentRunResult(
                        status="completed",
                        answer=action.answer,
                        reason_code=None,
                        failure_code=None,
                        iterations_used=iterations,
                        tool_calls_used=tool_calls,
                        tool_errors_used=tool_errors,
                        trace=tuple(trace),
                        evidence=tuple(evidence),
                    )
                if finalization_verifier is not None:
                    finalization_result = _run_finalization_verifier(
                        finalization_verifier,
                        evidence,
                        action.answer,
                    )
                    if (
                        changed_files_source_failed
                        and not changed_files_executions
                        and not evidence
                        and finalization_result.can_finalize
                    ):
                        # A failed status-list request cannot be converted into
                        # an evidence-free direct answer merely because the old
                        # Requirement has no body prerequisite.
                        return self._hard_stop(
                            trace,
                            evidence,
                            iterations,
                            tool_calls,
                            tool_errors,
                            INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                            trace_sink,
                        )
                    if not finalization_result.can_finalize:
                        selector = getattr(
                            self._provider, "select_changed_files", None
                        )
                        if (
                            not changed_files_selector_attempted
                            and callable(selector)
                            and len(changed_files_executions) == 1
                            and _typed_selector_is_applicable(finalization_result)
                        ):
                            # One optional selector request per run. This is
                            # outside the bounded Decision/Tool loop and is
                            # explicitly counted in execution metrics.
                            changed_files_selector_attempted = True
                            selector_outcome = selector(
                                user_query,
                                execution=changed_files_executions[0],
                                evidence_requirement=evidence_requirement,
                            )
                            if type(selector_outcome) is not ChangedFilesSelectorOutcome:
                                raise TypeError(
                                    "provider.select_changed_files 必须返回 "
                                    "ChangedFilesSelectorOutcome"
                                )
                            usage.record_selector(selector_outcome)
                            if selector_outcome.status == "failed":
                                failure_code = selector_outcome.failure_code
                                if failure_code not in {
                                    ACTION_PARSE_FAILED,
                                    ACTION_PROVIDER_ERROR,
                                    ACTION_TIMEOUT,
                                }:
                                    failure_code = ACTION_PROVIDER_ERROR
                                self._append_terminal(
                                    trace,
                                    iterations,
                                    tool_calls,
                                    tool_errors,
                                    failure_code,
                                    trace_sink,
                                )
                                return ToolAgentRunResult(
                                    status="failed",
                                    answer=None,
                                    reason_code=None,
                                    failure_code=failure_code,
                                    iterations_used=iterations,
                                    tool_calls_used=tool_calls,
                                    tool_errors_used=tool_errors,
                                    trace=tuple(trace),
                                    evidence=tuple(evidence),
                                )
                            if selector_outcome.status == "refusal":
                                if selector_outcome.refusal_reason == "insufficient_source":
                                    return self._hard_stop(
                                        trace,
                                        evidence,
                                        iterations,
                                        tool_calls,
                                        tool_errors,
                                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                        trace_sink,
                                    )
                                if selector_outcome.refusal_reason != "unsupported_request":
                                    return self._hard_stop(
                                        trace,
                                        evidence,
                                        iterations,
                                        tool_calls,
                                        tool_errors,
                                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                        trace_sink,
                                    )
                                # Explicit unsupported_request preserves the
                                # old natural-language path and its Gate.
                            elif selector_outcome.status == "selected":
                                typed_result = finalize_changed_files_typed(
                                    selector_outcome.selector,
                                    execution=changed_files_executions[0],
                                    current_public_evidence=tuple(evidence),
                                    finalization_verifier=finalization_verifier,
                                )
                                if not typed_result.protocol_valid or not typed_result.source_valid:
                                    return self._hard_stop(
                                        trace,
                                        evidence,
                                        iterations,
                                        tool_calls,
                                        tool_errors,
                                        INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                        trace_sink,
                                    )
                                if typed_result.accepted:
                                    self._append_terminal(
                                        trace,
                                        iterations,
                                        tool_calls,
                                        tool_errors,
                                        None,
                                        trace_sink,
                                    )
                                    return ToolAgentRunResult(
                                        status="completed",
                                        answer=typed_result.rendered_answer,
                                        reason_code=None,
                                        failure_code=None,
                                        iterations_used=iterations,
                                        tool_calls_used=tool_calls,
                                        tool_errors_used=tool_errors,
                                        trace=tuple(trace),
                                        evidence=tuple(evidence),
                                    )
                                # The typed protocol is valid, but a selected
                                # status list did not satisfy the existing
                                # Requirement/retrieval checks. Fall through to
                                # the original recovery/refusal behavior.
                            else:
                                return self._hard_stop(
                                    trace,
                                    evidence,
                                    iterations,
                                    tool_calls,
                                    tool_errors,
                                    INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                    trace_sink,
                                )
                        state = finalization_result.evidence_requirement_state
                        if (
                            not finalization_result.recovery_allowed
                            or not _recovery_is_feasible(
                                run_registry,
                                evidence_requirement,
                                state,
                                iterations=iterations,
                                tool_calls=tool_calls,
                                tool_errors=tool_errors,
                                budget=self._budget,
                            )
                        ):
                            return self._hard_stop(
                                trace,
                                evidence,
                                iterations,
                                tool_calls,
                                tool_errors,
                                INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                trace_sink,
                            )
                        fingerprint = _evidence_fingerprint(evidence)
                        if (
                            last_blocked_fingerprint is not None
                            and fingerprint == last_blocked_fingerprint
                        ):
                            return self._hard_stop(
                                trace,
                                evidence,
                                iterations,
                                tool_calls,
                                tool_errors,
                                INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                trace_sink,
                            )
                        self._record_trace(
                            trace,
                            RuntimeTraceEvent(
                                iteration=iterations,
                                event_type="finalization_guard_blocked",
                                guard_status="blocked",
                                missing_evidence_groups=state.missing_evidence_groups,
                                distinct_project_code_paths=(
                                    state.distinct_project_code_paths
                                ),
                                required_min_distinct_project_code_paths=(
                                    state.required_min_distinct_project_code_paths
                                ),
                                iterations_used=iterations,
                                tool_calls_used=tool_calls,
                                tool_errors_used=tool_errors,
                            ),
                            trace_sink,
                        )
                        self._record_activity(
                            VerificationBlockedActivity(
                                iteration=iterations,
                                missing_evidence_kinds=tuple(
                                    sorted(finalization_result.missing_evidence_kinds)
                                ),
                            ),
                            activity_sink,
                        )
                        last_blocked_fingerprint = fingerprint
                        recovery_control_active = True
                        continue
                elif evidence_requirement is not None:
                    state = evaluate_evidence_requirement(evidence_requirement, evidence)
                    if not state.satisfied:
                        fingerprint = _evidence_fingerprint(evidence)
                        if (
                            last_blocked_fingerprint is not None
                            and fingerprint == last_blocked_fingerprint
                        ):
                            return self._hard_stop(
                                trace,
                                evidence,
                                iterations,
                                tool_calls,
                                tool_errors,
                                INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                trace_sink,
                            )
                        if not _recovery_is_feasible(
                            run_registry,
                            evidence_requirement,
                            state,
                            iterations=iterations,
                            tool_calls=tool_calls,
                            tool_errors=tool_errors,
                            budget=self._budget,
                        ):
                            return self._hard_stop(
                                trace,
                                evidence,
                                iterations,
                                tool_calls,
                                tool_errors,
                                INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                trace_sink,
                            )
                        self._record_trace(
                            trace,
                            RuntimeTraceEvent(
                                iteration=iterations,
                                event_type="finalization_guard_blocked",
                                guard_status="blocked",
                                missing_evidence_groups=state.missing_evidence_groups,
                                distinct_project_code_paths=(
                                    state.distinct_project_code_paths
                                ),
                                required_min_distinct_project_code_paths=(
                                    state.required_min_distinct_project_code_paths
                                ),
                                iterations_used=iterations,
                                tool_calls_used=tool_calls,
                                tool_errors_used=tool_errors,
                            ),
                            trace_sink,
                        )
                        self._record_activity(
                            VerificationBlockedActivity(
                                iteration=iterations,
                                missing_evidence_kinds=tuple(
                                    sorted(_missing_evidence_kinds(evidence_requirement, state))
                                ),
                            ),
                            activity_sink,
                        )
                        last_blocked_fingerprint = fingerprint
                        recovery_control_active = True
                        continue
                self._append_terminal(
                    trace, iterations, tool_calls, tool_errors, None, trace_sink
                )
                return ToolAgentRunResult(
                    status="completed",
                    answer=action.answer,
                    reason_code=None,
                    failure_code=None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                    evidence=tuple(evidence),
                )
            if isinstance(action, RefuseAction):
                if (
                    enforce_evidence_acquisition
                    and evidence_requirement is not None
                    and guard_state is not None
                    and not guard_state.satisfied
                ):
                    fingerprint = _evidence_fingerprint(evidence)
                    if (
                        last_blocked_fingerprint is not None
                        and fingerprint == last_blocked_fingerprint
                    ):
                        return self._hard_stop(
                            trace,
                            evidence,
                            iterations,
                            tool_calls,
                            tool_errors,
                            INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                            trace_sink,
                        )
                    if not _recovery_is_feasible(
                        run_registry,
                        evidence_requirement,
                        guard_state,
                        iterations=iterations,
                        tool_calls=tool_calls,
                        tool_errors=tool_errors,
                        budget=self._budget,
                    ):
                        return self._hard_stop(
                            trace,
                            evidence,
                            iterations,
                            tool_calls,
                            tool_errors,
                            INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                            trace_sink,
                        )
                    self._record_trace(
                        trace,
                        RuntimeTraceEvent(
                            iteration=iterations,
                            event_type="finalization_guard_blocked",
                            guard_status="blocked",
                            missing_evidence_groups=guard_state.missing_evidence_groups,
                            distinct_project_code_paths=(
                                guard_state.distinct_project_code_paths
                            ),
                            required_min_distinct_project_code_paths=(
                                guard_state.required_min_distinct_project_code_paths
                            ),
                            iterations_used=iterations,
                            tool_calls_used=tool_calls,
                            tool_errors_used=tool_errors,
                        ),
                        trace_sink,
                    )
                    self._record_activity(
                        VerificationBlockedActivity(
                            iteration=iterations,
                            missing_evidence_kinds=tuple(
                                sorted(
                                    _missing_evidence_kinds(
                                        evidence_requirement,
                                        guard_state,
                                    )
                                )
                            ),
                        ),
                        activity_sink,
                    )
                    last_blocked_fingerprint = fingerprint
                    recovery_control_active = True
                    continue
                self._append_terminal(
                    trace,
                    iterations,
                    tool_calls,
                    tool_errors,
                    action.reason_code,
                    trace_sink,
                )
                return ToolAgentRunResult(
                    status="refused",
                    answer=None,
                    reason_code=action.reason_code,
                    failure_code=None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                    evidence=tuple(evidence),
                )

            # ToolCallAction：执行前按 §11 顺序检查
            if iterations >= self._budget.max_agent_iterations:
                # 最后一次 Decision 若仍要 tool_call：没有下一次 Decision 读 Observation
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                    trace_sink,
                )
            if tool_calls >= self._budget.max_tool_calls:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                    trace_sink,
                )
            canonical = _canonical_call(action.tool_name, action.arguments)
            if canonical in executed:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_DUPLICATE_TOOL_CALL,
                    trace_sink,
                )
            # PRODUCT-ENGINEERING-24B lifecycle boundary: stop before a new
            # Tool execution when the client disconnected or the run
            # deadline expired; the previous Tool already finished normally.
            if cancel_requested is not None and cancel_requested():
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    ENGINEERING_RUN_CANCELLED,
                    trace_sink,
                )
            if deadline_at is not None and time.monotonic() >= deadline_at:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    ENGINEERING_RUN_DEADLINE_EXCEEDED,
                    trace_sink,
                )

            call = ToolCall.create(action.tool_name, action.arguments)
            activity_number += 1
            activity_id = f"A{activity_number}"
            self._record_activity(
                build_tool_activity_event(
                    activity_id=activity_id,
                    iteration=iterations,
                    tool_name=call.tool_name,
                    state="started",
                    arguments=action.arguments,
                ),
                activity_sink,
            )
            self._record_trace(
                trace,
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="tool_call_created",
                    action_type="tool_call",
                    tool_name=call.tool_name,
                    call_id=call.call_id,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                ),
                trace_sink,
            )
            observation = executor.execute(call)
            tool_calls += 1
            if observation.status != "ok":
                tool_errors += 1
            executed.add(canonical)
            self._record_trace(
                trace,
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="tool_observation",
                    action_type="tool_call",
                    tool_name=call.tool_name,
                    call_id=call.call_id,
                    tool_status=observation.status,
                    error_code=observation.error_code,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                ),
                trace_sink,
            )
            context.append(
                DecisionContextItem(
                    tool_name=call.tool_name,
                    arguments=action.arguments,
                    call_id=call.call_id,
                    observation_status=observation.status,
                    observation_result=observation.result,
                    observation_error_code=observation.error_code,
                )
            )
            observed_evidence: list[PublicEvidence] = list(_evidence_from_knowledge_search(observation))
            observed_evidence.extend(_evidence_from_project_context_regions(observation))
            current_spec = run_registry.get_spec(call.tool_name)
            observed_evidence.extend(
                _evidence_from_tool_result(
                    observation,
                    call,
                    current_spec.version if current_spec is not None else None,
                )
            )
            if call.tool_name == "changed_files" and not any(
                isinstance(item, ToolResultEvidence)
                and item.tool_name == "changed_files"
                for item in observed_evidence
            ):
                changed_files_source_failed = True
            if call.tool_name == "changed_files" and observation.status != "ok":
                changed_files_source_failed = True
            added_evidence_ids: list[str] = []
            for observed in observed_evidence:
                key = _evidence_identity(observed)
                if key in seen_evidence:
                    continue
                seen_evidence.add(key)
                added = replace(observed, evidence_id=f"E{len(evidence) + 1}")
                evidence.append(added)
                added_evidence_ids.append(added.evidence_id)
                if (
                    call.tool_name == "changed_files"
                    and observation.status == "ok"
                    and isinstance(added, ToolResultEvidence)
                    and added.tool_name == "changed_files"
                    and current_spec is not None
                ):
                    changed_files_executions.append(
                        ChangedFilesExecution(
                            call=call,
                            observation=observation,
                            evidence=added,
                            tool_version=current_spec.version,
                        )
                    )
                evidence_activity = EvidenceAddedActivity.try_from_public_evidence(added)
                if evidence_activity is not None:
                    self._record_activity(evidence_activity, activity_sink)
            self._record_activity(
                build_tool_activity_event(
                    activity_id=activity_id,
                    iteration=iterations,
                    tool_name=call.tool_name,
                    state="completed" if observation.status == "ok" else "error",
                    arguments=action.arguments,
                    observation=observation,
                    evidence_ids_added=tuple(added_evidence_ids),
                ),
                activity_sink,
            )
            if tool_errors >= self._budget.max_tool_errors:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_TOOL_ERROR_LIMIT,
                    trace_sink,
                )
            # 否则继续下一次 Decision

    def _decide(
        self,
        registry: ToolRegistry,
        user_query: str,
        *,
        context: tuple[DecisionContextItem, ...],
        control_state: DecisionControlState,
    ) -> AgentDecisionOutcome:
        """Pass trusted control state without breaking pre-v1 test providers.

        The production provider implements the extended protocol. Older
        injected providers that only implement the original context keyword
        remain valid; no provider exception is caught or reclassified here.
        """
        decide = self._provider.decide
        try:
            parameters = inspect.signature(decide).parameters.values()
        except (TypeError, ValueError):
            parameters = ()
        accepts_control_state = any(
            parameter.name == "control_state"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        kwargs = {"context": context}
        if accepts_control_state:
            kwargs["control_state"] = control_state
        return decide(registry, user_query, **kwargs)

    def _append_terminal(
        self,
        trace: list[RuntimeTraceEvent],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str | None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None,
    ) -> None:
        """每次 run() 结束都追加 runtime_stopped 作为最后一条 Trace event。

        code 承载终止事实：completed→None、model refuse→reason_code、
        decision failure→failure_code、系统硬停止→termination code。
        """
        self._record_trace(
            trace,
            RuntimeTraceEvent(
                iteration=iterations,
                event_type="runtime_stopped",
                error_code=code,
                iterations_used=iterations,
                tool_calls_used=tool_calls,
                tool_errors_used=tool_errors,
            ),
            trace_sink,
        )

    @staticmethod
    def _record_trace(
        trace: list[RuntimeTraceEvent],
        event: RuntimeTraceEvent,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None,
    ) -> None:
        """Append the canonical trace before notifying an optional observer.

        Observability is deliberately outside the Runtime control plane. A UI
        or transport failure therefore cannot alter the result of this run.
        """

        trace.append(event)
        if trace_sink is not None:
            try:
                trace_sink(event)
            except Exception:
                pass

    @staticmethod
    def _record_activity(
        event: ActivityEvent,
        activity_sink: Callable[[ActivityEvent], None] | None,
    ) -> None:
        """Notify the optional observer without entering Runtime control flow."""

        if activity_sink is not None:
            try:
                activity_sink(event)
            except Exception:
                pass

    def _hard_stop(
        self,
        trace: list[RuntimeTraceEvent],
        evidence: list[PublicEvidence],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None,
        *,
        trace_code: str | None = None,
    ) -> ToolAgentRunResult:
        self._append_terminal(
            trace, iterations, tool_calls, tool_errors, trace_code or code, trace_sink
        )
        return ToolAgentRunResult(
            status="refused",
            answer=None,
            reason_code=code,
            failure_code=None,
            iterations_used=iterations,
            tool_calls_used=tool_calls,
            tool_errors_used=tool_errors,
            trace=tuple(trace),
            evidence=tuple(evidence),
        )
