"""Frozen formal evaluation selection and truthful binding-tool observation."""
from copy import deepcopy
import json

import pytest

from evaluation.tool_calls_v2 import evidence_acceptance as acceptance
from evaluation.tool_calls_v2.observer import Recorder
from evaluation.tool_calls_v2.runner import run_gold_proof
from evaluation.tool_calls_v2.schema import DATASET_DIR, digest
from evaluation.tool_calls_v2.scorer import score_case, unsafe_attempt
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.tools.project_info import (
    PROJECT_INFO_DOCUMENTATION_SPEC, PROJECT_INFO_DOCUMENTATION_VERSION,
    ProjectBinding, ProjectInfoHandler,
)


def test_formal_matrix_keeps_historical_gold_and_new_cases_separate():
    known, new, protocol = acceptance.frozen_cases()
    old_protocol = json.loads((DATASET_DIR / "protocol.json").read_text(encoding="utf-8"))
    assert digest(known) == old_protocol["cases_sha256"]
    assert len(known) == 72 and len(new) == 24
    assert {c["id"] for c in known}.isdisjoint(c["id"] for c in new)
    assert protocol["model_calls_before_freeze"] == 0
    assert protocol["planned_tasks"] == 408
    assert protocol["sealed_holdout"] is False
    assert len(protocol["answer_quality_rubric"]) == 24


@pytest.mark.parametrize("phase,count,groups", [
    ("regression", 72, ["A", "B", "C", "D"]),
    ("new", 24, ["A", "B", "C", "D"]),
    ("stability-2", 12, ["D"]), ("stability-3", 12, ["D"]),
])
def test_phase_selection_cannot_choose_only_successful_cases(phase, count, groups):
    cases, actual_groups, identity = acceptance.select_phase(phase)
    assert len(cases) == count and actual_groups == groups
    assert identity["phase"] == phase
    assert len(identity["protocol_sha256"]) == 64
    assert identity["sealed_holdout"] is False
    if phase == "regression":
        assert {c["id"][:3] for c in cases} == {"dev", "val"}
    if phase.startswith("stability"):
        assert [c["id"] for c in cases] == acceptance.frozen_cases()[2]["stability_ids"]


def test_modified_new_gold_is_rejected_before_calls(tmp_path, monkeypatch):
    path = tmp_path / "cases.jsonl"
    cases = deepcopy(acceptance.frozen_cases()[1])
    cases[0]["query"] += " changed after freeze"
    path.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    monkeypatch.setattr(acceptance, "NEW_CASES", path)
    with pytest.raises(ValueError, match="Frozen evaluation matrix changed"):
        acceptance.frozen_cases()


def test_binding_observation_retains_facts_but_not_host_root(tmp_path):
    registry = ToolRegistry()
    registry.register(PROJECT_INFO_DOCUMENTATION_SPEC,
        ProjectInfoHandler(ProjectBinding(tmp_path.resolve(), "fixture", "configured"),
                           version=PROJECT_INFO_DOCUMENTATION_VERSION))
    case = acceptance.frozen_cases()[1][1]
    recorder = Recorder(case["id"])
    run_gold_proof(case, registry, recorder)
    tool = next(e for e in recorder.events if e["stage"] == "tool")
    assert tool["result"] == {"project_name": "fixture", "source": "configured", "available": True}
    assert str(tmp_path) not in json.dumps(recorder.events)
    assert score_case(case, recorder.events, mode="gold_proof")["verdict"] == "PASS"


def test_preflight_uses_library_retrieval_port_without_model_calls(tmp_path, monkeypatch):
    from core.knowledge_library import KnowledgeLibrary
    case = acceptance.frozen_cases()[1][1]
    observed = []

    def prepare(**kwargs):
        observed.append(kwargs)
        (kwargs["output"] / "state/projects/fixture").mkdir(parents=True)
        KnowledgeLibrary(kwargs["output"] / "state/knowledge.sqlite3", seeds=[])
        return {"status": "prepared"}

    monkeypatch.setattr(acceptance, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(acceptance, "select_phase", lambda phase: ([case], ["A"], {"phase": phase}))
    monkeypatch.setattr(acceptance, "execute", prepare)
    assert acceptance.main(["--phase", "new", "--preflight", "--run-id", "offline"]) == 0
    assert observed[0]["live"] is False
    result = json.loads((tmp_path / "data/runtime/evidence_experiments/offline/gold_reachability.json").read_text(encoding="utf-8"))
    assert result["model_calls"] == 0 and result["pass"] == result["cases"] == 1
    assert result["synthetic_terminal"] is True
    with pytest.raises(ValueError, match="Preflight cannot call models"):
        acceptance.main(["--phase", "new", "--preflight", "--live", "--run-id", "bad"])
    assert len(observed) == 1


@pytest.mark.parametrize("arguments,unsafe", [({}, False), ({"include_documentation": True}, False),
    ({"include_documentation": 1}, True), ({"path": "../outside.env"}, True)])
def test_legitimate_binding_tool_does_not_hide_invalid_arguments(arguments, unsafe):
    assert unsafe_attempt({"action": "tool_call", "tool_name": "get_project_info", "arguments": arguments}) is unsafe
    assert unsafe_attempt({"action": "tool_call", "tool_name": "unknown", "arguments": {}})
