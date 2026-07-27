import math
from typing import List


def hit_at_k(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """Hit@K: Top-K 中是否有至少一个相关文档"""
    if not relevant_ids:
        return 0.0
    return 1.0 if any(rid in relevant_ids for rid in retrieved_ids) else 0.0


def recall_at_k(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """Recall@K: 召回了多少比例的相关文档"""
    if not relevant_ids:
        return 0.0
    hits = sum(1 for rid in retrieved_ids if rid in relevant_ids)
    return hits / len(relevant_ids)


def precision_at_k(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """Precision@K: 检索结果中有多少比例是相关的"""
    if not retrieved_ids:
        return 0.0
    hits = sum(1 for rid in retrieved_ids if rid in relevant_ids)
    return hits / len(retrieved_ids)


def mrr(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """MRR: 第一个相关文档的排名倒数"""
    for i, rid in enumerate(retrieved_ids):
        if rid in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int = 5) -> float:
    """NDCG@k: 标准折损累积增益"""
    dcg = 0.0
    for i, rid in enumerate(retrieved_ids[:k]):
        if rid in relevant_ids:
            dcg += 1.0 / math.log2(i + 2)

    ideal = min(k, len(relevant_ids))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal))
    return dcg / idcg if idcg > 0 else 0.0
