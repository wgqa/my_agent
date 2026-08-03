from typing import List

from core.loader.base import Document
from core.chunker.base import BaseChunker
from core.chunker.token_counter import TokenCounter


class RecursiveChunker(BaseChunker):
    """按分隔符优先级递归分割，保留语义边界，带真实 overlap"""

    SEPARATORS = ["\n\n", "\n", "。", ".", " ", ""]

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
            # 空文档 / 纯空白：不生成空块
            if not tokens or not doc.content.strip():
                continue
            chunks = self._split_tokens(tokens, 0, len(tokens))
            for i, (start, end) in enumerate(chunks):
                chunked.append(self._make_chunk(doc, tokens, i, start, end))
        return chunked

    def _split_tokens(
        self, tokens: List[int], start: int, end: int,
    ) -> List[tuple[int, int]]:
        """按分隔符优先切分 token 区间，带 overlap"""
        span = end - start
        if span <= self.chunk_size:
            return [(start, end)]

        text = self._counter.decode(tokens[start:end])
        segments = self._split_text(text, self.SEPARATORS, 0)

        # 每个 segment 单独编码，得到精确的 token 位置
        pos = start
        merged = []
        acc_segs = []
        acc_tokens = 0

        for seg in segments:
            seg_len = len(self._counter.encode(seg))
            if acc_tokens + seg_len <= self.chunk_size:
                acc_segs.append(seg)
                acc_tokens += seg_len
            else:
                if acc_segs:
                    end_pos = pos + acc_tokens
                    merged.append((pos, end_pos))
                    pos = end_pos
                # 单个 segment 超长：硬切
                if seg_len > self.chunk_size:
                    seg_tokens = self._counter.encode(seg)
                    seg_start = pos
                    seg_end = seg_start + seg_len
                    merged.extend(self._hard_split(tokens, seg_start, seg_end))
                    pos = seg_end
                    acc_segs = []
                    acc_tokens = 0
                else:
                    acc_segs = [seg]
                    acc_tokens = seg_len

        if acc_segs:
            merged.append((pos, pos + acc_tokens))

        # 加 overlap：相邻块向前扩展
        final = []
        for i, (s, e) in enumerate(merged):
            if i > 0 and self.chunk_overlap > 0:
                prev_end = merged[i - 1][1]
                overlap_start = max(s, prev_end - self.chunk_overlap)
                if overlap_start < s:
                    s = overlap_start
            final.append((s, e))
        return final

    def _split_text(self, text: str, separators: List[str], depth: int) -> List[str]:
        """递归按分隔符切分文本，保留分隔符在片段末尾"""
        if depth >= len(separators) or not text:
            return [text] if text else []

        sep = separators[depth]
        if not sep:
            return [text] if text else []

        parts = text.split(sep)
        if len(parts) <= 1:
            return self._split_text(text, separators, depth + 1)

        result = []
        for i, part in enumerate(parts):
            # 继续用更深层的分隔符切分
            sub = self._split_text(part, separators, depth + 1)
            if sub:
                result.extend(sub)
            # 分隔符附到最后一个子段上
            if i < len(parts) - 1 and result:
                result[-1] = result[-1] + sep
        return result

    def _hard_split(
        self, tokens: List[int], start: int, end: int,
    ) -> List[tuple[int, int]]:
        """按 token 硬切，带 overlap"""
        span = end - start
        if span <= self.chunk_size:
            return [(start, end)]

        step = self.chunk_size - self.chunk_overlap
        chunks = []
        s = start

        while s < end:
            e = min(s + self.chunk_size, end)
            chunks.append((s, e))
            s = s + step
            leftover = end - s
            if leftover > 0 and leftover < self.chunk_size * 0.3:
                break

        return chunks

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
