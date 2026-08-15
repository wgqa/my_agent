"""G4-TOOL-02：Gate 4 Structured Tool Agent 核心（纯确定性底座）。

公开 ToolSpec / ToolCall / ToolObservation / RegisteredTool / ToolRegistry /
ToolExecutor / ToolHandler 与错误码常量。本包不调用 LLM、不实现 Tool
Loop、不注册真实工具（G4-TOOLS-03 才会接入 knowledge_search /
code_search / calculator）。
"""

from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import (
    ACTION_PARSE_FAILED,
    AGENT_BUDGET_EXCEEDED,
    AGENT_ERROR_CODES,
    INVALID_TOOL_ARGUMENTS,
    TOOL_AGENT_ERROR_CODES,
    TOOL_BUDGET_EXCEEDED,
    TOOL_ERROR_CODES,
    TOOL_EXECUTION_FAILED,
    TOOL_OBSERVATION_STATUSES,
    TOOL_PERMISSION_DENIED,
    TOOL_RESULT_INVALID,
    UNKNOWN_TOOL,
    ToolCall,
    ToolObservation,
    ToolSpec,
    json_deep_copy,
)
from core.tool_agent.registry import (
    RegisteredTool,
    ToolHandler,
    ToolRegistry,
)
from core.tool_agent.tools import (
    CALCULATOR_SPEC,
    CODE_SEARCH_SPEC,
    KNOWLEDGE_SEARCH_SPEC,
    CalculatorHandler,
    CodeSearchHandler,
    KnowledgeSearchHandler,
)

__all__ = [
    "ToolSpec",
    "ToolCall",
    "ToolObservation",
    "ToolHandler",
    "RegisteredTool",
    "ToolRegistry",
    "ToolExecutor",
    "UNKNOWN_TOOL",
    "INVALID_TOOL_ARGUMENTS",
    "TOOL_PERMISSION_DENIED",
    "TOOL_EXECUTION_FAILED",
    "TOOL_RESULT_INVALID",
    "TOOL_BUDGET_EXCEEDED",
    "ACTION_PARSE_FAILED",
    "AGENT_BUDGET_EXCEEDED",
    "TOOL_ERROR_CODES",
    "AGENT_ERROR_CODES",
    "TOOL_AGENT_ERROR_CODES",
    "TOOL_OBSERVATION_STATUSES",
    "json_deep_copy",
    "CALCULATOR_SPEC",
    "CODE_SEARCH_SPEC",
    "KNOWLEDGE_SEARCH_SPEC",
    "CalculatorHandler",
    "CodeSearchHandler",
    "KnowledgeSearchHandler",
    "build_readonly_tool_registry",
]
