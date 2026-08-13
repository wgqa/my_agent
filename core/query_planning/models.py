"""G3-PLAN-03：Gate 3 QueryPlan 强类型契约。

实现 Subquery 与 QueryPlan 的不可变内存快照：字段级校验、跨字段
不变量 fail-fast、稳定 plan_id（canonical JSON + SHA-256[:12]）、
严格 to_dict / from_dict，以及合法 fallback QueryPlan 构造。

本模块只解决 Schema。不调用 LLM；不从自然语言判断 query_type；
不生成子问题；不选择 Retriever；不执行检索；不合并证据。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

QUERY_PLAN_SCHEMA_VERSION = "query_plan_v1"
QUERY_PLAN_FALLBACK_POLICY = "single_bm25_original_query"

# 正常规划 / 模型输出允许的语义类型（恰好原 7 种）。
# Gate3Case 的 query_type 标签也只用这 7 种，不含 unknown。
QUERY_PLAN_CLASSIFIED_QUERY_TYPES = (
    "fact",
    "comparison",
    "causal",
    "multi_entity",
    "code_symbol",
    "troubleshooting",
    "unanswerable_or_no_retrieval",
)

# 系统 fallback 专属类型：Planner 失败后不存在可信分类结果，只能标 unknown。
# unknown 不是模型输出类别、不是数据集标签；只允许配合 PLANNER_FALLBACK。
QUERY_PLAN_FALLBACK_QUERY_TYPE = "unknown"

# QueryPlan 对象层总枚举：分类类型 + 系统 fallback 哨兵。
QUERY_PLAN_QUERY_TYPES = (
    QUERY_PLAN_CLASSIFIED_QUERY_TYPES + (QUERY_PLAN_FALLBACK_QUERY_TYPE,)
)

QUERY_PLAN_ACTIONS = (
    "no_retrieval",
    "single_retrieval",
    "decomposed_retrieval",
)

QUERY_PLAN_REASON_CODES = (
    "NO_RETRIEVAL_NEEDED",
    "SIMPLE_FACT",
    "CODE_SYMBOL",
    "COMPARISON_EVIDENCE",
    "MULTI_ENTITY_EVIDENCE",
    "CAUSAL_SYNTHESIS",
    "TROUBLESHOOTING_EVIDENCE",
    "UNANSWERABLE_CHECK",
    "PLANNER_FALLBACK",
)

_VALID_SUBQUERY_IDS = ("sq1", "sq2", "sq3")
_MAX_ORIGINAL_QUERY_CHARS = 4000
_MAX_SUBQUERY_QUERY_CHARS = 1000
_MAX_EVIDENCE_TARGET_CHARS = 500
_PLAN_ID_RE = re.compile(r"^[0-9a-f]{12}$")

_SUBQUERY_ALLOWED_FIELDS = frozenset({
    "id",
    "query",
    "evidence_target",
    "required",
})
_QUERY_PLAN_ALLOWED_FIELDS = frozenset({
    "schema_version",
    "plan_id",
    "original_query",
    "query_type",
    "retrieval_required",
    "action",
    "reason_code",
    "subqueries",
    "fallback_policy",
})


def _validate_text(value: object, label: str, max_chars: int) -> None:
    """字符串文本校验：非空、首尾无空白、长度有界；不自动 strip。"""
    if not isinstance(value, str):
        raise TypeError(f"{label} 必须是字符串，实际 {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")
    if value != value.strip():
        raise ValueError(f"{label} 首尾不允许空白")
    if len(value) > max_chars:
        raise ValueError(f"{label} 超过 {max_chars} 字符上限")


def _check_type_str(value: object, label: str) -> None:
    """严格字符串类型校验：类型错误统一抛 TypeError（含字段名）。"""
    if type(value) is not str:
        raise TypeError(f"{label} 必须是字符串，实际 {type(value).__name__}")


def _check_type_bool(value: object, label: str) -> None:
    """严格 bool 类型校验：类型错误统一抛 TypeError（含字段名）。"""
    if type(value) is not bool:
        raise TypeError(f"{label} 必须是严格 bool，实际 {type(value).__name__}")


def _compute_plan_id(identity_payload: dict) -> str:
    """规范化 JSON + SHA-256 取前 12 位小写十六进制。

    payload 由 QueryPlan.identity_payload() 生成：包含 schema_version 与
    除 plan_id 外的全部规范化字段；subqueries 顺序保留，不排序。
    """
    canonical = json.dumps(
        identity_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]


@dataclass(frozen=True)
class Subquery:
    """一条子问题；frozen 不可变，字段级约束在构造时 fail-fast。"""

    id: str
    query: str
    evidence_target: str
    required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise TypeError(
                f"Subquery.id 必须是字符串，实际 {type(self.id).__name__}"
            )
        if self.id not in _VALID_SUBQUERY_IDS:
            raise ValueError(
                f"Subquery.id 只允许 {'、'.join(_VALID_SUBQUERY_IDS)} 之一，"
                f"实际 {self.id!r}"
            )
        _validate_text(self.query, "Subquery.query", _MAX_SUBQUERY_QUERY_CHARS)
        _validate_text(
            self.evidence_target,
            "Subquery.evidence_target",
            _MAX_EVIDENCE_TARGET_CHARS,
        )
        if type(self.required) is not bool:
            raise TypeError(
                f"Subquery.required 必须是严格 bool，"
                f"实际 {type(self.required).__name__}"
            )
        if not self.required:
            raise ValueError("v1 中 Subquery.required 必须为 true")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "evidence_target": self.evidence_target,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, obj: object) -> "Subquery":
        """严格反序列化：拒绝未知字段、缺失字段、错误类型。"""
        if not isinstance(obj, dict):
            raise TypeError(
                f"Subquery 必须是 dict，实际 {type(obj).__name__}"
            )
        extra = sorted(set(obj) - _SUBQUERY_ALLOWED_FIELDS)
        if extra:
            raise ValueError(
                f"Subquery 包含未知字段：{', '.join(extra)}"
            )
        missing = sorted(_SUBQUERY_ALLOWED_FIELDS - set(obj))
        if missing:
            raise ValueError(
                f"Subquery 缺少字段：{', '.join(missing)}"
            )
        return cls(
            id=obj["id"],
            query=obj["query"],
            evidence_target=obj["evidence_target"],
            required=obj["required"],
        )


@dataclass(frozen=True)
class QueryPlan:
    """一份规范化 QueryPlan 的不可变快照。

    对外用 create(...) 构造并自动计算 plan_id；用 from_dict(...) 读取
    完整快照并验证 plan_id。跨字段不变量在 __post_init__ 中 fail-fast。
    """

    schema_version: str
    plan_id: str
    original_query: str
    query_type: str
    retrieval_required: bool
    action: str
    reason_code: str
    subqueries: tuple[Subquery, ...]
    fallback_policy: str

    def __post_init__(self) -> None:
        _check_type_str(self.schema_version, "schema_version")
        if self.schema_version != QUERY_PLAN_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {QUERY_PLAN_SCHEMA_VERSION!r}，"
                f"实际 {self.schema_version!r}"
            )

        _check_type_str(self.original_query, "original_query")
        _validate_text(
            self.original_query, "original_query", _MAX_ORIGINAL_QUERY_CHARS
        )

        _check_type_str(self.query_type, "query_type")
        if self.query_type not in QUERY_PLAN_QUERY_TYPES:
            raise ValueError(
                f"query_type 必须是 {', '.join(QUERY_PLAN_QUERY_TYPES)} 之一，"
                f"实际 {self.query_type!r}"
            )

        _check_type_bool(self.retrieval_required, "retrieval_required")

        _check_type_str(self.action, "action")
        if self.action not in QUERY_PLAN_ACTIONS:
            raise ValueError(
                f"action 必须是 {', '.join(QUERY_PLAN_ACTIONS)} 之一，"
                f"实际 {self.action!r}"
            )

        _check_type_str(self.reason_code, "reason_code")
        if self.reason_code not in QUERY_PLAN_REASON_CODES:
            raise ValueError(
                f"reason_code 必须是 {', '.join(QUERY_PLAN_REASON_CODES)} 之一，"
                f"实际 {self.reason_code!r}"
            )

        _check_type_str(self.fallback_policy, "fallback_policy")
        if self.fallback_policy != QUERY_PLAN_FALLBACK_POLICY:
            raise ValueError(
                f"fallback_policy 必须是 {QUERY_PLAN_FALLBACK_POLICY!r}，"
                f"实际 {self.fallback_policy!r}"
            )

        if not isinstance(self.subqueries, tuple):
            raise TypeError(
                f"subqueries 必须是 tuple，实际 {type(self.subqueries).__name__}"
            )
        if not all(isinstance(s, Subquery) for s in self.subqueries):
            raise TypeError("subqueries 每项必须是 Subquery")

        if type(self.plan_id) is not str:
            raise TypeError(
                f"plan_id 必须是字符串，实际 {type(self.plan_id).__name__}"
            )
        if _PLAN_ID_RE.fullmatch(self.plan_id) is None:
            raise ValueError(
                f"plan_id 必须是12位小写十六进制，实际 {self.plan_id!r}"
            )

        self._validate_cross_field_invariants()

        recomputed = _compute_plan_id(self.identity_payload())
        if self.plan_id != recomputed:
            raise ValueError(
                f"plan_id 与规范化 QueryPlan 重算值不一致："
                f"期望 {recomputed}，实际 {self.plan_id}"
            )

    def identity_payload(self) -> dict:
        """plan_id 的身份载荷：排除 plan_id 自身，保留其余规范化字段。"""
        return {
            "schema_version": self.schema_version,
            "original_query": self.original_query,
            "query_type": self.query_type,
            "retrieval_required": self.retrieval_required,
            "action": self.action,
            "reason_code": self.reason_code,
            "subqueries": [s.to_dict() for s in self.subqueries],
            "fallback_policy": self.fallback_policy,
        }

    def to_dict(self) -> dict:
        """完整快照（含 plan_id）；每次返回全新 list/dict，修改不影响对象。"""
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "original_query": self.original_query,
            "query_type": self.query_type,
            "retrieval_required": self.retrieval_required,
            "action": self.action,
            "reason_code": self.reason_code,
            "subqueries": [s.to_dict() for s in self.subqueries],
            "fallback_policy": self.fallback_policy,
        }

    @classmethod
    def create(
        cls,
        *,
        schema_version: str = QUERY_PLAN_SCHEMA_VERSION,
        original_query: str,
        query_type: str,
        retrieval_required: bool,
        action: str,
        reason_code: str,
        subqueries: Sequence[Subquery] = (),
        fallback_policy: str = QUERY_PLAN_FALLBACK_POLICY,
    ) -> "QueryPlan":
        """规范化构造：先做字段类型校验，再归一化 subqueries 并计算 plan_id。

        类型校验在哈希之前执行，避免不可 JSON 序列化的错误类型把异常
        暴露成通用 json.dumps 错误；值/枚举/跨字段不变量仍由
        __post_init__ 统一 fail-fast，不会返回半成品。
        """
        _check_type_str(schema_version, "schema_version")
        _check_type_str(original_query, "original_query")
        _check_type_str(query_type, "query_type")
        _check_type_bool(retrieval_required, "retrieval_required")
        _check_type_str(action, "action")
        _check_type_str(reason_code, "reason_code")
        _check_type_str(fallback_policy, "fallback_policy")

        if isinstance(subqueries, tuple):
            normalized = subqueries
        elif isinstance(subqueries, list):
            normalized = tuple(subqueries)
        else:
            raise TypeError(
                f"subqueries 必须是 tuple 或 list，实际 "
                f"{type(subqueries).__name__}"
            )
        for sub in normalized:
            if not isinstance(sub, Subquery):
                raise TypeError(
                    f"subqueries 每项必须是 Subquery，实际 {type(sub).__name__}"
                )

        identity = {
            "schema_version": schema_version,
            "original_query": original_query,
            "query_type": query_type,
            "retrieval_required": retrieval_required,
            "action": action,
            "reason_code": reason_code,
            "subqueries": [s.to_dict() for s in normalized],
            "fallback_policy": fallback_policy,
        }
        plan_id = _compute_plan_id(identity)
        return cls(
            schema_version=schema_version,
            plan_id=plan_id,
            original_query=original_query,
            query_type=query_type,
            retrieval_required=retrieval_required,
            action=action,
            reason_code=reason_code,
            subqueries=normalized,
            fallback_policy=fallback_policy,
        )

    @classmethod
    def from_dict(cls, obj: object) -> "QueryPlan":
        """读取完整快照（含 plan_id）并验证 plan_id 与重算值一致。

        拒绝未知字段、缺失字段、错误类型；字段校验与跨字段不变量由
        __post_init__ 统一执行。
        """
        if not isinstance(obj, dict):
            raise TypeError(
                f"QueryPlan 必须是 dict，实际 {type(obj).__name__}"
            )
        extra = sorted(set(obj) - _QUERY_PLAN_ALLOWED_FIELDS)
        if extra:
            raise ValueError(
                f"QueryPlan 包含未知字段：{', '.join(extra)}"
            )
        missing = sorted(_QUERY_PLAN_ALLOWED_FIELDS - set(obj))
        if missing:
            raise ValueError(
                f"QueryPlan 缺少字段：{', '.join(missing)}"
            )

        raw_subqueries = obj["subqueries"]
        if not isinstance(raw_subqueries, list):
            raise TypeError(
                f"subqueries 必须是数组，实际 "
                f"{type(raw_subqueries).__name__}"
            )
        subqueries = tuple(
            Subquery.from_dict(item) for item in raw_subqueries
        )
        return cls(
            schema_version=obj["schema_version"],
            plan_id=obj["plan_id"],
            original_query=obj["original_query"],
            query_type=obj["query_type"],
            retrieval_required=obj["retrieval_required"],
            action=obj["action"],
            reason_code=obj["reason_code"],
            subqueries=subqueries,
            fallback_policy=obj["fallback_policy"],
        )

    def _validate_cross_field_invariants(self) -> None:
        """跨字段不变量（设计文档 §5.9 与任务 §10），fail-fast。"""
        action = self.action

        if action == "no_retrieval":
            if self.retrieval_required is not False:
                raise ValueError(
                    "no_retrieval 要求 retrieval_required=false"
                )
            if self.query_type != "unanswerable_or_no_retrieval":
                raise ValueError(
                    "no_retrieval 要求 query_type=unanswerable_or_no_retrieval"
                )
            if self.reason_code != "NO_RETRIEVAL_NEEDED":
                raise ValueError(
                    "no_retrieval 要求 reason_code=NO_RETRIEVAL_NEEDED"
                )
            if self.subqueries:
                raise ValueError("no_retrieval 要求 subqueries 为空")
        elif action == "single_retrieval":
            if self.retrieval_required is not True:
                raise ValueError(
                    "single_retrieval 要求 retrieval_required=true"
                )
            if self.subqueries:
                raise ValueError("single_retrieval 要求 subqueries 为空")
        elif action == "decomposed_retrieval":
            if self.retrieval_required is not True:
                raise ValueError(
                    "decomposed_retrieval 要求 retrieval_required=true"
                )
            count = len(self.subqueries)
            if count not in (2, 3):
                raise ValueError(
                    "decomposed_retrieval 要求 subqueries 数量为 2 或 3，"
                    f"实际 {count}"
                )
            expected_ids = (
                ("sq1", "sq2") if count == 2
                else ("sq1", "sq2", "sq3")
            )
            actual_ids = [s.id for s in self.subqueries]
            if actual_ids != list(expected_ids):
                raise ValueError(
                    "decomposed_retrieval 要求 subquery id 按顺序连续 "
                    f"{'/'.join(expected_ids)}，实际 {'/'.join(actual_ids)}"
                )
            if not all(s.required for s in self.subqueries):
                raise ValueError(
                    "decomposed_retrieval 要求所有 subquery required=true"
                )
            queries = [s.query for s in self.subqueries]
            if len(set(queries)) != len(queries):
                raise ValueError(
                    "decomposed_retrieval 不允许 subquery.query 完全重复"
                )
        else:  # pragma: no cover - 枚举已封闭，理论上不可达
            raise ValueError(f"未知 action {action!r}")

        if self.reason_code == "NO_RETRIEVAL_NEEDED" and action != "no_retrieval":
            raise ValueError(
                "reason_code=NO_RETRIEVAL_NEEDED 只能用于 no_retrieval"
            )
        # 双向强约束：unknown ⇔ PLANNER_FALLBACK（系统 fallback 专属状态）。
        if self.query_type == QUERY_PLAN_FALLBACK_QUERY_TYPE:
            if self.reason_code != "PLANNER_FALLBACK":
                raise ValueError(
                    f"query_type={QUERY_PLAN_FALLBACK_QUERY_TYPE!r} 只允许 "
                    "reason_code=PLANNER_FALLBACK"
                )
        if self.reason_code == "PLANNER_FALLBACK":
            if self.query_type != QUERY_PLAN_FALLBACK_QUERY_TYPE:
                raise ValueError(
                    "reason_code=PLANNER_FALLBACK 只允许 "
                    f"query_type={QUERY_PLAN_FALLBACK_QUERY_TYPE!r}"
                )
            if (
                action != "single_retrieval"
                or self.retrieval_required is not True
                or self.subqueries
            ):
                raise ValueError(
                    "reason_code=PLANNER_FALLBACK 必须是 single_retrieval + "
                    "retrieval_required=true + subqueries 为空 + "
                    f"query_type={QUERY_PLAN_FALLBACK_QUERY_TYPE!r}"
                )
        if (
            self.query_type == "unanswerable_or_no_retrieval"
            and self.retrieval_required is True
        ):
            if action != "single_retrieval":
                raise ValueError(
                    "unanswerable_or_no_retrieval + retrieval_required=true "
                    "要求 action=single_retrieval"
                )
            if self.reason_code != "UNANSWERABLE_CHECK":
                raise ValueError(
                    "unanswerable_or_no_retrieval + retrieval_required=true "
                    "只允许 reason_code=UNANSWERABLE_CHECK"
                )


def build_fallback_query_plan(original_query: str) -> QueryPlan:
    """构造合法 fallback QueryPlan：回到原问题单次 BM25。

    query_type 固定为系统专属 QUERY_PLAN_FALLBACK_QUERY_TYPE（unknown）：
    Planner 失败后不存在可信分类结果，不允许调用方、Dev 或 Gold 提供类型。
    调用方不能覆盖。不调用 LLM，不吞异常。
    """
    return QueryPlan.create(
        original_query=original_query,
        query_type=QUERY_PLAN_FALLBACK_QUERY_TYPE,
        retrieval_required=True,
        action="single_retrieval",
        reason_code="PLANNER_FALLBACK",
        subqueries=(),
        fallback_policy=QUERY_PLAN_FALLBACK_POLICY,
    )
