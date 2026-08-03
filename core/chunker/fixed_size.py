from typing import List

from core.loader.base import Document
from core.chunker.base import BaseChunker
from core.chunker.token_counter import TokenCounter


class FixedSizeChunker(BaseChunker):
    """按固定 token 数切分，带 overlap，中文友好"""

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
            tokens = self._counter.encode(doc.content)
            total = len(tokens)
            step = self.chunk_size - self.chunk_overlap

            # 空文档 / 纯空白：不生成空块
            if total == 0 or not doc.content.strip():
                continue

            # chunk_index 按文档重置
            chunk_index = 0

            if total <= self.chunk_size:
                chunked.append(self._make_chunk(doc, tokens, chunk_index, 0, total))
                continue

            start = 0
            while start < total:
                end = min(start + self.chunk_size, total)
                chunked.append(self._make_chunk(doc, tokens, chunk_index, start, end))
                chunk_index += 1
                if end == total:
                    break
                start += step

        return chunked

    def _make_chunk(
        self, doc: Document, tokens: List[int], idx: int,
        start: int, end: int,
    ) -> Document:
        return Document(
            content=self._counter.decode(tokens[start:end]),
            metadata={
                **doc.metadata,
                "chunk_index": idx,
                "token_count": end - start,
                "token_start": start,
                "token_end": end,
            },
        )
