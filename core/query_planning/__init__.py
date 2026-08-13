"""G3-PLAN-03：Gate 3 QueryPlan 强类型契约导出。

只公开必要 API：常量枚举、Subquery、QueryPlan 与 fallback factory。
本模块不反向依赖 evaluation，不承载 Planner/Router/Evidence 业务逻辑。
"""

from core.query_planning.models import (
    QUERY_PLAN_ACTIONS,
    QUERY_PLAN_FALLBACK_POLICY,
    QUERY_PLAN_QUERY_TYPES,
    QUERY_PLAN_REASON_CODES,
    QUERY_PLAN_SCHEMA_VERSION,
    Subquery,
    QueryPlan,
    build_fallback_query_plan,
)

__all__ = [
    "QUERY_PLAN_SCHEMA_VERSION",
    "QUERY_PLAN_ACTIONS",
    "QUERY_PLAN_REASON_CODES",
    "QUERY_PLAN_QUERY_TYPES",
    "QUERY_PLAN_FALLBACK_POLICY",
    "Subquery",
    "QueryPlan",
    "build_fallback_query_plan",
]
