"""G3-PLAN-03 + G3-DECOMP-04A/04B-01：Gate 3 QueryPlan / Planner / Provider 导出。

只公开必要 API：常量枚举、Subquery、QueryPlan、fallback factory、Planner
抽象接口、PlannerOutcome、严格解析入口、Prompt 常量与消息构造、Planner
调用元数据、fallback outcome 工厂与 OpenAI-compatible Provider。
本模块不反向依赖 evaluation，不承载 Router/Evidence 业务逻辑。
"""

from core.query_planning.models import (
    QUERY_PLAN_ACTIONS,
    QUERY_PLAN_CLASSIFIED_QUERY_TYPES,
    QUERY_PLAN_FALLBACK_POLICY,
    QUERY_PLAN_FALLBACK_QUERY_TYPE,
    QUERY_PLAN_QUERY_TYPES,
    QUERY_PLAN_REASON_CODES,
    QUERY_PLAN_SCHEMA_VERSION,
    Subquery,
    QueryPlan,
    build_fallback_query_plan,
)
from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
from core.query_planning.planner import (
    PLANNER_FAILURE_CODES,
    PLANNER_MODEL_ALLOWED_FIELDS,
    BaseQueryPlanner,
    PlannerCallMetadata,
    PlannerOutcome,
    build_planner_fallback_outcome,
    parse_planner_output,
)
from core.query_planning.prompt import (
    PLANNER_MAX_OUTPUT_TOKENS,
    PLANNER_MAX_RETRIES,
    PLANNER_PROMPT_SHA256,
    PLANNER_PROMPT_VERSION,
    PLANNER_SYSTEM_PROMPT,
    PLANNER_TEMPERATURE,
    PLANNER_TIMEOUT_SECONDS,
    PLANNER_USER_PAYLOAD_VERSION,
    build_planner_messages,
)

__all__ = [
    "QUERY_PLAN_SCHEMA_VERSION",
    "QUERY_PLAN_ACTIONS",
    "QUERY_PLAN_REASON_CODES",
    "QUERY_PLAN_QUERY_TYPES",
    "QUERY_PLAN_CLASSIFIED_QUERY_TYPES",
    "QUERY_PLAN_FALLBACK_QUERY_TYPE",
    "QUERY_PLAN_FALLBACK_POLICY",
    "Subquery",
    "QueryPlan",
    "build_fallback_query_plan",
    "PLANNER_FAILURE_CODES",
    "PLANNER_MODEL_ALLOWED_FIELDS",
    "BaseQueryPlanner",
    "PlannerCallMetadata",
    "PlannerOutcome",
    "build_planner_fallback_outcome",
    "parse_planner_output",
    "PLANNER_PROMPT_VERSION",
    "PLANNER_PROMPT_SHA256",
    "PLANNER_SYSTEM_PROMPT",
    "PLANNER_USER_PAYLOAD_VERSION",
    "PLANNER_TEMPERATURE",
    "PLANNER_MAX_OUTPUT_TOKENS",
    "PLANNER_TIMEOUT_SECONDS",
    "PLANNER_MAX_RETRIES",
    "build_planner_messages",
    "OpenAICompatibleQueryPlanner",
]
