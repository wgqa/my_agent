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
        """总 token 超预算时截断，最后一块按 token 截断"""
        total = sum(b.token_count for b in blocks)
        if total <= self.max_context_tokens:
            return blocks

        result = []
        used = 0
        for b in blocks:
            if used + b.token_count > self.max_context_tokens:
                remaining = self.max_context_tokens - used
                if remaining > 0:
                    tokens = self._counter.encode(b.content)
                    truncated = self._counter.decode(tokens[:remaining])
                    if truncated:
                        result.append(ContextBlock(
                            citation_id=b.citation_id,
                            chunk_id=b.chunk_id,
                            source_name=b.source_name,
                            page_number=b.page_number,
                            content=truncated,
                            token_count=remaining,
                            retrieval_scores=b.retrieval_scores,
                        ))
                break
            result.append(b)
            used += b.token_count
        return result
