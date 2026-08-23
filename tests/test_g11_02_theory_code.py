"""Offline contracts for the G11-02 Theory <-> Code prompt profile."""

from __future__ import annotations

import asyncio
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
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    LEGACY_DECISION_PROMPT_PROFILE,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler

import api.app


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


def test_engineering_production_wiring_uses_v2_without_clearing_legacy_runtime(
    monkeypatch, tmp_path
):
    legacy_runtime = object()
    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return legacy_runtime
        raise RuntimeError("engineering init failure")

    monkeypatch.setattr(api.app, "Pipeline", lambda **kwargs: SimpleNamespace(retriever=object()))
    monkeypatch.setattr(
        api.app,
        "resolve_engineering_project",
        lambda _root: SimpleNamespace(root=tmp_path),
    )
    monkeypatch.setattr(api.app, "_resolve_agent_provider", lambda _pipeline: ("fake", "key"))
    monkeypatch.setattr(api.app, "build_pipeline_agent_runtime", lambda *args, **kwargs: object())
    monkeypatch.setattr(api.app, "PipelineRetrievalAdapter", lambda _retriever: object())
    monkeypatch.setattr(
        api.app,
        "build_verified_engineering_knowledge",
        lambda *args, **kwargs: SimpleNamespace(retrieval_port=object()),
    )
    monkeypatch.setattr(api.app, "build_tool_agent_runtime", fake_builder)

    async def run_lifespan():
        async with api.app.lifespan(api.app.app):
            assert api.app.tool_agent_runtime is legacy_runtime
            assert api.app.engineering_agent_runtime is None
            assert api.app.engineering_agent_facade is None

    asyncio.run(run_lifespan())
    assert len(calls) == 2
    assert calls[0].get("prompt_profile") is None
    assert calls[1]["prompt_profile"] is ENGINEERING_DECISION_PROMPT_V2_PROFILE


def test_legacy_init_failure_blocks_engineering_init(monkeypatch, tmp_path):
    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("legacy init failure")

    monkeypatch.setattr(api.app, "Pipeline", lambda **kwargs: SimpleNamespace(retriever=object()))
    monkeypatch.setattr(
        api.app,
        "resolve_engineering_project",
        lambda _root: SimpleNamespace(root=tmp_path),
    )
    monkeypatch.setattr(api.app, "_resolve_agent_provider", lambda _pipeline: ("fake", "key"))
    monkeypatch.setattr(api.app, "build_pipeline_agent_runtime", lambda *args, **kwargs: object())
    monkeypatch.setattr(api.app, "PipelineRetrievalAdapter", lambda _retriever: object())
    monkeypatch.setattr(api.app, "build_tool_agent_runtime", fake_builder)

    async def run_lifespan():
        async with api.app.lifespan(api.app.app):
            assert api.app.tool_agent_runtime is None
            assert api.app.engineering_agent_runtime is None
            assert api.app.engineering_agent_facade is None

    asyncio.run(run_lifespan())
    assert len(calls) == 1
    assert calls[0].get("prompt_profile") is None
