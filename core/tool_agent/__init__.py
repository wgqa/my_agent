"""G4-TOOL-02：Gate 4 Structured Tool Agent 核心（纯确定性底座）。

公开 ToolSpec / ToolCall / ToolObservation / RegisteredTool / ToolRegistry /
ToolExecutor / ToolHandler 与错误码常量。本包不调用 LLM、不实现 Tool
Loop、不注册真实工具（G4-TOOLS-03/G6 才会接入 knowledge_search /
code_search / read_project_context / calculator）。
"""

from core.tool_agent.action_parser import strict_json_loads_no_duplicates
from core.tool_agent.actions import (
    ACTION_PROVIDER_ERROR,
    ACTION_TIMEOUT,
    AgentAction,
    AgentDecisionCallMetadata,
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.integration import (
    FROZEN_TOOL_MODEL,
    FROZEN_TOOL_PROVIDER,
    build_tool_agent_runtime,
)
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
    PROJECT_CONTEXT_FILE_NOT_FOUND,
    PROJECT_CONTEXT_FILE_UNREADABLE,
    PROJECT_CONTEXT_LINE_OUT_OF_RANGE,
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    UNKNOWN_TOOL,
    ToolCall,
    ToolExecutionError,
    ToolObservation,
    ToolSpec,
    json_deep_copy,
)
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.registry import (
    RegisteredTool,
    ToolHandler,
    ToolRegistry,
)
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    AGENT_DUPLICATE_TOOL_CALL,
    AGENT_TOOL_ERROR_LIMIT,
    AgentDecisionProvider,
    DecisionContextItem,
    RuntimeTraceEvent,
    ToolAgentBudget,
    ToolAgentRunResult,
)
from core.tool_agent.tools import (
    CALCULATOR_SPEC,
    CODE_SEARCH_SPEC,
    KNOWLEDGE_SEARCH_SPEC,
    READ_PROJECT_CONTEXT_SPEC,
    CalculatorHandler,
    CodeSearchHandler,
    KnowledgeSearchHandler,
    ReadProjectContextHandler,
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
    "PROJECT_CONTEXT_PATH_NOT_ALLOWED",
    "PROJECT_CONTEXT_FILE_NOT_FOUND",
    "PROJECT_CONTEXT_LINE_OUT_OF_RANGE",
    "PROJECT_CONTEXT_FILE_UNREADABLE",
    "TOOL_RESULT_INVALID",
    "TOOL_BUDGET_EXCEEDED",
    "ACTION_PARSE_FAILED",
    "ACTION_PROVIDER_ERROR",
    "ACTION_TIMEOUT",
    "AGENT_BUDGET_EXCEEDED",
    "TOOL_ERROR_CODES",
    "AGENT_ERROR_CODES",
    "TOOL_AGENT_ERROR_CODES",
    "TOOL_OBSERVATION_STATUSES",
    "ToolExecutionError",
    "json_deep_copy",
    "CALCULATOR_SPEC",
    "CODE_SEARCH_SPEC",
    "KNOWLEDGE_SEARCH_SPEC",
    "READ_PROJECT_CONTEXT_SPEC",
    "CalculatorHandler",
    "CodeSearchHandler",
    "KnowledgeSearchHandler",
    "ReadProjectContextHandler",
    "build_readonly_tool_registry",
    "build_tool_agent_runtime",
    "FROZEN_TOOL_PROVIDER",
    "FROZEN_TOOL_MODEL",
    "AgentAction",
    "ToolCallAction",
    "FinalAnswerAction",
    "RefuseAction",
    "AgentDecisionOutcome",
    "AgentDecisionCallMetadata",
    "OpenAICompatibleAgentDecisionProvider",
    "strict_json_loads_no_duplicates",
    "ToolAgentRuntime",
    "ToolAgentBudget",
    "ToolAgentRunResult",
    "DecisionContextItem",
    "RuntimeTraceEvent",
    "AgentDecisionProvider",
    "AGENT_DUPLICATE_TOOL_CALL",
    "AGENT_TOOL_ERROR_LIMIT",
]
