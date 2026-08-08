from typing import List

from core.loader.base import Document
from core.chunker.base import BaseChunker
from core.chunker.token_counter import TokenCounter


class FixedSizeChunker(BaseChunker):
    """按固定 token 预算切分，带 overlap。

    原始文本是事实来源：先按字符位置选候选区间，再算 token 预算，
    因此每个 chunk 都是原文的精确子串，不会切出半字符或丢内容。
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        token_counter: TokenCounter | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._counter = token_counter or TokenCounter()

    def chunk(self, documents: List[Document]) -> List[Document]:
        chunked = []

        for doc in documents:
            text = doc.content
            total = len(text)

            # 空文档 / 纯空白：不生成空块
            if total == 0 or not text.strip():
                continue

            chunk_index = 0
            start = 0
            while start < total:
                strict_end = self._counter.max_substring(text, start, self.chunk_size)
                end = self._counter.max_substring(
                    text, start, self.chunk_size, allow_oversize=True,
                )
                # 文本完整优先：单字符超过预算时放行一个完整字符并标记 oversized
                oversized = strict_end == start and end > start
                chunked.append(self._make_chunk(doc, text, chunk_index, start, end, oversized))
                chunk_index += 1
                if end >= total:
                    break
                # overlap 按 token 回退：从 end 往回找不超过 overlap token 的字符跨度
                next_start = end
                if self.chunk_overlap > 0:
                    # 使用 Counter 的 substring_start：对非单调 token count
                    # 仍然正确（找到真正合法的最左 start），cl100k 语义不变。
                    next_start = self._counter.substring_start(
                        text, end, self.chunk_overlap, min_start=start,
                    )
                # 前进保护：下一轮起点必须超过当前块起点（极端 overlap 不吃光窗口）
                start = next_start if next_start > start else end

        return chunked

    def _make_chunk(
        self, doc: Document, text: str, idx: int, start: int, end: int,
        oversized: bool = False,
    ) -> Document:
        content = text[start:end]
        return Document(
            content=content,
            metadata={
                **doc.metadata,
                "chunk_index": idx,
                "token_count": self._counter.count(content),
                "char_start": start,
                "char_end": end,
                "oversized": oversized,
            },
        )
