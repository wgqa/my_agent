"""G4-EVAL-06A：Gate 4 Tool-Agent 强类型 Dev 评测集契约。

只提供数据模型与严格 Loader / identity / manifest 构建。不实现
Runtime、不调用 LLM、不产生运行指标。
"""

from evaluation.gate4.schema import (
    ASSERTION_TYPES,
    CATEGORIES,
    CATEGORY_COUNT_PER_TYPE,
    CODE_REFERENCE_COMMIT,
    FIRST_ACTIONS,
    GATE4_TOOL_USE_CASE_SCHEMA_VERSION,
    GATE4_TOOL_USE_MANIFEST_SCHEMA_VERSION,
    GATE4_TOOL_USE_SET_SCHEMA_VERSION,
    KNOWLEDGE_CORPUS_FILE_COUNT,
    KNOWLEDGE_CORPUS_ID,
    REFUSE_REASON_CODES,
    TERMINALS,
    TOOLS,
    CompletionAssertion,
    Gate4ToolUseCase,
    Gate4ToolUseEvaluationSet,
    KnowledgeGold,
    build_manifest,
)

__all__ = [
    "GATE4_TOOL_USE_CASE_SCHEMA_VERSION",
    "GATE4_TOOL_USE_SET_SCHEMA_VERSION",
    "GATE4_TOOL_USE_MANIFEST_SCHEMA_VERSION",
    "CATEGORIES",
    "CATEGORY_COUNT_PER_TYPE",
    "TERMINALS",
    "FIRST_ACTIONS",
    "TOOLS",
    "ASSERTION_TYPES",
    "REFUSE_REASON_CODES",
    "CODE_REFERENCE_COMMIT",
    "KNOWLEDGE_CORPUS_ID",
    "KNOWLEDGE_CORPUS_FILE_COUNT",
    "CompletionAssertion",
    "KnowledgeGold",
    "Gate4ToolUseCase",
    "Gate4ToolUseEvaluationSet",
    "build_manifest",
]
