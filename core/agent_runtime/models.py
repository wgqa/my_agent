"""G3-RUNTIME-05A：Gate 3 最小 Agent Runtime 强类型契约。

在 QueryPlan/Planner 之上建立 Agent 运行时领域模型：AgentRunBudget /
Document / RouteDecision / EvidenceItem / EvidenceBundle /
VerificationResult / TraceEvent / AgentRunResult 全部为 frozen
dataclass，构造时 fail-fast。本模块只定义契约与不变量，不调用 LLM、
不执行检索、不生成答案、不访问 Dev/Holdout。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Optional, Sequence

from core.query_planning import PlannerOutcome

# ---- schema 版本 ----
ROUTE_DECISION_SCHEMA_VERSION = "route_decision_v1"
EVIDENCE_BUNDLE_SCHEMA_VERSION = "evidence_bundle_v1"
VERIFICATION_RESULT_SCHEMA_VERSION = "verification_result_v1"
AGENT_RUN_RESULT_SCHEMA_VERSION = "agent_run_result_v1"

# ---- 枚举 ----
ROUTE_DECISION_ROUTES = (
    "direct_answer",
    "single_retrieval",
    "decomposed_retrieval",
)
ROUTE_DECISION_STRATEGIES = ("none", "bm25")
VERIFICATION_STATUSES = (
    "not_required",
    "supported",
    "insufficient_evidence",
)
VERIFICATION_REASON_CODES = (
    "NOT_REQUIRED",
    "SUPPORTED",
    "INSUFFICIENT_EVIDENCE",
)
AGENT_RUN_STATUSES = ("completed", "refused", "deferred", "failed")
AGENT_ANSWER_MODES = ("direct", "grounded")
AGENT_TRACE_EVENTS = (
    "run_started",
    "planning_completed",
    "routing_completed",
    "retrieval_completed",
    "verification_completed",
    "generation_completed",
    "run_completed",
    "run_deferred",
    "run_failed",
)
AGENT_RUNTIME_ERROR_CODES = (
    "PLANNING_FAILED",
    "RETRIEVAL_FAILED",
    "GENERATION_FAILED",
    "BUDGET_EXCEEDED",
    "DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED",
)

AGENT_REFUSAL_ANSWER = "现有资料不足，无法可靠回答该问题。"

_CITATION_RE = re.compile(r"^\[C(\d+)\]$")
_TRACE_FORBIDDEN_DATA_KEYS = frozenset({
    "chain_of_thought",
    "system_prompt",
    "raw_output",
    "api_key",
    "authorization",
    "traceback",
})
_TRACE_EVENTS_SET = frozenset(AGENT_TRACE_EVENTS)
_ERROR_CODES_SET = frozenset(AGENT_RUNTIME_ERROR_CODES)
_REASON_CODES_SET = frozenset(VERIFICATION_REASON_CODES)


# ---- 校验工具（类型错误统一 TypeError，值/不变量错误统一 ValueError）----


def _require_type(value: object, expected: type, label: str) -> None:
    if type(value) is not expected:
        raise TypeError(
            f"{label} 必须是 {expected.__name__}，实际 {type(value).__name__}"
        )


def _require_positive_int(value: object, label: str) -> None:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError(
            f"{label} 必须是严格 int（不允许 bool），实际 {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(f"{label} 必须是严格正整数，实际 {value}")


def _require_non_negative_int(value: object, label: str) -> None:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError(
            f"{label} 必须是严格 int（不允许 bool），实际 {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{label} 必须非负，实际 {value}")


def _require_non_empty_str(value: object, label: str) -> None:
    _require_type(value, str, label)
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")
    if value != value.strip():
        raise ValueError(f"{label} 首尾不允许空白")


def _require_non_empty_content(value: object, label: str) -> None:
    """正文文本校验：只要求非空，允许首尾空白（文档正文不 trim）。"""
    _require_type(value, str, label)
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")


def _require_optional_str(value: object, label: str) -> None:
    if value is not None:
        _require_type(value, str, label)


def _require_optional_score(value: object, label: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or type(value) not in (int, float):
        raise TypeError(f"{label} 必须是有限非负数字或 None（不允许 bool）")
    if not math.isfinite(value):
        raise ValueError(f"{label} 必须是有限数字（不允许 NaN/inf）")
    if value < 0:
        raise ValueError(f"{label} 必须非负")


def _require_str_tuple(value: object, label: str) -> None:
    _require_type(value, tuple, label)
    for i, item in enumerate(value):
        _require_type(item, str, f"{label}[{i}]")


def validate_answer_mode(mode: object) -> None:
    """AnswerPort 的 mode 只允许 direct / grounded。"""
    _require_type(mode, str, "mode")
    if mode not in AGENT_ANSWER_MODES:
        raise ValueError(
            f"mode 必须是 {'、'.join(AGENT_ANSWER_MODES)} 之一，实际 {mode!r}"
        )


# ---- 领域模型 ----


@dataclass(frozen=True)
class AgentRunBudget:
    """一次 Agent 运行的有界预算；全部字段严格正整数，bool 不得冒充 int。"""

    max_steps: int = 6
    max_planner_calls: int = 1
    max_retrieval_calls: int = 1
    max_generation_calls: int = 1
    max_evidence_items: int = 5

    def __post_init__(self) -> None:
        for label in (
            "max_steps",
            "max_planner_calls",
            "max_retrieval_calls",
            "max_generation_calls",
            "max_evidence_items",
        ):
            _require_positive_int(getattr(self, label), label)

    def to_dict(self) -> dict:
        return {
            "max_steps": self.max_steps,
            "max_planner_calls": self.max_planner_calls,
            "max_retrieval_calls": self.max_retrieval_calls,
            "max_generation_calls": self.max_generation_calls,
            "max_evidence_items": self.max_evidence_items,
        }


@dataclass(frozen=True)
class Document:
    """RetrievalPort 返回的单条检索结果快照。

    chunk_id / document_id / score 允许为 None（不虚构缺失字段）；缺哪些
    由 Adapter 如实透传，由调用方决定是否提供。content 与 source_name 非空。
    """

    chunk_id: Optional[str]
    document_id: Optional[str]
    source_name: str
    content: str
    score: Optional[float]
    rank: int

    def __post_init__(self) -> None:
        for label in ("chunk_id", "document_id"):
            value = getattr(self, label)
            if value is not None:
                _require_type(value, str, label)
                if not value.strip():
                    raise ValueError(f"{label} 不允许空字符串")
                if value != value.strip():
                    raise ValueError(f"{label} 首尾不允许空白")
        _require_non_empty_str(self.source_name, "source_name")
        _require_non_empty_content(self.content, "content")
        _require_optional_score(self.score, "score")
        _require_positive_int(self.rank, "rank")

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_name": self.source_name,
            "content": self.content,
            "score": self.score,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class RouteDecision:
    """DeterministicRouter 由 QueryPlan 映射出的路由决策快照。

    只读、不可变；不携带 plan 之外的语义，不生成子问题，不选 Hybrid/Dense。
    """

    schema_version: str
    route: str
    retrieval_strategy: str
    queries: tuple[str, ...]
    reason_code: str

    def __post_init__(self) -> None:
        _require_type(self.schema_version, str, "schema_version")
        if self.schema_version != ROUTE_DECISION_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {ROUTE_DECISION_SCHEMA_VERSION!r}，"
                f"实际 {self.schema_version!r}"
            )
        _require_type(self.route, str, "route")
        if self.route not in ROUTE_DECISION_ROUTES:
            raise ValueError(
                f"route 必须是 {'、'.join(ROUTE_DECISION_ROUTES)} 之一，"
                f"实际 {self.route!r}"
            )
        _require_type(self.retrieval_strategy, str, "retrieval_strategy")
        if self.retrieval_strategy not in ROUTE_DECISION_STRATEGIES:
            raise ValueError(
                f"retrieval_strategy 必须是 {'、'.join(ROUTE_DECISION_STRATEGIES)} "
                f"之一，实际 {self.retrieval_strategy!r}"
            )
        _require_type(self.queries, tuple, "queries")
        for i, query in enumerate(self.queries):
            if type(query) is not str or not query.strip():
                raise ValueError(f"queries[{i}] 必须是非空字符串")
        _require_non_empty_str(self.reason_code, "reason_code")

        if self.route == "direct_answer":
            if self.retrieval_strategy != "none":
                raise ValueError("direct_answer 要求 retrieval_strategy=none")
            if self.queries:
                raise ValueError("direct_answer 要求 queries 为空")
        elif self.route == "single_retrieval":
            if self.retrieval_strategy != "bm25":
                raise ValueError("single_retrieval 要求 retrieval_strategy=bm25")
            if len(self.queries) != 1:
                raise ValueError("single_retrieval 要求恰好 1 个 query")
        elif self.route == "decomposed_retrieval":
            if self.retrieval_strategy != "bm25":
                raise ValueError(
                    "decomposed_retrieval 要求 retrieval_strategy=bm25"
                )
            if len(self.queries) not in (2, 3):
                raise ValueError(
                    "decomposed_retrieval 要求 2 或 3 个子问题，"
                    f"实际 {len(self.queries)}"
                )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "route": self.route,
            "retrieval_strategy": self.retrieval_strategy,
            "queries": list(self.queries),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class EvidenceItem:
    """一条可引用证据；citation_id 由 EvidenceBundle 统一按 [C1]、[C2]… 分配。

    缺失的 chunk_id / document_id / score 如实保留为 None，不虚构。
    """

    citation_id: str
    chunk_id: Optional[str]
    document_id: Optional[str]
    source_name: str
    content: str
    score: Optional[float]
    rank: int
    query_id: str

    def __post_init__(self) -> None:
        _require_type(self.citation_id, str, "citation_id")
        if _CITATION_RE.fullmatch(self.citation_id) is None:
            raise ValueError(
                f"citation_id 必须是 [C1]、[C2]… 格式，实际 {self.citation_id!r}"
            )
        for label in ("chunk_id", "document_id"):
            value = getattr(self, label)
            if value is not None:
                _require_type(value, str, label)
                if not value.strip():
                    raise ValueError(f"{label} 不允许空字符串")
                if value != value.strip():
                    raise ValueError(f"{label} 首尾不允许空白")
        _require_non_empty_str(self.source_name, "source_name")
        _require_non_empty_content(self.content, "content")
        _require_optional_score(self.score, "score")
        _require_positive_int(self.rank, "rank")
        _require_non_empty_str(self.query_id, "query_id")

    def to_dict(self) -> dict:
        return {
            "citation_id": self.citation_id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_name": self.source_name,
            "content": self.content,
            "score": self.score,
            "rank": self.rank,
            "query_id": self.query_id,
        }


@dataclass(frozen=True)
class EvidenceBundle:
    """一次运行聚合出的证据集合：去重、上限截断、连续 citation_id。

    items 为不可变 tuple；citation_id 必须从 [C1] 连续唯一递增。上限
    （max_evidence_items）由 from_documents 在构建时从运行时预算强制执行；
    本对象自身不感知预算，直接构造时不做数量上限校验。
    """

    schema_version: str
    items: tuple[EvidenceItem, ...]
    retrieval_call_count: int
    query_count: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_type(self.schema_version, str, "schema_version")
        if self.schema_version != EVIDENCE_BUNDLE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {EVIDENCE_BUNDLE_SCHEMA_VERSION!r}，"
                f"实际 {self.schema_version!r}"
            )
        _require_type(self.items, tuple, "items")
        if not all(isinstance(item, EvidenceItem) for item in self.items):
            raise TypeError("items 每项必须是 EvidenceItem")
        expected = [f"[C{i}]" for i in range(1, len(self.items) + 1)]
        actual = [item.citation_id for item in self.items]
        if actual != expected:
            raise ValueError(
                f"citation_id 必须从 [C1] 连续递增，实际 {actual}"
            )
        _require_non_negative_int(
            self.retrieval_call_count, "retrieval_call_count"
        )
        _require_non_negative_int(self.query_count, "query_count")
        _require_str_tuple(self.warnings, "warnings")

    @classmethod
    def from_documents(
        cls,
        documents: Sequence[Document],
        *,
        query_id: str,
        max_items: int,
        retrieval_call_count: int = 1,
        query_count: int = 1,
        warnings: Sequence[str] = (),
    ) -> "EvidenceBundle":
        """把检索结果规范化为去重、截断、连续编号的证据集合。

        去重规则：chunk_id 非空时按 chunk_id 去重；chunk_id 为空时按
        (source_name, content) 去重。保留首次出现顺序。截断到 max_items。
        """
        _require_non_empty_str(query_id, "query_id")
        _require_positive_int(max_items, "max_items")
        items: list[EvidenceItem] = []
        seen: set[tuple] = set()
        for doc in documents:
            if not isinstance(doc, Document):
                raise TypeError(
                    f"documents 每项必须是 Document，实际 {type(doc).__name__}"
                )
            if len(items) >= max_items:
                break
            if doc.chunk_id is not None and doc.chunk_id.strip():
                key = ("chunk", doc.chunk_id)
            else:
                key = ("pair", doc.source_name, doc.content)
            if key in seen:
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
        return cls(
            schema_version=EVIDENCE_BUNDLE_SCHEMA_VERSION,
            items=tuple(items),
            retrieval_call_count=retrieval_call_count,
            query_count=query_count,
            warnings=tuple(warnings),
        )

    @classmethod
    def empty(
        cls,
        *,
        retrieval_call_count: int = 0,
        query_count: int = 0,
        warnings: Sequence[str] = (),
    ) -> "EvidenceBundle":
        return cls(
            schema_version=EVIDENCE_BUNDLE_SCHEMA_VERSION,
            items=(),
            retrieval_call_count=retrieval_call_count,
            query_count=query_count,
            warnings=tuple(warnings),
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "items": [item.to_dict() for item in self.items],
            "retrieval_call_count": self.retrieval_call_count,
            "query_count": self.query_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class VerificationResult:
    """最小规则版 Verifier 的结论；本阶段不宣称 claim-level Faithfulness。"""

    schema_version: str
    status: str
    can_generate: bool
    reason_code: str
    evidence_count: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_type(self.schema_version, str, "schema_version")
        if self.schema_version != VERIFICATION_RESULT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {VERIFICATION_RESULT_SCHEMA_VERSION!r}，"
                f"实际 {self.schema_version!r}"
            )
        _require_type(self.status, str, "status")
        if self.status not in VERIFICATION_STATUSES:
            raise ValueError(
                f"status 必须是 {'、'.join(VERIFICATION_STATUSES)} 之一，"
                f"实际 {self.status!r}"
            )
        _require_type(self.can_generate, bool, "can_generate")
        _require_type(self.reason_code, str, "reason_code")
        if self.reason_code not in _REASON_CODES_SET:
            raise ValueError(
                f"reason_code 必须是 {'、'.join(VERIFICATION_REASON_CODES)} 之一，"
                f"实际 {self.reason_code!r}"
            )
        _require_non_negative_int(self.evidence_count, "evidence_count")
        _require_str_tuple(self.warnings, "warnings")

        if self.status == "not_required":
            if self.can_generate is not True:
                raise ValueError("not_required 要求 can_generate=true")
            if self.reason_code != "NOT_REQUIRED":
                raise ValueError("not_required 要求 reason_code=NOT_REQUIRED")
        elif self.status == "supported":
            if self.can_generate is not True:
                raise ValueError("supported 要求 can_generate=true")
            if self.reason_code != "SUPPORTED":
                raise ValueError("supported 要求 reason_code=SUPPORTED")
            if self.evidence_count <= 0:
                raise ValueError("supported 要求 evidence_count>0")
        elif self.status == "insufficient_evidence":
            if self.can_generate is not False:
                raise ValueError(
                    "insufficient_evidence 要求 can_generate=false"
                )
            if self.reason_code != "INSUFFICIENT_EVIDENCE":
                raise ValueError(
                    "insufficient_evidence 要求 "
                    "reason_code=INSUFFICIENT_EVIDENCE"
                )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "can_generate": self.can_generate,
            "reason_code": self.reason_code,
            "evidence_count": self.evidence_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TraceEvent:
    """一条 RunTrace 事件；只记结构化摘要，不保存思维链/Prompt/raw output/
    Key/traceback/文档正文。data 为可 JSON 序列化 dict，禁止敏感键。"""

    sequence: int
    event_type: str
    summary: str
    data: dict

    def __post_init__(self) -> None:
        _require_positive_int(self.sequence, "sequence")
        _require_type(self.event_type, str, "event_type")
        if self.event_type not in _TRACE_EVENTS_SET:
            raise ValueError(
                f"event_type 必须是 {'、'.join(AGENT_TRACE_EVENTS)} 之一，"
                f"实际 {self.event_type!r}"
            )
        _require_non_empty_str(self.summary, "summary")
        _require_type(self.data, dict, "data")
        for key in self.data:
            _require_type(key, str, "data 键必须是字符串")
            if key in _TRACE_FORBIDDEN_DATA_KEYS:
                raise ValueError(f"TraceEvent.data 禁止键 {key!r}")
        try:
            json.dumps(self.data, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"TraceEvent.data 必须可 JSON 序列化：{exc}")

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "summary": self.summary,
            "data": dict(self.data),
        }


@dataclass(frozen=True)
class AgentRunResult:
    """一次 Agent 运行的最终结构化结果。

    status 触发不变量：completed/refused/deferred 要求规划与路由已发生；
    completed/refused 必须带答案；refused 的答案必须是固定拒答文本；
    deferred 必须带 DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED；failed 必须带
    error_code 且不允许 answer。planner_outcome / route_decision /
    evidence_bundle / verification 在规划失败（PLANNING_FAILED）时可为 None。
    """

    run_id: str
    status: str
    planner_outcome: Optional[PlannerOutcome]
    route_decision: Optional[RouteDecision]
    evidence_bundle: Optional[EvidenceBundle]
    verification: Optional[VerificationResult]
    answer: Optional[str]
    sources: tuple[str, ...]
    trace: tuple[TraceEvent, ...]
    error_code: Optional[str]
    warnings: tuple[str, ...]
    schema_version: str = AGENT_RUN_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty_str(self.run_id, "run_id")
        _require_type(self.status, str, "status")
        if self.status not in AGENT_RUN_STATUSES:
            raise ValueError(
                f"status 必须是 {'、'.join(AGENT_RUN_STATUSES)} 之一，"
                f"实际 {self.status!r}"
            )
        if self.planner_outcome is not None and not isinstance(
            self.planner_outcome, PlannerOutcome
        ):
            raise TypeError("planner_outcome 必须是 PlannerOutcome 或 None")
        if self.route_decision is not None and not isinstance(
            self.route_decision, RouteDecision
        ):
            raise TypeError("route_decision 必须是 RouteDecision 或 None")
        if self.evidence_bundle is not None and not isinstance(
            self.evidence_bundle, EvidenceBundle
        ):
            raise TypeError("evidence_bundle 必须是 EvidenceBundle 或 None")
        if self.verification is not None and not isinstance(
            self.verification, VerificationResult
        ):
            raise TypeError("verification 必须是 VerificationResult 或 None")
        _require_optional_str(self.answer, "answer")
        _require_str_tuple(self.sources, "sources")
        _require_type(self.trace, tuple, "trace")
        if not all(isinstance(event, TraceEvent) for event in self.trace):
            raise TypeError("trace 每项必须是 TraceEvent")
        if self.error_code is not None:
            _require_type(self.error_code, str, "error_code")
            if self.error_code not in _ERROR_CODES_SET:
                raise ValueError(
                    f"error_code 必须是 {'、'.join(AGENT_RUNTIME_ERROR_CODES)} "
                    f"之一，实际 {self.error_code!r}"
                )
        _require_str_tuple(self.warnings, "warnings")
        _require_type(self.schema_version, str, "schema_version")
        if self.schema_version != AGENT_RUN_RESULT_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {AGENT_RUN_RESULT_SCHEMA_VERSION!r}，"
                f"实际 {self.schema_version!r}"
            )
        self._validate_status_invariants()

    def _validate_status_invariants(self) -> None:
        if self.status in ("completed", "refused", "deferred"):
            if self.planner_outcome is None:
                raise ValueError(f"{self.status} 要求 planner_outcome 存在")
            if self.route_decision is None:
                raise ValueError(f"{self.status} 要求 route_decision 存在")
            if self.evidence_bundle is None:
                raise ValueError(f"{self.status} 要求 evidence_bundle 存在")
            if self.verification is None:
                raise ValueError(f"{self.status} 要求 verification 存在")
            if self.status in ("completed", "refused"):
                if self.answer is None:
                    raise ValueError(f"{self.status} 要求 answer 存在")
                if self.error_code is not None:
                    raise ValueError(f"{self.status} 不允许 error_code")
                if self.status == "refused" and self.answer != AGENT_REFUSAL_ANSWER:
                    raise ValueError("refused 的 answer 必须为固定拒答文本")
            else:  # deferred
                if self.error_code != "DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED":
                    raise ValueError(
                        "deferred 要求 "
                        "error_code=DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED"
                    )
                if self.answer is not None:
                    raise ValueError("deferred 不允许 answer")
        else:  # failed
            if self.error_code is None:
                raise ValueError("failed 要求 error_code 存在")
            if self.answer is not None:
                raise ValueError("failed 不允许 answer")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status,
            "planner_outcome": (
                self.planner_outcome.to_dict()
                if self.planner_outcome is not None
                else None
            ),
            "route_decision": (
                self.route_decision.to_dict()
                if self.route_decision is not None
                else None
            ),
            "evidence_bundle": (
                self.evidence_bundle.to_dict()
                if self.evidence_bundle is not None
                else None
            ),
            "verification": (
                self.verification.to_dict()
                if self.verification is not None
                else None
            ),
            "answer": self.answer,
            "sources": list(self.sources),
            "trace": [event.to_dict() for event in self.trace],
            "error_code": self.error_code,
            "warnings": list(self.warnings),
        }
