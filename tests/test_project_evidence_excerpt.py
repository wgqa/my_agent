"""Reader output fidelity and bounded public delivery, without a live model."""

from __future__ import annotations

import json
from types import SimpleNamespace

import jsonschema
import pytest
from fastapi.testclient import TestClient

import api.app
from api.schemas import ToolAgentEvidence
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.runtime import ToolAgentRuntime, _evidence_from_project_context
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence, ToolAgentBudget
from core.tool_agent.source_excerpt import (
    MAX_PROJECT_CONTEXT_CHARACTERS, MAX_PROJECT_CHANGE_CHARACTERS,
)
from core.tool_agent.tools.read_project_context import ReadProjectContextHandler
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime


class _ReadThenAnswer:
    def __init__(self, path, mode):
        self.path, self.mode = path, mode
        self.contexts, self.states = [], []

    def decide(self, _registry, _question, *, context=(), control_state=None):
        self.contexts.append(context)
        self.states.append(control_state)
        if len(self.contexts) == 1:
            action = ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={
                "path": self.path, "line": 1 if self.mode == "definition" else 31,
                "context_lines": 0 if self.mode == "definition" else 30, "mode": self.mode,
            })
        else:
            action = FinalAnswerAction(action="final_answer", answer="The final instruction is RETURN_TARGET. [E1]")
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def _facade(tmp_path, path, mode):
    lines = ["def demo():"] + [f"    value = {n}  # bounded source text for a complete citation" for n in range(59)]
    lines.append("    return 'RETURN_TARGET'")
    source = tmp_path / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    provider = _ReadThenAnswer(path, mode)
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort())
    runtime = build_full_unified_runtime(ToolAgentRuntime(registry=registry, provider=provider))
    return EngineeringAgentFacade(runtime), provider, "\n".join(lines)


@pytest.mark.parametrize("path, mode, kind", [
    ("README.md", "window", "project_doc"),
    ("src/service.py", "window", "project_code"),
    ("tests/test_service.py", "window", "project_test"),
    ("src/service.py", "definition", "project_code"),
])
@pytest.mark.parametrize("endpoint", [
    "/engineering/query", "/engineering/query/stream", "/engineering/query/stream/v2",
])
def test_reader_tail_survives_full_runtime_api_and_both_streams(monkeypatch, tmp_path, path, mode, kind, endpoint):
    facade, provider, expected = _facade(tmp_path, path, mode)
    assert len(expected) > 2000
    monkeypatch.setattr(api.app, "engineering_agent_facade", facade)
    response = TestClient(api.app.app).post(endpoint, json={"question": f"Read {path} and cite the final instruction"})
    assert response.status_code == 200
    if endpoint == "/engineering/query":
        data = response.json()
    else:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert not [e for e in events if e["type"] == "error"]
        assert events[-1]["type"] == "done"
        data = next(e["result"] for e in events if e["type"] == "final")
        if endpoint == "/engineering/query/stream":
            assert [e["evidence"] for e in events if e["type"] == "evidence"] == data["evidence"]
    assert data["status"] == "completed"
    assert (data["iterations_used"], data["tool_calls_used"], data["tool_errors_used"]) == (2, 1, 0)
    assert len(data["evidence"]) == 1
    public_evidence = data["evidence"][0]
    assert (public_evidence["evidence_id"], public_evidence["kind"]) == ("E1", kind)
    assert (public_evidence["path"], public_evidence["start_line"], public_evidence["end_line"]) == (path, 1, 61)
    assert public_evidence["snippet"] == expected
    assert public_evidence["granularity"] == "source_body"
    assert public_evidence["completeness"] == "unknown"
    actual = provider.contexts[-1][-1].observation_result
    assert "\n".join(line["text"] for line in actual["lines"]) == expected
    # Only locators enter trusted control, never source text.
    assert provider.states[-1].available_evidence_refs[0].end_line == 61
    assert "RETURN_TARGET" not in json.dumps(provider.states[-1].to_dict(include_evidence_reference_control=True))


@pytest.mark.parametrize("character", ["x", "界", "🙂"])
def test_maximum_unicode_window_is_retained_without_second_clipping(tmp_path, character):
    (tmp_path / "README.md").write_text((character * 300 + "\n") * 61, encoding="utf-8")
    result = ReadProjectContextHandler(tmp_path).execute({"path": "README.md", "line": 31, "context_lines": 30})
    lines = result["lines"]
    evidence = _evidence_from_project_context(SimpleNamespace(status="ok", tool_name="read_project_context", result=result))
    assert evidence is not None
    assert len(evidence.snippet) == MAX_PROJECT_CONTEXT_CHARACTERS == 18360
    assert evidence.snippet == "\n".join(line["text"] for line in lines)
    assert ToolAgentEvidence(**evidence.to_dict()).snippet == evidence.snippet


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(end_line=4),
    lambda r: r["lines"][1].update(line=3),
    lambda r: r["lines"][0].update(line=True),
    lambda r: r["lines"][0].update(text="x" * 301),
    lambda r: r.update(mode="file"),
    lambda r: r.update(lines=[]),
    lambda r: r.update(start_line=True),
    lambda r: r["lines"].append({"line": 3, "text": "extra"}),
])
def test_inconsistent_reader_data_never_gets_a_public_locator(mutation):
    result = {"path": "README.md", "start_line": 1, "end_line": 2, "lines": [
        {"line": 1, "text": "a"}, {"line": 2, "text": "b"},
    ]}
    mutation(result)
    assert _evidence_from_project_context(SimpleNamespace(status="ok", tool_name="read_project_context", result=result)) is None


@pytest.mark.parametrize("mode, count", [("window", 62), ("definition", 121)])
def test_reader_line_budget_is_not_bypassed(mode, count):
    result = {"path": "src/service.py", "start_line": 1, "end_line": count, "mode": mode,
              "lines": [{"line": n, "text": "x"} for n in range(1, count + 1)]}
    assert _evidence_from_project_context(SimpleNamespace(status="ok", tool_name="read_project_context", result=result)) is None


def test_definition_character_budget_is_not_bypassed():
    result = {"path": "src/service.py", "start_line": 1, "end_line": 30, "mode": "definition",
              "lines": [{"line": n, "text": "x" * 300} for n in range(1, 31)]}
    assert _evidence_from_project_context(SimpleNamespace(status="ok", tool_name="read_project_context", result=result)) is None


@pytest.mark.parametrize("kind, limit", [
    ("project_code", 18360), ("project_doc", 18360), ("project_test", 18360), ("project_change", 2000),
])
def test_runtime_api_and_openapi_apply_the_same_kind_size_policy(kind, limit):
    payload = {"evidence_id": "E1", "kind": kind, "path": "source.txt", "start_line": 1, "end_line": 1,
               "snippet": "x" * limit}
    assert EngineeringEvidence(**payload).snippet == ToolAgentEvidence(**payload).snippet
    jsonschema.validate(payload, ToolAgentEvidence.model_json_schema())
    payload["snippet"] += "x"
    for model in (EngineeringEvidence, ToolAgentEvidence):
        with pytest.raises(ValueError):
            model(**payload)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, ToolAgentEvidence.model_json_schema())


def test_knowledge_limit_and_agent_budget_are_unchanged():
    assert MAX_PROJECT_CHANGE_CHARACTERS == 2000
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
    with pytest.raises(ValueError):
        KnowledgeEvidence(evidence_id="E1", kind="knowledge", source_name="knowledge/guide.md", chunk_id=None,
                          score=None, rank=1, snippet="x" * 501)
