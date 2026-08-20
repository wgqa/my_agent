"""G4-TOOLS-03：knowledge_search —— 从独立技术知识库检索证据的 Tool。

复用 Gate 3 的 RetrievalPort 契约（core.agent_runtime.RetrievalPort），
不重建 Retriever / 不建索引 / 不复制 Gate 3 检索算法。strategy / top_k
由 Handler 构造时系统配置决定（v1: bm25 / 5），模型只控制 query；若注入
的 port 不支持配置的 strategy，则执行失败，不偷偷换策略。输出为受限的
matches（snippet 单条 <=500 字符，不返回完整正文、不返回本地绝对路径）。
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.agent_runtime import Document, RetrievalPort
from core.tool_agent.models import ToolSpec

KNOWLEDGE_SEARCH_VERSION = "knowledge_search_v2"

DEFAULT_STRATEGY = "bm25"
DEFAULT_TOP_K = 5
DEFAULT_SNIPPET_LIMIT = 500
TOP_K_MAX = 5
SNIPPET_LIMIT_MAX = 500

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
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "source_name": {"type": "string"},
                    "chunk_id": {"type": ["string", "null"]},
                    "score": {"type": ["number", "null"]},
                    "snippet": {"type": "string", "maxLength": 500},
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
        "在系统预先索引的独立技术知识库中检索证据片段。当问题需要该知识库中的"
        "技术资料或实验资料时使用；它不是当前绑定 Engineering Project 的源码、README、"
        "配置、SQL 或测试索引。不要用它回答当前仓库如何实现的问题；这类问题使用 "
        "code_search 和 read_project_context；它不能替代当前项目的 Engineering Evidence，"
        "也不能标记当前项目义务为已覆盖。只接受一个 query。"
        "检索策略与条数由系统固定（bm25 / 前 5 条），模型不能调整。返回证据片段，"
        "不是最终答案。"
    ),
    input_schema=KNOWLEDGE_SEARCH_INPUT_SCHEMA,
    output_schema=KNOWLEDGE_SEARCH_OUTPUT_SCHEMA,
    version=KNOWLEDGE_SEARCH_VERSION,
)


def _is_absolute_provenance(source_name: str) -> bool:
    """跨平台 provenance 检查：POSIX 绝对、Windows drive/UNC/verbatim 绝对一律拒绝。

    用标准库 PurePosixPath / PureWindowsPath 的路径语义（而非堆 drive-letter
    regex）；对任何 Windows rooted/UNC-like 前缀额外 fail-closed。
    """
    if PurePosixPath(source_name).is_absolute():
        return True
    if PureWindowsPath(source_name).is_absolute():
        return True
    if source_name.startswith("\\"):
        return True
    return False


def _require_strict_int_range(value: object, label: str, lo: int, hi: int) -> None:
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(
            f"{label} 必须是严格 int（不允许 bool），实际 {type(value).__name__}"
        )
    if not (lo <= value <= hi):
        raise ValueError(f"{label} 必须在 {lo}~{hi} 之间，实际 {value}")


class KnowledgeSearchHandler:
    """ToolHandler：经注入的 RetrievalPort 检索证据。

    构造参数（strategy / top_k / snippet_limit）是系统配置，模型无法控制；
    Tool 自己 enforce output boundary：即使 backend 返回超出 top_k 的条目，
    最终 matches 也强制截断到 top_k，不信任 backend 自觉。
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
        if not isinstance(strategy, str) or not strategy.strip():
            raise ValueError("strategy 必须是非空字符串")
        _require_strict_int_range(top_k, "top_k", 1, TOP_K_MAX)
        _require_strict_int_range(snippet_limit, "snippet_limit", 1, SNIPPET_LIMIT_MAX)
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
        # Tool 强制截断：不信任 backend 只返回 top_k 条
        docs = docs[: self._top_k]
        matches = []
        for rank, doc in enumerate(docs, 1):
            if _is_absolute_provenance(doc.source_name):
                # fail-closed：不把本地绝对路径放进 success Observation
                # （错误消息不回显原始路径，避免 provenance 泄漏）
                raise ValueError("unsafe source provenance（本地绝对路径被拒绝）")
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
