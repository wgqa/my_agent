"""默认只读 Tool Registry factory。

build_readonly_tool_registry(...) 注册六个真实 read-only Tool：calculator /
code_search / read_project_context / knowledge_search / changed_files / git_diff。
依赖（repo_root、retrieval_port）
经构造参数传入；**import 本模块时不做任何副作用**：不读环境变量、不初始化
模型、不创建 Retriever、不联网、不建索引。Factory 本身不调用 LLM。
"""

from __future__ import annotations

import os

from core.agent_runtime import RetrievalPort
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC, CodeSearchHandler
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
    ReadProjectContextHandler,
)
from core.tool_agent.tools.knowledge_search import (
    KNOWLEDGE_SEARCH_SPEC,
    KnowledgeSearchHandler,
)
from core.tool_agent.tools.git_change import (
    CHANGED_FILES_SPEC,
    GIT_DIFF_SPEC,
    ChangedFilesHandler,
    GitDiffHandler,
)


def build_readonly_tool_registry(
    repo_root: str | os.PathLike,
    retrieval_port: RetrievalPort,
    *,
    knowledge_strategy: str = "bm25",
    knowledge_top_k: int = 5,
) -> ToolRegistry:
    """构造并注册六个真实 read-only Tool；所有依赖经参数显式传入。

    - calculator：无外部依赖；
    - code_search：repo_root（构造时 fail-fast 若不是目录）；
    - read_project_context：同一个 repo_root 中的有限只读源码窗口；
    - knowledge_search：retrieval_port + 系统固定 strategy / top_k。
    """
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(repo_root=repo_root))
    registry.register(
        READ_PROJECT_CONTEXT_SPEC,
        ReadProjectContextHandler(repo_root=repo_root),
    )
    registry.register(
        KNOWLEDGE_SEARCH_SPEC,
        KnowledgeSearchHandler(
            retrieval_port=retrieval_port,
            strategy=knowledge_strategy,
            top_k=knowledge_top_k,
        ),
    )
    registry.register(CHANGED_FILES_SPEC, ChangedFilesHandler(repo_root=repo_root))
    registry.register(GIT_DIFF_SPEC, GitDiffHandler(repo_root=repo_root))
    return registry
