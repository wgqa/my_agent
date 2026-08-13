"""G3-PLAN-03 + G3-DECOMP-04A：Gate 3 QueryPlan 契约与 Planner 输出边界导出。

只公开必要 API：常量枚举、Subquery、QueryPlan、fallback factory，以及
Planner 抽象接口、PlannerOutcome 与严格解析入口。
本模块不反向依赖 evaluation，不承载 Router/Evidence 业务逻辑。
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
from core.query_planning.planner import (
    PLANNER_FAILURE_CODES,
    PLANNER_MODEL_ALLOWED_FIELDS,
    BaseQueryPlanner,
    PlannerOutcome,
    parse_planner_output,
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
    "PLANNER_FAILURE_CODES",
    "PLANNER_MODEL_ALLOWED_FIELDS",
    "BaseQueryPlanner",
    "PlannerOutcome",
    "parse_planner_output",
]
