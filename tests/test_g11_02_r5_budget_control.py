"""Offline contracts for G11-02-R5 Runtime-owned decision control."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from core.tool_agent import (
    AGENT_BUDGET_EXCEEDED,
    AgentDecisionOutcome,
    DecisionControlState,
    FinalAnswerAction,
    RefuseAction,
    ToolAgentBudget,
    ToolAgentRuntime,
    ToolRegistry,
    build_readonly_tool_registry,
    OpenAICompatibleAgentDecisionProvider,
)
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    LEGACY_DECISION_PROMPT_PROFILE,
    build_decision_messages,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.actions import ToolCallAction
from api.schemas import EngineeringQueryRequest


class CapturingProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.states.append(control_state)
        action = self.actions[min(self.calls, len(self.actions) - 1)]
        self.calls += 1
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=None,
        )


def _calculator_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    return registry


def _tool_call(expression: str) -> ToolCallAction:
    return ToolCallAction(
        action="tool_call",
        tool_name="calculator",
        arguments={"expression": expression},
    )


def _run_to_fifth_decision(final_action):
    provider = CapturingProvider(
        [
            _tool_call("1+1"),
            _tool_call("2+2"),
            _tool_call("3+3"),
            _tool_call("4+4"),
            final_action,
        ]
    )
    result = ToolAgentRuntime(
        registry=_calculator_registry(), provider=provider
    ).run("budget control")
    return result, provider


def test_decision_control_state_contract_and_immutability():
    state = DecisionControlState(
        iteration=4,
        remaining_iterations=1,
        remaining_tool_calls=1,
        tool_call_allowed=True,
        must_terminate=False,
    )
    assert state.to_dict() == {
        "iteration": 4,
        "remaining_iterations": 1,
        "remaining_tool_calls": 1,
        "tool_call_allowed": True,
        "must_terminate": False,
    }
    last = DecisionControlState(
        iteration=5,
        remaining_iterations=0,
        remaining_tool_calls=1,
        tool_call_allowed=False,
        must_terminate=True,
    )
    assert last.must_terminate is True
    calls_exhausted = DecisionControlState(
        iteration=2,
        remaining_iterations=3,
        remaining_tool_calls=0,
        tool_call_allowed=False,
        must_terminate=True,
    )
    assert calls_exhausted.must_terminate is True
    with pytest.raises(FrozenInstanceError):
        state.iteration = 5


def test_runtime_passes_budget_aware_state_and_last_final_completes():
    result, provider = _run_to_fifth_decision(
        FinalAnswerAction(action="final_answer", answer="complete")
    )
    assert result.status == "completed"
    assert result.iterations_used == 5
    assert result.tool_calls_used == 4
    assert provider.states[0].to_dict() == {
        "iteration": 1,
        "remaining_iterations": 4,
        "remaining_tool_calls": 4,
        "tool_call_allowed": True,
        "must_terminate": False,
    }
    assert provider.states[3].to_dict() == {
        "iteration": 4,
        "remaining_iterations": 1,
        "remaining_tool_calls": 1,
        "tool_call_allowed": True,
        "must_terminate": False,
    }
    assert provider.states[4].must_terminate is True
    assert provider.states[4].tool_call_allowed is False
    assert provider.states[4].remaining_iterations == 0


def test_last_refuse_can_end_without_budget_failure():
    result, provider = _run_to_fifth_decision(
        RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION")
    )
    assert result.status == "refused"
    assert result.reason_code == "INSUFFICIENT_INFORMATION"
    assert provider.states[-1].must_terminate is True


def test_runtime_hard_stops_malicious_tool_call_at_last_decision():
    result, provider = _run_to_fifth_decision(_tool_call("5+5"))
    assert result.status == "refused"
    assert result.reason_code == AGENT_BUDGET_EXCEEDED
    assert result.iterations_used == 5
    assert result.tool_calls_used == 4
    assert provider.states[-1].tool_call_allowed is False


def test_legacy_v3_ignores_control_state_and_keeps_identity():
    state = DecisionControlState(5, 0, 0, False, True)
    specs = _calculator_registry().list_specs()
    with_state = LEGACY_DECISION_PROMPT_PROFILE.build_messages(
        specs, "question", control_state=state
    )
    without_state = build_decision_messages(specs, "question")
    assert with_state == without_state
    assert LEGACY_DECISION_PROMPT_PROFILE.version == "tool_agent_decision_prompt_v3"
    assert LEGACY_DECISION_PROMPT_PROFILE.sha256 == DECISION_PROMPT_SHA256
    assert "Trusted Runtime control state" not in with_state[0]["content"]


def test_engineering_v2_renders_trusted_state_in_system_only():
    state = DecisionControlState(4, 1, 1, True, False)
    messages = ENGINEERING_DECISION_PROMPT_V2_PROFILE.build_messages(
        _calculator_registry().list_specs(), "question", control_state=state
    )
    assert messages[0]["role"] == "system"
    assert "Trusted Runtime control state" in messages[0]["content"]
    assert '"remaining_tool_calls": 1' in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "question"}
    assert all("Trusted Runtime control state" not in message["content"] for message in messages[1:])
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.version == (
        "engineering_agent_decision_prompt_v2"
    )


def test_engineering_v2_provider_metadata_and_state_identity():
    class Client:
        def __init__(self):
            self.last_kwargs = None

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            self.last_kwargs = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"final_answer","answer":"ok"}'
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    client = Client()
    provider = OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="sk-test",
        client=client,
        prompt_profile=ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    )
    outcome = provider.decide(
        _calculator_registry(),
        "question",
        control_state=DecisionControlState(5, 0, 0, False, True),
    )
    assert outcome.call_metadata.prompt_version == "engineering_agent_decision_prompt_v2"
    assert outcome.call_metadata.prompt_sha256 == ENGINEERING_DECISION_PROMPT_V2_SHA256
    assert "Trusted Runtime control state" in client.last_kwargs["messages"][0]["content"]


def test_frozen_budget_and_seven_tool_registry(tmp_path):
    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    registry = build_readonly_tool_registry(tmp_path, RetrievalPort())
    assert len(registry.list_specs()) == 7
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)


def test_control_state_is_not_added_to_runtime_trace():
    result, _ = _run_to_fifth_decision(
        FinalAnswerAction(action="final_answer", answer="complete")
    )
    encoded = str([event.to_dict() for event in result.trace])
    assert "remaining_iterations" not in encoded
    assert "tool_call_allowed" not in encoded
    assert "must_terminate" not in encoded


def test_api_request_cannot_override_runtime_budget():
    with pytest.raises(ValueError):
        EngineeringQueryRequest(
            question="question",
            remaining_iterations=1,
            remaining_tool_calls=1,
            tool_call_allowed=True,
        )
