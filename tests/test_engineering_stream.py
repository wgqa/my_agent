"""Deterministic safety tests for guarded Engineering SSE presentation."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import api.app
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_requirements import CHANGE_TEST_V1, EngineeringEvidenceRequirement
from core.tool_agent.actions import (
    ACTION_TIMEOUT,
    AgentDecisionOutcome,
    FinalAnswerAction,
    ToolCallAction,
)
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    EngineeringEvidence,
    INSUFFICIENT_EVIDENCE_TO_FINALIZE,
    RuntimeTraceEvent,
    ToolAgentRunResult,
)
from core.tool_agent.tools.git_change import GIT_DIFF_SPEC
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC


client = TestClient(api.app.app)


class _StaticHandler:
    def __init__(self, payload):
        self.payload = payload

    def execute(self, _arguments):
        return self.payload


class _ScriptedProvider:
    def __init__(self, actions):
        self._actions = list(actions)
        self._calls = 0

    def decide(self, _registry, _question, *, context=(), control_state=None):
        action = self._actions[min(self._calls, len(self._actions) - 1)]
        self._calls += 1
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=None,
        )


def _stream_events(response):
    events = []
    for frame in response.text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


def _completed_result(answer="APPROVED"):
    return ToolAgentRunResult(
        status="completed",
        answer=answer,
        reason_code=None,
        failure_code=None,
        iterations_used=1,
        tool_calls_used=0,
        tool_errors_used=0,
        trace=(
            RuntimeTraceEvent(
                iteration=1,
                event_type="decision_completed",
                action_type="final_answer",
                iterations_used=1,
                tool_calls_used=0,
                tool_errors_used=0,
            ),
            RuntimeTraceEvent(
                iteration=1,
                event_type="runtime_stopped",
                iterations_used=1,
                tool_calls_used=0,
                tool_errors_used=0,
            ),
        ),
        evidence=(
            EngineeringEvidence(
                evidence_id="E1",
                kind="project_code",
                path="src/service.py",
                start_line=1,
                end_line=1,
                snippet="return approved",
            ),
        ),
    )


class _Facade:
    def __init__(self, result=None, events=(), error=None):
        self.result = result
        self.events = tuple(events)
        self.error = error
        self.calls = []

    def run(self, question, *, trace_sink=None):
        self.calls.append(question)
        for event in self.events:
            if trace_sink is not None:
                trace_sink(event)
        if self.error is not None:
            raise self.error
        return self.result


def _install_facade(monkeypatch, facade):
    monkeypatch.setattr(api.app, "engineering_agent_facade", facade)


def _post_stream(question="Trace the config", **extra):
    body = {"question": question}
    body.update(extra)
    return client.post("/engineering/query/stream", json=body)


def test_stream_content_type_and_question_only_contract(monkeypatch):
    facade = _Facade(_completed_result())
    _install_facade(monkeypatch, facade)

    response = _post_stream("Trace this config")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-engineering-stream-schema"] == "engineering_query_stream_v1"
    assert facade.calls == ["Trace this config"]
    for extra in (
        {"history": []},
        {"top_k": 5},
        {"provider": "deepseek"},
        {"model": "other"},
        {"budget": 99},
        {"task_family": "diagnosis"},
        {"Gold": "leak"},
        {"required_evidence_groups": [["project_code"]]},
    ):
        assert _post_stream(**extra).status_code == 422


def test_existing_engineering_query_contract_is_unchanged(monkeypatch):
    facade = _Facade(_completed_result("Existing response"))
    _install_facade(monkeypatch, facade)

    response = client.post("/engineering/query", json={"question": "Existing path"})

    assert response.status_code == 200
    assert response.json()["schema_version"] == "engineering_query_response_v1"
    assert response.json()["answer"] == "Existing response"
    assert facade.calls == ["Existing path"]


def test_guard_blocked_answer_never_enters_sse_and_approved_answer_streams(monkeypatch):
    registry = ToolRegistry()
    registry.register(
        GIT_DIFF_SPEC,
        _StaticHandler(
            {
                "path": "src/service.py",
                "mode": "working_tree",
                "truncated": False,
                "diff": "@@\n-old\n+new",
                "start_line": 1,
                "end_line": 1,
            }
        ),
    )
    registry.register(
        READ_PROJECT_CONTEXT_SPEC,
        _StaticHandler(
            {
                "path": "tests/test_service.py",
                "start_line": 1,
                "end_line": 1,
                "lines": [{"line": 1, "text": "def test_service(): pass"}],
            }
        ),
    )
    runtime = ToolAgentRuntime(
        registry=registry,
        provider=_ScriptedProvider(
            [
                ToolCallAction(
                    action="tool_call",
                    tool_name="git_diff",
                    arguments={"mode": "working_tree", "path": "src/service.py"},
                ),
                FinalAnswerAction("final_answer", "DO_NOT_LEAK"),
                ToolCallAction(
                    action="tool_call",
                    tool_name="read_project_context",
                    arguments={
                        "path": "tests/test_service.py",
                        "line": 1,
                        "context_lines": 0,
                    },
                ),
                FinalAnswerAction("final_answer", "APPROVED grounded answer"),
            ]
        ),
    )
    facade = EngineeringAgentFacade(runtime)
    requirement = EngineeringEvidenceRequirement(
        requirement_profile=CHANGE_TEST_V1,
        required_evidence_groups=(("project_change",), ("project_test",)),
        min_distinct_project_code_paths=0,
    )
    monkeypatch.setattr(
        "core.engineering_agent.route_engineering_evidence_requirement",
        lambda _question: requirement,
    )
    _install_facade(monkeypatch, facade)

    response = _post_stream("commit regression test impact")
    events = _stream_events(response)

    assert response.status_code == 200
    assert "DO_NOT_LEAK" not in response.text
    assert any(
        event == {
            "type": "status",
            "stage": "verification",
            "state": "blocked",
            "iteration": 2,
        }
        for event in events
    )
    started = [
        event for event in events
        if event["type"] == "status" and event["stage"] == "tool" and event["state"] == "started"
    ]
    completed = [
        event for event in events
        if event["type"] == "status" and event["stage"] == "tool" and event["state"] == "completed"
    ]
    assert [event["tool_name"] for event in started] == [
        "git_diff",
        "read_project_context",
    ]
    assert [event["tool_name"] for event in completed] == [
        "git_diff",
        "read_project_context",
    ]
    assert all(
        events.index(started[index]) < events.index(completed[index])
        for index in range(len(started))
    )
    deltas = [event["delta"] for event in events if event["type"] == "answer_delta"]
    final = next(event for event in events if event["type"] == "final")
    assert "".join(deltas) == final["result"]["answer"] == "APPROVED grounded answer"
    assert all(1 <= len(delta) <= 16 for delta in deltas)
    assert events[-1] == {"type": "done"}
    assert events.index(final) == len(events) - 2


def test_refused_and_failed_never_emit_answer_deltas(monkeypatch):
    refused = ToolAgentRunResult(
        status="refused",
        answer=None,
        reason_code=INSUFFICIENT_EVIDENCE_TO_FINALIZE,
        failure_code=None,
        iterations_used=1,
        tool_calls_used=0,
        tool_errors_used=0,
        trace=(),
    )
    _install_facade(monkeypatch, _Facade(refused))
    refused_events = _stream_events(_post_stream())
    assert all(event["type"] not in {"answer_start", "answer_delta"} for event in refused_events)
    assert refused_events[-1] == {"type": "done"}

    failed = ToolAgentRunResult(
        status="failed",
        answer=None,
        reason_code=None,
        failure_code=ACTION_TIMEOUT,
        iterations_used=1,
        tool_calls_used=0,
        tool_errors_used=0,
        trace=(),
    )
    _install_facade(monkeypatch, _Facade(failed))
    failed_events = _stream_events(_post_stream())
    assert all(event["type"] not in {"answer_start", "answer_delta"} for event in failed_events)
    assert failed_events[-1] == {"type": "done"}


def test_unknown_worker_error_is_redacted_and_runtime_unavailable_is_503(monkeypatch):
    _install_facade(
        monkeypatch,
        _Facade(error=RuntimeError(r"api_key=secret C:\private\traceback")),
    )
    response = _post_stream()

    assert response.status_code == 200
    assert _stream_events(response) == [
        {"type": "status", "stage": "analysis", "state": "started"},
        {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"},
        {"type": "done"},
    ]
    for forbidden in ("api_key", "secret", "private", "traceback", "C:\\"):
        assert forbidden.lower() not in response.text.lower()

    monkeypatch.setattr(api.app, "engineering_agent_facade", None)
    assert _post_stream().status_code == 503


def test_stream_events_expose_only_product_safe_shapes(monkeypatch):
    trace = RuntimeTraceEvent(
        iteration=1,
        event_type="tool_call_created",
        action_type="tool_call",
        tool_name="code_search",
        call_id="call-safe",
        iterations_used=1,
        tool_calls_used=0,
        tool_errors_used=0,
    )
    _install_facade(monkeypatch, _Facade(_completed_result(), events=(trace,)))
    response = _post_stream()
    events = _stream_events(response)

    assert {event["type"] for event in events} == {
        "status", "evidence", "answer_start", "answer_delta", "final", "done"
    }
    status = [event for event in events if event["type"] == "status"][-1]
    assert status == {
        "type": "status",
        "stage": "tool",
        "state": "started",
        "tool_name": "code_search",
        "iteration": 1,
    }
    for forbidden in ("prompt", "cot", "raw_response", "api_key", "absolute_path"):
        assert forbidden not in response.text.lower()
