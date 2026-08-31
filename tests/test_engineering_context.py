"""ARCH-CONTEXT-03 contracts for the Unified Engineering context component."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError

import api.app
import core.unified_engineering_runtime as unified_runtime_module
from core.conversation_context import (
    ContextMessage,
    ConversationQueryResolution,
    OpenAICompatibleConversationQueryResolver,
)
from core.engineering_context import EngineeringContextResolver
from core.engineering_requirements import route_engineering_evidence_requirement
from core.tool_agent import AgentDecisionOutcome, FinalAnswerAction, ToolAgentRuntime
from core.tool_agent.activity import ActivityEvent
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)


class _RecordingResolver:
    def __init__(self, resolution: ConversationQueryResolution):
        self.resolution = resolution
        self.calls = []

    def resolve(self, history, question):
        self.calls.append((history, question))
        return self.resolution


class _RaisingResolver:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def resolve(self, _history, _question):
        self.calls += 1
        raise self.error


class _Provider:
    def __init__(self):
        self.queries = []

    def decide(self, _registry, user_query, *, context=(), control_state=None):
        self.queries.append(user_query)
        return AgentDecisionOutcome(
            action=FinalAnswerAction("final_answer", "ok"),
            failure_code=None,
            call_metadata=None,
        )


def _tool_runtime(provider=None):
    provider = provider or _Provider()
    return ToolAgentRuntime(registry=ToolRegistry(), provider=provider), provider


def _unified(context_resolver, provider=None):
    runtime, provider = _tool_runtime(provider)
    return (
        UnifiedEngineeringRuntime(
            LegacyToolAgentExecutionAdapter(runtime),
            context_resolver=context_resolver,
        ),
        provider,
    )


def _history(size=8):
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": str(index)}
        for index in range(size)
    ]


def test_context_snapshot_reuses_g8_bounded_window_and_hides_message_repr():
    query_resolver = _RecordingResolver(
        ConversationQueryResolution("standalone query", True, False)
    )
    snapshot = EngineeringContextResolver(query_resolver).resolve(
        "follow-up", _history()
    )

    assert [message.content for message in snapshot.selected_messages] == [
        "2", "3", "4", "5", "6", "7"
    ]
    assert snapshot.received_count == 8
    assert snapshot.used_count == 6
    assert snapshot.used_tokens > 0
    assert snapshot.truncated is True
    assert snapshot.resolved_input == "standalone query"
    assert snapshot.resolver_used is True
    assert snapshot.resolver_fallback is False
    assert "standalone query" in repr(snapshot)
    assert "7" not in repr(snapshot)
    assert len(query_resolver.calls) == 1


def test_none_tuple_and_list_history_are_legal_without_provider_calls():
    query_resolver = _RecordingResolver(
        ConversationQueryResolution("question", False, False)
    )
    resolver = EngineeringContextResolver(query_resolver)

    for history in (None, (), []):
        snapshot = resolver.resolve("question", history)
        assert snapshot.original_input == "question"
        assert snapshot.resolved_input == "question"
        assert snapshot.selected_messages == ()
        assert snapshot.received_count == 0
        assert snapshot.used_count == 0
        assert snapshot.used_tokens == 0
        assert snapshot.resolver_used is False
        assert snapshot.resolver_fallback is False

    assert query_resolver.calls == []


def test_resolved_input_drives_requirement_route_and_tool_agent_provider(monkeypatch):
    query_resolver = _RecordingResolver(
        ConversationQueryResolution("resolved engineering query", True, False)
    )
    unified, provider = _unified(EngineeringContextResolver(query_resolver))
    route_calls = []

    def route_once(question):
        route_calls.append(question)
        return route_engineering_evidence_requirement(question)

    monkeypatch.setattr(
        unified_runtime_module,
        "route_engineering_evidence_requirement",
        route_once,
    )

    result = unified.run("follow-up", conversation_context=_history(1))

    assert result.status == "completed"
    assert route_calls == ["resolved engineering query"]
    assert provider.queries == ["resolved engineering query"]
    assert query_resolver.calls[0][1] == "follow-up"


def test_context_resolver_is_called_exactly_once_and_expected_failure_falls_back():
    client = SimpleNamespace()

    class _Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            raise APIConnectionError(
                request=httpx.Request("POST", "https://resolver.invalid")
            )

    completions = _Completions()
    client.chat = SimpleNamespace(completions=completions)
    provider = _Provider()
    context_resolver = EngineeringContextResolver(
        OpenAICompatibleConversationQueryResolver(
            provider="deepseek",
            model="deepseek-chat",
            api_key="secret-key",
            client=client,
        )
    )
    unified, _ = _unified(context_resolver, provider)

    result = unified.run("original question", conversation_context=_history(1))
    snapshot = context_resolver.resolve("original question", _history(1))

    assert result.status == "completed"
    assert result.failure_code is None
    assert provider.queries == ["original question"]
    assert completions.calls == 2
    assert snapshot.resolved_input == "original question"
    assert snapshot.resolver_used is True
    assert snapshot.resolver_fallback is True


def test_programming_error_propagates_before_route_or_tool_execution():
    resolver = _RaisingResolver(RuntimeError("programming bug"))
    unified, provider = _unified(EngineeringContextResolver(resolver))

    with pytest.raises(RuntimeError, match="programming bug"):
        unified.run("question", conversation_context=_history(1))

    assert resolver.calls == 1
    assert provider.queries == []


def test_malformed_context_fails_fast_without_silent_drop_or_execution():
    resolver = _RecordingResolver(
        ConversationQueryResolution("resolved", True, False)
    )
    unified, provider = _unified(EngineeringContextResolver(resolver))

    with pytest.raises(ValueError, match="content must be non-empty"):
        unified.run(
            "question",
            conversation_context=[{"role": "user", "content": "   "}],
        )

    assert resolver.calls == []
    assert provider.queries == []


def test_context_content_never_enters_safe_trace_or_rich_activity():
    secret = "conversation-secret-do-not-log"
    resolver = _RecordingResolver(
        ConversationQueryResolution("resolved", True, False)
    )
    unified, _ = _unified(EngineeringContextResolver(resolver))
    trace = []
    activity: list[ActivityEvent] = []

    result = unified.run(
        "question",
        conversation_context=[{"role": "user", "content": secret}],
        trace_sink=trace.append,
        activity_sink=activity.append,
    )
    snapshot = EngineeringContextResolver(resolver).resolve(
        "question", [{"role": "user", "content": secret}]
    )
    serialized = json.dumps(
        [event.to_dict() for event in trace]
        + [event.to_dict() for event in activity]
        + [snapshot.__repr__()],
        ensure_ascii=False,
    )

    assert result.status == "completed"
    assert secret not in serialized


def test_public_engineering_request_remains_question_only_and_passes_none_context(
    monkeypatch,
):
    calls = []

    class _Facade:
        def run(self, question, *, conversation_context=None, **_kwargs):
            calls.append((question, conversation_context))
            return ToolAgentRunResult(
                status="completed",
                answer="ok",
                reason_code=None,
                failure_code=None,
                iterations_used=1,
                tool_calls_used=0,
                tool_errors_used=0,
                trace=(
                    RuntimeTraceEvent(
                        iteration=1,
                        event_type="runtime_stopped",
                        action_type=None,
                        iterations_used=1,
                        tool_calls_used=0,
                        tool_errors_used=0,
                    ),
                ),
                evidence=(),
            )

    monkeypatch.setattr(api.app, "engineering_agent_facade", _Facade())
    assert set(api.app.EngineeringQueryRequest.model_fields) == {"question"}
    response = TestClient(api.app.app).post(
        "/engineering/query", json={"question": "public question"}
    )

    assert response.status_code == 200
    assert calls == [("public question", None)]
    assert (
        TestClient(api.app.app)
        .post("/engineering/query", json={"question": "q", "history": []})
        .status_code
        == 422
    )
