"""薄 integration builder——把已验收组件接起来，不重写 Tool / Runtime。

只做装配：七个 read-only Tool + AgentDecisionProvider + ToolAgentRuntime。
正式 Provider 默认 deepseek / deepseek-chat / base_url=DEEPSEEK_BASE_URL；
测试可注入 Fake/Scripted Provider（provider 参数），0 网络调用。
预算固定 5/4/2（ToolAgentBudget），不开放调用方 override。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Optional

from core.generator.deepseek_gen import DEEPSEEK_BASE_URL
from core.provider_config import OpenAICompatibleProviderConfig
from core.tool_agent.decision_prompt import (
    DecisionPromptProfile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import ToolAgentBudget

FROZEN_TOOL_PROVIDER = "deepseek"
FROZEN_TOOL_MODEL = "deepseek-chat"


def build_tool_agent_runtime(
    *,
    repo_root: str | os.PathLike,
    retrieval_port: Any,
    provider: Any = None,
    api_key: Optional[str] = None,
    base_url: str = DEEPSEEK_BASE_URL,
    knowledge_strategy: str = "bm25",
    knowledge_top_k: int = 5,
    prompt_profile: Optional[DecisionPromptProfile] = None,
    provider_id: Optional[str] = None,
    model: Optional[str] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
    provider_config: Optional[OpenAICompatibleProviderConfig] = None,
) -> ToolAgentRuntime:
    """把七个只读 Tool + Decision Provider + Bounded Runtime 装配成 Tool Agent。

    - registry：build_readonly_tool_registry（七个只读工具）；
    - code_search 的 repo_root 由调用方注入（仓库根），不来自用户请求；
    - knowledge_search 复用传入的 RetrievalPort（Pipeline/Adapter），不另造检索器；
    - provider：默认真实 OpenAI-compatible（deepseek/deepseek-chat），测试可注入 Fake；
      provider_id/model/base_url/extra_headers 或 provider_config 是 additive 的
      transport wiring；未提供时仍使用既有 DeepSeek 默认值；
    - budget：固定 ToolAgentBudget()（5/4/2），不可 override。
    """
    registry = build_readonly_tool_registry(
        repo_root,
        retrieval_port,
        knowledge_strategy=knowledge_strategy,
        knowledge_top_k=knowledge_top_k,
    )
    if provider is None:
        from core.tool_agent.openai_compatible import (
            OpenAICompatibleAgentDecisionProvider,
        )

        if provider_config is not None:
            if not isinstance(provider_config, OpenAICompatibleProviderConfig):
                raise TypeError(
                    "provider_config 必须是 OpenAICompatibleProviderConfig 或 None"
                )
            if provider_id is not None and provider_id != provider_config.provider_id:
                raise ValueError("provider_id 与 provider_config 不一致")
            if model is not None and model != provider_config.model:
                raise ValueError("model 与 provider_config 不一致")
            # The historical default remains in the signature for compatibility.
            # A supplied config owns the endpoint unless a genuinely different
            # explicit endpoint is supplied.
            if base_url not in (DEEPSEEK_BASE_URL, provider_config.base_url):
                raise ValueError("base_url 与 provider_config 不一致")
            if extra_headers is not None and dict(extra_headers) != dict(
                provider_config.extra_headers
            ):
                raise ValueError("extra_headers 与 provider_config 不一致")
            resolved_provider_id = provider_config.provider_id
            resolved_model = provider_config.model
            resolved_base_url = provider_config.base_url
            resolved_headers = provider_config.extra_headers
            resolved_api_key = api_key or os.getenv(provider_config.api_key_env)
        else:
            resolved_provider_id = provider_id or FROZEN_TOOL_PROVIDER
            resolved_model = model or FROZEN_TOOL_MODEL
            resolved_base_url = base_url
            resolved_headers = extra_headers
            resolved_api_key = api_key

        if not resolved_api_key:
            raise ValueError("缺少 api_key（真实 Provider 需要）")
        provider = OpenAICompatibleAgentDecisionProvider(
            provider=resolved_provider_id,
            model=resolved_model,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            extra_headers=resolved_headers,
            prompt_profile=prompt_profile,
            max_parse_repairs=max_parse_repairs_for_profile(prompt_profile),
        )
    return ToolAgentRuntime(
        registry=registry,
        provider=provider,
        budget=ToolAgentBudget(),
    )


__all__ = [
    "FROZEN_TOOL_PROVIDER",
    "FROZEN_TOOL_MODEL",
    "build_tool_agent_runtime",
]
