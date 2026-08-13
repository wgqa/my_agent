"""G3-DECOMP-04A：Planner 结构化输出边界、严格解析与统一 Fallback。

在 QueryPlan/Subquery 强类型契约之上建立不可信 Planner 输出边界：
输入是模型未来可能返回的原始 JSON 字符串，输出只能是正常 QueryPlan
或系统生成的确定性 single_retrieval fallback。本任务不接入真实 LLM、
不写正式 Prompt、不运行 Dev/Holdout 指标。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from core.query_planning.models import (
    QUERY_PLAN_FALLBACK_POLICY,
    QUERY_PLAN_SCHEMA_VERSION,
    Subquery,
    QueryPlan,
    build_fallback_query_plan,
)

PLANNER_FAILURE_CODES = (
    "PLAN_EMPTY",
    "PLAN_INVALID_SCHEMA",
    "PLAN_OVER_DECOMPOSE",
    "PLAN_UNDER_DECOMPOSE",
    "PLAN_DUPLICATE_SUBQUERY",
    # 后续 G3-DECOMP-04B 使用，本任务只声明不主动产生：
    "PLAN_NEW_ENTITY",
    "PLANNER_TIMEOUT",
)

# 模型输出顶层的唯一允许字段集合；其余任何字段（含 original_query /
# schema_version / plan_id / fallback_policy 等身份字段，以及检索策略、
# 候选池、重排开关、检索轮数、评测标签等越界字段）都视为未知字段。
PLANNER_MODEL_ALLOWED_FIELDS = frozenset({
    "query_type",
    "retrieval_required",
    "action",
    "reason_code",
    "subqueries",
})

_PLANNER_FAILURE_CODE_SET = frozenset(PLANNER_FAILURE_CODES)


class _DuplicateKeyError(ValueError):
    """JSON 解析时检测到重复 key。"""


def _object_pairs_no_duplicates(pairs):
    """object_pairs_hook：任何嵌套层级的重复 key 都直接失败。

    避免接受 json.loads 默认的“后值覆盖前值”行为。
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"重复 JSON key: {key!r}")
        result[key] = value
    return result


class BaseQueryPlanner(ABC):
    """Planner 最小抽象接口：从原问题产出 PlannerOutcome。

    只负责“是否检索、是否分解、分解成什么”，不负责检索策略与预算。
    本任务只定义接口，不实现真实模型 Planner。
    """

    @abstractmethod
    def plan(self, original_query: str) -> "PlannerOutcome":
        """对单个原问题做规划并返回结构化结果。"""
        raise NotImplementedError


@dataclass(frozen=True)
class PlannerOutcome:
    """Planner 结果：正常 QueryPlan 或系统生成的 fallback。

    normal：fallback_used=False、failure_code=None、reason_code 非
    PLANNER_FALLBACK。fallback：fallback_used=True、failure_code 必须
    是允许枚举、plan 必须是单次检索 PLANNER_FALLBACK。构造时 fail-fast。

    to_dict() 不含 raw_output、完整异常、traceback、Prompt 或思维链。
    """

    plan: QueryPlan
    fallback_used: bool
    failure_code: Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, QueryPlan):
            raise TypeError(
                f"plan 必须是 QueryPlan，实际 {type(self.plan).__name__}"
            )
        if type(self.fallback_used) is not bool:
            raise TypeError(
                f"fallback_used 必须是严格 bool，实际 "
                f"{type(self.fallback_used).__name__}"
            )
        if self.failure_code is not None:
            if type(self.failure_code) is not str:
                raise TypeError(
                    f"failure_code 必须是字符串或 None，实际 "
                    f"{type(self.failure_code).__name__}"
                )
            if self.failure_code not in _PLANNER_FAILURE_CODE_SET:
                raise ValueError(
                    f"failure_code 必须是 {', '.join(PLANNER_FAILURE_CODES)} "
                    f"之一，实际 {self.failure_code!r}"
                )

        if self.fallback_used:
            if self.failure_code is None:
                raise ValueError("fallback 结果必须带 failure_code")
            if self.plan.reason_code != "PLANNER_FALLBACK":
                raise ValueError(
                    "fallback 结果的 plan.reason_code 必须为 PLANNER_FALLBACK"
                )
            if self.plan.action != "single_retrieval":
                raise ValueError(
                    "fallback 结果的 plan.action 必须为 single_retrieval"
                )
            if self.plan.retrieval_required is not True:
                raise ValueError(
                    "fallback 结果的 plan.retrieval_required 必须为 true"
                )
            if self.plan.subqueries:
                raise ValueError("fallback 结果的 plan.subqueries 必须为空")
        else:
            if self.failure_code is not None:
                raise ValueError("正常结果不允许带 failure_code")
            if self.plan.reason_code == "PLANNER_FALLBACK":
                raise ValueError(
                    "正常结果的 plan.reason_code 不能为 PLANNER_FALLBACK"
                )

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.to_dict(),
            "fallback_used": self.fallback_used,
            "failure_code": self.failure_code,
        }


def parse_planner_output(
    *,
    original_query: str,
    raw_output: str,
) -> PlannerOutcome:
    """严格解析模型输出：正常 QueryPlan 或确定性 fallback。

    解析开始先用 build_fallback_query_plan(original_query) 构造并缓存
    fallback plan（其 query_type 固定为系统专属 unknown）。original_query
    非法属于调用方错误，直接抛 TypeError/ValueError，不会被误判成模型
    输出错误；模型无权提供或覆盖 fallback 类型。
    """
    fallback_plan = build_fallback_query_plan(original_query)

    if type(raw_output) is not str:
        raise TypeError(
            f"raw_output 必须是字符串（后端接口契约），实际 "
            f"{type(raw_output).__name__}"
        )
    if not raw_output.strip():
        return _make_fallback(fallback_plan, "PLAN_EMPTY")

    try:
        obj = json.loads(
            raw_output, object_pairs_hook=_object_pairs_no_duplicates
        )
    except (json.JSONDecodeError, _DuplicateKeyError):
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    if not isinstance(obj, dict):
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    extra = sorted(set(obj) - PLANNER_MODEL_ALLOWED_FIELDS)
    if extra:
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")
    missing = sorted(PLANNER_MODEL_ALLOWED_FIELDS - set(obj))
    if missing:
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    # PLANNER_FALLBACK 是系统拥有的状态，模型无权主动声明。
    if obj["reason_code"] == "PLANNER_FALLBACK":
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    action = obj["action"]
    subqueries_raw = obj["subqueries"]

    if type(action) is not str:
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")
    if not isinstance(subqueries_raw, list):
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    if action == "decomposed_retrieval":
        if len(subqueries_raw) > 3:
            return _make_fallback(fallback_plan, "PLAN_OVER_DECOMPOSE")
        if len(subqueries_raw) < 2:
            return _make_fallback(fallback_plan, "PLAN_UNDER_DECOMPOSE")

    try:
        subqueries = tuple(Subquery.from_dict(item) for item in subqueries_raw)
    except (TypeError, ValueError):
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    if action == "decomposed_retrieval":
        queries = [s.query for s in subqueries]
        if len(set(queries)) != len(queries):
            return _make_fallback(fallback_plan, "PLAN_DUPLICATE_SUBQUERY")

    try:
        plan = QueryPlan.create(
            original_query=original_query,
            query_type=obj["query_type"],
            retrieval_required=obj["retrieval_required"],
            action=action,
            reason_code=obj["reason_code"],
            subqueries=subqueries,
        )
    except (TypeError, ValueError):
        return _make_fallback(fallback_plan, "PLAN_INVALID_SCHEMA")

    return PlannerOutcome(plan=plan, fallback_used=False, failure_code=None)


def _make_fallback(fallback_plan: QueryPlan, failure_code: str) -> PlannerOutcome:
    return PlannerOutcome(
        plan=fallback_plan,
        fallback_used=True,
        failure_code=failure_code,
    )
