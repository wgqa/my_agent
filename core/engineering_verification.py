"""Unified Engineering evidence verification and finalization state.

This module composes the existing G3 query-level verifier, the frozen G12
evidence-shape evaluator, and the existing citation-ID validator.  It does not
introduce a new verifier algorithm, LLM judge, recovery loop, or finalization
controller.  The returned result is trusted internal state consumed by the
single ToolAgent finalization point.
"""

from __future__ import annotations

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
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence


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
INSUFFICIENCY_REASONS = (
    RETRIEVAL_EVIDENCE_INSUFFICIENT,
    INCOMPLETE_SUBQUERY_COVERAGE,
    REQUIRED_EVIDENCE_MISSING,
    INVALID_CITATION_REFERENCE,
)


def _strict_evidence_sequence(
    value: object,
) -> tuple[EngineeringEvidence | KnowledgeEvidence, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("current_public_evidence 必须是 public evidence 序列")
    normalized = tuple(value)
    if any(type(item) not in (EngineeringEvidence, KnowledgeEvidence) for item in normalized):
        raise TypeError(
            "current_public_evidence 必须全部是 EngineeringEvidence 或 KnowledgeEvidence"
        )
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
        if self.insufficiency_reasons != tuple(expected_reasons):
            raise ValueError("insufficiency_reasons 必须由三个正交 check 推导")
        if self.citation_status == CITATION_STATUS_INVALID and not self.invalid_citation_ids:
            raise ValueError("INVALID citation_status 要求 invalid_citation_ids")
        if self.citation_status != CITATION_STATUS_INVALID and self.invalid_citation_ids:
            raise ValueError("只有 INVALID citation_status 可以有 invalid_citation_ids")
        expected_can_finalize = (
            self.retrieval_can_generate
            and self.evidence_requirement_satisfied
            and self.citation_status != CITATION_STATUS_INVALID
        )
        if self.can_finalize != expected_can_finalize:
            raise ValueError("can_finalize 必须是三个正交 check 的合取")
        expected_recovery = (
            not self.can_finalize
            and self.retrieval_can_generate
            and self.evidence_requirement_satisfied is False
            and self.citation_status != CITATION_STATUS_INVALID
        )
        if self.recovery_allowed != expected_recovery:
            raise ValueError(
                "recovery_allowed 只允许用于 retrieval 已足够且 G12 evidence 缺失"
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
        current_public_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence],
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
        current_public_evidence: Sequence[EngineeringEvidence | KnowledgeEvidence],
        *,
        proposed_answer: str | None = None,
    ) -> EngineeringVerificationResult:
        """Run all orthogonal checks and return one finalization state."""

        self._validate_inputs(planner_outcome, retrieval_snapshot, requirement)
        evidence = _strict_evidence_sequence(current_public_evidence)
        if proposed_answer is not None and type(proposed_answer) is not str:
            raise TypeError("proposed_answer 必须是 str 或 None")

        retrieval_result = MinimalEvidenceVerifier().verify(
            planner_outcome.plan,
            retrieval_snapshot.evidence_bundle,
            required_query_ids=retrieval_snapshot.required_query_ids,
            covered_query_ids=retrieval_snapshot.covered_query_ids,
            upgrade_attempted=retrieval_snapshot.upgrade_attempted,
            upgrade_used=retrieval_snapshot.upgrade_used,
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

        can_finalize = (
            retrieval_result.can_generate
            and requirement_state.satisfied
            and citation_status != CITATION_STATUS_INVALID
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
        )


__all__ = [
    "CITATION_STATUS_NOT_CHECKED",
    "CITATION_STATUS_NOT_PRESENT",
    "CITATION_STATUS_VALID",
    "CITATION_STATUS_INVALID",
    "CITATION_STATUSES",
    "RETRIEVAL_EVIDENCE_INSUFFICIENT",
    "INCOMPLETE_SUBQUERY_COVERAGE",
    "REQUIRED_EVIDENCE_MISSING",
    "INVALID_CITATION_REFERENCE",
    "INSUFFICIENCY_REASONS",
    "evidence_bundle_to_citation_blocks",
    "EngineeringVerificationResult",
    "EngineeringEvidenceVerifier",
    "BoundEngineeringEvidenceVerifier",
]
