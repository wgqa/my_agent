"""G3-ADAPT-06A：确定性 Adaptive Retrieval Policy v1。

按 QueryPlan 的 action / query_type / reason_code 与 Retriever 的能力声明
（supported_strategies）确定性选择初始检索策略与固定原因码。本模块不调用
LLM，不读取 Dev/Holdout，不产生随机结果。
"""

from __future__ import annotations

from core.query_planning import (
    QUERY_PLAN_FALLBACK_QUERY_TYPE,
    QUERY_PLAN_FALLBACK_POLICY,
    QUERY_PLAN_REASON_CODES,
)

ADAPTIVE_RETRIEVAL_POLICY_VERSION = "adaptive_retrieval_policy_v1"

# 检索策略枚举（RouteDecision v2 扩展后）。
RETRIEVAL_STRATEGIES = ("none", "bm25", "hybrid")

# Router 的策略原因码（固定枚举，与 Planner 的 reason_code 分开）。
STRATEGY_REASON_CODES = (
    "DIRECT_NO_RETRIEVAL",
    "PLANNER_FALLBACK_BM25",
    "LEXICAL_EXACT_BM25",
    "COMPLEX_SEMANTIC_HYBRID",
    "DECOMPOSED_BM25_PRIMARY",
    "CAPABILITY_FALLBACK_BM25",
)

# 语义较复杂、single 时优先尝试 Hybrid 的类型；能力不支持则显式降级 BM25。
_HYBRID_PREFERRED_TYPES = frozenset({
    "comparison",
    "causal",
    "multi_entity",
    "troubleshooting",
    "unanswerable_or_no_retrieval",
})


def resolve_initial_strategy(plan, supported_strategies) -> tuple[str, str]:
    """确定性策略：返回 (strategy, strategy_reason_code)。

    规则：
      no_retrieval                            → none / DIRECT_NO_RETRIEVAL
      decomposed_retrieval                    → bm25 / DECOMPOSED_BM25_PRIMARY
      Planner fallback（unknown）             → bm25 / PLANNER_FALLBACK_BM25
      fact / code_symbol（single）            → bm25 / LEXICAL_EXACT_BM25
      comparison/causal/multi_entity/
        troubleshooting/unanswerable 且要求检索（single）
                                              → hybrid / COMPLEX_SEMANTIC_HYBRID
                                                若 hybrid 不支持 → bm25 / CAPABILITY_FALLBACK_BM25
    """
    supported = frozenset(supported_strategies or ())
    action = plan.action

    if action == "no_retrieval":
        return "none", "DIRECT_NO_RETRIEVAL"
    if action == "decomposed_retrieval":
        return "bm25", "DECOMPOSED_BM25_PRIMARY"
    if (
        plan.reason_code == "PLANNER_FALLBACK"
        or plan.query_type == QUERY_PLAN_FALLBACK_QUERY_TYPE
    ):
        return "bm25", "PLANNER_FALLBACK_BM25"
    if plan.query_type in ("fact", "code_symbol"):
        return "bm25", "LEXICAL_EXACT_BM25"
    if plan.query_type in _HYBRID_PREFERRED_TYPES:
        if "hybrid" in supported:
            return "hybrid", "COMPLEX_SEMANTIC_HYBRID"
        return "bm25", "CAPABILITY_FALLBACK_BM25"
    return "bm25", "LEXICAL_EXACT_BM25"
