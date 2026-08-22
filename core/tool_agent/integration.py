"""薄 integration builder——把已验收组件接起来，不重写 Tool / Runtime。

只做装配：七个 read-only Tool + AgentDecisionProvider + ToolAgentRuntime。
正式 Provider 默认 deepseek / deepseek-chat / base_url=DEEPSEEK_BASE_URL；
测试可注入 Fake/Scripted Provider（provider 参数），0 网络调用。
预算固定 5/4/2（ToolAgentBudget），不开放调用方 override。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from core.generator.deepseek_gen import DEEPSEEK_BASE_URL
from core.tool_agent.decision_prompt import DecisionPromptProfile
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
) -> ToolAgentRuntime:
    """把七个只读 Tool + Decision Provider + Bounded Runtime 装配成 Tool Agent。

    - registry：build_readonly_tool_registry（七个只读工具）；
    - code_search 的 repo_root 由调用方注入（仓库根），不来自用户请求；
    - knowledge_search 复用传入的 RetrievalPort（Pipeline/Adapter），不另造检索器；
    - provider：默认真实 OpenAI-compatible（deepseek/deepseek-chat），测试可注入 Fake；
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

        if not api_key:
            raise ValueError("缺少 api_key（真实 Provider 需要）")
        provider = OpenAICompatibleAgentDecisionProvider(
            provider=FROZEN_TOOL_PROVIDER,
            model=FROZEN_TOOL_MODEL,
            api_key=api_key,
            base_url=base_url,
            prompt_profile=prompt_profile,
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
