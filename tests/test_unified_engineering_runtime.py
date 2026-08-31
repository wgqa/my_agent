"""ARCH-RUNTIME-02 contract tests for the single Engineering Runtime boundary."""

from __future__ import annotations

import pytest

import core.unified_engineering_runtime as unified_runtime_module
from core.conversation_context import ConversationQueryResolution
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_context import EngineeringContextResolver
from core.engineering_requirements import route_engineering_evidence_requirement
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import ToolAgentRunResult
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)
from tests._engineering_runtime_support import build_full_unified_runtime


class ScriptedProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0

    def decide(self, registry, user_query, *, context=(), control_state=None):
        action = self.actions[min(self.calls, len(self.actions) - 1)]
        self.calls += 1
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=None,
        )


def _runtime(actions):
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    provider = ScriptedProvider(actions)
    return ToolAgentRuntime(registry=registry, provider=provider), provider


def _calculate_actions(answer="12 * 7 = 84"):
    return [
        ToolCallAction(
            action="tool_call",
            tool_name="calculator",
            arguments={"expression": "12*7"},
        ),
        FinalAnswerAction(action="final_answer", answer=answer),
    ]


def _direct_actions(answer="synthetic answer"):
    return [FinalAnswerAction(action="final_answer", answer=answer)]


def _completed_result(answer="synthetic"):
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


def _unified(runtime, *, context_resolver=None):
    return build_full_unified_runtime(
        runtime,
        context_resolver=context_resolver,
    )


def test_delegation_parity_preserves_the_complete_tool_agent_result():
    question = "calculate 12*7"

    legacy_runtime, legacy_provider = _runtime(_direct_actions())
    requirement = route_engineering_evidence_requirement(question)
    expected = legacy_runtime.run(
        question,
        evidence_requirement=requirement,
    )

    unified_runtime, unified_provider = _runtime(_direct_actions())
    actual = _unified(unified_runtime).run(question)

    assert actual == expected
    for field in (
        "status",
        "answer",
        "reason_code",
        "failure_code",
        "iterations_used",
        "tool_calls_used",
        "tool_errors_used",
        "trace",
        "evidence",
    ):
        assert getattr(actual, field) == getattr(expected, field)
    assert unified_provider.calls == legacy_provider.calls == 1


def test_requirement_routing_happens_once_in_unified_runtime_not_in_facade(monkeypatch):
    question = "Explain the mechanism and compare it with the current implementation"
    expected_requirement = route_engineering_evidence_requirement(question)
    route_calls = []

    class RecordingRuntime(ToolAgentRuntime):
        def __init__(self):
            self.received = []

        def run(
            self,
            user_input,
            *,
            evidence_requirement=None,
            initial_context=(),
            initial_evidence=(),
            disabled_tools=(),
            finalization_verifier=None,
            trace_sink=None,
            activity_sink=None,
        ):
            self.received.append(
                (user_input, evidence_requirement, trace_sink, activity_sink)
            )
            return _completed_result()

    def route_once(user_input):
        route_calls.append(user_input)
        return expected_requirement

    monkeypatch.setattr(
        unified_runtime_module,
        "route_engineering_evidence_requirement",
        route_once,
    )
    execution_runtime = RecordingRuntime()
    facade = EngineeringAgentFacade(_unified(execution_runtime))

    result = facade.run(question)

    assert result == _completed_result()
    assert route_calls == [question]
    assert execution_runtime.received == [
        (question, expected_requirement, None, None)
    ]


def test_unified_runtime_does_not_add_a_loop_or_budget_counter():
    runtime, provider = _runtime(_calculate_actions())

    result = _unified(runtime).run("calculate 12*7")

    assert result.iterations_used == 2
    assert result.tool_calls_used == 1
    assert result.tool_errors_used == 0
    assert provider.calls == 2


def test_trace_sink_passthrough_does_not_change_business_result():
    question = "calculate 12*7"
    no_sink_runtime, _ = _runtime(_direct_actions())
    without_sink = _unified(no_sink_runtime).run(question)

    with_sink_runtime, _ = _runtime(_direct_actions())
    trace = []
    with_sink = _unified(with_sink_runtime).run(
        question,
        trace_sink=trace.append,
    )

    assert with_sink == without_sink
    assert trace == list(with_sink.trace)


def test_activity_sink_passthrough_and_failure_are_observational():
    question = "calculate 12*7"
    no_sink_runtime, _ = _runtime(_direct_actions())
    without_sink = _unified(no_sink_runtime).run(question)

    with_sink_runtime, _ = _runtime(_direct_actions())
    activities = []
    with_sink = _unified(with_sink_runtime).run(
        question,
        activity_sink=activities.append,
    )

    def failing_sink(_event):
        raise RuntimeError("observer failure")

    failing_runtime, _ = _runtime(_direct_actions())
    with_failing_sink = _unified(failing_runtime).run(
        question,
        activity_sink=failing_sink,
    )

    assert with_sink == without_sink
    assert with_failing_sink == without_sink
    assert activities


def test_conversation_context_none_empty_and_nonempty_use_context_component():
    runtime, provider = _runtime(
        [FinalAnswerAction(action="final_answer", answer="ok")]
    )
    unified_runtime = _unified(runtime)

    assert unified_runtime.run("hello", conversation_context=None).answer == "ok"
    assert unified_runtime.run("hello", conversation_context=()).answer == "ok"
    assert unified_runtime.run("hello", conversation_context=[]).answer == "ok"

    class Resolver:
        def resolve(self, _history, _question):
            return ConversationQueryResolution("resolved", True, False)

    context_runtime = _unified(
        runtime,
        context_resolver=EngineeringContextResolver(Resolver()),
    )
    assert context_runtime.run(
        "follow-up",
        conversation_context=[{"role": "user", "content": "previous"}],
    ).answer == "ok"
    assert provider.calls == 4


def test_direct_tool_agent_runtime_construction_is_not_a_supported_facade_boundary():
    runtime, _ = _runtime(
        [FinalAnswerAction(action="final_answer", answer="ok")]
    )

    with pytest.raises(TypeError):
        UnifiedEngineeringRuntime(runtime)
    with pytest.raises(TypeError, match="UnifiedEngineeringRuntime"):
        EngineeringAgentFacade(runtime)


def test_unified_runtime_requires_all_core_components():
    runtime, _ = _runtime(_direct_actions())

    with pytest.raises(TypeError, match="context_resolver"):
        UnifiedEngineeringRuntime(LegacyToolAgentExecutionAdapter(runtime))
