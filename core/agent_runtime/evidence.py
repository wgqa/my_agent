"""G3-RUNTIME-05C + G3-ADAPT-06C：多子问题检索结果的确定性证据合并。

merge_subquery_results 把每个子问题（sq1/sq2/sq3）的原始有序检索结果按
subquery_round_robin_v1 轮转合并成单个 EvidenceBundle：全局去重、轮转
贡献、截断、重新编号 citation、保留证据来源 query_id。本模块不调用
模型/检索，不比较跨子问题 BM25 分数，不读取 Dev/Holdout。

subquery_rrf_merge_v2 是 06C 新增的文档级 Reciprocal Rank Fusion：对
同一份 ranked candidate lists 按 merge_score(d)=Σ1/(merge_rrf_k+rank_i(d))
做确定性的 rank-based 融合，纯 rank、不依赖原始 retriever score。
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from core.agent_runtime.models import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    Document,
    EvidenceBundle,
    EvidenceItem,
)

SUBQUERY_ROUND_ROBIN_V1 = "subquery_round_robin_v1"
SUBQUERY_RRF_MERGE_V2 = "subquery_rrf_merge_v2"
DEFAULT_MERGE_RRF_K = 60.0
MERGE_POLICIES = (SUBQUERY_ROUND_ROBIN_V1, SUBQUERY_RRF_MERGE_V2)


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


def _require_rrf_k(value: object) -> float:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise TypeError("merge_rrf_k 必须是数字（不允许 bool）")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("merge_rrf_k 必须是有限正数")
    return float(value)


def merge_subquery_results_rrf(
    query_results,
    max_items: int,
    *,
    merge_rrf_k: float = DEFAULT_MERGE_RRF_K,
    retrieval_call_count: Optional[int] = None,
    query_count: Optional[int] = None,
    warnings: Sequence[str] = (),
    stats: Optional[dict] = None,
) -> EvidenceBundle:
    """subquery_rrf_merge_v2：文档级 Reciprocal Rank Fusion。

    对同一次多子问题检索产生的 ranked candidate lists 做文档级 rank
    fusion。对 canonical document d（runtime 层以 source_name 为文档身份）：

        merge_score(d) = Σ 1 / (merge_rrf_k + rank_i(d))

    只累加 d 真正出现的 subquery list；未出现的 subquery 贡献严格为 0。
    rank_i(d) 取 d 在该 subquery 内的最好（最小）Document.rank；生产环境
    Adapter 把 rank 设为检索列表 1-based 位置。

    排序契约：merge_score DESC → best_rank ASC → source_name ASC。runtime
    层不持有 evaluation 的 canonical 相对路径映射，故以文档源名升序作为
    确定性的 canonical 身份 tie-break（见 study-note 75 说明）。随后
    dedupe 到文档、截断到 max_items、按合并后顺序重编号 citation。
    不比较 BM25/Dense/Hybrid 原始 score，不使用 Gold/obligation/评测结果。
    """
    if type(max_items) is not int or isinstance(max_items, bool) or max_items <= 0:
        raise ValueError(f"max_items 必须是严格正整数，实际 {max_items!r}")
    k = _require_rrf_k(merge_rrf_k)

    # 1) 每个 subquery 内按文档（source_name）去重，保留最好 rank 与代表 chunk。
    sub_docs: list[tuple[str, list[tuple[str, int, Document]]]] = []
    total_chunk_candidates = 0
    for entry in query_results:
        if not (isinstance(entry, tuple) and len(entry) == 2):
            raise TypeError(
                f"query_results 每项必须是 (query_id, documents)，实际 "
                f"{type(entry).__name__}"
            )
        query_id, documents = entry
        if type(query_id) is not str or not query_id.strip():
            raise ValueError("query_id 必须是非空字符串")
        seen: dict[str, tuple[int, Document]] = {}
        for doc in documents:
            if not isinstance(doc, Document):
                raise TypeError(
                    f"documents 每项必须是 Document，实际 {type(doc).__name__}"
                )
            total_chunk_candidates += 1
            prev = seen.get(doc.source_name)
            if prev is None or doc.rank < prev[0]:
                seen[doc.source_name] = (doc.rank, doc)
        sub_docs.append(
            (query_id, [(src, rk, dc) for src, (rk, dc) in seen.items()])
        )

    # 2) 聚合跨 subquery 的文档 RRF score / best_rank / 代表 chunk。
    agg: dict[str, dict] = {}
    for sub_idx, (_query_id, doc_list) in enumerate(sub_docs):
        for src, rank, doc in doc_list:
            a = agg.get(src)
            if a is None:
                a = {
                    "score": 0.0,
                    "best_rank": rank,
                    "repr_sub_idx": sub_idx,
                    "repr_rank": rank,
                    "repr_doc": doc,
                }
                agg[src] = a
            a["score"] += 1.0 / (k + rank)
            if rank < a["best_rank"]:
                a["best_rank"] = rank
            if rank < a["repr_rank"]:
                a["repr_rank"] = rank
                a["repr_sub_idx"] = sub_idx
                a["repr_doc"] = doc

    # 3) 排序（score DESC → best_rank ASC → source_name ASC）后截断。
    ordered = sorted(
        agg.items(),
        key=lambda kv: (-kv[1]["score"], kv[1]["best_rank"], kv[0]),
    )[:max_items]

    # 4) 输出 EvidenceItem（重编号 citation）；query_id 取代表 chunk 来源 subquery。
    items: list[EvidenceItem] = []
    for citation_idx, (src, a) in enumerate(ordered, 1):
        doc = a["repr_doc"]
        query_id = sub_docs[a["repr_sub_idx"]][0]
        items.append(
            EvidenceItem(
                citation_id=f"[C{citation_idx}]",
                chunk_id=doc.chunk_id,
                document_id=doc.document_id,
                source_name=doc.source_name,
                content=doc.content,
                score=doc.score,
                rank=doc.rank,
                query_id=query_id,
            )
        )

    total_doc_occurrences = sum(len(dl) for _, dl in sub_docs)
    if stats is not None:
        stats["merge_policy"] = SUBQUERY_RRF_MERGE_V2
        stats["merge_rrf_k"] = k
        stats["input_candidate_count"] = total_chunk_candidates
        stats["document_candidate_count"] = len(agg)
        stats["duplicate_count"] = total_doc_occurrences - len(agg)
        stats["truncated"] = len(agg) > max_items

    n_sub = len(sub_docs)
    return EvidenceBundle(
        schema_version=EVIDENCE_BUNDLE_SCHEMA_VERSION,
        items=tuple(items),
        retrieval_call_count=(
            retrieval_call_count if retrieval_call_count is not None else n_sub
        ),
        query_count=(query_count if query_count is not None else n_sub),
        warnings=tuple(warnings),
    )


def merge_subquery_results_policy(
    query_results,
    max_items: int,
    *,
    merge_policy: str = SUBQUERY_ROUND_ROBIN_V1,
    merge_rrf_k: float = DEFAULT_MERGE_RRF_K,
    retrieval_call_count: Optional[int] = None,
    query_count: Optional[int] = None,
    warnings: Sequence[str] = (),
    stats: Optional[dict] = None,
) -> EvidenceBundle:
    """按 merge_policy 分发到 v1（round-robin）或 v2（RRF）。未知策略拒绝。"""
    if merge_policy == SUBQUERY_ROUND_ROBIN_V1:
        return merge_subquery_results(
            query_results,
            max_items,
            retrieval_call_count=retrieval_call_count,
            query_count=query_count,
            warnings=warnings,
            stats=stats,
        )
    if merge_policy == SUBQUERY_RRF_MERGE_V2:
        return merge_subquery_results_rrf(
            query_results,
            max_items,
            merge_rrf_k=merge_rrf_k,
            retrieval_call_count=retrieval_call_count,
            query_count=query_count,
            warnings=warnings,
            stats=stats,
        )
    raise ValueError(
        f"未知 merge_policy {merge_policy!r}（只支持 {'、'.join(MERGE_POLICIES)}）"
    )
