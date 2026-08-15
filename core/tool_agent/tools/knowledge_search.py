"""G4-TOOLS-03：knowledge_search —— 从现有技术知识库检索证据的 Tool。

复用 Gate 3 的 RetrievalPort 契约（core.agent_runtime.RetrievalPort），
不重建 Retriever / 不建索引 / 不复制 Gate 3 检索算法。strategy / top_k
由 Handler 构造时系统配置决定（v1: bm25 / 5），模型只控制 query；若注入
的 port 不支持配置的 strategy，则执行失败，不偷偷换策略。输出为受限的
matches（snippet 单条 <=500 字符，不返回完整正文、不返回本地绝对路径）。
"""

from __future__ import annotations

from typing import Any, Mapping

from core.agent_runtime import Document, RetrievalPort
from core.tool_agent.models import ToolSpec

KNOWLEDGE_SEARCH_VERSION = "knowledge_search_v1"

DEFAULT_STRATEGY = "bm25"
DEFAULT_TOP_K = 5
DEFAULT_SNIPPET_LIMIT = 500

KNOWLEDGE_SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
    "additionalProperties": False,
    "required": ["query"],
}

KNOWLEDGE_SEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "source_name": {"type": "string"},
                    "chunk_id": {"type": ["string", "null"]},
                    "score": {"type": ["number", "null"]},
                    "snippet": {"type": "string"},
                },
                "additionalProperties": False,
                "required": ["rank", "source_name", "snippet"],
            },
        },
    },
    "additionalProperties": False,
    "required": ["matches"],
}

KNOWLEDGE_SEARCH_SPEC = ToolSpec(
    name="knowledge_search",
    description=(
        "在项目的技术知识库中检索证据片段。当问题需要基于项目文档/实验资料 "
        "给出有依据的答案时使用；只接受一个 query。检索策略与条数由系统固定 "
        "（bm25 / 前 5 条），模型不能调整。返回证据片段，不是最终答案。"
    ),
    input_schema=KNOWLEDGE_SEARCH_INPUT_SCHEMA,
    output_schema=KNOWLEDGE_SEARCH_OUTPUT_SCHEMA,
    version=KNOWLEDGE_SEARCH_VERSION,
)


class KnowledgeSearchHandler:
    """ToolHandler：经注入的 RetrievalPort 检索证据。

    构造参数（strategy / top_k / snippet_limit）是系统配置，模型无法控制。
    """

    def __init__(
        self,
        retrieval_port: RetrievalPort,
        strategy: str = DEFAULT_STRATEGY,
        top_k: int = DEFAULT_TOP_K,
        snippet_limit: int = DEFAULT_SNIPPET_LIMIT,
    ) -> None:
        if not isinstance(retrieval_port, RetrievalPort) or not callable(
            getattr(retrieval_port, "search", None)
        ):
            raise TypeError("retrieval_port 必须实现 RetrievalPort（含 search）")
        self._port = retrieval_port
        self._strategy = strategy
        self._top_k = top_k
        self._snippet_limit = snippet_limit

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        query = arguments["query"]
        supported = tuple(getattr(self._port, "supported_strategies", ()))
        if self._strategy not in supported:
            # 不偷偷换策略：明确执行失败（由 Executor 转 TOOL_EXECUTION_FAILED）
            raise RuntimeError(
                f"retrieval_port 不支持 strategy={self._strategy!r}"
                f"（supported={supported}）"
            )
        docs: tuple[Document, ...] = tuple(
            self._port.search(query, self._strategy, self._top_k)
        )
        matches = []
        for rank, doc in enumerate(docs, 1):
            snippet = (doc.content or "")[: self._snippet_limit]
            matches.append(
                {
                    "rank": rank,
                    "source_name": doc.source_name,
                    "chunk_id": doc.chunk_id,
                    "score": doc.score,
                    "snippet": snippet,
                }
            )
        return {"matches": matches}
