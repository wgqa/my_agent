"""The development harness keeps heldout Gold out and uses the real assembly."""
import pytest

from evaluation.tool_calls_v2.evidence_experiment import GROUP_SETTINGS, PILOT_CASE_IDS, select_cases


def test_pilot_selection_is_frozen_known_cases_without_heldout_access():
    cases = select_cases(PILOT_CASE_IDS)
    assert len(cases) == 12 and all(case["split"] == "dev" for case in cases)
    for ids in ([], ["dev-001", "dev-001"], ["val-001"], ["unknown"]):
        with pytest.raises(ValueError):
            select_cases(ids)


def test_matrix_keeps_material_changes_requirement_changes_and_review_separate():
    assert GROUP_SETTINGS == {"A": ("rule", "legacy", "legacy"), "B": ("rule", "goal_v2", "structural_v2"),
                             "C": ("llm", "goal_v2", "structural_v2"), "D": ("llm", "goal_v2", "semantic_v1")}
