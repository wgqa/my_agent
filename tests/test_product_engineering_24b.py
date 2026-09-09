"""PRODUCT-ENGINEERING-24B contracts: lifecycle + observability.

Covers safe execution metrics (aggregated from the existing call metadata),
the system-owned cooperative deadline, disconnect-driven cancellation, and
the process-local bounded admission limit. Agent intelligence behavior —
prompt, router, grounding, 5/4/2, persistence semantics — is unchanged.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import api.app
from api.app import _build_engineering_response
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_requirements import (
    NO_ADDITIONAL_REQUIREMENT,
    EngineeringEvidenceRequirement,
)
from core.tool_agent.actions import (
    AgentDecisionCallMetadata,
    AgentDecisionOutcome,
    FinalAnswerAction,
    ToolCallAction,
)
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    ENGINEERING_RUN_CANCELLED,
    ENGINEERING_RUN_DEADLINE_EXCEEDED,
    ToolAgentBudget,
    ToolAgentExecutionMetrics,
    ToolAgentRunResult,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
from tests._engineering_runtime_support import build_full_unified_runtime


class _MetadataProvider:
    """Scripted provider that reports provider usage like the real one."""

    def __init__(self, actions, *, input_tokens=100, output_tokens=50):
        self.actions = list(actions)
        self.calls = 0
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.calls += 1
        action = self.actions[min(self.calls - 1, len(self.actions) - 1)]
        is_repair_call = self.calls == 2
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=AgentDecisionCallMetadata(
                provider="deepseek",
                model="deepseek-chat",
                prompt_version="p",
                prompt_sha256="a" * 64,
                toolset_sha256="b" * 64,
                call_count=2 if is_repair_call else 1,
                input_tokens=None if is_repair_call else self.input_tokens,
                output_tokens=None if is_repair_call else self.output_tokens,
                latency_ms=12.0,
                repair_attempted=is_repair_call,
                repair_succeeded=is_repair_call,
            ),
        )


class _StaticReadHandler:
    def execute(self, arguments):
        return {
            "path": arguments["path"],
            "start_line": 1,
            "end_line": 1,
            "lines": [{"line": 1, "text": "synthetic implementation"}],
        }


def _registry():
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    registry.register(READ_PROJECT_CONTEXT_SPEC, _StaticReadHandler())
    return registry


class TestExecutionMetrics:
    def test_call_metadata_aggregates_into_public_metrics(self):
        provider = _MetadataProvider(
            [
                FinalAnswerAction("final_answer", "done"),
            ]
        )
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question")

        assert result.status == "completed"
        metrics = result.execution
        assert isinstance(metrics, ToolAgentExecutionMetrics)
        assert metrics.decision_llm_calls == 1
        assert metrics.input_tokens == 100
        assert metrics.output_tokens == 50
        assert metrics.elapsed_ms >= 0

    def test_two_decisions_sum_calls_and_tokens(self):
        provider = _MetadataProvider(
            [
                ToolCallAction(
                    action="tool_call",
                    tool_name="calculator",
                    arguments={"expression": "1+1"},
                ),
                FinalAnswerAction("final_answer", "done"),
            ],
            input_tokens=10,
            output_tokens=5,
        )
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question")

        assert result.tool_calls_used == 1
        assert result.execution.decision_llm_calls == 3  # 1 + 2 (repair window)
        assert result.execution.input_tokens == 10  # repair call reported none
        assert result.execution.output_tokens == 5

    def test_usage_missing_reports_null_not_zero(self):
        provider = _MetadataProvider(
            [FinalAnswerAction("final_answer", "done")],
            input_tokens=None,
            output_tokens=None,
        )
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question")

        assert result.execution.decision_llm_calls == 1
        assert result.execution.input_tokens is None
        assert result.execution.output_tokens is None

    def test_completed_run_always_carries_metrics(self):
        provider = _MetadataProvider([FinalAnswerAction("final_answer", "x")])
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question")
        assert result.status == "completed"
        assert result.execution is not None


class TestDeadline:
    def test_expired_deadline_stops_before_first_decision(self, monkeypatch):
        # Deterministic fake clock: every monotonic() read advances 100s, so
        # the 10s deadline is already expired at the first loop boundary.
        clock = {"t": 1000.0}

        def fake_monotonic():
            clock["t"] += 100.0
            return clock["t"]

        fake_time = SimpleNamespace(monotonic=fake_monotonic)
        monkeypatch.setattr(
            "core.tool_agent.runtime.time", fake_time, raising=True
        )
        provider = _MetadataProvider([FinalAnswerAction("final_answer", "x")])
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question", deadline_seconds=10)

        assert result.status == "refused"
        assert result.reason_code == ENGINEERING_RUN_DEADLINE_EXCEEDED
        assert provider.calls == 0
        assert result.execution.decision_llm_calls == 0

    def test_deadline_stops_next_decision_without_tool_execution(self):
        provider = _MetadataProvider(
            [
                ToolCallAction(
                    action="tool_call",
                    tool_name="read_project_context",
                    arguments={"path": "core/x.py", "line": 1, "context_lines": 0},
                ),
            ]
        )

        original_decide = provider.decide

        def slow_decide(*args, **kwargs):
            time.sleep(0.05)
            return original_decide(*args, **kwargs)

        provider.decide = slow_decide
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question", deadline_seconds=0.01)

        assert result.status == "refused"
        assert result.reason_code == ENGINEERING_RUN_DEADLINE_EXCEEDED
        assert provider.calls == 1
        assert result.tool_calls_used == 0

    def test_satisfied_deadline_is_not_reported(self):
        provider = _MetadataProvider([FinalAnswerAction("final_answer", "done")])
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question", deadline_seconds=30)

        assert result.status == "completed"
        assert result.reason_code is None


class TestCancellation:
    def test_cancel_probe_stops_before_first_decision(self):
        provider = _MetadataProvider([FinalAnswerAction("final_answer", "x")])
        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run("synthetic question", cancel_requested=lambda: True)

        assert result.status == "refused"
        assert result.reason_code == ENGINEERING_RUN_CANCELLED
        assert provider.calls == 0

    def test_cancel_between_decision_and_tool_execution(self):
        provider = _MetadataProvider(
            [
                ToolCallAction(
                    action="tool_call",
                    tool_name="read_project_context",
                    arguments={"path": "core/x.py", "line": 1, "context_lines": 0},
                ),
            ]
        )
        state = {"cancelled": False}

        def cancel_after_first_decision():
            return provider.calls >= 1 or state["cancelled"]

        runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
        result = runtime.run(
            "synthetic question", cancel_requested=cancel_after_first_decision
        )

        assert result.status == "refused"
        assert result.reason_code == ENGINEERING_RUN_CANCELLED
        assert provider.calls == 1
        assert result.tool_calls_used == 0


def _install_product(monkeypatch, provider):
    runtime = ToolAgentRuntime(registry=_registry(), provider=provider)
    monkeypatch.setattr(api.app, "tool_agent_runtime", runtime)
    monkeypatch.setattr(
        api.app,
        "engineering_agent_facade",
        EngineeringAgentFacade(build_full_unified_runtime(runtime)),
    )
    monkeypatch.setattr(
        "core.unified_engineering_runtime.route_engineering_evidence_requirement",
        lambda _q: EngineeringEvidenceRequirement(
            requirement_profile=NO_ADDITIONAL_REQUIREMENT,
            required_evidence_groups=(),
            min_distinct_project_code_paths=0,
        ),
    )


class TestPublicMetricsContract:
    def test_query_endpoint_carries_execution(self, monkeypatch):
        provider = _MetadataProvider(
            [FinalAnswerAction("final_answer", "plain deterministic answer")],
            input_tokens=123,
            output_tokens=45,
        )
        _install_product(monkeypatch, provider)
        # No `with client:`: lifespan would reset the monkeypatched runtimes.
        # This mirrors tests/test_engineering_agent_api.py's established
        # offline pattern.
        client = TestClient(api.app.app)
        response = client.post(
            "/engineering/query", json={"question": "synthetic question"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        execution = data["execution"]
        assert execution is not None
        assert execution["decision_llm_calls"] == 1
        assert execution["input_tokens"] == 123
        assert execution["output_tokens"] == 45
        assert execution["elapsed_ms"] >= 0


class TestConcurrencyAdmission:
    def test_bounded_slots_fail_fast_and_recover(self, monkeypatch):
        provider = _MetadataProvider([FinalAnswerAction("final_answer", "ok")])
        _install_product(monkeypatch, provider)
        client = TestClient(api.app.app)

        assert api.app._engineering_run_slots.acquire(blocking=False)
        assert api.app._engineering_run_slots.acquire(blocking=False)
        response = client.post(
            "/engineering/query", json={"question": "synthetic question"}
        )
        assert response.status_code == 503
        assert "at capacity" in response.json()["detail"]
        api.app._engineering_run_slots.release()
        api.app._engineering_run_slots.release()

        response = client.post(
            "/engineering/query", json={"question": "synthetic question"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"


class TestSseDisconnectCancellation:
    def test_generator_close_sets_cancellation_signal(self):
        from api.engineering_stream import stream_engineering_query

        cancel_event = threading.Event()
        seen = {"returned_after_cancel": False}

        class _WaitingProvider:
            def decide(self, registry, user_query, *, context=(), control_state=None):
                if cancel_event.wait(timeout=5.0):
                    seen["returned_after_cancel"] = True
                return AgentDecisionOutcome(
                    action=FinalAnswerAction("final_answer", "done"),
                    failure_code=None,
                    call_metadata=None,
                )

        class _DirectFacade:
            """Same run() surface as EngineeringAgentFacade over a runtime."""

            def __init__(self, runtime):
                self._runtime = runtime

            def run(self, question, *, conversation_context=None, trace_sink=None,
                    activity_sink=None, cancel_requested=None):
                return self._runtime.run(
                    question, trace_sink=trace_sink, cancel_requested=cancel_requested
                )

        facade = _DirectFacade(
            ToolAgentRuntime(registry=_registry(), provider=_WaitingProvider())
        )
        stream = stream_engineering_query(
            facade,
            "synthetic question",
            build_response=lambda _r: None,
            cancel_event=cancel_event,
        )
        next(stream)  # consume the initial status frame
        stream.close()  # client disconnect

        assert cancel_event.is_set()
        deadline = time.time() + 5
        while time.time() < deadline and not seen["returned_after_cancel"]:
            time.sleep(0.01)
        assert seen["returned_after_cancel"], "runtime never observed the cancel"

    def test_v2_generator_close_passes_cancellation_signal(self):
        from api.engineering_stream_v2 import stream_engineering_query_v2

        cancel_event = threading.Event()
        seen = {"probe_received": False, "observed": False}

        class _WaitingFacade:
            def run(
                self,
                question,
                *,
                conversation_context=None,
                activity_sink=None,
                cancel_requested=None,
            ):
                seen["probe_received"] = callable(cancel_requested)
                deadline = time.time() + 5
                while not cancel_requested() and time.time() < deadline:
                    time.sleep(0.01)
                seen["observed"] = cancel_requested()
                return ToolAgentRunResult(
                    status="refused",
                    answer=None,
                    reason_code=ENGINEERING_RUN_CANCELLED,
                    failure_code=None,
                    iterations_used=0,
                    tool_calls_used=0,
                    tool_errors_used=0,
                    trace=(),
                )

        stream = stream_engineering_query_v2(
            _WaitingFacade(),
            "synthetic question",
            build_response=lambda _result: {
                "status": "refused",
                "answer": None,
                "evidence": [],
            },
            cancel_event=cancel_event,
        )
        cancel_event.set()
        list(stream)

        assert seen == {"probe_received": True, "observed": True}
        assert cancel_event.is_set()

    def test_cancelled_conversation_turn_is_never_a_half_turn(self, tmp_path):
        from api.conversation_store import ConversationStore
        from api.engineering_stream import stream_engineering_query

        store = ConversationStore(tmp_path / "conv.sqlite3")
        summary = store.create_conversation(
            project_key="pkey", project_name="p", project_source="default_repo"
        )
        persist_calls = []
        cancel_event = threading.Event()
        cancel_event.set()  # disconnect before the run starts

        class _NeverProvider:
            def decide(self, *args, **kwargs):  # pragma: no cover - never runs
                raise AssertionError("cancelled run must not start decisions")

        runtime = ToolAgentRuntime(registry=_registry(), provider=_NeverProvider())
        facade = EngineeringAgentFacade(
            build_full_unified_runtime(runtime)
        )

        def persist(public):
            # Mirror the endpoint's before_public_result seam exactly: one
            # atomic user+assistant pair per public result.
            persist_calls.append(public)
            store.append_turn(
                "pkey",
                summary["id"],
                user_content="synthetic question",
                assistant_content="Refused: " + str(public.get("reason_code")),
                result=public,
            )

        stream = stream_engineering_query(
            facade,
            "synthetic question",
            conversation_context=None,
            build_response=_build_engineering_response,
            before_public_result=persist,
            cancel_event=cancel_event,
        )
        for _ in stream:
            pass

        # The cancelled run terminates at the first lifecycle boundary and the
        # persistence hook sees exactly one atomic public result — a complete
        # refused turn, never a half turn.
        assert len(persist_calls) == 1
        assert persist_calls[0]["status"] == "refused"
        assert persist_calls[0]["reason_code"] == ENGINEERING_RUN_CANCELLED
        detail = store.get_conversation("pkey", summary["id"])
        assert detail is not None
        roles = [m["role"] for m in detail["messages"]]
        assert roles == ["user", "assistant"]


class TestStreamingAdmissionOwnership:
    def test_disconnect_does_not_free_slot_until_worker_stops(self, monkeypatch):
        from api.engineering_stream import stream_engineering_query

        started = {"A": threading.Event(), "B": threading.Event()}
        unblock = {"A": threading.Event(), "B": threading.Event()}
        worker_done = {"A": threading.Event(), "B": threading.Event()}
        cancel_events = {"A": threading.Event(), "B": threading.Event()}

        class _BlockedFacade:
            def run(
                self,
                question,
                *,
                conversation_context=None,
                trace_sink=None,
                activity_sink=None,
                cancel_requested=None,
            ):
                if question in started:
                    started[question].set()
                    # Simulate an in-flight provider call that is cooperative
                    # but does not return merely because the client detached.
                    assert unblock[question].wait(timeout=5)
                    worker_done[question].set()
                return ToolAgentRunResult(
                    status="completed",
                    answer="worker stopped",
                    reason_code=None,
                    failure_code=None,
                    iterations_used=1,
                    tool_calls_used=0,
                    tool_errors_used=0,
                    trace=(),
                )

        monkeypatch.setattr(api.app, "engineering_agent_facade", _BlockedFacade())
        client = TestClient(api.app.app)
        acquired = []
        streams = []

        def acquire_stream(question):
            release_slot = api.app._acquire_engineering_run_slot()
            acquired.append(release_slot)
            callback_done = threading.Event()

            def on_worker_done():
                release_slot()
                callback_done.set()

            stream = stream_engineering_query(
                api.app.engineering_agent_facade,
                question,
                build_response=lambda result: result,
                cancel_event=cancel_events[question],
                on_worker_done=on_worker_done,
            )
            streams.append(stream)
            return callback_done

        callback_done = {}
        try:
            callback_done["A"] = acquire_stream("A")
            callback_done["B"] = acquire_stream("B")
            assert started["A"].wait(timeout=5)
            assert started["B"].wait(timeout=5)

            # Closing the producer generator only requests cancellation; the
            # blocked workers still own both admission slots.
            for question, stream in zip(("A", "B"), streams):
                assert next(stream).startswith("data:")
                stream.close()
                assert cancel_events[question].is_set()

            third_while_alive = client.post(
                "/engineering/query", json={"question": "third"}
            )
            assert third_while_alive.status_code == 503

            unblock["A"].set()
            unblock["B"].set()
            assert worker_done["A"].wait(timeout=5)
            assert worker_done["B"].wait(timeout=5)
            assert callback_done["A"].wait(timeout=5)
            assert callback_done["B"].wait(timeout=5)

            third_after_stop = client.post(
                "/engineering/query", json={"question": "third"}
            )
            assert third_after_stop.status_code == 200
        finally:
            unblock["A"].set()
            unblock["B"].set()
            for stream in streams:
                stream.close()
            for release_slot in acquired:
                release_slot()


class TestFrozenBehavior:
    def test_budget_and_prompt_identity_unchanged(self):
        assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
        from core.tool_agent.decision_prompt import (
            ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE,
        )

        assert (
            ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE.version
            == "engineering_agent_decision_prompt_unified_kind_aware_grounded_v1"
        )

    def test_metrics_model_rejects_negative(self):
        import pytest

        with pytest.raises(ValueError):
            ToolAgentExecutionMetrics(elapsed_ms=-1, decision_llm_calls=0)
        with pytest.raises(TypeError):
            ToolAgentExecutionMetrics(elapsed_ms="x", decision_llm_calls=0)
