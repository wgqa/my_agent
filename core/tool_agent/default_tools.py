"""默认只读 Tool Registry factory。

build_readonly_tool_registry(...) 注册七个真实 read-only Tool：calculator /
code_search / read_project_context / knowledge_search / changed_files / git_diff /
find_tests。
依赖（repo_root、retrieval_port）
经构造参数传入；**import 本模块时不做任何副作用**：不读环境变量、不初始化
模型、不创建 Retriever、不联网、不建索引。Factory 本身不调用 LLM。
"""

from __future__ import annotations

import os
from pathlib import Path

from core.agent_runtime import RetrievalPort
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.tools.code_search import (
    CODE_SEARCH_SPEC, CODE_SEARCH_VERSION, CodeSearchHandler, code_search_spec,
)
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
    READ_PROJECT_CONTEXT_VERSION,
    ReadProjectContextHandler,
)
from core.tool_agent.tools.read_project_targets import (
    READ_PROJECT_TARGETS_SPEC, READ_PROJECT_TARGETS_VERSION, ReadProjectTargetsHandler,
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
from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC, FindTestsHandler
from core.tool_agent.tools.project_info import (
    PROJECT_INFO_VERSION, ProjectBinding, ProjectInfoHandler, project_info_spec,
)


def build_readonly_tool_registry(
    repo_root: str | os.PathLike,
    retrieval_port: RetrievalPort,
    *,
    knowledge_strategy: str = "bm25",
    knowledge_top_k: int = 5,
    code_search_version: str = CODE_SEARCH_VERSION,
    read_project_context_version: str = READ_PROJECT_CONTEXT_VERSION,
    project_binding: ProjectBinding | None = None,
    project_info_version: str = PROJECT_INFO_VERSION,
) -> ToolRegistry:
    """构造七个默认只读 Tool，可显式增加当前项目绑定查询。

    - calculator：无外部依赖；
    - code_search：repo_root（构造时 fail-fast 若不是目录）；
    - read_project_context：同一个 repo_root 中的有限只读源码窗口；
    - knowledge_search：retrieval_port + 系统固定 strategy / top_k。
    - get_project_info：仅在提供不可变 project_binding 时启用。
    """
    # Legacy factories retain their frozen seven-tool set. Engineering opts in
    # with the same host binding as all filesystem tools; model args cannot
    # select a root or a project from the registry.
    if project_binding is not None:
        if not isinstance(project_binding, ProjectBinding):
            raise TypeError("project_binding must be ProjectBinding or None")
        if Path(repo_root).resolve() != project_binding.root:
            raise ValueError("project_binding.root must match repo_root")
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    registry.register(
        code_search_spec(code_search_version),
        CodeSearchHandler(repo_root=repo_root, version=code_search_version),
    )
    if read_project_context_version == READ_PROJECT_CONTEXT_VERSION:
        reader_spec, reader_handler = READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler
    elif read_project_context_version == READ_PROJECT_TARGETS_VERSION:
        reader_spec, reader_handler = READ_PROJECT_TARGETS_SPEC, ReadProjectTargetsHandler
    else:
        raise ValueError(f"Unsupported read_project_context version: {read_project_context_version!r}")
    registry.register(reader_spec, reader_handler(repo_root=repo_root))
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
    registry.register(FIND_TESTS_SPEC, FindTestsHandler(repo_root=repo_root))
    if project_binding is not None:
        registry.register(project_info_spec(project_info_version), ProjectInfoHandler(
            project_binding, version=project_info_version,
        ))
    return registry
