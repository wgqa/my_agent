"""Offline contracts for the G11-02 Theory <-> Code prompt profile."""

from __future__ import annotations

from types import SimpleNamespace

from core.tool_agent import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    OpenAICompatibleAgentDecisionProvider,
    ToolRegistry,
)
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    DECISION_PROMPT_VERSION,
    ENGINEERING_DECISION_PROMPT_PROFILE,
    ENGINEERING_DECISION_PROMPT_SHA256,
    LEGACY_DECISION_PROMPT_PROFILE,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler


class FakeClient:
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


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    return registry


def _provider(client, **kwargs):
    return OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="sk-test",
        client=client,
        **kwargs,
    )


def test_legacy_profile_identity_and_default_provider_are_unchanged():
    assert LEGACY_DECISION_PROMPT_PROFILE.version == DECISION_PROMPT_VERSION
    assert LEGACY_DECISION_PROMPT_PROFILE.sha256 == DECISION_PROMPT_SHA256
    client = FakeClient()
    outcome = _provider(client).decide(_registry(), "general question")
    assert isinstance(outcome, AgentDecisionOutcome)
    assert outcome.call_metadata.prompt_version == "tool_agent_decision_prompt_v3"
    assert outcome.call_metadata.prompt_sha256 == DECISION_PROMPT_SHA256


def test_engineering_profile_has_independent_identity_and_policy():
    assert ENGINEERING_DECISION_PROMPT_PROFILE.version == (
        "engineering_agent_decision_prompt_v1"
    )
    assert ENGINEERING_DECISION_PROMPT_SHA256 == (
        ENGINEERING_DECISION_PROMPT_PROFILE.sha256
    )
    system = ENGINEERING_DECISION_PROMPT_PROFILE.build_messages(
        _registry().list_specs(), "theory and current implementation"
    )[0]["content"]
    assert "Knowledge Evidence 与 Repository Evidence 是不同的 evidence backend" in system
    assert "Theory ↔ Code" in system
    assert "knowledge_search 与 repository context" in system
    assert "E1/E2" in system
    assert "Petclinic" not in system
    assert "spring_petclinic" not in system


def test_engineering_provider_metadata_and_system_message_use_v1():
    client = FakeClient()
    outcome = _provider(
        client, prompt_profile=ENGINEERING_DECISION_PROMPT_PROFILE
    ).decide(_registry(), "theory and current implementation")
    assert outcome.call_metadata.prompt_version == "engineering_agent_decision_prompt_v1"
    assert outcome.call_metadata.prompt_sha256 == ENGINEERING_DECISION_PROMPT_SHA256
    system = client.last_kwargs["messages"][0]["content"]
    assert "只问通用技术知识时，可以独立使用 knowledge_search" in system
    assert "不要为了凑异构 evidence 强制 knowledge_search" in system
