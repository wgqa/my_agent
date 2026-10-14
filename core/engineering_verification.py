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
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from core.engineering_task_contract import HybridTaskContract

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


_STATUS_WORDS = {
    "modified": ("modified", "已修改", "修改"),
    "added": ("added", "新增"),
    "deleted": ("deleted", "已删除", "删除"),
    "renamed": ("renamed", "重命名"),
    "untracked": ("untracked", "未跟踪"),
}
_CANDIDATE_REASON_WORDS = frozenset(
    {"mirrored_path", "filename_match", "content_reference"}
)
_BOUNDED_FACT_PATH_PATTERN = re.compile(
    r"(?<![\w./-])(?:[A-Za-z0-9_.@+-]+/)*[A-Za-z0-9_.@+-]+\.[A-Za-z0-9_+-]+"
)


def _formatting_only(text: str) -> bool:
    """Return true only when the remaining text is punctuation/Markdown."""
    return not re.sub(
        r"[\s|:：,，、;；.!?。()（）\[\]{}<>`'\"*_#~—–→-]", "", text
    )


def _remove_terms(text: str, terms: Sequence[str]) -> str:
    for term in sorted((term for term in terms if term), key=len, reverse=True):
        text = re.sub(re.escape(term), "", text, flags=re.IGNORECASE)
    return text


def _line_and_path(text: str, path: str) -> tuple[tuple[int, int] | None, int | None]:
    """Find one common path/line spelling and return its span and line."""
    escaped = re.escape(path)
    patterns = (
        re.compile(rf"(?<![\w./-]){escaped}\s*[:：]\s*(\d+)(?:\s*行)?"),
        re.compile(rf"(?<![\w./-]){escaped}\s+(?:第\s*)?(\d+)\s*行"),
        re.compile(rf"(?:第\s*)?(\d+)\s*行\s*(?:位于|在|in)?\s*{escaped}(?![\w./-])", re.IGNORECASE),
        re.compile(rf"\bline\s+(\d+)\s+(?:in|at)\s+{escaped}(?![\w./-])", re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            number = next(group for group in match.groups() if group is not None)
            return match.span(), int(number)
    return None, None


def _source_arguments(item: ToolResultEvidence) -> dict:
    try:
        value = json.loads(item.arguments_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if type(value) is dict else {}


def _bounded_location_fact(line: str, item: ToolResultEvidence) -> bool:
    """Extract one path/line fact and reject any extra substantive claim."""
    _, text = _answer_line_without_references(line)
    text = text.replace("`", "")
    if type(item.path) is not str or not item.path:
        return False
    paths = _BOUNDED_FACT_PATH_PATTERN.findall(text)
    if paths != [item.path]:
        return False
    span, line_number = _line_and_path(text, item.path)
    if item.granularity == "locator":
        if span is None or line_number != item.start_line:
            return False
    elif item.granularity == "candidate":
        if span is not None and line_number != item.start_line:
            return False
        if span is None and re.search(r"(?:第\s*)?\d+\s*行|\bline\s+\d+", text, re.IGNORECASE):
            return False
    else:
        return False

    residual = text
    if span is not None:
        residual = residual[:span[0]] + " " + residual[span[1]:]
    residual = re.sub(re.escape(item.path), "", residual)
    terms = [
        "位置", "命中位置", "文件和行号", "文件/行号", "定位结果", "位于", "在",
        "Located at", "Location", "is located", "is at", "at", "line", "行",
        "候选测试位置", "候选测试文件", "候选测试", "关联测试文件", "关联测试",
        "候选文件", "候选", "测试文件", "文件", "工具返回的", "返回的",
        "candidate test location", "candidate test", "candidate", "test file",
    ]
    if item.granularity == "locator":
        query = _source_arguments(item).get("query")
        if type(query) is str and query.strip():
            terms.append(query.strip())
    else:
        reasons, reason_spans_ok = _candidate_reason_claims(residual, item)
        if not reason_spans_ok:
            return False
        if reasons is not None:
            residual = reasons
        terms.extend(("候选理由", "reason", "reasons"))
    residual = _remove_terms(residual, terms)
    return _formatting_only(residual)


def _candidate_reason_claims(
    text: str, item: ToolResultEvidence
) -> tuple[str | None, bool]:
    """Remove only reason labels whose tokens match the observed result."""
    matches = list(
        re.finditer(
            r"(?:候选理由|reasons?)\s*[:：]\s*([^）)\n;；。]+)",
            text,
            re.IGNORECASE,
        )
    )
    reason_words = [
        word
        for word in _CANDIDATE_REASON_WORDS
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text)
    ]
    if not matches:
        return text, not reason_words
    if len(matches) != 1:
        return text, False
    match = matches[0]
    claimed = tuple(
        token.strip()
        for token in re.split(r"[\s,，、]+", match.group(1).strip())
        if token.strip()
    )
    if (
        not claimed
        or len(claimed) != len(set(claimed))
        or set(claimed) != set(item.candidate_reasons)
        or not item.candidate_reasons
    ):
        return text, False
    remaining = text[:match.start()] + " " + text[match.end():]
    return remaining, True


def _status_fact(line: str) -> tuple[str, str, str | None] | None:
    """Parse a single file/status row, including common Markdown rename forms."""
    _, text = _answer_line_without_references(line)
    text = text.replace("`", "").strip()
    if not text:
        return None
    cells = [cell.strip() for cell in text.strip("|").split("|")] if "|" in text else [text]
    if cells and all(cell and set(cell) <= {"-", ":", " "} for cell in cells):
        return None
    statuses: set[str] = set()
    for status, aliases in _STATUS_WORDS.items():
        for alias in aliases:
            if alias.isascii():
                found = re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", text, re.IGNORECASE)
            else:
                found = re.search(re.escape(alias), text)
            if found:
                statuses.add(status)
    if len(statuses) != 1:
        return None
    status = next(iter(statuses))
    paths = _BOUNDED_FACT_PATH_PATTERN.findall(text)
    if status != "renamed":
        if len(paths) != 1:
            return None
        target, old_path = paths[0], None
    else:
        if len(paths) != 2:
            return None
        if re.search(r"由\s*" + re.escape(paths[1]) + r"\s*重命名而来", text):
            target, old_path = paths[0], paths[1]
        elif re.search(re.escape(paths[1]) + r"\s+(?:renamed\s+from)\s+" + re.escape(paths[0]), text, re.IGNORECASE):
            target, old_path = paths[1], paths[0]
        elif re.search(re.escape(paths[0]) + r"\s*(?:->|→)\s*" + re.escape(paths[1]), text):
            old_path, target = paths[0], paths[1]
        elif re.search(re.escape(paths[0]) + r"\s+(?:renamed\s+to)\s+" + re.escape(paths[1]), text, re.IGNORECASE):
            old_path, target = paths[0], paths[1]
        elif len(cells) == 2 and _REPO_PATH_MENTION_PATTERN.fullmatch(cells[0]):
            # The status cell may say "renamed (from old/path.py)".
            target, old_path = paths[0], paths[1]
        else:
            return None

    residual = text
    for path in paths:
        residual = re.sub(re.escape(path), "", residual)
    words = [alias for aliases in _STATUS_WORDS.values() for alias in aliases]
    words.extend(("由", "重命名而来", "重命名为", "renamed from", "renamed to", "status", "状态"))
    residual = _remove_terms(residual, words)
    if not _formatting_only(residual):
        return None
    return target, status, old_path


def _is_bounded_location_line(line: str, item: ToolResultEvidence) -> bool:
    references, _ = _answer_line_without_references(line)
    return item.evidence_id in references and _bounded_location_fact(line, item)


def _is_bounded_status_line(line: str, item: ToolResultEvidence) -> tuple[str, str, str | None] | None:
    references, _ = _answer_line_without_references(line)
    if item.evidence_id not in references:
        return None
    fact = _status_fact(line)
    return fact if fact in item.status_entries else None


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


def _is_status_heading(line: str, item: ToolResultEvidence) -> bool:
    """Check a scoped inventory heading and any numeric completeness claims."""
    _, text = _answer_line_without_references(line)
    text = text.replace("`", "")
    if _status_fact(line) is not None:
        return False
    arguments = _source_arguments(item)
    mode = arguments.get("mode")
    mentions_workspace = bool(re.search(r"工作区|工作树|workspace|working\s*tree", text, re.IGNORECASE))
    if mentions_workspace and mode != "working_tree":
        return False
    if mode and re.search(r"working_tree|staged|unstaged|committed", text, re.IGNORECASE):
        mode_match = re.search(r"working_tree|staged|unstaged|committed", text, re.IGNORECASE)
        if mode_match and mode_match.group(0).lower() != mode:
            return False
    counts = [
        int(value)
        for value in re.findall(
            r"(?:共(?:计)?\s*|(?:returned_count|total_count)\s*[=:：]\s*)(\d+)\s*(?:个|项|文件)?",
            text,
            re.IGNORECASE,
        )
    ]
    if any(count != len(item.status_entries) for count in counts):
        return False
    truncation = re.search(r"truncated\s*[=:：]\s*(true|false)", text, re.IGNORECASE)
    if truncation and truncation.group(1).lower() != "false":
        return False
    omitted = re.search(r"omitted_sensitive_count\s*(?:[=:：]|为)\s*(\d+)", text, re.IGNORECASE)
    if omitted and int(omitted.group(1)) != 0:
        return False
    if re.search(r"(?:全部|所有|全量|完整|complete|all|entire)", text, re.IGNORECASE) and item.completeness != "complete":
        return False
    # Remove only verifiable scope/count/completeness fields and neutral labels.
    residual = re.sub(r"truncated\s*[=:：]\s*false", "", text, flags=re.IGNORECASE)
    residual = re.sub(r"omitted_sensitive_count\s*(?:[=:：]|为)\s*0", "", residual, flags=re.IGNORECASE)
    residual = re.sub(
        r"(?:共(?:计)?\s*|(?:returned_count|total_count)\s*[=:：]\s*)\d+\s*(?:个|项|文件)?",
        "",
        residual,
        flags=re.IGNORECASE,
    )
    terms = [
        "当前", "工作区", "工作树", "可见", "变更", "文件", "清单", "列表", "状态", "共", "个", "项", "的", "及", "与", "和",
        "working_tree", "staged", "unstaged", "committed", "workspace", "working tree",
        "visible", "changed", "files", "list", "inventory", "status", "returned", "truncated",
        "omitted_sensitive_count", "说明", "以上", "项目",
    ]
    residual = _remove_terms(residual, terms)
    if not _formatting_only(residual):
        return False
    return any(term in text.lower() for term in ("变更", "清单", "列表", "status", "inventory", "files"))


def _is_candidate_heading(line: str, batch: tuple[ToolResultEvidence, ...]) -> bool:
    """Check a candidate list heading against its source path and exact count."""
    _, text = _answer_line_without_references(line)
    text = text.replace("`", "")
    if not batch or any(item.completeness != "complete" for item in batch):
        return False
    if any(_bounded_location_fact(line, item) for item in batch):
        return False
    paths = _BOUNDED_FACT_PATH_PATTERN.findall(text)
    arguments = [_source_arguments(item) for item in batch]
    source_paths = {arg.get("path") for arg in arguments if type(arg.get("path")) is str}
    if len(source_paths) != 1 or paths != [next(iter(source_paths))]:
        return False
    counts = [int(value) for value in re.findall(r"(?:返回|found|returned)\s*(\d+)\s*(?:个|项|files?|candidates?)?", text, re.IGNORECASE)]
    if any(count != len(batch) for count in counts):
        return False
    truncation = re.search(r"truncated\s*[=:：]\s*(true|false)", text, re.IGNORECASE)
    if truncation and truncation.group(1).lower() != "false":
        return False
    omitted = re.search(r"omitted_sensitive_count\s*(?:[=:：]|为)\s*(\d+)", text, re.IGNORECASE)
    if omitted and int(omitted.group(1)) != 0:
        return False
    residual = re.sub(r"(?:返回|found|returned)\s*\d+\s*(?:个|项|files?|candidates?)?", "", text, flags=re.IGNORECASE)
    residual = re.sub(r"truncated\s*[=:：]\s*false", "", residual, flags=re.IGNORECASE)
    residual = re.sub(r"omitted_sensitive_count\s*(?:[=:：]|为)\s*0", "", residual, flags=re.IGNORECASE)
    residual = re.sub(re.escape(next(iter(source_paths))), "", residual)
    residual = _remove_terms(
        residual,
        (
            "find_tests", "工具", "针对", "返回", "候选", "关联", "测试", "文件", "个", "项",
            "未截断", "结果", "candidate", "related", "test", "files", "truncated",
            "omitted_sensitive_count", "说明", "工具针对", "候选关联测试",
        ),
    )
    return _formatting_only(residual)


def _is_bounded_boundary_note(line: str, item: ToolResultEvidence) -> bool:
    """Allow only explicit, source-consistent caveats around low-granularity facts."""
    _, text = _answer_line_without_references(line)
    text = text.replace("`", "")
    if item.granularity == "candidate":
        if item.completeness != "complete":
            return False
        patterns = (
            r"说明\s*[:：]?", r"这是候选(?:关联)?测试(?:文件)?", r"以上(?:均为|是)候选(?:关联)?测试(?:文件)?",
            r"不代表已证明受影响", r"(?:也)?未执行任何测试", r"(?:也)?未运行任何测试",
            r"结果未截断", r"truncated\s*[=:：]\s*false", r"omitted_sensitive_count\s*(?:[=:：]|为)\s*0",
        )
    elif item.granularity == "status_list":
        if item.completeness != "complete":
            return False
        mode = _source_arguments(item).get("mode")
        if re.search(r"工作区|工作树|workspace|working[_\s-]*tree", text, re.IGNORECASE) and mode != "working_tree":
            return False
        if "untracked" in {status for _, status, _ in item.status_entries}:
            untracked_pattern = r"untracked\s*文件正文不在(?:该)?工具(?:返回)?范围内"
        else:
            untracked_pattern = r"(?!)"
        patterns = (
            r"说明\s*[:：]?", r"以上仅为(?:当前)?(?:working_tree)?变更文件清单(?:与|及)状态",
            r"未读取各文件的具体\s*diff\s*内容", r"未读取(?:文件)?\s*diff(?:\s*内容)?",
            r"truncated\s*[=:：]\s*false", r"omitted_sensitive_count\s*(?:[=:：]|为)\s*0",
            untracked_pattern,
        )
    else:
        return False
    residual = text
    changed = False
    for pattern in patterns:
        residual, count = re.subn(pattern, "", residual, flags=re.IGNORECASE)
        changed = changed or count > 0
    residual = _remove_terms(residual, ("以上", "结果", "本次", "仅", "该", "与", "和", "且", "也", "不", "任何"))
    return changed and _formatting_only(residual)


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


def _is_table_decoration(line: str) -> bool:
    """Recognize Markdown table headers and separators without facts."""
    _, text = _answer_line_without_references(line)
    if "|" not in text:
        return False
    cells = [cell.strip().lower() for cell in text.strip("|").split("|")]
    if cells in (["路径", "状态"], ["path", "status"], ["file", "status"]):
        return True
    return bool(cells) and all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def _tool_result_citations_have_complete_matching_scope(
    answer: str,
    cited_evidence: tuple[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence, ...],
    all_evidence: tuple[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence, ...] | None = None,
) -> bool:
    """Bind low-granularity citations to facts extracted from their typed source.

    The parser accepts a narrow set of Markdown and natural-language renderings
    for paths, line numbers, candidate reasons, and status rows. It compares
    those extracted facts to immutable Tool Evidence metadata. This is not a
    general semantic-entailment check: low-granularity Evidence still cannot
    establish implementation behavior, test execution, or test impact.
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
    if any(item.completeness != "complete" for item in low_granularity_items):
        return False

    lines = answer.splitlines()
    line_references = [
        tuple(f"E{match.group(1)}" for match in _EVIDENCE_REFERENCE_PATTERN.finditer(line))
        for line in lines
    ]
    status_items = tuple(item for item in low_granularity_items if item.granularity == "status_list")
    status_anchors: dict[str, list[int]] = {item.evidence_id: [] for item in status_items}
    for index, line in enumerate(lines):
        for item in status_items:
            if item.evidence_id in line_references[index] and _is_status_heading(line, item):
                status_anchors[item.evidence_id].append(index)

    # Locators and candidate batches are complete result sets. Every emitted
    # fact row must map to its own E-ID; candidate result reasons are checked
    # against the exact enum values retained from that Observation.
    for item in low_granularity_items:
        if item.granularity not in {"locator", "candidate"}:
            continue
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
        if not batch_ids or batch_ids - set(references):
            return False
        for member in batch:
            matched_rows = [
                index
                for index, line in enumerate(lines)
                if _bounded_location_fact(line, member)
                and (
                    member.evidence_id in line_references[index]
                    or (
                        not line_references[index]
                        and member.granularity == "candidate"
                        and any(
                            member.evidence_id in line_references[heading_index]
                            and _is_candidate_heading(
                                lines[heading_index], batch
                            )
                            for heading_index in range(index)
                        )
                    )
                )
            ]
            if len(matched_rows) != 1:
                return False
        for index, line_refs in enumerate(line_references):
            if item.evidence_id not in line_refs:
                continue
            if _bounded_location_fact(lines[index], item):
                continue
            if (
                item.granularity == "candidate"
                and _is_candidate_heading(lines[index], batch)
                and set(line_refs).issubset(batch_ids)
            ):
                continue
            return False

    # A status-list citation can introduce a following structured list/table,
    # or sit on each row. In either form every entry must occur exactly once,
    # including the source/target direction for renames.
    assigned_status_rows: dict[str, list[tuple[str, str, str | None]]] = {
        item.evidence_id: [] for item in status_items
    }
    for index, line in enumerate(lines):
        fact = _status_fact(line)
        if fact is None:
            continue
        line_refs = line_references[index]
        referenced_status = [item for item in status_items if item.evidence_id in line_refs]
        if referenced_status:
            if any(fact not in item.status_entries for item in referenced_status):
                return False
            if any(
                reference in tool_by_id
                and tool_by_id[reference].granularity in {"locator", "candidate"}
                for reference in line_refs
            ):
                return False
            for item in referenced_status:
                assigned_status_rows[item.evidence_id].append(fact)
            continue
        # An unreferenced row inherits only the nearest explicit inventory
        # heading. This is the citation binding for Markdown table rows.
        prior_anchors = [
            (anchor_index, item)
            for item in status_items
            for anchor_index in status_anchors[item.evidence_id]
            if anchor_index < index
        ]
        if not prior_anchors:
            return False
        nearest_index = max(anchor_index for anchor_index, _ in prior_anchors)
        owners = [
            item
            for anchor_index, item in prior_anchors
            if anchor_index == nearest_index and fact in item.status_entries
        ]
        if len(owners) != 1:
            return False
        assigned_status_rows[owners[0].evidence_id].append(fact)

    for item in status_items:
        cited_lines = [
            index for index, refs_on_line in enumerate(line_references)
            if item.evidence_id in refs_on_line
        ]
        if not cited_lines:
            return False
        if not item.status_entries:
            if not any(_is_bounded_empty_status_line(lines[index], item) for index in cited_lines):
                return False
            if assigned_status_rows[item.evidence_id]:
                return False
            continue
        for index in cited_lines:
            if _status_fact(lines[index]) is None and not _is_status_heading(lines[index], item):
                return False
        if Counter(assigned_status_rows[item.evidence_id]) != Counter(item.status_entries):
            return False

    if not answer_grade_ids:
        # When only low-granularity Tool Evidence is cited, every answer line
        # must parse as a checked fact, a checked scope heading, Markdown
        # structure, or a source-consistent boundary note.
        for index, line in enumerate(lines):
            if not line.strip() or _is_table_decoration(line):
                continue
            if _status_fact(line) is not None:
                continue
            if any(_bounded_location_fact(line, item) for item in low_granularity_items):
                continue
            if any(_is_bounded_empty_status_line(line, item) for item in status_items):
                continue
            if any(_is_status_heading(line, item) for item in status_items):
                continue
            candidate_batches = {
                (item.tool_name, item.call_id, item.result_sha256): tuple(
                    other
                    for other in all_evidence
                    if type(other) is ToolResultEvidence
                    and other.tool_name == item.tool_name
                    and other.call_id == item.call_id
                    and other.result_sha256 == item.result_sha256
                    and other.granularity == "candidate"
                )
                for item in low_granularity_items
                if item.granularity == "candidate"
            }
            if any(_is_candidate_heading(line, batch) for batch in candidate_batches.values()):
                continue
            if any(_is_bounded_boundary_note(line, item) for item in low_granularity_items):
                continue
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
        task_contract: HybridTaskContract | None = None,
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
        self.task_contract = task_contract

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
            **({"task_contract": self.task_contract} if self.task_contract is not None else {}),
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
        *,
        task_contract: HybridTaskContract | None = None,
    ) -> BoundEngineeringEvidenceVerifier:
        return BoundEngineeringEvidenceVerifier(
            self,
            planner_outcome,
            retrieval_snapshot,
            requirement,
            task_contract,
        )

    def verify(
        self,
        planner_outcome: PlannerOutcome,
        retrieval_snapshot: EngineeringRetrievalSnapshot,
        requirement: EngineeringEvidenceRequirement,
        current_public_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence],
        *,
        proposed_answer: str | None = None,
        task_contract: HybridTaskContract | None = None,
    ) -> EngineeringVerificationResult:
        """Run all orthogonal checks and return one finalization state."""

        self._validate_inputs(planner_outcome, retrieval_snapshot, requirement)
        if task_contract is not None and type(task_contract) is not HybridTaskContract:
            raise TypeError("task_contract must be HybridTaskContract")
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
        if task_contract is not None and task_contract.operation != "other":
            planned_knowledge_required = task_contract.requires_knowledge
        retrieval_result = MinimalEvidenceVerifier().verify(
            planner_outcome.plan,
            retrieval_snapshot.evidence_bundle,
            required_query_ids=retrieval_snapshot.required_query_ids,
            covered_query_ids=retrieval_snapshot.covered_query_ids,
            upgrade_attempted=retrieval_snapshot.upgrade_attempted,
            upgrade_used=retrieval_snapshot.upgrade_used,
            retrieval_required=planned_knowledge_required,
        )
        requirement_evidence = (
            task_contract.scoped_evidence(evidence) if task_contract is not None else evidence
        )
        requirement_state = evaluate_evidence_requirement(requirement, requirement_evidence)
        if task_contract is not None and task_contract.material_error(requirement_evidence):
            requirement_state = replace(requirement_state, satisfied=False)

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
