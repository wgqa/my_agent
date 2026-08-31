"""Deterministic rich SSE tests. No API server, provider, or network is used."""

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
from core.tool_agent.activity import (
    EvidenceAddedActivity,
    RunStartedActivity,
    ToolActivityEvent,
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
from tests._engineering_runtime_support import build_full_unified_runtime


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


class _Facade:
    def __init__(self, result, events=(), error=None):
        self.result = result
        self.events = tuple(events)
        self.error = error
        self.calls = []

    def run(self, question, *, conversation_context=None, activity_sink=None):
        self.calls.append(question)
        for event in self.events:
            if activity_sink is not None:
                activity_sink(event)
        if self.error is not None:
            raise self.error
        return self.result


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
                snippet="public source evidence",
            ),
        ),
    )


def _install_facade(monkeypatch, facade):
    monkeypatch.setattr(api.app, "engineering_agent_facade", facade)


def _post_stream_v2(question="Trace the config", **extra):
    body = {"question": question}
    body.update(extra)
    return client.post("/engineering/query/stream/v2", json=body)


def test_v2_schema_and_question_only_request_contract(monkeypatch):
    facade = _Facade(
        _completed_result(),
        events=(
            RunStartedActivity(available_tool_count=7),
            ToolActivityEvent(
                activity_id="A1",
                iteration=1,
                tool_name="code_search",
                state="started",
                purpose="Locate source",
                target={"query": "runtime"},
            ),
        ),
    )
    _install_facade(monkeypatch, facade)

    response = _post_stream_v2("Trace this config")
    events = _stream_events(response)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-engineering-stream-schema"] == "engineering_query_stream_v2"
    assert facade.calls == ["Trace this config"]
    assert events[0] == {
        "type": "run_started",
        "execution_model": "single_agent",
        "available_tool_count": 7,
    }
    assert events[1]["type"] == "activity"
    assert events[-1] == {"type": "done"}
    for extra in (
        {"history": []},
        {"task_family": "diagnosis"},
        {"required_evidence_groups": [["project_code"]]},
        {"Gold": "leak"},
    ):
        assert _post_stream_v2(**extra).status_code == 422


def test_v2_uses_real_tool_lifecycle_evidence_and_guard_events(monkeypatch):
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
    requirement = EngineeringEvidenceRequirement(
        requirement_profile=CHANGE_TEST_V1,
        required_evidence_groups=(("project_change",), ("project_test",)),
        min_distinct_project_code_paths=0,
    )
    monkeypatch.setattr(
        "core.unified_engineering_runtime.route_engineering_evidence_requirement",
        lambda _question: requirement,
    )
    _install_facade(
        monkeypatch,
        EngineeringAgentFacade(
            build_full_unified_runtime(runtime)
        ),
    )

    response = _post_stream_v2("commit regression test impact")
    events = _stream_events(response)
    activities = [event for event in events if event["type"] == "activity"]
    evidence_events = [event for event in events if event["type"] == "evidence_added"]

    assert response.status_code == 200
    assert "DO_NOT_LEAK" not in response.text
    assert [event["tool_name"] for event in activities if event["state"] == "started"] == [
        "git_diff",
        "read_project_context",
    ]
    completed = [event for event in activities if event["state"] == "completed"]
    assert [event["activity_id"] for event in completed] == ["A1", "A2"]
    assert [event["evidence_ids_added"] for event in completed] == [["E1"], ["E2"]]
    assert [(event["evidence_id"], event["kind"]) for event in evidence_events] == [
        ("E1", "project_change"),
        ("E2", "project_test"),
    ]
    assert all(events.index(evidence_events[index]) < events.index(completed[index]) for index in range(2))
    assert {
        "type": "verification",
        "state": "blocked",
        "iteration": 2,
        "missing_evidence_kinds": ["project_test"],
    } in events
    deltas = [event["delta"] for event in events if event["type"] == "answer_delta"]
    final = next(event for event in events if event["type"] == "final")
    assert "".join(deltas) == final["result"]["answer"] == "APPROVED grounded answer"
    assert events[-1] == {"type": "done"}
    for forbidden in ("prompt", "raw", "api_key", r"C:\\", "chain_of_thought"):
        assert forbidden.lower() not in response.text.lower()


def test_v2_refused_and_failed_results_never_emit_answer_chunks(monkeypatch):
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
    _install_facade(monkeypatch, _Facade(refused, events=(RunStartedActivity(7),)))
    refused_events = _stream_events(_post_stream_v2())
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
    _install_facade(monkeypatch, _Facade(failed, events=(RunStartedActivity(7),)))
    failed_events = _stream_events(_post_stream_v2())
    assert all(event["type"] not in {"answer_start", "answer_delta"} for event in failed_events)
    assert failed_events[-1] == {"type": "done"}


def test_v2_worker_errors_are_generic_and_do_not_leak_worker_details(monkeypatch):
    _install_facade(
        monkeypatch,
        _Facade(
            _completed_result(),
            error=RuntimeError(r"api_key=secret C:\private\traceback raw provider response"),
        ),
    )

    response = _post_stream_v2()

    assert response.status_code == 200
    assert _stream_events(response) == [
        {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"},
        {"type": "done"},
    ]
    for forbidden in ("api_key", "secret", "private", "traceback", "raw", r"C:\\"):
        assert forbidden.lower() not in response.text.lower()
