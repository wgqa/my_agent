from dataclasses import dataclass, field
from typing import List, Optional

from core.loader.base import Document
from core.chunker.token_counter import TokenCounter


@dataclass
class ContextBlock:
    """一条可引用的上下文单元"""
    citation_id: str          # [C1], [C2]...
    chunk_id: str
    source_name: str
    page_number: Optional[int]
    content: str
    token_count: int
    retrieval_scores: dict = field(default_factory=dict)


def render_context_block(block) -> str:
    """统一的 ContextBlock 渲染契约：`[C1] [来源: xxx]\n正文`。

    ContextAssembler 与 BaseGenerator 共用，保证预算、生成、引用校验
    看到的是同一份渲染文本。兼容无 citation_id 的普通 Document。
    """
    citation = getattr(block, "citation_id", "") or ""
    source = (
        getattr(block, "source_name", None)
        or block.metadata.get("source_name", block.metadata.get("source", "unknown"))
    )
    return f"{citation} [来源: {source}]\n{block.content}"


class ContextAssembler:
    """把检索结果组装成带预算、去重、稳定引用的 ContextBlock 列表"""

    def __init__(
        self,
        max_context_tokens: int = 3000,
        max_doc_ratio: float = 0.5,
        token_counter: TokenCounter | None = None,
    ):
        self.max_context_tokens = max_context_tokens
        self.max_doc_ratio = max_doc_ratio
        self._counter = token_counter or TokenCounter()

    def assemble(self, hits: List[Document]) -> List[ContextBlock]:
        """输入检索结果，输出带引用编号的 ContextBlock 列表"""
        # 1. 按检索分数排序：有 rerank_score 时优先（rerank 顺序不被稠密分数覆盖）
        ordered = sorted(
            hits,
            key=lambda d: d.metadata.get("rerank_score", d.metadata.get("score", 0.0)),
            reverse=True,
        )

        # 2. 去重：相同 content 只保留一个
        seen_content = set()
        blocks = []
        for d in ordered:
            if d.content in seen_content:
                continue
            seen_content.add(d.content)

            citation_id = f"[C{len(blocks) + 1}]"
            blocks.append(ContextBlock(
                citation_id=citation_id,
                chunk_id=d.metadata.get("id", ""),
                source_name=d.metadata.get("source_name", d.metadata.get("source", "unknown")),
                page_number=d.metadata.get("page_num"),
                content=d.content,
                token_count=self._counter.count(d.content),
                retrieval_scores={
                    "score": d.metadata.get("rerank_score", d.metadata.get("score", 0.0)),
                    "rank": d.metadata.get("final_rank", d.metadata.get("rank")),
                },
            ))

        # 3. 单文档占比限制：防止一个文档垄断上下文
        blocks = self._limit_doc_share(blocks)

        # 4. token 预算截断
        blocks = self._truncate_to_budget(blocks)

        return blocks

    def _limit_doc_share(self, blocks: List[ContextBlock]) -> List[ContextBlock]:
        """每个文档的内容占比不超过 max_doc_ratio（首块超限时至少保留一块）"""
        cap = int(self.max_context_tokens * self.max_doc_ratio)
        used: dict = {}
        kept = []
        for b in blocks:
            doc_used = used.get(b.source_name, 0)
            if doc_used == 0:
                # 该文档第一块：无论多大都保留（否则整个文档消失）
                used[b.source_name] = b.token_count
                kept.append(b)
            elif doc_used + b.token_count > cap:
                continue
            else:
                used[b.source_name] = doc_used + b.token_count
                kept.append(b)
        return kept

    def _truncate_to_budget(self, blocks: List[ContextBlock]) -> List[ContextBlock]:
        """按渲染后文本预算：citation + 来源头 + 换行 + 正文 + 块间双换行。

        header 必须完整保留，只允许安全截断正文（渲染前缀二分，
        用真实 count(header + content[:cut]) 判断，不做 token decode）；
        连完整头部+至少一个正文字符都放不下则跳过该块。
        """
        sep = "\n\n"
        sep_tokens = self._counter.count(sep)
        result = []
        used = 0
        for b in blocks:
            header = f"{b.citation_id} [来源: {b.source_name or 'unknown'}]\n"
            header_tokens = self._counter.count(header)
            sep_cost = sep_tokens if result else 0
            remaining = self.max_context_tokens - used - sep_cost
            if remaining <= header_tokens:
                continue
            cut = self._max_body_for_header(header, b.content, remaining)
            if cut <= 0:
                continue
            truncated = b.content[:cut]
            result.append(ContextBlock(
                citation_id=b.citation_id,
                chunk_id=b.chunk_id,
                source_name=b.source_name,
                page_number=b.page_number,
                content=truncated,
                token_count=self._counter.count(truncated),
                retrieval_scores=b.retrieval_scores,
            ))
            used += sep_cost + self._counter.count(header + truncated)
        return result

    def _max_body_for_header(self, header: str, content: str, remaining: int) -> int:
        """返回最大 cut 使 count(header + content[:cut]) <= remaining（0 表示放不下）"""
        lo = 0
        step = 1
        probe = 1
        while probe <= len(content):
            if self._counter.count(header + content[:probe]) > remaining:
                break
            lo = probe
            if probe == len(content):
                break
            step *= 2
            probe = min(len(content), probe + step)
        while lo + 1 < probe:
            mid = (lo + probe) // 2
            if self._counter.count(header + content[:mid]) <= remaining:
                lo = mid
            else:
                probe = mid
        return lo
