"""Provider-free tests for ARCH-EVAL-14B-MICRO."""

from __future__ import annotations

from types import SimpleNamespace

from evaluation.integration_v7.case_contract import compute_premature_finalization
from evaluation.integration_v7.finalization_attribution import (
    FINALIZATION_ATTRIBUTION_VERSION,
    attribute_finalization,
)


def _state(satisfied: bool):
    return SimpleNamespace(satisfied=satisfied)


def _requirement(groups, minimum=0):
    return SimpleNamespace(
        required_evidence_groups=tuple(tuple(group) for group in groups),
        min_distinct_project_code_paths=minimum,
    )


def _case(groups, minimum=0):
    return {
        "required_evidence_groups": [list(group) for group in groups],
        "min_distinct_project_code_paths": minimum,
    }


def _evidence(*items):
    return [SimpleNamespace(**item) for item in items]


def test_versioned_attribution_separates_a_real_runtime_premature_completion():
    result = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(False),
        runtime_requirement=_requirement([["project_code"]]),
        frozen_case=_case([["project_code"]]),
        public_evidence=[],
    )
    assert FINALIZATION_ATTRIBUTION_VERSION == "integration_v7_finalization_attribution_v1"
    assert result.runtime_requirement_satisfied is False
    assert result.runtime_premature_finalization is True
    assert result.gold_incomplete_at_completion is True
    assert result.router_gold_contract_match is True
    assert result.to_dict()["version"] == FINALIZATION_ATTRIBUTION_VERSION


def test_runtime_satisfied_but_router_gold_mismatch_is_not_runtime_premature():
    result = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(True),
        runtime_requirement=_requirement([["knowledge"], ["project_code", "project_doc"]]),
        frozen_case=_case([["knowledge"], ["project_code"]]),
        public_evidence=_evidence(
            {"kind": "knowledge"}, {"kind": "project_code", "path": "src/app.py"}
        ),
    )
    assert result.runtime_premature_finalization is False
    assert result.router_gold_contract_match is False
    assert result.gold_structural_evidence_satisfied is True


def test_runtime_normal_but_gold_evidence_incomplete_is_independent():
    result = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(True),
        runtime_requirement=_requirement([["project_doc"]]),
        frozen_case=_case([["project_doc"], ["project_code"]]),
        public_evidence=_evidence({"kind": "project_doc", "path": "docs/design.md"}),
    )
    assert result.runtime_premature_finalization is False
    assert result.gold_evidence_groups_satisfied is False
    assert result.gold_structural_evidence_satisfied is False
    assert result.gold_incomplete_at_completion is True
    assert result.router_gold_contract_match is False


def test_gold_complete_but_router_contract_differs_cannot_become_guard_failure():
    result = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(True),
        runtime_requirement=_requirement([["knowledge"], ["project_code", "project_doc"]]),
        frozen_case=_case([["knowledge"], ["project_code"]]),
        public_evidence=_evidence(
            {"kind": "knowledge"}, {"kind": "project_code", "path": "src/app.py"}
        ),
    )
    assert result.router_gold_contract_match is False
    assert result.gold_structural_evidence_satisfied is True
    assert result.runtime_premature_finalization is False


def test_gold_distinct_project_code_path_floor_counts_only_valid_distinct_code_paths():
    evidence = _evidence(
        {"kind": "project_code", "path": "src/app.py"},
        {"kind": "project_code", "path": "src/app.py"},
        {"kind": "project_doc", "path": "docs/app.md"},
        {"kind": "project_test", "path": "tests/test_app.py"},
        {"kind": "project_change", "path": "src/app.py"},
    )
    one = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(True),
        runtime_requirement=_requirement([["project_code"]], 2),
        frozen_case=_case([["project_code"]], 2),
        public_evidence=evidence,
    )
    two = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(True),
        runtime_requirement=_requirement([["project_code"]], 2),
        frozen_case=_case([["project_code"]], 2),
        public_evidence=evidence + _evidence({"kind": "project_code", "path": "src/other.py"}),
    )
    assert one.gold_min_project_code_paths_satisfied is False
    assert two.gold_min_project_code_paths_satisfied is True


def test_refusal_is_never_attributed_as_premature_or_completed_incomplete():
    result = attribute_finalization(
        final_status="refused",
        runtime_requirement_state=_state(False),
        runtime_requirement=_requirement([["project_code"]]),
        frozen_case=_case([["project_code"]]),
        public_evidence=[],
    )
    assert result.runtime_premature_finalization is False
    assert result.gold_incomplete_at_completion is False
    assert result.gold_structural_evidence_satisfied is False


def test_frozen_metric_is_unchanged_and_new_attribution_is_independent():
    assert (
        compute_premature_finalization(
            {},
            {
                "finalized": True,
                "required_evidence_satisfied": True,
                "typed_requirement_satisfied": False,
            },
        )
        is True
    )
    result = attribute_finalization(
        final_status="completed",
        runtime_requirement_state=_state(True),
        runtime_requirement=_requirement([["project_doc"]]),
        frozen_case=_case([["project_code"]]),
        public_evidence=_evidence({"kind": "project_code", "path": "src/app.py"}),
    )
    assert result.runtime_premature_finalization is False
    assert result.router_gold_contract_match is False
    assert result.gold_structural_evidence_satisfied is True
