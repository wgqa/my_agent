"""ARCH-CUTOVER-07 architecture and main-chain contract assertions."""

from __future__ import annotations

import json
import inspect

from fastapi.testclient import TestClient
import pytest

import api.app
from api.schemas import EngineeringQueryRequest
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent.runtime_models import AgentDecisionProvider
from core.tool_agent.runtime_models import ToolAgentRunResult
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)
from tests._engineering_runtime_support import build_full_unified_runtime


client = TestClient(api.app.app)


def _completed_result(answer: str = "same unified answer") -> ToolAgentRunResult:
    return ToolAgentRunResult(
        status="completed",
        answer=answer,
        reason_code=None,
        failure_code=None,
        iterations_used=1,
        tool_calls_used=0,
        tool_errors_used=0,
        trace=(),
        evidence=(),
    )


def _sse_payloads(response):
    payloads = []
    for frame in response.text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data: "):
                payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


def test_unified_runtime_requires_full_assembly_and_has_no_compatibility_bypass():
    signature = inspect.signature(UnifiedEngineeringRuntime)
    for name in (
        "context_resolver",
        "evidence_planner",
        "retrieval_component",
        "evidence_verifier",
    ):
        assert signature.parameters[name].default is inspect.Parameter.empty

    source = inspect.getsource(UnifiedEngineeringRuntime)
    assert "_CompatibilityFallbackPlanner" not in source
    assert "_default_evidence_planner" not in source
    assert "retrieval_component is None" not in source


def test_full_assembly_has_one_facade_and_one_execution_adapter():
    from core.tool_agent.registry import ToolRegistry
    from core.tool_agent.runtime import ToolAgentRuntime

    class NoopProvider(AgentDecisionProvider):
        def decide(self, registry, user_query, *, context=(), control_state=None):
            raise AssertionError("architecture test must not execute the provider")

    runtime = ToolAgentRuntime(registry=ToolRegistry(), provider=NoopProvider())
    unified = build_full_unified_runtime(runtime)
    facade = EngineeringAgentFacade(unified)

    assert isinstance(unified._execution_adapter, LegacyToolAgentExecutionAdapter)
    assert facade._runtime is unified
    assert unified._execution_adapter._runtime is runtime
    assert not hasattr(unified, "_budget")
    assert not hasattr(unified, "_controller")

    with pytest.raises(TypeError):
        UnifiedEngineeringRuntime(runtime)


def test_three_engineering_entries_share_facade_and_observers_only(monkeypatch):
    calls = []

    class RecordingFacade:
        def run(
            self,
            question,
            *,
            conversation_context=None,
            trace_sink=None,
            activity_sink=None,
        ):
            calls.append(
                (question, conversation_context, trace_sink is not None, activity_sink is not None)
            )
            return _completed_result()

    facade = RecordingFacade()
    monkeypatch.setattr(api.app, "engineering_agent_facade", facade)

    request = EngineeringQueryRequest(question="same business request")
    sync_result = api.app.engineering_query(request)
    v1_result = api.app.engineering_query_stream(request)
    v2_result = api.app.engineering_query_stream_v2(request)

    assert sync_result.answer == "same unified answer"
    assert v1_result.media_type == "text/event-stream"
    assert v2_result.media_type == "text/event-stream"
    assert calls == [
        ("same business request", None, False, False),
        ("same business request", None, True, False),
        ("same business request", None, False, True),
    ]

    # Each transport selects one observer sink; neither stream creates a
    # second business-runtime invocation or a second control loop.
    assert v1_result.body_iterator is not None
    assert v2_result.body_iterator is not None


def test_sync_stream_v1_and_stream_v2_have_same_business_result(monkeypatch):
    class ParityFacade:
        def run(self, question, *, conversation_context=None, trace_sink=None, activity_sink=None):
            return _completed_result("parity answer")

    monkeypatch.setattr(api.app, "engineering_agent_facade", ParityFacade())

    sync = client.post("/engineering/query", json={"question": "parity"})
    v1 = client.post("/engineering/query/stream", json={"question": "parity"})
    v2 = client.post("/engineering/query/stream/v2", json={"question": "parity"})

    assert sync.status_code == v1.status_code == v2.status_code == 200
    sync_payload = sync.json()
    v1_final = next(item["result"] for item in _sse_payloads(v1) if item["type"] == "final")
    v2_final = next(item["result"] for item in _sse_payloads(v2) if item["type"] == "final")
    assert sync_payload == v1_final == v2_final


def test_knowledge_status_is_identity_only_and_runtime_selector_is_not_public(
    monkeypatch,
):
    class ExplodingFacade:
        def run(self, *args, **kwargs):
            raise AssertionError("knowledge status must not execute the Agent")

    monkeypatch.setattr(api.app, "engineering_agent_facade", ExplodingFacade())
    monkeypatch.setattr(api.app, "engineering_knowledge_backend", None)

    status = client.get("/engineering/knowledge")
    selector = client.post(
        "/engineering/query",
        json={"question": "q", "runtime": "tool-agent"},
    )

    assert status.status_code == 200
    assert status.json()["schema_version"] == "engineering_knowledge_status_v1"
    assert selector.status_code == 422
