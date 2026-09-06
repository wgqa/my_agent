"""Provider-free contract tests for ARCH-EVAL-15C."""

from __future__ import annotations

import pytest

from evaluation.integration_v7.semantic_review_contract import (
    SEMANTIC_REVIEW_RUBRIC_VERSION,
    SEMANTIC_REVIEW_VERSION,
    SemanticReviewContractError,
    validate_semantic_review,
)


def _case(*, expected_outcome="answerable", family="repo_only", case_id="v7d001"):
    result = {
        "case_id": case_id,
        "expected_outcome": expected_outcome,
        "task_family": family,
        "gold_obligations": [
            {"id": "O1", "text": "First frozen obligation"},
            {"id": "O2", "text": "Second frozen obligation"},
        ],
        "source_proofs": [{"kind": "project_code", "relative_path": "core/runtime.py"}],
    }
    if family == "context_followup":
        result["expected_standalone_intent"] = "Explain the current implementation."
    return result


def _run(*, status="completed", validity="VALID", evidence=True, case_id="v7d001"):
    if validity == "INVALID":
        return {
            "case_id": case_id,
            "run_validity": "INVALID",
            "final": None,
            "public_evidence": None,
        }
    return {
        "case_id": case_id,
        "run_validity": "VALID",
        "final": {
            "status": status,
            "answer": "A completed answer." if status == "completed" else None,
        },
        "public_evidence": (
            [{"evidence_id": "E1", "kind": "project_code", "path": "core/runtime.py"}]
            if evidence
            else []
        ),
        "runtime_requirement_state": {"satisfied": True},
        "router_gold_contract_match": True,
        "context": {
            "resolved_input": "Explain the implementation.",
            "resolution_correct_frozen_exact": False,
        },
    }


def _review(
    *,
    case_id="v7d001",
    validity="VALID",
    terminal="PASS",
    coverage="FULL",
    grounding="SUPPORTED",
    context="NOT_APPLICABLE",
    refusal="NOT_APPLICABLE",
    labels=("none",),
    claims=(),
):
    obligations = []
    if validity == "VALID":
        obligations = [
            {"obligation_id": "O1", "answer_coverage": coverage, "review_note": "manual review"},
            {"obligation_id": "O2", "answer_coverage": coverage, "review_note": "manual review"},
        ]
    return {
        "schema_version": SEMANTIC_REVIEW_VERSION,
        "rubric_version": SEMANTIC_REVIEW_RUBRIC_VERSION,
        "case_id": case_id,
        "run_validity": validity,
        "terminal_assessment": terminal,
        "obligation_assessments": obligations,
        "grounding_assessment": {
            "assessment": grounding,
            "unsupported_material_claims": list(claims),
            "review_note": "grounding review",
        },
        "context_assessment": {"assessment": context, "review_note": "context review"},
        "refusal_assessment": refusal,
        "failure_labels": list(labels),
        "review_notes": "overall human review",
    }


def _validate(case, run, review):
    return validate_semantic_review(frozen_case=case, semantic_run=run, review=review).to_dict()


def test_answerable_completed_is_terminal_pass():
    record = _validate(_case(), _run(), _review())
    assert record["terminal_assessment"] == "PASS"
    assert record["refusal_assessment"] == "NOT_APPLICABLE"


def test_answerable_refusal_is_terminal_fail_and_over_refusal():
    record = _validate(
        _case(),
        _run(status="refused"),
        _review(
            terminal="FAIL",
            coverage="NOT_APPLICABLE_NO_ANSWER",
            grounding="NOT_APPLICABLE_NO_CLAIM",
            refusal="OVER_REFUSAL",
            labels=("terminal_outcome", "refusal"),
        ),
    )
    assert record["terminal_assessment"] == "FAIL"
    assert record["refusal_assessment"] == "OVER_REFUSAL"


def test_expected_refusal_refused_is_terminal_pass_and_justified():
    record = _validate(
        _case(expected_outcome="refusal"),
        _run(status="refused"),
        _review(
            terminal="PASS",
            coverage="NOT_APPLICABLE_NO_ANSWER",
            grounding="NOT_APPLICABLE_NO_CLAIM",
            refusal="JUSTIFIED",
        ),
    )
    assert record["terminal_assessment"] == "PASS"
    assert record["refusal_assessment"] == "JUSTIFIED"


def test_expected_refusal_completed_is_terminal_fail_and_under_refusal():
    record = _validate(
        _case(expected_outcome="refusal"),
        _run(status="completed"),
        _review(
            terminal="FAIL",
            refusal="UNDER_REFUSAL",
            labels=("terminal_outcome", "refusal"),
        ),
    )
    assert record["terminal_assessment"] == "FAIL"
    assert record["refusal_assessment"] == "UNDER_REFUSAL"


def test_invalid_run_is_not_applicable_for_every_semantic_dimension():
    record = _validate(
        _case(),
        _run(validity="INVALID"),
        _review(
            validity="INVALID",
            terminal="NOT_APPLICABLE_INVALID",
            grounding="NOT_APPLICABLE_INVALID",
            context="NOT_APPLICABLE_INVALID",
            refusal="NOT_APPLICABLE",
            labels=("infrastructure",),
        ),
    )
    assert record["obligation_assessments"] == []
    assert record["grounding_assessment"]["assessment"] == "NOT_APPLICABLE_INVALID"
    assert record["context_assessment"]["assessment"] == "NOT_APPLICABLE_INVALID"


def test_answer_correctness_and_grounding_are_intentionally_independent():
    record = _validate(
        _case(),
        _run(evidence=False),
        _review(
            coverage="FULL",
            grounding="UNSUPPORTED",
            labels=("semantic_grounding", "unsupported_material_claim"),
            claims=(
                {"claim": "The final answer makes a material implementation claim.", "rationale": "No public evidence was retrieved."},
            ),
        ),
    )
    assert {item["answer_coverage"] for item in record["obligation_assessments"]} == {"FULL"}
    assert record["grounding_assessment"]["assessment"] == "UNSUPPORTED"


def test_runtime_and_router_facts_do_not_automatically_create_semantic_pass():
    run = _run(evidence=False)
    assert run["runtime_requirement_state"]["satisfied"] is True
    assert run["router_gold_contract_match"] is True
    record = _validate(
        _case(),
        run,
        _review(
            coverage="MISSING",
            grounding="UNSUPPORTED",
            labels=("answer_obligation_missing", "semantic_grounding"),
            claims=(
                {"claim": "The answer omits a required material fact.", "rationale": "No retrieved evidence supports the missing fact."},
            ),
        ),
    )
    assert {item["answer_coverage"] for item in record["obligation_assessments"]} == {"MISSING"}
    assert record["grounding_assessment"]["assessment"] == "UNSUPPORTED"


def test_context_semantic_pass_is_legal_when_frozen_exact_metric_is_false():
    case = _case(family="context_followup")
    run = _run()
    assert run["context"]["resolution_correct_frozen_exact"] is False
    record = _validate(case, run, _review(context="PASS"))
    assert record["context_assessment"]["assessment"] == "PASS"


def test_context_review_requires_resolved_input_for_semantic_comparison():
    case = _case(family="context_followup")
    run = _run()
    run["context"]["resolved_input"] = None
    with pytest.raises(SemanticReviewContractError, match="resolved_input"):
        _validate(case, run, _review(context="FAIL", labels=("context_resolution",)))


def test_gold_source_proof_cannot_be_treated_as_retrieved_public_evidence():
    case = _case()
    run = _run(evidence=False)
    review = _review(grounding="SUPPORTED")
    with pytest.raises(SemanticReviewContractError, match="Gold reference"):
        _validate(case, run, review)
    record = _validate(
        case,
        run,
        _review(
            grounding="UNSUPPORTED",
            labels=("semantic_grounding",),
            claims=(
                {"claim": "Gold proof exists outside the run artifact.", "rationale": "It is not retrieved public evidence."},
            ),
        ),
    )
    assert record["grounding_assessment"]["assessment"] == "UNSUPPORTED"


def test_multiple_failure_labels_are_supported_without_responsibility_attribution():
    record = _validate(
        _case(),
        _run(evidence=False),
        _review(
            coverage="CONTRADICTED",
            grounding="CONTRADICTED",
            labels=("answer_contradiction", "semantic_grounding", "unsupported_material_claim"),
            claims=(
                {"claim": "A material answer claim conflicts with evidence.", "rationale": "The public evidence does not support it."},
            ),
        ),
    )
    assert record["failure_labels"] == [
        "answer_contradiction",
        "semantic_grounding",
        "unsupported_material_claim",
    ]
    with pytest.raises(SemanticReviewContractError):
        _validate(
            _case(),
            _run(),
            _review(labels=("router_bug",)),
        )


def test_schema_rejects_composite_scores_and_unknown_fields():
    review = _review()
    review["overall_accuracy"] = 1.0
    with pytest.raises(SemanticReviewContractError, match="fields"):
        _validate(_case(), _run(), review)
    review = _review()
    review["weighted_score"] = 100
    with pytest.raises(SemanticReviewContractError, match="fields"):
        _validate(_case(), _run(), review)
