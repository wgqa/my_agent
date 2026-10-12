"""Unified Engineering evidence verification and finalization state.

This module composes the existing G3 query-level verifier, the frozen G12
evidence-shape evaluator, and the existing citation-ID validator.  It does not
introduce a new verifier algorithm, LLM judge, recovery loop, or finalization
controller.  The returned result is trusted internal state consumed by the
single ToolAgent finalization point.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from core.agent_runtime.models import EvidenceBundle, EvidenceItem, VerificationResult
from core.agent_runtime.runtime import MinimalEvidenceVerifier
from core.context.assembler import ContextBlock
from core.engineering_requirements import (
    EngineeringEvidenceRequirement,
    EvidenceRequirementState,
    evaluate_evidence_requirement,
)
from core.engineering_retrieval import EngineeringRetrievalSnapshot
from core.generator.citation import CitationValidator
from core.query_planning import PlannerOutcome
from core.tool_agent.runtime_models import (
    EngineeringEvidence,
    KnowledgeEvidence,
    ToolResultEvidence,
)


CITATION_STATUS_NOT_CHECKED = "NOT_CHECKED"
CITATION_STATUS_NOT_PRESENT = "NOT_PRESENT"
CITATION_STATUS_VALID = "VALID"
CITATION_STATUS_INVALID = "INVALID"
CITATION_STATUSES = (
    CITATION_STATUS_NOT_CHECKED,
    CITATION_STATUS_NOT_PRESENT,
    CITATION_STATUS_VALID,
    CITATION_STATUS_INVALID,
)

RETRIEVAL_EVIDENCE_INSUFFICIENT = "RETRIEVAL_EVIDENCE_INSUFFICIENT"
INCOMPLETE_SUBQUERY_COVERAGE = "INCOMPLETE_SUBQUERY_COVERAGE"
REQUIRED_EVIDENCE_MISSING = "REQUIRED_EVIDENCE_MISSING"
INVALID_CITATION_REFERENCE = "INVALID_CITATION_REFERENCE"
ANSWER_EVIDENCE_REFERENCE_MISSING = "ANSWER_EVIDENCE_REFERENCE_MISSING"
ANSWER_EVIDENCE_REFERENCE_INCOMPLETE = "ANSWER_EVIDENCE_REFERENCE_INCOMPLETE"
ANSWER_EVIDENCE_REFERENCE_INVALID = "ANSWER_EVIDENCE_REFERENCE_INVALID"
INSUFFICIENCY_REASONS = (
    RETRIEVAL_EVIDENCE_INSUFFICIENT,
    INCOMPLETE_SUBQUERY_COVERAGE,
    REQUIRED_EVIDENCE_MISSING,
    INVALID_CITATION_REFERENCE,
    ANSWER_EVIDENCE_REFERENCE_MISSING,
    ANSWER_EVIDENCE_REFERENCE_INCOMPLETE,
    ANSWER_EVIDENCE_REFERENCE_INVALID,
)

# PRODUCT-GROUNDING-21: structural Answer ↔ Evidence binding statuses. The
# binding is deterministic reference-truth + requirement-shape checking; it
# makes no semantic entailment claim.
ANSWER_BINDING_STATUS_NOT_CHECKED = "NOT_CHECKED"
ANSWER_BINDING_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
ANSWER_BINDING_STATUS_MISSING = "MISSING"
ANSWER_BINDING_STATUS_INCOMPLETE = "INCOMPLETE"
ANSWER_BINDING_STATUS_INVALID = "INVALID"
ANSWER_BINDING_STATUS_VALID = "VALID"
ANSWER_BINDING_STATUSES = (
    ANSWER_BINDING_STATUS_NOT_CHECKED,
    ANSWER_BINDING_STATUS_NOT_REQUIRED,
    ANSWER_BINDING_STATUS_MISSING,
    ANSWER_BINDING_STATUS_INCOMPLETE,
    ANSWER_BINDING_STATUS_INVALID,
    ANSWER_BINDING_STATUS_VALID,
)
ANSWER_BINDING_PASS_STATUSES = (
    ANSWER_BINDING_STATUS_NOT_CHECKED,
    ANSWER_BINDING_STATUS_NOT_REQUIRED,
    ANSWER_BINDING_STATUS_VALID,
)

# Exact, case-sensitive [E1]/[E2] reference syntax. [e1], [E0], [E-1] and
# [Efoo] deliberately do not parse as references.
_EVIDENCE_REFERENCE_PATTERN = re.compile(r"\[E([1-9][0-9]*)\]")


def parse_answer_evidence_references(answer: str) -> tuple[str, ...]:
    """Extract [E#] references in first-occurrence order, deduplicated."""

    if type(answer) is not str:
        raise TypeError("answer 必须是 str")
    references: list[str] = []
    for match in _EVIDENCE_REFERENCE_PATTERN.finditer(answer):
        reference = f"E{match.group(1)}"
        if reference not in references:
            references.append(reference)
    return tuple(references)


def _evaluate_answer_evidence_binding(
    requirement: EngineeringEvidenceRequirement,
    evidence: tuple[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence, ...],
    proposed_answer: str | None,
) -> tuple[str, bool, tuple[str, ...], tuple[str, ...]]:
    """Return (status, required, cited_evidence_ids, invalid_evidence_ids).

    Reference truth comes only from current public evidence; a reference to
    any other ID is INVALID with precedence over all other outcomes. Citation
    eligibility is checked at each source's complete, bounded granularity.
    Requirement eligibility is a separate projection into the frozen G12
    evaluator, so a narrow locator can be cited without filling a body/diff
    requirement.
    """

    evidence_ids = {item.evidence_id for item in evidence}
    binding_required = (
        bool(evidence)
        or bool(requirement.required_evidence_groups)
        or requirement.min_distinct_project_code_paths > 0
    )
    if proposed_answer is None:
        # Pre-finalization verification: no answer exists to bind yet.
        return (
            ANSWER_BINDING_STATUS_NOT_CHECKED,
            binding_required,
            (),
            (),
        )
    references = parse_answer_evidence_references(proposed_answer)
    invalid_references = tuple(
        reference for reference in references if reference not in evidence_ids
    )
    if invalid_references:
        return (
            ANSWER_BINDING_STATUS_INVALID,
            binding_required,
            tuple(
                reference
                for reference in references
                if reference in evidence_ids
            ),
            invalid_references,
        )
    if not binding_required:
        # Genuinely evidence-free direct answer: citations are not required
        # and none may exist (any reference would have been INVALID above).
        return (
            ANSWER_BINDING_STATUS_NOT_REQUIRED,
            False,
            (),
            (),
        )
    if not references:
        return (
            ANSWER_BINDING_STATUS_MISSING,
            True,
            (),
            (),
        )
    cited_evidence = tuple(
        item for item in evidence if item.evidence_id in references
    )
    if not _tool_result_citations_have_complete_matching_scope(
        proposed_answer, cited_evidence, evidence
    ):
        return (
            ANSWER_BINDING_STATUS_INCOMPLETE,
            True,
            references,
            (),
        )
    requirement_evidence = tuple(
        item
        for item in cited_evidence
        if type(item) is not ToolResultEvidence or item.requirement_eligible
    )
    if evaluate_evidence_requirement(requirement, requirement_evidence).satisfied:
        return (
            ANSWER_BINDING_STATUS_VALID,
            True,
            references,
            (),
        )
    return (
        ANSWER_BINDING_STATUS_INCOMPLETE,
        True,
        references,
        (),
    )


_REPO_PATH_MENTION_PATTERN = re.compile(
    r"(?<![\w./-])(?:[A-Za-z0-9_.@+-]+/)+[A-Za-z0-9_.@+-]+\.[A-Za-z0-9_+-]+"
)
_EXHAUSTIVE_WORKSPACE_CLAIM_PATTERN = re.compile(
    r"(?:整个|全|全部|所有|全量).{0,8}(?:工作区|工作树|仓库|项目|变更|修改)|"
    r"(?:whole|entire|all)\s+(?:workspace|working tree|repository|repo|changes)",
    re.IGNORECASE,
)


def _citation_clause(answer: str, start: int, end: int) -> str:
    """Return the line/sentence fragment attached to one citation marker."""
    # A bare period also occurs inside repo paths (for example src/app.py),
    # so treat it as sentence punctuation only when followed by whitespace or
    # the end of the answer.
    boundaries = [
        match.start()
        for match in re.finditer(r"\n|[。！？!?;；]|\.(?=\s|$)", answer)
    ]
    left = max((index + 1 for index in boundaries if index < start), default=0)
    right = min((index for index in boundaries if index >= end), default=len(answer))
    return answer[left:right]


def _answer_line_without_references(line: str) -> tuple[tuple[str, ...], str]:
    references = tuple(
        f"E{match.group(1)}" for match in _EVIDENCE_REFERENCE_PATTERN.finditer(line)
    )
    text = _EVIDENCE_REFERENCE_PATTERN.sub("", line).strip()
    text = re.sub(r"^(?:[-*•]\s+)", "", text).strip()
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.strip("` \t\r\n。.!?；;")
    return references, text


def _is_bounded_location_line(line: str, item: ToolResultEvidence) -> bool:
    references, text = _answer_line_without_references(line)
    if references != (item.evidence_id,):
        return False
    location = f"{item.path}:{item.start_line}"
    if item.granularity == "locator":
        prefixes = (
            "",
            "位置：",
            "命中位置：",
            "文件和行号：",
            "文件/行号：",
            "Location: ",
            "Located at: ",
        )
        accepted = {f"{prefix}{location}" for prefix in prefixes}
        try:
            arguments = json.loads(item.arguments_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            arguments = {}
        query = arguments.get("query") if isinstance(arguments, dict) else None
        if type(query) is str and query.strip():
            query = query.strip()
            accepted.update(
                {
                    f"{query}: {location}",
                    f"{query}：{location}",
                    f"{query} 在 {location}",
                    f"{query} 位于 {location}",
                    f"{query} is at {location}",
                    f"{query} is located at {location}",
                }
            )
    else:
        prefixes = (
            "",
            "候选测试：",
            "候选测试文件：",
            "候选测试位置：",
            "工具返回的候选测试位置：",
            "关联测试文件：",
            "关联测试文件是 ",
            "Candidate test location: ",
            "Candidate test: ",
        )
        # A candidate observation proves the candidate file's location. A
        # requester who only asks for the file does not need a line suffix.
        locations = {location, item.path}
        accepted = {f"{prefix}{value}" for prefix in prefixes for value in locations}
    return text in accepted


def _is_bounded_status_line(line: str, item: ToolResultEvidence) -> tuple[str, str, str | None] | None:
    references, text = _answer_line_without_references(line)
    if references != (item.evidence_id,):
        return None
    for path, status, old_path in item.status_entries:
        status_labels = {
            "modified": ("modified", "已修改", "修改"),
            "added": ("added", "新增"),
            "deleted": ("deleted", "已删除", "删除"),
            "renamed": ("renamed", "重命名"),
            "untracked": ("untracked", "未跟踪"),
        }[status]
        if status == "renamed":
            assert old_path is not None
            accepted = set()
            for label in status_labels:
                accepted.update(
                    {
                        f"{old_path} -> {path} — {label}",
                        f"{old_path} → {path} — {label}",
                        f"{old_path} -> {path} - {label}",
                        f"{old_path} → {path} - {label}",
                        f"{old_path} -> {path} ({label})",
                        f"{old_path} → {path} ({label})",
                        f"{old_path} renamed to {path}",
                        f"{old_path} 重命名为 {path}",
                    }
                )
        else:
            accepted = set()
            for label in status_labels:
                accepted.update(
                    {
                        f"{path} — {label}",
                        f"{path} - {label}",
                        f"{path}: {label}",
                        f"{path} ({label})",
                        f"{path} [{label}]",
                    }
                )
        if text in accepted:
            return path, status, old_path
    return None


def _is_bounded_empty_status_line(line: str, item: ToolResultEvidence) -> bool:
    references, text = _answer_line_without_references(line)
    return (
        references == (item.evidence_id,)
        and text
        in {
            "没有可见变更",
            "当前没有可见变更",
            "变更文件清单为空",
            "No visible changes",
            "No changed files",
        }
    )


def _is_complete_working_tree_inventory(item: object) -> bool:
    if (
        type(item) is not ToolResultEvidence
        or item.tool_name != "changed_files"
        or item.granularity != "status_list"
        or item.completeness != "complete"
    ):
        return False
    try:
        arguments = json.loads(item.arguments_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return type(arguments) is dict and arguments.get("mode") == "working_tree"


def _tool_result_citations_have_complete_matching_scope(
    answer: str,
    cited_evidence: tuple[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence, ...],
    all_evidence: tuple[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence, ...] | None = None,
) -> bool:
    """Check structured Tool citations at the granularity they actually prove.

    This is deliberately a syntax-and-provenance check, not semantic
    entailment. Locator/candidate evidence can support only a bare bounded
    location row. A status list can support only the complete path/status rows
    returned by changed_files. None of these records becomes source_body or
    diff evidence, and the frozen Requirement evaluator remains authoritative.
    """
    tool_by_id = {
        item.evidence_id: item
        for item in cited_evidence
        if type(item) is ToolResultEvidence
    }
    if not tool_by_id:
        return True
    all_evidence = cited_evidence if all_evidence is None else all_evidence
    call_identities: dict[str, tuple[str, str, str, str]] = {}
    for item in all_evidence:
        if type(item) is not ToolResultEvidence:
            continue
        identity = (
            item.tool_name,
            item.tool_version,
            item.arguments_sha256,
            item.result_sha256,
        )
        previous = call_identities.setdefault(item.call_id, identity)
        if previous != identity:
            # Evidence emitted by one Observation must share one immutable
            # source identity; a mismatched digest cannot split a batch.
            return False
    answer_grade_ids = {
        item.evidence_id
        for item in cited_evidence
        if type(item) is not ToolResultEvidence
        or item.granularity in {"source_body", "diff"}
    }
    references = tuple(
        f"E{match.group(1)}" for match in _EVIDENCE_REFERENCE_PATTERN.finditer(answer)
    )
    if not references:
        return False

    low_granularity_items = tuple(
        item
        for item in tool_by_id.values()
        if item.granularity in {"locator", "candidate", "status_list"}
    )
    for item in low_granularity_items:
        if item.completeness != "complete":
            return False
        cited_lines = [
            line
            for line in answer.splitlines()
            if item.evidence_id
            in tuple(
                f"E{match.group(1)}"
                for match in _EVIDENCE_REFERENCE_PATTERN.finditer(line)
            )
        ]
        if not cited_lines:
            return False
        if item.granularity in {"locator", "candidate"}:
            if any(not _is_bounded_location_line(line, item) for line in cited_lines):
                return False
            # One result may produce several locators/candidates. A complete
            # list is accepted only when every row from that same Observation
            # is cited, so the metadata cannot silently stand for a subset.
            batch = tuple(
                other
                for other in all_evidence
                if type(other) is ToolResultEvidence
                and other.tool_name == item.tool_name
                and other.granularity == item.granularity
                and other.call_id == item.call_id
                and other.result_sha256 == item.result_sha256
            )
            batch_ids = {other.evidence_id for other in batch}
            answer_batch_ids = set(references) & batch_ids
            if not batch_ids or answer_batch_ids != batch_ids:
                return False
        else:
            if item.tool_name != "changed_files":
                return False
            if not item.status_entries:
                if (
                    item.scope_paths
                    or item.completeness != "complete"
                    or len(cited_lines) != 1
                    or not _is_bounded_empty_status_line(cited_lines[0], item)
                ):
                    return False
                continue
            observed_entries = [
                parsed
                for line in cited_lines
                if (parsed := _is_bounded_status_line(line, item)) is not None
            ]
            expected_entries = list(item.status_entries)
            if len(observed_entries) != len(cited_lines):
                return False
            if sorted(observed_entries) != sorted(expected_entries):
                return False

    if not answer_grade_ids:
        # With only acquisition metadata cited, every non-empty answer line
        # must itself be one of the exact bounded rows above; no free-form
        # conclusion can ride on a low-granularity E-ID.
        for line in answer.splitlines():
            if not line.strip():
                continue
            if not _EVIDENCE_REFERENCE_PATTERN.search(line):
                if line.strip() in {
                    "变更文件清单：",
                    "当前工作区变更文件清单：",
                    "当前 working_tree 变更清单：",
                    "工作区变更文件及状态：",
                }:
                    continue
                return False
            if not any(
                _is_bounded_location_line(line, item)
                or _is_bounded_status_line(line, item) is not None
                or _is_bounded_empty_status_line(line, item)
                for item in low_granularity_items
            ):
                return False

    for match in _EVIDENCE_REFERENCE_PATTERN.finditer(answer):
        evidence_id = f"E{match.group(1)}"
        item = tool_by_id.get(evidence_id)
        if item is None or item.granularity in {"locator", "candidate", "status_list"}:
            continue
        if item.completeness != "complete":
            return False
        clause = _citation_clause(answer, match.start(), match.end())
        mentioned_paths = set(_REPO_PATH_MENTION_PATTERN.findall(clause))
        if not mentioned_paths or not mentioned_paths.issubset(set(item.scope_paths)):
            return False
        if (
            item.granularity == "diff"
            and _EXHAUSTIVE_WORKSPACE_CLAIM_PATTERN.search(clause)
            and not any(_is_complete_working_tree_inventory(other) for other in cited_evidence)
        ):
            # A path-scoped diff cannot establish that it is the exhaustive
            # workspace change set. That claim needs a complete changed_files
            # inventory as separate provenance.
            return False
    return True
def _strict_evidence_sequence(
    value: object,
) -> tuple[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("current_public_evidence 必须是 public evidence 序列")
    normalized = tuple(value)
    if any(
        type(item) not in (EngineeringEvidence, KnowledgeEvidence, ToolResultEvidence)
        for item in normalized
    ):
        raise TypeError(
            "current_public_evidence 必须全部是受信任的 public Evidence 类型"
        )
    evidence_ids = [item.evidence_id for item in normalized]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("current_public_evidence 的 evidence_id 不得重复")
    return normalized


def _strict_string_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{label} 必须是 tuple")
    normalized = tuple(value)
    if any(type(item) is not str or not item.strip() for item in normalized):
        raise TypeError(f"{label} 必须全部是非空字符串")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} 不得重复")
    return normalized


def evidence_bundle_to_citation_blocks(
    bundle: EvidenceBundle,
) -> tuple[ContextBlock, ...]:
    """Adapt trusted G3 evidence to CitationValidator's existing ContextBlock."""

    if not isinstance(bundle, EvidenceBundle):
        raise TypeError("bundle 必须是 EvidenceBundle")
    blocks: list[ContextBlock] = []
    for item in bundle.items:
        if type(item) is not EvidenceItem:
            raise TypeError("EvidenceBundle.items 必须全部是 EvidenceItem")
        retrieval_scores = {}
        if item.score is not None:
            retrieval_scores["score"] = item.score
        blocks.append(
            ContextBlock(
                citation_id=item.citation_id,
                chunk_id=item.chunk_id or "",
                source_name=item.source_name,
                page_number=None,
                content=item.content,
                token_count=len(item.content),
                retrieval_scores=retrieval_scores,
            )
        )
    return tuple(blocks)


@dataclass(frozen=True)
class EngineeringVerificationResult:
    """The one trusted verification state consumed by finalization.

    G3, G12, and citation checks remain separately inspectable as orthogonal
    facts, but only ``can_finalize`` is the terminal decision input.  This is
    query-level/shape-level verification; it does not claim semantic
    entailment or claim-level faithfulness.
    """

    can_finalize: bool
    retrieval_status: str
    retrieval_reason_code: str
    retrieval_can_generate: bool
    evidence_requirement_satisfied: bool
    missing_evidence_groups: tuple[tuple[str, ...], ...]
    distinct_project_code_paths: int
    required_min_distinct_project_code_paths: int
    coverage_complete: bool
    required_query_ids: tuple[str, ...]
    covered_query_ids: tuple[str, ...]
    missing_query_ids: tuple[str, ...]
    citation_status: str
    invalid_citation_ids: tuple[str, ...]
    insufficiency_reasons: tuple[str, ...]
    recovery_allowed: bool
    retrieval_verification: VerificationResult
    evidence_requirement_state: EvidenceRequirementState
    evidence_count: int
    answer_evidence_binding_status: str
    answer_evidence_binding_required: bool
    cited_evidence_ids: tuple[str, ...]
    invalid_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for label in (
            "can_finalize",
            "retrieval_can_generate",
            "evidence_requirement_satisfied",
            "coverage_complete",
            "recovery_allowed",
        ):
            if type(getattr(self, label)) is not bool:
                raise TypeError(f"{label} 必须是 bool")
        if self.retrieval_status not in {
            "not_required",
            "supported",
            "insufficient_evidence",
        }:
            raise ValueError("retrieval_status 不是合法 G3 status")
        if type(self.retrieval_reason_code) is not str or not self.retrieval_reason_code:
            raise ValueError("retrieval_reason_code 必须是非空字符串")
        if self.citation_status not in CITATION_STATUSES:
            raise ValueError("citation_status 不是合法内部 status")
        for label in (
            "distinct_project_code_paths",
            "required_min_distinct_project_code_paths",
            "evidence_count",
        ):
            value = getattr(self, label)
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} 必须是非负严格 int")
        if not isinstance(self.retrieval_verification, VerificationResult):
            raise TypeError("retrieval_verification 必须是 VerificationResult")
        if not isinstance(self.evidence_requirement_state, EvidenceRequirementState):
            raise TypeError(
                "evidence_requirement_state 必须是 EvidenceRequirementState"
            )
        if self.retrieval_status != self.retrieval_verification.status:
            raise ValueError("retrieval_status 必须来自 G3 VerificationResult")
        if self.retrieval_reason_code != self.retrieval_verification.reason_code:
            raise ValueError("retrieval_reason_code 必须来自 G3 VerificationResult")
        if self.retrieval_can_generate != self.retrieval_verification.can_generate:
            raise ValueError("retrieval_can_generate 必须来自 G3 VerificationResult")
        if self.required_query_ids != self.retrieval_verification.required_query_ids:
            raise ValueError("required_query_ids 必须来自 G3 VerificationResult")
        if self.covered_query_ids != self.retrieval_verification.covered_query_ids:
            raise ValueError("covered_query_ids 必须来自 G3 VerificationResult")
        if self.missing_query_ids != self.retrieval_verification.missing_query_ids:
            raise ValueError("missing_query_ids 必须来自 G3 VerificationResult")
        if self.evidence_requirement_satisfied != self.evidence_requirement_state.satisfied:
            raise ValueError("evidence_requirement_satisfied 必须来自 G12 state")
        if self.missing_evidence_groups != self.evidence_requirement_state.missing_evidence_groups:
            raise ValueError("missing_evidence_groups 必须来自 G12 state")
        if (
            self.distinct_project_code_paths
            != self.evidence_requirement_state.distinct_project_code_paths
        ):
            raise ValueError("distinct_project_code_paths 必须来自 G12 state")
        if (
            self.required_min_distinct_project_code_paths
            != self.evidence_requirement_state.required_min_distinct_project_code_paths
        ):
            raise ValueError("required_min_distinct_project_code_paths 必须来自 G12 state")
        for label in (
            "required_query_ids",
            "covered_query_ids",
            "missing_query_ids",
            "invalid_citation_ids",
            "insufficiency_reasons",
        ):
            _strict_string_tuple(getattr(self, label), label)
        if any(
            query_id not in self.required_query_ids
            for query_id in self.covered_query_ids + self.missing_query_ids
        ):
            raise ValueError("coverage query IDs 必须来自 required_query_ids")
        expected_missing = tuple(
            query_id
            for query_id in self.required_query_ids
            if query_id not in self.covered_query_ids
        )
        if self.missing_query_ids != expected_missing:
            raise ValueError("missing_query_ids 必须由 required/covered truth 推导")
        if self.coverage_complete != self.retrieval_verification.coverage_complete:
            raise ValueError("coverage_complete 必须来自 G3 VerificationResult")
        if self.evidence_count != self.retrieval_verification.evidence_count:
            raise ValueError("evidence_count 必须来自 G3 VerificationResult")
        if any(reason not in INSUFFICIENCY_REASONS for reason in self.insufficiency_reasons):
            raise ValueError("insufficiency_reasons 含未知 reason")
        expected_reasons: list[str] = []
        if not self.retrieval_can_generate:
            expected_reasons.append(
                INCOMPLETE_SUBQUERY_COVERAGE
                if self.retrieval_reason_code == "INCOMPLETE_SUBQUERY_EVIDENCE"
                else RETRIEVAL_EVIDENCE_INSUFFICIENT
            )
        if not self.evidence_requirement_satisfied:
            expected_reasons.append(REQUIRED_EVIDENCE_MISSING)
        if self.citation_status == CITATION_STATUS_INVALID:
            expected_reasons.append(INVALID_CITATION_REFERENCE)
        if self.answer_evidence_binding_status == ANSWER_BINDING_STATUS_MISSING:
            expected_reasons.append(ANSWER_EVIDENCE_REFERENCE_MISSING)
        if self.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INCOMPLETE:
            expected_reasons.append(ANSWER_EVIDENCE_REFERENCE_INCOMPLETE)
        if self.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INVALID:
            expected_reasons.append(ANSWER_EVIDENCE_REFERENCE_INVALID)
        if self.insufficiency_reasons != tuple(expected_reasons):
            raise ValueError("insufficiency_reasons 必须由正交 check 推导")
        if self.citation_status == CITATION_STATUS_INVALID and not self.invalid_citation_ids:
            raise ValueError("INVALID citation_status 要求 invalid_citation_ids")
        if self.citation_status != CITATION_STATUS_INVALID and self.invalid_citation_ids:
            raise ValueError("只有 INVALID citation_status 可以有 invalid_citation_ids")
        if self.answer_evidence_binding_status not in ANSWER_BINDING_STATUSES:
            raise ValueError("answer_evidence_binding_status 不是合法内部 status")
        if type(self.answer_evidence_binding_required) is not bool:
            raise TypeError("answer_evidence_binding_required 必须是 bool")
        _strict_string_tuple(self.cited_evidence_ids, "cited_evidence_ids")
        _strict_string_tuple(self.invalid_evidence_ids, "invalid_evidence_ids")
        if self.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INVALID:
            if not self.invalid_evidence_ids:
                raise ValueError("INVALID binding_status 要求 invalid_evidence_ids")
        elif self.invalid_evidence_ids:
            raise ValueError("只有 INVALID binding_status 可以有 invalid_evidence_ids")
        if self.answer_evidence_binding_status in {
            ANSWER_BINDING_STATUS_NOT_CHECKED,
            ANSWER_BINDING_STATUS_NOT_REQUIRED,
            ANSWER_BINDING_STATUS_MISSING,
        } and self.cited_evidence_ids:
            raise ValueError(f"{self.answer_evidence_binding_status} binding_status 不允许 cited_evidence_ids")
        if self.answer_evidence_binding_status in {
            ANSWER_BINDING_STATUS_VALID,
            ANSWER_BINDING_STATUS_INCOMPLETE,
        } and not self.cited_evidence_ids:
            raise ValueError(f"{self.answer_evidence_binding_status} binding_status 要求 cited_evidence_ids")
        expected_can_finalize = (
            self.retrieval_can_generate
            and self.evidence_requirement_satisfied
            and self.citation_status != CITATION_STATUS_INVALID
            and self.answer_evidence_binding_status in ANSWER_BINDING_PASS_STATUSES
        )
        if self.can_finalize != expected_can_finalize:
            raise ValueError("can_finalize 必须是四个正交 check 的合取")
        expected_recovery = (
            not self.can_finalize
            and self.retrieval_can_generate
            and self.evidence_requirement_satisfied is False
            and self.citation_status != CITATION_STATUS_INVALID
        )
        if self.recovery_allowed != expected_recovery:
            raise ValueError(
                "recovery_allowed 只允许用于 retrieval 已足够且 G12 evidence 缺失；"
                "evidence 已足够时的 binding failure 不是 acquisition failure"
            )

    @property
    def missing_evidence_kinds(self) -> frozenset[str]:
        """Bounded recovery hint derived from the one G12 state."""

        kinds = {
            kind
            for group in self.missing_evidence_groups
            for kind in group
        }
        if (
            not kinds
            and self.distinct_project_code_paths
            < self.required_min_distinct_project_code_paths
        ):
            kinds.add("project_code")
        return frozenset(kinds)


class BoundEngineeringEvidenceVerifier:
    """Per-run binding; it delegates every check to one verifier instance."""

    def __init__(
        self,
        verifier: "EngineeringEvidenceVerifier",
        planner_outcome: PlannerOutcome,
        retrieval_snapshot: EngineeringRetrievalSnapshot,
        requirement: EngineeringEvidenceRequirement,
    ) -> None:
        verifier._validate_inputs(
            planner_outcome,
            retrieval_snapshot,
            requirement,
        )
        self._verifier = verifier
        self._planner_outcome = planner_outcome
        self._retrieval_snapshot = retrieval_snapshot
        self._requirement = requirement

    def verify(
        self,
        current_public_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence],
        proposed_answer: str | None = None,
    ) -> EngineeringVerificationResult:
        return self._verifier.verify(
            self._planner_outcome,
            self._retrieval_snapshot,
            self._requirement,
            current_public_evidence,
            proposed_answer=proposed_answer,
        )


class EngineeringEvidenceVerifier:
    """Compose G3, G12, and citation checks into one trusted result."""

    def _validate_inputs(
        self,
        planner_outcome: PlannerOutcome,
        retrieval_snapshot: EngineeringRetrievalSnapshot,
        requirement: EngineeringEvidenceRequirement,
    ) -> None:
        if not isinstance(planner_outcome, PlannerOutcome):
            raise TypeError("planner_outcome 必须是 PlannerOutcome")
        if not isinstance(retrieval_snapshot, EngineeringRetrievalSnapshot):
            raise TypeError(
                "retrieval_snapshot 必须是 EngineeringRetrievalSnapshot"
            )
        if not isinstance(requirement, EngineeringEvidenceRequirement):
            raise TypeError("requirement 必须是 EngineeringEvidenceRequirement")
        if retrieval_snapshot.planner_outcome != planner_outcome:
            raise ValueError("retrieval_snapshot 必须属于同一个 PlannerOutcome")
        if retrieval_snapshot.resolved_input != planner_outcome.plan.original_query:
            raise ValueError("PlannerOutcome 与 retrieval_snapshot identity 不一致")

    def bind(
        self,
        planner_outcome: PlannerOutcome,
        retrieval_snapshot: EngineeringRetrievalSnapshot,
        requirement: EngineeringEvidenceRequirement,
    ) -> BoundEngineeringEvidenceVerifier:
        return BoundEngineeringEvidenceVerifier(
            self,
            planner_outcome,
            retrieval_snapshot,
            requirement,
        )

    def verify(
        self,
        planner_outcome: PlannerOutcome,
        retrieval_snapshot: EngineeringRetrievalSnapshot,
        requirement: EngineeringEvidenceRequirement,
        current_public_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence],
        *,
        proposed_answer: str | None = None,
    ) -> EngineeringVerificationResult:
        """Run all orthogonal checks and return one finalization state."""

        self._validate_inputs(planner_outcome, retrieval_snapshot, requirement)
        evidence = _strict_evidence_sequence(current_public_evidence)
        if proposed_answer is not None and type(proposed_answer) is not str:
            raise TypeError("proposed_answer 必须是 str 或 None")

        requirement_kinds = {
            kind
            for group in requirement.required_evidence_groups
            for kind in group
        }
        # Knowledge Planned Retrieval is a parallel backend.  For a
        # Project-only requirement it may enrich the seed, but its coverage
        # cannot become a second prerequisite that blocks Repo/Git/Test
        # finalization.  The default G3 verifier behavior remains unchanged;
        # this is the Unified Runtime composition boundary.
        planned_knowledge_required = not (
            any(kind.startswith("project_") for kind in requirement_kinds)
            and "knowledge" not in requirement_kinds
        )
        retrieval_result = MinimalEvidenceVerifier().verify(
            planner_outcome.plan,
            retrieval_snapshot.evidence_bundle,
            required_query_ids=retrieval_snapshot.required_query_ids,
            covered_query_ids=retrieval_snapshot.covered_query_ids,
            upgrade_attempted=retrieval_snapshot.upgrade_attempted,
            upgrade_used=retrieval_snapshot.upgrade_used,
            retrieval_required=planned_knowledge_required,
        )
        requirement_state = evaluate_evidence_requirement(requirement, evidence)

        citation_status = CITATION_STATUS_NOT_CHECKED
        invalid_citation_ids: tuple[str, ...] = ()
        if proposed_answer is not None:
            citation_validation = CitationValidator().validate(
                proposed_answer,
                list(evidence_bundle_to_citation_blocks(retrieval_snapshot.evidence_bundle)),
            )
            if citation_validation.invalid:
                citation_status = CITATION_STATUS_INVALID
                invalid_citation_ids = tuple(
                    check.citation_id for check in citation_validation.invalid
                )
            elif citation_validation.valid:
                citation_status = CITATION_STATUS_VALID
            else:
                citation_status = CITATION_STATUS_NOT_PRESENT

        insufficiency_reasons: list[str] = []
        if not retrieval_result.can_generate:
            if retrieval_result.reason_code == "INCOMPLETE_SUBQUERY_EVIDENCE":
                insufficiency_reasons.append(INCOMPLETE_SUBQUERY_COVERAGE)
            else:
                insufficiency_reasons.append(RETRIEVAL_EVIDENCE_INSUFFICIENT)
        if not requirement_state.satisfied:
            insufficiency_reasons.append(REQUIRED_EVIDENCE_MISSING)
        if citation_status == CITATION_STATUS_INVALID:
            insufficiency_reasons.append(INVALID_CITATION_REFERENCE)

        binding_status, binding_required, cited_evidence_ids, invalid_evidence_ids = (
            _evaluate_answer_evidence_binding(requirement, evidence, proposed_answer)
        )
        if binding_status == ANSWER_BINDING_STATUS_MISSING:
            insufficiency_reasons.append(ANSWER_EVIDENCE_REFERENCE_MISSING)
        elif binding_status == ANSWER_BINDING_STATUS_INCOMPLETE:
            insufficiency_reasons.append(ANSWER_EVIDENCE_REFERENCE_INCOMPLETE)
        elif binding_status == ANSWER_BINDING_STATUS_INVALID:
            insufficiency_reasons.append(ANSWER_EVIDENCE_REFERENCE_INVALID)

        can_finalize = (
            retrieval_result.can_generate
            and requirement_state.satisfied
            and citation_status != CITATION_STATUS_INVALID
            and binding_status in ANSWER_BINDING_PASS_STATUSES
        )
        return EngineeringVerificationResult(
            can_finalize=can_finalize,
            retrieval_status=retrieval_result.status,
            retrieval_reason_code=retrieval_result.reason_code,
            retrieval_can_generate=retrieval_result.can_generate,
            evidence_requirement_satisfied=requirement_state.satisfied,
            missing_evidence_groups=requirement_state.missing_evidence_groups,
            distinct_project_code_paths=requirement_state.distinct_project_code_paths,
            required_min_distinct_project_code_paths=(
                requirement_state.required_min_distinct_project_code_paths
            ),
            coverage_complete=retrieval_result.coverage_complete,
            required_query_ids=retrieval_result.required_query_ids,
            covered_query_ids=retrieval_result.covered_query_ids,
            missing_query_ids=retrieval_result.missing_query_ids,
            citation_status=citation_status,
            invalid_citation_ids=invalid_citation_ids,
            insufficiency_reasons=tuple(insufficiency_reasons),
            recovery_allowed=(
                not can_finalize
                and retrieval_result.can_generate
                and not requirement_state.satisfied
                and citation_status != CITATION_STATUS_INVALID
            ),
            retrieval_verification=retrieval_result,
            evidence_requirement_state=requirement_state,
            evidence_count=retrieval_result.evidence_count,
            answer_evidence_binding_status=binding_status,
            answer_evidence_binding_required=binding_required,
            cited_evidence_ids=cited_evidence_ids,
            invalid_evidence_ids=invalid_evidence_ids,
        )


__all__ = [
    "CITATION_STATUS_NOT_CHECKED",
    "CITATION_STATUS_NOT_PRESENT",
    "CITATION_STATUS_VALID",
    "CITATION_STATUS_INVALID",
    "CITATION_STATUSES",
    "ANSWER_BINDING_STATUS_NOT_CHECKED",
    "ANSWER_BINDING_STATUS_NOT_REQUIRED",
    "ANSWER_BINDING_STATUS_MISSING",
    "ANSWER_BINDING_STATUS_INCOMPLETE",
    "ANSWER_BINDING_STATUS_INVALID",
    "ANSWER_BINDING_STATUS_VALID",
    "ANSWER_BINDING_STATUSES",
    "ANSWER_BINDING_PASS_STATUSES",
    "ANSWER_EVIDENCE_REFERENCE_MISSING",
    "ANSWER_EVIDENCE_REFERENCE_INCOMPLETE",
    "ANSWER_EVIDENCE_REFERENCE_INVALID",
    "RETRIEVAL_EVIDENCE_INSUFFICIENT",
    "INCOMPLETE_SUBQUERY_COVERAGE",
    "REQUIRED_EVIDENCE_MISSING",
    "INVALID_CITATION_REFERENCE",
    "INSUFFICIENCY_REASONS",
    "parse_answer_evidence_references",
    "evidence_bundle_to_citation_blocks",
    "EngineeringVerificationResult",
    "EngineeringEvidenceVerifier",
    "BoundEngineeringEvidenceVerifier",
]
