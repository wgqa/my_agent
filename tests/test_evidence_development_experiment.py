"""The development harness keeps heldout Gold out and uses the real assembly."""
import pytest

from copy import deepcopy
from evaluation.tool_calls_v2.evidence_experiment import GROUP_SETTINGS, PILOT_CASE_IDS, select_cases, score_tool_records


def test_pilot_selection_is_frozen_known_cases_without_heldout_access():
    cases = select_cases(PILOT_CASE_IDS)
    assert len(cases) == 12 and all(case["split"] == "dev" for case in cases)
    for ids in ([], ["dev-001", "dev-001"], ["val-001"], ["unknown"]):
        with pytest.raises(ValueError):
            select_cases(ids)


def test_matrix_keeps_material_changes_requirement_changes_and_review_separate():
    assert GROUP_SETTINGS == {"A": ("rule", "legacy", "legacy"), "B": ("rule", "goal_v2", "structural_v2"),
                             "C": ("llm", "goal_v2", "structural_v2"), "D": ("llm", "goal_v2", "semantic_v1")}


def test_projection_preserves_tool_decision_terminal_records_and_unknown_stages(monkeypatch):
    events = [{"seq": 1, "stage": "provider_call", "role": "requirement"},
              {"seq": 2, "stage": "tool", "arguments": {"path": "a.py"}, "result": {"text": "actual"}},
              {"seq": 3, "stage": "decision", "action": {"action": "refuse"}},
              {"seq": 4, "stage": "terminal", "status": "refused"},
              {"seq": 5, "stage": "requirement_result", "call_count": 1,
               "schema_version": "engineering_requirement_planning_metadata_v1"},
              {"seq": 6, "stage": "unknown_stage"}]
    original = deepcopy(events)
    observed = []
    monkeypatch.setattr("evaluation.tool_calls_v2.evidence_experiment.score_case",
                        lambda case, records, mode: observed.extend(records) or {"verdict": "INVALID"})
    score = score_tool_records({"id": "dev-001"}, events)
    assert events == original
    assert [{**e, "seq": seq} for seq, e in zip((2, 3, 4, 6), observed)] == [events[i] for i in (1, 2, 3, 5)]
    assert score["verdict"] == "INVALID"  # Unknown stages are still seen by the strict scorer.
    assert score["record_projection"]["excluded_stage_sequences"] == [1, 5]


@pytest.mark.parametrize("events", [
    [{"seq": 2, "stage": "terminal"}],
    [{"seq": 1, "stage": "provider_call", "role": "review"}],
    [{"seq": 1, "stage": "review_summary", "review_calls": 1,
      "schema_version": "engineering_candidate_finalization_v1"}],
    [{"seq": 1, "stage": "requirement_result", "call_count": 0, "schema_version": "unknown"}],
])
def test_projection_cannot_hide_missing_model_calls_or_unknown_metadata(events):
    with pytest.raises(ValueError):
        score_tool_records({"id": "dev-001"}, events)
