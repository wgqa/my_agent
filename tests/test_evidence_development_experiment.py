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


def test_material_repair_has_separate_frozen_matrix_and_known_case_selection():
    from evaluation.tool_calls_v2.material_repair import GROUPS, FOCUSED_IDS, select_cases
    cases, _ = select_cases("focused")
    assert [c["id"] for c in cases] == list(FOCUSED_IDS)
    assert GROUPS == {"D": ("llm", "goal_v2", "semantic_v1"), "D2": ("llm", "goal_v2", "semantic_v2")}
    assert GROUP_SETTINGS["D"] == ("llm", "goal_v2", "semantic_v1")
    all_known, _ = select_cases("all-known")
    assert len(all_known) == 96 and len({c["id"] for c in all_known}) == 96


def _probe_source(tmp_path):
    import hashlib
    import json
    from evaluation.tool_calls_v2.fixtures import materialize_project, project_identity
    from evaluation.tool_calls_v2.schema import digest
    from core.tool_agent.actions import ToolCallAction
    from tests.test_engineering_candidate_runtime import build, answer, Reviewer, review
    from tests.test_engineering_requirement_planning import goal
    source = tmp_path/"source"
    root = source/"state/projects/fixture"
    materialize_project("fixture", root, tmp_path/"cache")
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E1"]),))])
    runtime, _ = build(root, [ToolCallAction(action="tool_call", tool_name="read_project_context",
        arguments={"path": "a.py", "target": {"kind": "file", "start_line": 1}}), answer("A 返回1 [E1]。")],
        reviewer=reviewer, goals=[goal("A", "A")])
    result = runtime.run("解释 A 的完整实现")
    assert result.status == "refused"  # v4 whole-file metadata cannot identify A.
    artifact = source/"dev-001_D.json"
    artifact.write_text(json.dumps({"audit": result.to_audit_dict()}, ensure_ascii=False), encoding="utf-8")
    cases = [{"id": "dev-001", "project": "fixture"}]
    (source/"cases.jsonl").write_text(json.dumps(cases[0])+"\n", encoding="utf-8")
    (source/"runs.jsonl").write_text(json.dumps({"case_id": "dev-001", "group": "D", "artifact": artifact.name,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})+"\n", encoding="utf-8")
    (source/"manifest.json").write_text(json.dumps({"status": "finished", "run_id": "synthetic-test",
        "code_head": "synthetic-test", "cases_sha256": digest(cases),
        "projects": {"fixture": project_identity("fixture", root)}}, ensure_ascii=False), encoding="utf-8")
    return source


def test_component_probe_reproduces_real_bodies_without_rewriting_original_scores(tmp_path):
    import json
    from evaluation.tool_calls_v2.material_repair import component_probe
    source = _probe_source(tmp_path)
    original = (source/"dev-001_D.json").read_bytes()
    output = tmp_path/"probe"
    summary = component_probe([source], output)
    assert summary["model_calls"] == 0 and summary["checked_artifacts"] == 1
    assert summary["byte_identical_body_records"] == 1
    assert summary["review_accept_blocked_before"] == summary["review_accept_source_gaps_resolved"] == 2
    assert summary["lost_previously_supported_goals"] == 0
    assert (source/"dev-001_D.json").read_bytes() == original
    assert json.loads(original)["audit"]["result"]["status"] == "refused"
    with pytest.raises(ValueError, match="never overwrite"):
        component_probe([source], output)


@pytest.mark.parametrize("corruption", ["artifact", "fixture"])
def test_component_probe_rejects_changed_source_artifacts_and_fixtures(tmp_path, corruption):
    from evaluation.tool_calls_v2.material_repair import component_probe
    source = _probe_source(tmp_path)
    path = source/("dev-001_D.json" if corruption == "artifact" else "state/projects/fixture/a.py")
    with path.open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValueError, match="changed"):
        component_probe([source], tmp_path/"probe")
