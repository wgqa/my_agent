"""Versioned offline contract for human semantic review of Dev artifacts.

This module validates a human review record against a frozen evaluator case
and a semantic-evaluable run artifact.  It intentionally does not judge
natural-language entailment, calculate a composite score, call a provider, or
attribute product responsibility from evaluation observations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SEMANTIC_REVIEW_VERSION = "integration_v7_semantic_review_v1"
SEMANTIC_REVIEW_RUBRIC_VERSION = "integration_v7_semantic_review_rubric_v1"

TERMINAL_ASSESSMENTS = frozenset({"PASS", "FAIL", "NOT_APPLICABLE_INVALID"})
ANSWER_COVERAGE = frozenset(
    {"FULL", "PARTIAL", "MISSING", "CONTRADICTED", "NOT_APPLICABLE_NO_ANSWER"}
)
GROUNDING_ASSESSMENTS = frozenset(
    {
        "SUPPORTED",
        "PARTIAL",
        "UNSUPPORTED",
        "CONTRADICTED",
        "NOT_APPLICABLE_NO_CLAIM",
        "NOT_APPLICABLE_INVALID",
    }
)
CONTEXT_ASSESSMENTS = frozenset(
    {"PASS", "PARTIAL", "FAIL", "NOT_APPLICABLE", "NOT_APPLICABLE_INVALID"}
)
REFUSAL_ASSESSMENTS = frozenset(
    {"JUSTIFIED", "OVER_REFUSAL", "UNDER_REFUSAL", "NOT_APPLICABLE"}
)
FAILURE_LABELS = frozenset(
    {
        "infrastructure",
        "terminal_outcome",
        "evidence_acquisition",
        "answer_obligation_missing",
        "answer_contradiction",
        "semantic_grounding",
        "unsupported_material_claim",
        "context_resolution",
        "refusal",
        "none",
    }
)
_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "rubric_version",
        "case_id",
        "run_validity",
        "terminal_assessment",
        "obligation_assessments",
        "grounding_assessment",
        "context_assessment",
        "refusal_assessment",
        "failure_labels",
        "review_notes",
    }
)
_VALID_RUN = "VALID"
_INVALID_RUN = "INVALID"


class SemanticReviewContractError(ValueError):
    """Raised when a human semantic review record violates the frozen contract."""


@dataclass(frozen=True)
class SemanticReviewRecord:
    """Validated review dimensions, deliberately without a composite score."""

    case_id: str
    run_validity: str
    terminal_assessment: str
    obligation_assessments: Sequence[Mapping[str, str]]
    grounding_assessment: Mapping[str, Any]
    context_assessment: Mapping[str, str]
    refusal_assessment: str
    failure_labels: Sequence[str]
    review_notes: str

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": SEMANTIC_REVIEW_VERSION,
            "rubric_version": SEMANTIC_REVIEW_RUBRIC_VERSION,
            "case_id": self.case_id,
            "run_validity": self.run_validity,
            "terminal_assessment": self.terminal_assessment,
            "obligation_assessments": self.obligation_assessments,
            "grounding_assessment": self.grounding_assessment,
            "context_assessment": self.context_assessment,
            "refusal_assessment": self.refusal_assessment,
            "failure_labels": self.failure_labels,
            "review_notes": self.review_notes,
        }
        return json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        )


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticReviewContractError(f"{label} must be an object")
    return value


def _require_text(value: object, label: str, *, max_length: int = 2000) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_length:
        raise SemanticReviewContractError(f"{label} must be bounded non-empty text")
    return value


def _require_choice(value: object, choices: frozenset[str], label: str) -> str:
    if value not in choices:
        raise SemanticReviewContractError(f"{label} has an unsupported value")
    return value


def _case_identity(frozen_case: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    case_id = _require_text(frozen_case.get("case_id"), "frozen case.case_id", max_length=100)
    expected_outcome = frozen_case.get("expected_outcome")
    if expected_outcome not in {"answerable", "refusal"}:
        raise SemanticReviewContractError("frozen case.expected_outcome is invalid")
    obligations = frozen_case.get("gold_obligations")
    if not isinstance(obligations, list) or not obligations:
        raise SemanticReviewContractError("frozen case.gold_obligations must be a non-empty list")
    obligation_ids: list[str] = []
    for obligation in obligations:
        item = _require_mapping(obligation, "gold obligation")
        obligation_id = _require_text(item.get("id"), "gold obligation.id", max_length=100)
        if obligation_id in obligation_ids:
            raise SemanticReviewContractError("frozen case has duplicate gold obligation IDs")
        obligation_ids.append(obligation_id)
    return case_id, expected_outcome, obligation_ids


def _semantic_run_state(semantic_run: Mapping[str, Any]) -> tuple[str, str | None, bool]:
    validity = semantic_run.get("run_validity")
    if validity not in {_VALID_RUN, _INVALID_RUN}:
        raise SemanticReviewContractError("semantic run.run_validity is invalid")
    if validity == _INVALID_RUN:
        return validity, None, False
    final = _require_mapping(semantic_run.get("final"), "VALID semantic run.final")
    status = final.get("status")
    if status not in {"completed", "refused", "failed"}:
        raise SemanticReviewContractError("VALID semantic run final status is invalid")
    evidence = semantic_run.get("public_evidence")
    if not isinstance(evidence, list):
        raise SemanticReviewContractError("VALID semantic run.public_evidence must be a list")
    return validity, status, bool(evidence)


def expected_terminal_assessment(expected_outcome: str, final_status: str | None) -> str:
    """Return the deterministic terminal outcome dimension only."""

    if final_status is None:
        return "NOT_APPLICABLE_INVALID"
    if expected_outcome == "answerable":
        return "PASS" if final_status == "completed" else "FAIL"
    if expected_outcome == "refusal":
        return "PASS" if final_status == "refused" else "FAIL"
    raise SemanticReviewContractError("expected_outcome is invalid")


def expected_refusal_assessment(expected_outcome: str, final_status: str | None) -> str:
    """Return the deterministic refusal category where the terminal shape fixes it."""

    if final_status is None or final_status == "failed":
        return "NOT_APPLICABLE"
    if expected_outcome == "answerable" and final_status == "refused":
        return "OVER_REFUSAL"
    if expected_outcome == "refusal" and final_status == "completed":
        return "UNDER_REFUSAL"
    if expected_outcome == "refusal" and final_status == "refused":
        return "JUSTIFIED"
    return "NOT_APPLICABLE"


def _validate_obligation_assessments(
    value: object,
    obligation_ids: Sequence[str],
    *,
    answer_present: bool,
    invalid: bool,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise SemanticReviewContractError("obligation_assessments must be a list")
    if invalid:
        if value:
            raise SemanticReviewContractError("INVALID review must not assess obligations")
        return []
    if len(value) != len(obligation_ids):
        raise SemanticReviewContractError("every frozen Gold obligation requires one assessment")
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        assessment = _require_mapping(item, "obligation assessment")
        if set(assessment) != {"obligation_id", "answer_coverage", "review_note"}:
            raise SemanticReviewContractError("obligation assessment has unsupported fields")
        obligation_id = _require_text(assessment.get("obligation_id"), "obligation_id", max_length=100)
        if obligation_id not in obligation_ids or obligation_id in seen:
            raise SemanticReviewContractError("obligation assessment IDs must match frozen Gold once")
        coverage = _require_choice(
            assessment.get("answer_coverage"), ANSWER_COVERAGE, "answer_coverage"
        )
        if answer_present and coverage == "NOT_APPLICABLE_NO_ANSWER":
            raise SemanticReviewContractError("completed answer cannot have NO_ANSWER obligation coverage")
        if not answer_present and coverage != "NOT_APPLICABLE_NO_ANSWER":
            raise SemanticReviewContractError("missing final answer requires NO_ANSWER obligation coverage")
        output.append(
            {
                "obligation_id": obligation_id,
                "answer_coverage": coverage,
                "review_note": _require_text(assessment.get("review_note"), "obligation review_note"),
            }
        )
        seen.add(obligation_id)
    if [item["obligation_id"] for item in output] != list(obligation_ids):
        raise SemanticReviewContractError("obligation assessments must retain frozen Gold order")
    return output


def _validate_grounding(
    value: object,
    *,
    answer_present: bool,
    public_evidence_present: bool,
    invalid: bool,
) -> dict[str, Any]:
    assessment = _require_mapping(value, "grounding_assessment")
    if set(assessment) != {"assessment", "unsupported_material_claims", "review_note"}:
        raise SemanticReviewContractError("grounding_assessment has unsupported fields")
    kind = _require_choice(
        assessment.get("assessment"), GROUNDING_ASSESSMENTS, "grounding assessment"
    )
    claims = assessment.get("unsupported_material_claims")
    if not isinstance(claims, list):
        raise SemanticReviewContractError("unsupported_material_claims must be a list")
    output_claims: list[dict[str, str]] = []
    for claim in claims:
        item = _require_mapping(claim, "unsupported material claim")
        if set(item) != {"claim", "rationale"}:
            raise SemanticReviewContractError("unsupported material claim has unsupported fields")
        output_claims.append(
            {
                "claim": _require_text(item.get("claim"), "material claim", max_length=1000),
                "rationale": _require_text(item.get("rationale"), "claim rationale", max_length=1000),
            }
        )
    if invalid:
        if kind != "NOT_APPLICABLE_INVALID" or output_claims:
            raise SemanticReviewContractError("INVALID review grounding must be not applicable")
    elif not answer_present:
        if kind != "NOT_APPLICABLE_NO_CLAIM" or output_claims:
            raise SemanticReviewContractError("no final answer grounding must be not applicable")
    else:
        if kind == "NOT_APPLICABLE_INVALID":
            raise SemanticReviewContractError("VALID review grounding cannot be invalid")
        if kind in {"SUPPORTED", "PARTIAL"} and not public_evidence_present:
            raise SemanticReviewContractError(
                "Gold reference cannot substitute for retrieved public evidence"
            )
        if kind in {"UNSUPPORTED", "CONTRADICTED"} and not output_claims:
            raise SemanticReviewContractError(
                "unsupported or contradicted grounding needs a material claim"
            )
        if kind in {"SUPPORTED", "NOT_APPLICABLE_NO_CLAIM"} and output_claims:
            raise SemanticReviewContractError(
                "supported/no-claim grounding cannot list unsupported claims"
            )
    return {
        "assessment": kind,
        "unsupported_material_claims": output_claims,
        "review_note": _require_text(assessment.get("review_note"), "grounding review_note"),
    }


def _validate_context(
    value: object,
    frozen_case: Mapping[str, Any],
    semantic_run: Mapping[str, Any],
    *,
    invalid: bool,
) -> dict[str, str]:
    assessment = _require_mapping(value, "context_assessment")
    if set(assessment) != {"assessment", "review_note"}:
        raise SemanticReviewContractError("context_assessment has unsupported fields")
    kind = _require_choice(
        assessment.get("assessment"), CONTEXT_ASSESSMENTS, "context assessment"
    )
    if invalid and kind != "NOT_APPLICABLE_INVALID":
        raise SemanticReviewContractError("INVALID review context must be not applicable")
    if not invalid and frozen_case.get("task_family") != "context_followup" and kind != "NOT_APPLICABLE":
        raise SemanticReviewContractError("only context_followup cases may have a context assessment")
    if not invalid and frozen_case.get("task_family") == "context_followup":
        if kind in {"NOT_APPLICABLE", "NOT_APPLICABLE_INVALID"}:
            raise SemanticReviewContractError(
                "context_followup requires semantic context assessment"
            )
        _require_text(
            frozen_case.get("expected_standalone_intent"),
            "context_followup expected_standalone_intent",
        )
        run_context = _require_mapping(
            semantic_run.get("context"), "context_followup semantic run.context"
        )
        # The reviewer compares this observable input with the frozen intent.
        # The legacy exact-string signal is deliberately not read to derive the
        # semantic assessment; a false exact match may still be semantically PASS.
        _require_text(
            run_context.get("resolved_input"),
            "context_followup semantic run.context.resolved_input",
        )
    return {
        "assessment": kind,
        "review_note": _require_text(assessment.get("review_note"), "context review_note"),
    }


def _validate_failure_labels(value: object, *, invalid: bool) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SemanticReviewContractError("failure_labels must be a non-empty list")
    if any(label not in FAILURE_LABELS for label in value) or len(set(value)) != len(value):
        raise SemanticReviewContractError("failure_labels contain an unsupported or duplicate label")
    if "none" in value and len(value) != 1:
        raise SemanticReviewContractError("failure_labels.none cannot be combined with another label")
    if invalid and "infrastructure" not in value:
        raise SemanticReviewContractError("INVALID review requires the infrastructure label")
    return list(value)


def validate_semantic_review(
    *,
    frozen_case: Mapping[str, Any],
    semantic_run: Mapping[str, Any],
    review: Mapping[str, Any],
) -> SemanticReviewRecord:
    """Validate a manual review without deriving semantic correctness from Runtime facts."""

    case = _require_mapping(frozen_case, "frozen case")
    run = _require_mapping(semantic_run, "semantic run")
    candidate = _require_mapping(review, "semantic review")
    if set(candidate) != _REVIEW_FIELDS:
        raise SemanticReviewContractError("semantic review fields do not match the frozen schema")
    if candidate.get("schema_version") != SEMANTIC_REVIEW_VERSION:
        raise SemanticReviewContractError("semantic review schema_version mismatch")
    if candidate.get("rubric_version") != SEMANTIC_REVIEW_RUBRIC_VERSION:
        raise SemanticReviewContractError("semantic review rubric_version mismatch")

    case_id, expected_outcome, obligation_ids = _case_identity(case)
    if candidate.get("case_id") != case_id or run.get("case_id") != case_id:
        raise SemanticReviewContractError("review, semantic run, and frozen case IDs must agree")
    validity, final_status, public_evidence_present = _semantic_run_state(run)
    if candidate.get("run_validity") != validity:
        raise SemanticReviewContractError("review run_validity must equal the semantic run")
    invalid = validity == _INVALID_RUN
    answer_present = final_status == "completed"

    terminal = _require_choice(
        candidate.get("terminal_assessment"), TERMINAL_ASSESSMENTS, "terminal_assessment"
    )
    expected_terminal = expected_terminal_assessment(expected_outcome, final_status)
    if terminal != expected_terminal:
        raise SemanticReviewContractError("terminal_assessment must match frozen expected outcome")
    obligations = _validate_obligation_assessments(
        candidate.get("obligation_assessments"),
        obligation_ids,
        answer_present=answer_present,
        invalid=invalid,
    )
    grounding = _validate_grounding(
        candidate.get("grounding_assessment"),
        answer_present=answer_present,
        public_evidence_present=public_evidence_present,
        invalid=invalid,
    )
    context = _validate_context(
        candidate.get("context_assessment"), case, run, invalid=invalid
    )
    refusal = _require_choice(
        candidate.get("refusal_assessment"), REFUSAL_ASSESSMENTS, "refusal_assessment"
    )
    if refusal != expected_refusal_assessment(expected_outcome, final_status):
        raise SemanticReviewContractError("refusal_assessment must match the terminal/refusal contract")
    return SemanticReviewRecord(
        case_id=case_id,
        run_validity=validity,
        terminal_assessment=terminal,
        obligation_assessments=obligations,
        grounding_assessment=grounding,
        context_assessment=context,
        refusal_assessment=refusal,
        failure_labels=_validate_failure_labels(
            candidate.get("failure_labels"), invalid=invalid
        ),
        review_notes=_require_text(candidate.get("review_notes"), "review_notes"),
    )


__all__ = [
    "ANSWER_COVERAGE",
    "CONTEXT_ASSESSMENTS",
    "FAILURE_LABELS",
    "GROUNDING_ASSESSMENTS",
    "REFUSAL_ASSESSMENTS",
    "SEMANTIC_REVIEW_RUBRIC_VERSION",
    "SEMANTIC_REVIEW_VERSION",
    "TERMINAL_ASSESSMENTS",
    "SemanticReviewContractError",
    "SemanticReviewRecord",
    "expected_refusal_assessment",
    "expected_terminal_assessment",
    "validate_semantic_review",
]
