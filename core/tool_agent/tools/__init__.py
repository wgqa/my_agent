"""G4-TOOLS-03：真实 read-only Tools（calculator / code_search / knowledge_search）。

每个 Tool = 一个 ToolSpec + 一个 ToolHandler，经 ToolRegistry / ToolExecutor
安全注册与执行。本包不调用 LLM、不实现 Tool Loop。
"""

from core.tool_agent.tools.calculator import (
    CALCULATOR_SPEC,
    CalculatorHandler,
    evaluate_expression,
)
from core.tool_agent.tools.code_search import (
    CODE_SEARCH_SPEC,
    CodeSearchHandler,
)
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
    ReadProjectContextHandler,
)
from core.tool_agent.tools.knowledge_search import (
    KNOWLEDGE_SEARCH_SPEC,
    KnowledgeSearchHandler,
)

__all__ = [
    "CALCULATOR_SPEC",
    "CalculatorHandler",
    "evaluate_expression",
    "CODE_SEARCH_SPEC",
    "CodeSearchHandler",
    "READ_PROJECT_CONTEXT_SPEC",
    "ReadProjectContextHandler",
    "KNOWLEDGE_SEARCH_SPEC",
    "KnowledgeSearchHandler",
]
