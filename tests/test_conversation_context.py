"""G8 bounded recent context and standalone-query resolver contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from core.agent_runtime import AgentRuntime
from core.conversation_context import (
    CONTEXT_RESOLUTION_FALLBACK,
    ContextMessage,
    OpenAICompatibleConversationQueryResolver,
    RecentContextWindow,
)
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan
from core.agent_runtime.models import Document


class _FakeCompletions:
    def __init__(self, content=None, error=None):
        self.calls = []
        self.content = content
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class _FakeClient:
    def __init__(self, content=None, error=None):
        self.completions = _FakeCompletions(content, error)
        self.chat = SimpleNamespace(completions=self.completions)


def _message(content: str, role: str = "user") -> dict:
    return {"role": role, "content": content}


def test_recent_window_keeps_newest_six_and_order():
    result = RecentContextWindow().prepare(
        [_message(str(i), "user" if i % 2 == 0 else "assistant") for i in range(8)]
    )
    assert [message.content for message in result.selected_messages] == [
        "2", "3", "4", "5", "6", "7"
    ]
    assert result.received_count == 8
    assert result.used_count == 6
    assert result.truncated is True


def test_recent_window_truncates_one_oversized_message_to_budget():
    result = RecentContextWindow(token_budget=1).prepare([_message("abcdefghijk")])
    assert result.used_tokens <= 1
    assert result.selected_messages[0].content
    assert "abcdefghijk".endswith(result.selected_messages[0].content)
    assert result.truncated is True


def test_recent_window_evicts_oldest_suffix_when_budget_is_full():
    result = RecentContextWindow(token_budget=1).prepare(
        [_message("one"), _message("two"), _message("three")]
    )
    assert len(result.selected_messages) == 1
    assert "three".endswith(result.selected_messages[0].content)
    assert result.used_tokens <= 1
    assert result.truncated is True


def test_resolver_no_history_does_not_call_provider():
    client = _FakeClient(json.dumps({"standalone_query": "unused"}))
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="key", client=client
    )
    result = resolver.resolve((), "当前问题")
    assert result.standalone_query == "当前问题"
    assert result.resolver_used is False
    assert client.completions.calls == []


def test_resolver_returns_structured_standalone_query_and_bounded_call():
    client = _FakeClient(json.dumps({"standalone_query": "完整追问"}))
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="key", client=client
    )
    result = resolver.resolve((ContextMessage("user", "旧问题"),), "它怎么实现？")
    assert result.standalone_query == "完整追问"
    assert result.resolver_used is True
    assert len(client.completions.calls) == 1
    call = client.completions.calls[0]
    assert call["temperature"] == 0
    assert call["max_tokens"] == 160
    assert json.loads(call["messages"][1]["content"])["current_question"] == "它怎么实现？"


def test_resolver_preserves_a_new_topic_from_current_question():
    client = _FakeClient(json.dumps({"standalone_query": "全新的检索主题"}))
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="key", client=client
    )
    result = resolver.resolve((ContextMessage("user", "旧主题"),), "换个全新的主题")
    assert result.standalone_query == "全新的检索主题"


def test_resolver_failure_falls_back_without_exposing_error():
    client = _FakeClient(
        error=APIConnectionError(request=httpx.Request("POST", "https://x"))
    )
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="secret-key", client=client
    )
    result = resolver.resolve((ContextMessage("user", "旧问题"),), "新主题")
    assert result.standalone_query == "新主题"
    assert result.fallback is True
    assert CONTEXT_RESOLUTION_FALLBACK == "CONTEXT_RESOLUTION_FALLBACK"


@pytest.mark.parametrize(
    "content",
    [
        42,
        "not-json",
        "{}",
        '{"standalone_query": 42}',
        '{"standalone_query": "ok", "extra": true}',
    ],
)
def test_resolver_expected_response_failures_fallback(content):
    client = _FakeClient(content)
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="key", client=client
    )
    result = resolver.resolve((ContextMessage("user", "旧问题"),), "当前问题")
    assert result.standalone_query == "当前问题"
    assert result.resolver_used is True
    assert result.fallback is True


def test_resolver_unknown_programming_error_propagates():
    client = _FakeClient(error=RuntimeError("programming bug"))
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="secret-key", client=client
    )
    with pytest.raises(RuntimeError, match="programming bug"):
        resolver.resolve((ContextMessage("user", "旧问题"),), "当前问题")


@pytest.mark.parametrize(
    "error",
    [
        APIConnectionError(request=httpx.Request("POST", "https://x")),
        APITimeoutError(request=httpx.Request("POST", "https://x")),
        AuthenticationError(
            "unauthorized",
            response=httpx.Response(401, request=httpx.Request("POST", "https://x")),
            body=None,
        ),
        RateLimitError(
            "rate limited",
            response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
            body=None,
        ),
        APIStatusError(
            "server",
            response=httpx.Response(500, request=httpx.Request("POST", "https://x")),
            body=None,
        ),
    ],
)
def test_resolver_known_provider_errors_fallback(error):
    client = _FakeClient(error=error)
    resolver = OpenAICompatibleConversationQueryResolver(
        provider="fake", model="model", api_key="key", client=client
    )
    result = resolver.resolve((ContextMessage("user", "旧问题"),), "当前问题")
    assert result.standalone_query == "当前问题"
    assert result.resolver_used is True
    assert result.fallback is True


class _Planner(BaseQueryPlanner):
    def __init__(self):
        self.queries = []

    def plan(self, original_query):
        self.queries.append(original_query)
        plan = QueryPlan.create(
            retrieval_required=True,
            action="single_retrieval",
            reason_code="SIMPLE_FACT",
            original_query=original_query,
            query_type="fact",
        )
        return PlannerOutcome(plan, False, None)


class _Resolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve(self, history, question):
        self.calls.append((history, question))
        return self.result


class _Retriever:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        self.query = query
        return (Document("c1", "d1", "a.md", "evidence", 1.0, 1),)


class _Answer:
    def answer(self, question, evidence_bundle, mode):
        self.question = question
        return "answer"


def test_runtime_uses_resolved_query_for_planner_retrieval_and_answer():
    planner = _Planner()
    retriever = _Retriever()
    answer = _Answer()
    resolver = _Resolver(
        type("Resolution", (), {
            "standalone_query": "独立问题",
            "resolver_used": True,
            "fallback": False,
        })()
    )
    runtime = AgentRuntime(
        planner=planner,
        retrieval_port=retriever,
        answer_port=answer,
        query_resolver=resolver,
    )
    result = runtime.run("它怎么实现？", history=(_message("旧问题"),))
    assert result.status == "completed"
    assert planner.queries == ["独立问题"]
    assert retriever.query == "独立问题"
    assert answer.question == "独立问题"
    assert result.warnings == ()


def test_runtime_resolver_failure_is_safe_warning_and_current_question():
    planner = _Planner()
    retriever = _Retriever()
    answer = _Answer()
    resolver = _Resolver(
        type("Resolution", (), {
            "standalone_query": "当前问题",
            "resolver_used": True,
            "fallback": True,
        })()
    )
    runtime = AgentRuntime(
        planner=planner,
        retrieval_port=retriever,
        answer_port=answer,
        query_resolver=resolver,
    )
    result = runtime.run("当前问题", history=(_message("旧问题"),))
    assert result.status == "completed"
    assert planner.queries == ["当前问题"]
    assert result.warnings == (CONTEXT_RESOLUTION_FALLBACK,)
    trace_text = json.dumps([event.to_dict() for event in result.trace], ensure_ascii=False)
    assert "旧问题" not in trace_text
    assert "当前问题" not in trace_text
