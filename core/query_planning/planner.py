"""G3-DECOMP-04A + 04B-01：Planner 结构化输出边界、严格解析与统一 Fallback。

在 QueryPlan/Subquery 强类型契约之上建立不可信 Planner 输出边界：
输入是模型未来可能返回的原始 JSON 字符串，输出只能是正常 QueryPlan
或系统生成的确定性 single_retrieval fallback。本模块还定义 Planner 调用
元数据（PlannerCallMetadata）与 Provider 失败代码（PLANNER_TIMEOUT /
PLANNER_PROVIDER_ERROR）。本模块不接入真实 LLM。
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from core.query_planning.models import (
    QueryPlan,
    Subquery,
    build_fallback_query_plan,
)

PLANNER_FAILURE_CODES = (
    "PLAN_EMPTY",
    "PLAN_INVALID_SCHEMA",
    "PLAN_OVER_DECOMPOSE",
    "PLAN_UNDER_DECOMPOSE",
    "PLAN_DUPLICATE_SUBQUERY",
    "PLANNER_PROVIDER_ERROR",
    # 后续任务使用，本文件只声明不主动产生：
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
_HEX = frozenset("0123456789abcdef")


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
class PlannerCallMetadata:
    """一次 Planner 模型调用的观测元数据。

    不参与 plan_id；不包含 API Key、Authorization、base_url 秘密参数、
    raw model output、traceback、完整异常字符串或思维链。
    """

    provider: str
    model: str
    prompt_version: str
    prompt_sha256: str
    call_count: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        for label in ("provider", "model", "prompt_version"):
            value = getattr(self, label)
            if type(value) is not str:
                raise TypeError(
                    f"{label} 必须是字符串，实际 {type(value).__name__}"
                )
            if not value.strip():
                raise ValueError(f"{label} 不能为空或只含空白")
            if value != value.strip():
                raise ValueError(f"{label} 首尾不允许空白")
        sha = self.prompt_sha256
        if type(sha) is not str:
            raise TypeError("prompt_sha256 必须是字符串")
        if len(sha) != 64 or any(c not in _HEX for c in sha):
            raise ValueError("prompt_sha256 必须是 64 位小写十六进制")
        if type(self.call_count) is not int or isinstance(self.call_count, bool):
            raise TypeError("call_count 必须是严格 int（不允许 bool）")
        if self.call_count != 1:
            raise ValueError("call_count 当前版本必须等于 1")
        for label in ("input_tokens", "output_tokens"):
            value = getattr(self, label)
            if value is not None:
                if type(value) is not int or isinstance(value, bool):
                    raise TypeError(
                        f"{label} 必须是 None 或非负严格 int（不允许 bool）"
                    )
                if value < 0:
                    raise ValueError(f"{label} 必须非负")
        latency = self.latency_ms
        if isinstance(latency, bool) or type(latency) not in (int, float):
            raise TypeError("latency_ms 必须是有限非负数字（不允许 bool）")
        if not math.isfinite(latency):
            raise ValueError("latency_ms 必须是有限数字（不允许 NaN/inf）")
        if latency < 0:
            raise ValueError("latency_ms 必须非负")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "call_count": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class PlannerOutcome:
    """Planner 结果：正常 QueryPlan 或系统生成的 fallback。

    normal：fallback_used=False、failure_code=None、reason_code 非
    PLANNER_FALLBACK。fallback：fallback_used=True、failure_code 必须
    是允许枚举、plan 必须是单次检索 PLANNER_FALLBACK。构造时 fail-fast。

    call_metadata：parse_planner_output 单独调用时为 None；真实 Provider
    返回时由 Provider 附加观测元数据。

    to_dict() 不含 raw_output、完整异常、traceback、Prompt 或思维链。
    """

    plan: QueryPlan
    fallback_used: bool
    failure_code: Optional[str]
    call_metadata: Optional[PlannerCallMetadata] = None

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
        if self.call_metadata is not None and not isinstance(
            self.call_metadata, PlannerCallMetadata
        ):
            raise TypeError(
                "call_metadata 必须是 PlannerCallMetadata 或 None，实际 "
                f"{type(self.call_metadata).__name__}"
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
            "call_metadata": (
                self.call_metadata.to_dict()
                if self.call_metadata is not None
                else None
            ),
        }


def build_planner_fallback_outcome(
    original_query: str,
    failure_code: str,
    call_metadata: Optional[PlannerCallMetadata] = None,
) -> PlannerOutcome:
    """构造合法 fallback PlannerOutcome（系统拥有的 PLANNER_FALLBACK 计划）。

    复用 build_fallback_query_plan(original_query)，不复制 fallback 计划
    逻辑；不接受 query_type、不接受模型生成的 fallback。failure_code 必须
    属于允许枚举；调用方 original_query 错误继续 fail-fast。
    """
    if type(failure_code) is not str or failure_code not in _PLANNER_FAILURE_CODE_SET:
        raise ValueError(
            f"failure_code 必须是 {', '.join(PLANNER_FAILURE_CODES)} 之一，"
            f"实际 {failure_code!r}"
        )
    fallback_plan = build_fallback_query_plan(original_query)
    return PlannerOutcome(
        plan=fallback_plan,
        fallback_used=True,
        failure_code=failure_code,
        call_metadata=call_metadata,
    )


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
