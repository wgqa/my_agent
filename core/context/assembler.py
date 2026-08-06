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
    """统一的 ContextBlock 渲染契约。

    有 citation：`[C1] [来源: xxx]\n正文`；无 citation：`[来源: xxx]\n正文`。
    ContextAssembler 与 BaseGenerator 共用，保证预算、生成、引用校验
    看到的是同一份渲染文本。兼容无 citation_id 的普通 Document。
    """
    citation = getattr(block, "citation_id", "") or ""
    source = (
        getattr(block, "source_name", None)
        or block.metadata.get("source_name", block.metadata.get("source", "unknown"))
    )
    if citation:
        return f"{citation} [来源: {source}]\n{block.content}"
    return f"[来源: {source}]\n{block.content}"


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
        """按最终完整渲染字符串的真实 token 数做预算。

        BPE token 不可跨字符串相加（study-notes 35），因此每次加入
        Block 都基于 `"\n\n".join(render(...))` 的真实 count 判断：
        - 完整 Block 能放下 → 直接加入；
        - 放不下 → 只截当前正文（header 完整），判断用
          已保留 Context + 分隔符 + header + content[:cut] 的真实 count；
        - 连分隔符+完整 header+一个正文字符都放不下 → 跳过。
        """
        result = []
        for b in blocks:
            candidate = result + [b]
            if self._counter.count(
                "\n\n".join(render_context_block(x) for x in candidate)
            ) <= self.max_context_tokens:
                result.append(b)
                continue
            header = f"{b.citation_id} [来源: {b.source_name or 'unknown'}]\n"
            cut = self._max_body_against_context(result, header, b.content)
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
        return result

    def _max_body_against_context(
        self, base_blocks: List[ContextBlock], header: str, content: str,
    ) -> int:
        """返回最大 cut 使 count(已保留 Context + sep + header + content[:cut])
        <= max_context_tokens；0 表示连一个正文字符都放不下。"""
        prefix = "\n\n".join(render_context_block(x) for x in base_blocks)
        if base_blocks:
            prefix += "\n\n"
        prefix += header
        if self._counter.count(prefix) >= self.max_context_tokens:
            return 0
        lo = 0
        step = 1
        probe = 1
        while probe <= len(content):
            if self._counter.count(prefix + content[:probe]) > self.max_context_tokens:
                break
            lo = probe
            if probe == len(content):
                break
            step *= 2
            probe = min(len(content), probe + step)
        while lo + 1 < probe:
            mid = (lo + probe) // 2
            if self._counter.count(prefix + content[:mid]) <= self.max_context_tokens:
                lo = mid
            else:
                probe = mid
        return lo
