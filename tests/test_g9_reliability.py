"""G9 reliability demonstrations for generator failure semantics."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

import api.app
from core.agent_runtime import AgentRuntime, Document, EvidenceBundle
from core.generator.deepseek_gen import DeepSeekGenerator
from core.generator.errors import (
    GeneratorAuthenticationError,
    GeneratorResponseError,
    GeneratorTimeoutError,
    GeneratorUnavailableError,
)
from core.generator.openai_gen import OpenAIGenerator
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan


SECRET_MARKERS = (
    "secret-key",
    "C:\\Users\\private\\",
    "https://internal.example",
    "raw provider text",
)


class _Response:
    def __init__(self, content):
        self.choices = [
            SimpleNamespace(message=SimpleNamespace(content=content))
        ]


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://internal.example/chat")


def _status_error(error_type, status_code: int):
    response = httpx.Response(status_code, request=_request())
    return error_type(
        "raw provider text secret-key C:\\Users\\private\\",
        response=response,
        body={"detail": "raw provider text"},
    )


def _connection_error():
    return APIConnectionError(
        message="raw provider text secret-key",
        request=_request(),
    )


def _deepseek_generator(max_retries: int = 1) -> DeepSeekGenerator:
    return DeepSeekGenerator(api_key="secret-key", max_retries=max_retries)


def _openai_generator() -> OpenAIGenerator:
    return OpenAIGenerator(api_key="secret-key")


def test_deepseek_auth_is_typed_and_not_retried():
    generator = _deepseek_generator()
    generator.client.chat.completions.create = MagicMock(
        side_effect=_status_error(AuthenticationError, 401)
    )

    with pytest.raises(GeneratorAuthenticationError) as exc_info:
        generator.generate("q", [])

    assert generator.client.chat.completions.create.call_count == 1
    assert str(exc_info.value) == "GENERATOR_AUTHENTICATION_ERROR"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (APITimeoutError("timeout"), GeneratorTimeoutError),
        (_status_error(RateLimitError, 429), GeneratorUnavailableError),
        (_status_error(APIStatusError, 429), GeneratorUnavailableError),
        (_status_error(APIStatusError, 503), GeneratorUnavailableError),
    ],
)
def test_deepseek_retryable_failures_keep_existing_retry_count(
    monkeypatch, failure, expected
):
    generator = _deepseek_generator(max_retries=1)
    create = MagicMock(side_effect=failure)
    generator.client.chat.completions.create = create
    sleeps = []
    monkeypatch.setattr(
        "core.generator.deepseek_gen.time.sleep", sleeps.append
    )

    with pytest.raises(expected):
        generator.generate("q", [])

    assert create.call_count == 2
    assert len(sleeps) == 1


def test_deepseek_connection_is_unavailable_without_retry():
    generator = _deepseek_generator(max_retries=2)
    create = MagicMock(side_effect=_connection_error())
    generator.client.chat.completions.create = create

    with pytest.raises(GeneratorUnavailableError):
        generator.generate("q", [])

    assert create.call_count == 1


@pytest.mark.parametrize(
    "response",
    [
        object(),
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace(message=None)]),
        _Response(None),
        _Response("   "),
    ],
)
def test_deepseek_invalid_response_is_typed(response):
    generator = _deepseek_generator(max_retries=0)
    generator.client.chat.completions.create = MagicMock(return_value=response)

    with pytest.raises(GeneratorResponseError):
        generator.generate("q", [])


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (_status_error(AuthenticationError, 401), GeneratorAuthenticationError),
        (APITimeoutError("timeout"), GeneratorTimeoutError),
        (_connection_error(), GeneratorUnavailableError),
        (_status_error(RateLimitError, 429), GeneratorUnavailableError),
        (_status_error(APIStatusError, 503), GeneratorUnavailableError),
    ],
)
def test_openai_known_failures_use_common_error_types(failure, expected):
    generator = _openai_generator()
    generator.client.chat.completions.create = MagicMock(side_effect=failure)

    with pytest.raises(expected):
        generator.generate("q", [])


@pytest.mark.parametrize(
    "response",
    [object(), SimpleNamespace(choices=[]), _Response(None), _Response(" ")],
)
def test_openai_invalid_response_is_typed(response):
    generator = _openai_generator()
    generator.client.chat.completions.create = MagicMock(return_value=response)

    with pytest.raises(GeneratorResponseError):
        generator.generate("q", [])


@pytest.mark.parametrize("generator_factory", [_deepseek_generator, _openai_generator])
def test_unknown_programming_error_is_not_reclassified(generator_factory):
    generator = generator_factory()
    generator.client.chat.completions.create = MagicMock(
        side_effect=RuntimeError("secret programming bug")
    )

    with pytest.raises(RuntimeError, match="secret programming bug"):
        generator.generate("q", [])


def test_typed_errors_are_secret_free():
    errors = [
        GeneratorAuthenticationError(),
        GeneratorTimeoutError(),
        GeneratorUnavailableError(),
        GeneratorResponseError(),
    ]

    for error in errors:
        assert all(marker not in str(error) for marker in SECRET_MARKERS)
        assert all(marker not in repr(error) for marker in SECRET_MARKERS)
        assert str(error) == error.code


class _Planner(BaseQueryPlanner):
    def plan(self, question: str) -> PlannerOutcome:
        return PlannerOutcome(
            plan=QueryPlan.create(
                original_query=question,
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
                subqueries=(),
            ),
            fallback_used=False,
            failure_code=None,
        )


class _Retriever:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return [
            Document(
                chunk_id="c1",
                document_id="d1",
                source_name="public.md",
                content="evidence",
                score=0.9,
                rank=1,
            )
        ]


class _AnswerPort:
    def __init__(self, failure):
        self.failure = failure

    def answer(self, question, evidence_bundle: EvidenceBundle, mode: str):
        raise self.failure


def test_agentic_grounded_timeout_is_structured_and_trace_safe():
    runtime = AgentRuntime(
        planner=_Planner(),
        retrieval_port=_Retriever(),
        answer_port=_AnswerPort(GeneratorTimeoutError()),
    )

    result = runtime.run("q")
    trace = json.dumps([event.to_dict() for event in result.trace])

    assert result.status == "failed"
    assert result.error_code == "GENERATION_FAILED"
    assert result.answer is None
    assert "GENERATION_FAILED" in trace
    assert "GeneratorTimeoutError" not in trace
    assert all(marker not in trace for marker in SECRET_MARKERS)


def test_agentic_unknown_generator_error_does_not_leak_message():
    runtime = AgentRuntime(
        planner=_Planner(),
        retrieval_port=_Retriever(),
        answer_port=_AnswerPort(
            RuntimeError(
                "secret-key C:\\Users\\private\\ "
                "https://internal.example raw provider text"
            )
        ),
    )

    result = runtime.run("q")
    trace = json.dumps([event.to_dict() for event in result.trace])
    result_blob = json.dumps(result.to_dict(), ensure_ascii=False)

    assert result.status == "failed"
    assert result.error_code == "GENERATION_FAILED"
    assert result.answer is None
    assert "GENERATION_FAILED" in trace
    assert all(marker not in trace for marker in SECRET_MARKERS)
    assert all(marker not in result_blob for marker in SECRET_MARKERS)


def test_basic_query_timeout_returns_generic_http_500():
    pipeline = MagicMock()
    pipeline.query.side_effect = GeneratorTimeoutError()
    pipeline.config = SimpleNamespace(generator_provider="deepseek")

    with patch("api.app.Pipeline", return_value=pipeline):
        with TestClient(api.app.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/query", json={"question": "q", "top_k": 1}
            )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal query error"}
    assert all(marker not in response.text for marker in SECRET_MARKERS)
