"""Deterministic evidence collection tests for the structured Tool Agent."""

from __future__ import annotations

import pytest

from core.tool_agent import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    ToolAgentRuntime,
    ToolCallAction,
    build_readonly_tool_registry,
)
from core.tool_agent.runtime_models import EngineeringEvidence


class FakeRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


class ScriptedProvider:
    def __init__(self, actions):
        self._actions = list(actions)
        self._calls = 0

    def decide(self, registry, user_query, *, context=()):
        action = self._actions[min(self._calls, len(self._actions) - 1)]
        self._calls += 1
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def _runtime(repo, actions):
    return ToolAgentRuntime(
        registry=build_readonly_tool_registry(repo, FakeRetrievalPort()),
        provider=ScriptedProvider(actions),
    )


def test_repeated_context_window_is_deduplicated(tmp_path):
    repo = tmp_path / "demo_project"
    repo.mkdir()
    (repo / "README.md").write_text("Configuration note\n", encoding="utf-8")
    result = _runtime(repo, [
        ToolCallAction(
            action="tool_call",
            tool_name="read_project_context",
            arguments={"path": "README.md", "line": 1, "context_lines": 0},
        ),
        ToolCallAction(
            action="tool_call",
            tool_name="read_project_context",
            arguments={"path": "README.md", "line": 1, "context_lines": 1},
        ),
        FinalAnswerAction(action="final_answer", answer="Configuration note found."),
    ]).run("Read the project note")

    assert result.status == "completed"
    assert result.tool_calls_used == 2
    assert [item.to_dict() for item in result.evidence] == [
        {
            "evidence_id": "E1",
            "kind": "project_doc",
            "path": "README.md",
            "start_line": 1,
            "end_line": 1,
            "snippet": "Configuration note",
        }
    ]


@pytest.mark.parametrize("path", ["../outside.py", "/outside.py", "C:/outside.py"])
def test_evidence_model_rejects_non_relative_paths(path):
    with pytest.raises(ValueError):
        EngineeringEvidence(
            evidence_id="E1",
            kind="project_code",
            path=path,
            start_line=1,
            end_line=1,
            snippet="pass",
        )
