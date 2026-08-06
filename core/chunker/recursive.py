from typing import List

from core.loader.base import Document
from core.chunker.base import BaseChunker
from core.chunker.token_counter import TokenCounter


class RecursiveChunker(BaseChunker):
    """按分隔符优先级递归分割，保留语义边界，带真实 overlap。

    原始文本是事实来源：先按分隔符切出字符级语义段，再按 token 预算组装，
    chunk 永远是原文的精确子串，不丢标点/汉字/Emoji。
    """

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
            text = doc.content
            if not text or not text.strip():
                continue

            # 语义段（字符级，分隔符保留在段尾）→ 全局字符区间
            seg_ranges = []
            pos = 0
            for seg in self._split_text(text, self.SEPARATORS, 0):
                seg_ranges.append((pos, pos + len(seg)))
                pos += len(seg)

            # 超长段按 token 预算判断（字符数 ≠ token 数），在段内硬切；
            # 下一片起点从上一片终点回退 chunk_overlap 个 token（真实重叠，
            # 不越出语义段；chunk_size 覆盖不了 overlap 时退化为无重叠）
            overlap_limit = min(self.chunk_overlap, self.chunk_size - 1)
            pieces = []
            for (s, e) in seg_ranges:
                if self._counter.count(text[s:e]) <= self.chunk_size:
                    pieces.append((s, e))
                else:
                    p = s
                    while p < e:
                        q = self._counter.max_substring(
                            text, p, self.chunk_size, end=e, allow_oversize=True,
                        )
                        pieces.append((p, q))
                        if q >= e:
                            break
                        p = self._counter.substring_start(
                            text, q, overlap_limit, min_start=s,
                        )

            # 按预算组装：完整候选文本重新计数（BPE token 不可严格相加）；
            # 超预算时块终点 = 上一片终点（重叠区保留在前一块）；
            # 普通换块时新块起点向上一块末尾回退（真实 overlap，见
            # _next_block_start），硬切已回退的 pieces 不叠加第二层
            merged = []
            acc_start = pieces[0][0]
            for i, (s, e) in enumerate(pieces):
                if self._counter.count(text[acc_start:e]) > self.chunk_size:
                    if i > 0:
                        merged.append((acc_start, pieces[i - 1][1]))
                        acc_start = self._next_block_start(
                            text, pieces[i - 1][0], pieces[i - 1][1], s, e,
                        )
                    else:
                        acc_start = s
            if acc_start < pieces[-1][1]:
                merged.append((acc_start, pieces[-1][1]))

            for i, (start, end) in enumerate(merged):
                # 文本完整优先：严格预算放不下但放行单字符时标记 oversized
                strict_end = self._counter.max_substring(text, start, self.chunk_size)
                oversized = strict_end == start and end > start
                chunked.append(self._make_chunk(doc, text, i, start, end, oversized))
        return chunked

    def _next_block_start(
        self, text: str, prev_start: int, block_end: int,
        cur_start: int, cur_end: int,
    ) -> int:
        """普通换块的新块起点：向上一块末尾回退。

        - 重叠 ≤ chunk_overlap（substring_start 保证 count(text[start:block_end])
          ≤ chunk_overlap，且取最左可行点 = 重叠尽量接近配置）；
        - 新块（含当前片）≤ chunk_size：取含当前片不超预算的最左起点
          （substring_start(text, cur_end, chunk_size)），若完整 overlap
          会超预算则自动缩小；
        - 不越过上一片起点（min_start=prev_start），当前片完整保留；
        - 对最终候选子串重新计数，不做 count(overlap)+count(piece) 相加。
        """
        if self.chunk_overlap <= 0:
            return cur_start
        lo = self._counter.substring_start(
            text, cur_end, self.chunk_size, min_start=prev_start,
        )
        ov = self._counter.substring_start(
            text, block_end, self.chunk_overlap, min_start=prev_start,
        )
        # max(lo, ov)：重叠不超过配置（ov 是最左可行，任何更右起点重叠更小），
        # 同时含当前片不超预算（lo 保证）
        return max(lo, ov)

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
        pending = ""
        for i, part in enumerate(parts):
            # 继续用更深层的分隔符切分
            sub = self._split_text(part, separators, depth + 1)
            if sub:
                # 前导空 part 产生的分隔符附加到下一个子段开头（否则字符丢失）
                if pending:
                    sub[0] = pending + sub[0]
                    pending = ""
                result.extend(sub)
            # 分隔符附到最后一个子段上；前面没有内容时先缓存
            if i < len(parts) - 1:
                if result:
                    result[-1] = result[-1] + sep
                else:
                    pending += sep
        # 全文只含分隔符（如 "."、"。。。")：缓存的 pending 也要保留，
        # 否则 seg_ranges 为空导致 pieces 为空、后续 IndexError
        if not result and pending:
            return [pending]
        return result

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
