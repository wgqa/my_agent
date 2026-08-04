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
                end = self._counter.max_substring(text, start, self.chunk_size)
                chunked.append(self._make_chunk(doc, text, chunk_index, start, end))
                chunk_index += 1
                if end >= total:
                    break
                # overlap 按字符位置向前回退
                start = end if self.chunk_overlap == 0 else max(start, end - self.chunk_overlap)

        return chunked

    def _make_chunk(
        self, doc: Document, text: str, idx: int, start: int, end: int,
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
            },
        )
