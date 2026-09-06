"""Provider-port-01: provider configuration and transport-boundary tests.

All tests use injected/fake SDK construction and never contact a real provider.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.conversation_context import OpenAICompatibleConversationQueryResolver
from core.generator.deepseek_gen import DEEPSEEK_BASE_URL
from core.provider_config import (
    OPENCODE_GO_API_KEY_ENV,
    OPENCODE_GO_BASE_URL,
    OpenAICompatibleProviderConfig,
    build_opencode_go_provider_config,
    deepseek_provider_config,
)
from core.query_planning import OpenAICompatibleQueryPlanner
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
)
from core.tool_agent.integration import (
    FROZEN_TOOL_MODEL,
    FROZEN_TOOL_PROVIDER,
    build_tool_agent_runtime,
)
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.runtime_models import ToolAgentBudget


def _fake_retrieval_port():
    return SimpleNamespace(
        supported_strategies=("bm25",),
        search=lambda _query, _strategy, _top_k: (),
    )


def test_deepseek_default_config_keeps_historical_transport_identity():
    config = deepseek_provider_config()

    assert config.provider_id == FROZEN_TOOL_PROVIDER == "deepseek"
    assert config.model == FROZEN_TOOL_MODEL == "deepseek-chat"
    assert config.base_url == DEEPSEEK_BASE_URL == "https://api.deepseek.com/v1"
    assert config.api_key_env == "DEEPSEEK_API_KEY"
    assert dict(config.extra_headers) == {}
    assert "api_key" not in config.__dataclass_fields__


def test_opencode_factory_requires_explicit_model_and_work_unit_session():
    config = build_opencode_go_provider_config(
        model="opencode-development-model",
        session_id="provider-port-case-001",
        user_agent="rag-knowledge-base/provider-port-01-tests",
    )

    assert config.provider_id == "opencode-go"
    assert config.model == "opencode-development-model"
    assert config.base_url == OPENCODE_GO_BASE_URL
    assert config.api_key_env == OPENCODE_GO_API_KEY_ENV
    assert dict(config.extra_headers) == {
        "User-Agent": "rag-knowledge-base/provider-port-01-tests",
        "x-opencode-session": "provider-port-case-001",
    }
    assert "sk-provider-port-test-key" not in repr(config)

    with pytest.raises((TypeError, ValueError)):
        build_opencode_go_provider_config(model="model", session_id="")
    with pytest.raises(ValueError):
        build_opencode_go_provider_config(model="model", session_id="bad session")


def test_provider_config_is_immutable_and_rejects_secret_headers():
    config = OpenAICompatibleProviderConfig(
        provider_id="provider",
        model="model",
        base_url="https://provider.example/v1",
        api_key_env="PROVIDER_API_KEY",
        extra_headers={"User-Agent": "public-client", "x-work-unit": "case-1"},
    )

    with pytest.raises(TypeError):
        config.extra_headers["x-new"] = "value"

    for header_name in ("Authorization", "X-API-Key", "X-Auth-Token", "Cookie"):
        with pytest.raises(ValueError):
            OpenAICompatibleProviderConfig(
                provider_id="provider",
                model="model",
                base_url="https://provider.example/v1",
                api_key_env="PROVIDER_API_KEY",
                extra_headers={header_name: "public-looking-value"},
            )


def test_same_opencode_transport_headers_reach_all_three_sdk_clients(monkeypatch):
    config = build_opencode_go_provider_config(
        model="custom-opencode-model",
        session_id="same-work-unit-42",
        user_agent="rag-knowledge-base/provider-port-01",
    )
    captures: list[dict] = []

    class CapturingSDKClient:
        def __init__(self, **kwargs):
            captures.append(kwargs)

    monkeypatch.setattr(
        "core.conversation_context.resolver.OpenAI", CapturingSDKClient
    )
    monkeypatch.setattr(
        "core.query_planning.openai_compatible.OpenAI", CapturingSDKClient
    )
    monkeypatch.setattr(
        "core.tool_agent.openai_compatible.OpenAI", CapturingSDKClient
    )

    resolver = OpenAICompatibleConversationQueryResolver(
        provider=config.provider_id,
        model=config.model,
        api_key="sk-provider-port-test-key",
        base_url=config.base_url,
        extra_headers=config.extra_headers,
    )
    planner = OpenAICompatibleQueryPlanner(
        provider=config.provider_id,
        model=config.model,
        api_key="sk-provider-port-test-key",
        base_url=config.base_url,
        extra_headers=config.extra_headers,
    )
    decision = OpenAICompatibleAgentDecisionProvider(
        provider=config.provider_id,
        model=config.model,
        api_key="sk-provider-port-test-key",
        base_url=config.base_url,
        extra_headers=config.extra_headers,
        prompt_profile=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    )

    assert [resolver._client, planner._client, decision._client]
    assert len(captures) == 3
    assert all(item["base_url"] == OPENCODE_GO_BASE_URL for item in captures)
    assert all(
        item["default_headers"] == dict(config.extra_headers) for item in captures
    )
    assert all(
        item["default_headers"]["x-opencode-session"] == "same-work-unit-42"
        for item in captures
    )
    assert all(
        item["default_headers"]["User-Agent"]
        == "rag-knowledge-base/provider-port-01"
        for item in captures
    )
    assert all("api_key" in item for item in captures)
    assert all(
        "sk-provider-port-test-key" not in repr(component)
        for component in (resolver, planner, decision)
    )


def test_injected_fake_clients_never_construct_sdk(monkeypatch):
    class NetworkForbiddenSDKClient:
        def __init__(self, **_kwargs):
            raise AssertionError("provider SDK must not be constructed")

    monkeypatch.setattr(
        "core.conversation_context.resolver.OpenAI", NetworkForbiddenSDKClient
    )
    monkeypatch.setattr(
        "core.query_planning.openai_compatible.OpenAI", NetworkForbiddenSDKClient
    )
    monkeypatch.setattr(
        "core.tool_agent.openai_compatible.OpenAI", NetworkForbiddenSDKClient
    )

    fake_client = object()
    OpenAICompatibleConversationQueryResolver(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        client=fake_client,
    )
    OpenAICompatibleQueryPlanner(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        client=fake_client,
    )
    OpenAICompatibleAgentDecisionProvider(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        client=fake_client,
    )


def test_tool_agent_builder_defaults_to_deepseek_and_keeps_budget(monkeypatch, tmp_path):
    captures: list[dict] = []

    class CapturingSDKClient:
        def __init__(self, **kwargs):
            captures.append(kwargs)

    monkeypatch.setattr(
        "core.tool_agent.openai_compatible.OpenAI", CapturingSDKClient
    )
    runtime = build_tool_agent_runtime(
        repo_root=tmp_path,
        retrieval_port=_fake_retrieval_port(),
        api_key="sk-provider-port-default-test",
    )

    assert runtime._provider._provider == FROZEN_TOOL_PROVIDER
    assert runtime._provider._model == FROZEN_TOOL_MODEL
    assert runtime._provider._base_url == DEEPSEEK_BASE_URL
    assert runtime._budget == ToolAgentBudget(5, 4, 2)
    assert captures[0]["base_url"] == DEEPSEEK_BASE_URL
    assert "default_headers" not in captures[0]


def test_tool_agent_builder_accepts_explicit_config_without_changing_runtime_controls(
    monkeypatch, tmp_path
):
    config = build_opencode_go_provider_config(
        model="custom-development-model",
        session_id="tool-agent-work-unit-1",
    )
    captures: list[dict] = []

    class CapturingSDKClient:
        def __init__(self, **kwargs):
            captures.append(kwargs)

    monkeypatch.setenv(config.api_key_env, "sk-provider-port-env-test")
    monkeypatch.setattr(
        "core.tool_agent.openai_compatible.OpenAI", CapturingSDKClient
    )
    runtime = build_tool_agent_runtime(
        repo_root=tmp_path,
        retrieval_port=_fake_retrieval_port(),
        provider_config=config,
    )

    assert runtime._provider._provider == config.provider_id
    assert runtime._provider._model == config.model
    assert runtime._provider._base_url == config.base_url
    assert dict(runtime._provider._extra_headers) == dict(config.extra_headers)
    assert runtime._budget == ToolAgentBudget(5, 4, 2)
    assert captures[0]["default_headers"] == dict(config.extra_headers)


def test_pipeline_runtime_can_wire_one_config_to_planner_resolver_and_direct_client():
    from core.agent_runtime import build_pipeline_agent_runtime

    config = build_opencode_go_provider_config(
        model="pipeline-development-model",
        session_id="pipeline-work-unit-1",
    )
    pipeline = SimpleNamespace(retriever=object(), generator=object())
    runtime = build_pipeline_agent_runtime(
        pipeline,
        provider_config=config,
        api_key="sk-provider-port-pipeline-test",
        planner_client=object(),
        context_resolver_client=object(),
        direct_answer_client=object(),
    )

    assert runtime._planner._provider == config.provider_id
    assert runtime._planner._model == config.model
    assert runtime._planner._base_url == config.base_url
    assert dict(runtime._planner._extra_headers) == dict(config.extra_headers)
    assert dict(runtime._query_resolver._extra_headers) == dict(config.extra_headers)
    assert dict(runtime._answer_port._direct_extra_headers) == dict(config.extra_headers)


def test_api_key_is_not_config_identity_or_runtime_metadata():
    config = deepseek_provider_config()
    secret = "sk-provider-port-never-serialized"
    assert secret not in repr(config)
    assert secret not in repr(
        OpenAICompatibleAgentDecisionProvider(
            provider=config.provider_id,
            model=config.model,
            api_key=secret,
            client=SimpleNamespace(),
        )
    )


def test_formal_unified_prompt_and_hard_controls_remain_unchanged():
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
