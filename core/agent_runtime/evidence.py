"""G3-RUNTIME-05C：多子问题检索结果的确定性证据合并。

merge_subquery_results 把每个子问题（sq1/sq2/sq3）的原始有序检索结果按
subquery_round_robin_v1 轮转合并成单个 EvidenceBundle：全局去重、轮转
贡献、截断、重新编号 citation、保留证据来源 query_id。本模块不调用
模型/检索，不比较跨子问题 BM25 分数，不读取 Dev/Holdout。
"""

from __future__ import annotations

from typing import Optional, Sequence

from core.agent_runtime.models import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    Document,
    EvidenceBundle,
    EvidenceItem,
)

SUBQUERY_ROUND_ROBIN_V1 = "subquery_round_robin_v1"


def _dedup_key(doc: Document) -> tuple:
    """全局去重键：chunk_id 非空按 chunk_id；缺失按 (source_name, content)。"""
    if doc.chunk_id is not None and doc.chunk_id.strip():
        return ("chunk", doc.chunk_id)
    return ("pair", doc.source_name, doc.content)


def merge_subquery_results(
    query_results,
    max_items: int,
    *,
    retrieval_call_count: Optional[int] = None,
    query_count: Optional[int] = None,
    warnings: Sequence[str] = (),
    stats: Optional[dict] = None,
) -> EvidenceBundle:
    """把 (query_id, documents) 序列按轮转策略合并成 EvidenceBundle。

    query_results 按 sq1 → sq2 → sq3 顺序给定；每个 (query_id, documents)
    保持该子问题内部检索排名。合并规则：
      1. 每轮每个子问题最多贡献一个尚未出现的证据；
      2. 当前候选与已入选重复时，继续向后找该子问题下一个唯一候选；
      3. chunk_id 非空按 chunk_id 全局去重，否则按 (source_name, content)；
      4. 达到 max_items 或候选耗尽即停；
      5. citation 按合并后顺序重新编号 [C1]~[Cn]；
      6. EvidenceItem.query_id = 证据首次入选时的子问题（sq1/sq2/sq3）；
      7. 不比较不同子问题之间的 BM25 分数。

    stats（可选 dict）会被填充：merge_policy / input_candidate_count /
    duplicate_count / truncated，供 Trace 事件使用。
    """
    if type(max_items) is not int or isinstance(max_items, bool) or max_items <= 0:
        raise ValueError(f"max_items 必须是严格正整数，实际 {max_items!r}")

    sub_queues = []
    total_candidates = 0
    for entry in query_results:
        if not (isinstance(entry, tuple) and len(entry) == 2):
            raise TypeError(
                f"query_results 每项必须是 (query_id, documents)，实际 "
                f"{type(entry).__name__}"
            )
        query_id, documents = entry
        if type(query_id) is not str or not query_id.strip():
            raise ValueError("query_id 必须是非空字符串")
        qlist = []
        for doc in documents:
            if not isinstance(doc, Document):
                raise TypeError(
                    f"documents 每项必须是 Document，实际 {type(doc).__name__}"
                )
            qlist.append((doc, _dedup_key(doc)))
        total_candidates += len(qlist)
        sub_queues.append((query_id, qlist))

    items: list[EvidenceItem] = []
    seen: set[tuple] = set()
    pointers = [0] * len(sub_queues)
    duplicate_count = 0

    while len(items) < max_items:
        added_this_round = 0
        for i, (query_id, qlist) in enumerate(sub_queues):
            if len(items) >= max_items:
                break
            j = pointers[i]
            while j < len(qlist):
                doc, key = qlist[j]
                j += 1
                if key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                items.append(
                    EvidenceItem(
                        citation_id=f"[C{len(items) + 1}]",
                        chunk_id=doc.chunk_id,
                        document_id=doc.document_id,
                        source_name=doc.source_name,
                        content=doc.content,
                        score=doc.score,
                        rank=doc.rank,
                        query_id=query_id,
                    )
                )
                pointers[i] = j
                added_this_round += 1
                break
            else:
                pointers[i] = j
        if added_this_round == 0:
            break

    all_processed = True
    for i, pointer in enumerate(pointers):
        if pointer < len(sub_queues[i][1]):
            all_processed = False
            break
    truncated = len(items) >= max_items and not all_processed

    if stats is not None:
        stats["merge_policy"] = SUBQUERY_ROUND_ROBIN_V1
        stats["input_candidate_count"] = total_candidates
        stats["duplicate_count"] = duplicate_count
        stats["truncated"] = truncated

    n_sub = len(sub_queues)
    return EvidenceBundle(
        schema_version=EVIDENCE_BUNDLE_SCHEMA_VERSION,
        items=tuple(items),
        retrieval_call_count=(
            retrieval_call_count if retrieval_call_count is not None else n_sub
        ),
        query_count=(query_count if query_count is not None else n_sub),
        warnings=tuple(warnings),
    )
