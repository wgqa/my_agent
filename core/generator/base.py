from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document
from core.chunker.token_counter import TokenCounter


class BaseGenerator(ABC):

    MAX_CONTEXT_TOKENS = 3000

    @abstractmethod
    def generate(self, query: str, context_docs: List[Document]) -> str:
        ...

    def _build_prompt(
        self, query: str, context_docs: List[Document],
        max_context_tokens: int = 0,
    ) -> str:
        limit = max_context_tokens or self.MAX_CONTEXT_TOKENS
        counter = TokenCounter()

        parts = []
        used = 0
        for d in context_docs:
            # 兼容 Document 和 ContextBlock 两种输入
            citation = getattr(d, "citation_id", "")
            source = (
                getattr(d, "source_name", None)
                or d.metadata.get("source", "unknown")
            )
            if citation:
                block = f"{citation} [来源: {source}]\n{d.content}"
            else:
                block = f"[来源: {source}]\n{d.content}"
            block_tokens = counter.count(block)
            if used + block_tokens > limit:
                if used < limit:
                    remaining = limit - used
                    tokens = counter.encode(block)
                    parts.append(counter.decode(tokens[:remaining]))
                break
            parts.append(block)
            used += block_tokens

        context = "\n\n".join(parts)
        return f"""你是一个知识库问答助手。请根据以下提供的参考资料回答问题。
如果参考资料不足以回答问题，请如实说明。
引用规则：回答中的每个事实性结论必须用 [Cx] 标注来源，例如"缓存穿透是……[C1]"。

参考资料：
{context}

问题：{query}

请基于参考资料给出准确的回答，并在回答中引用信息来源。"""
