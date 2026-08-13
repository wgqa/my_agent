"""G3-DECOMP-04B-02A + R1：可复现 Dev Planner 校准 Runner 与离线分析。

对公开 Gate 3 Dev 24 Case 运行已审计 BaseQueryPlanner 的调优前真实
baseline，计算 Planning 指标，并提供基于 R0 Artifact 的离线 R1 重分析
（不调用模型）。Config v2 强类型校验；metrics v2 区分条件错误率与总体
发生占比。Gold 只在模型调用后用于指标。本模块不访问 sealed/Holdout。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from core.query_planning import (
    BaseQueryPlanner,
    PlannerCallMetadata,
    PlannerOutcome,
    QueryPlan,
)
from evaluation.gate3.evaluation_set import Gate3Case, Gate3EvaluationSet

PLANNER_DEV_SCHEMA_VERSION = "gate3_planner_dev_run_v2"
PLANNER_DEV_SCHEMA_VERSION_V1 = "gate3_planner_dev_run_v1"
PLANNER_RESULTS_SCHEMA_VERSION = "gate3_planner_dev_results_v2"
PLANNER_METRICS_SCHEMA_VERSION = "gate3_planner_dev_metrics_v2"
PLANNER_DEV_ANALYSIS_SCHEMA_VERSION = "gate3_planner_dev_analysis_v1"
PLANNER_DEV_ANALYSIS_RESULT_SCHEMA_VERSION = "gate3_planner_dev_analysis_result_v1"
PLANNER_RESULT_SUMMARY_SCHEMA_VERSION = "gate3_planner_dev_result_v1"
PLANNER_ABORT_SCHEMA_VERSION = "gate3_planner_dev_abort_v1"

_HEX = frozenset("0123456789abcdef")


def _canonical_json(obj: object) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _conditional_rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return numerator / denominator


def _percentile_ms(values: Sequence[float], p: int) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    k = math.ceil(p / 100 * len(ordered))
    return float(ordered[k - 1])


def _check_hex(value: object, length: int, label: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} 必须是字符串")
    if len(value) != length or any(c not in _HEX for c in value):
        raise ValueError(f"{label} 必须是 {length} 位小写十六进制，实际 {value!r}")


def _check_nonempty_no_ws(value: object, label: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} 必须是字符串")
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")
    if value != value.strip():
        raise ValueError(f"{label} 首尾不允许空白")


def gold_action_for(case: Gate3Case) -> str:
    """Gold action 映射（任务七固定口径）。

    required → decomposed；forbidden 且 retrieval=true → single；
    forbidden 且 retrieval=false → no_retrieval；optional 单独报告。
    """
    if case.decomposition_expected == "optional":
        return "optional"
    if case.decomposition_expected == "required":
        return "decomposed_retrieval"
    if case.retrieval_required:
        return "single_retrieval"
    return "no_retrieval"


# ---------------------------------------------------------------------------
# 身份
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate3PlannerDevConfig:
    """一次 Dev Planner 校准运行的固定配置（v2，强类型校验）。

    run_id 由身份 payload 计算；不绑定 API Key/base_url/路径/时间/latency。
    """

    schema_version: str = PLANNER_DEV_SCHEMA_VERSION
    source_commit: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    gate3_dataset_freeze_id: str = ""
    dev_jsonl_sha256: str = ""
    dev_manifest_sha256: str = ""
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    prompt_sha256: str = ""
    temperature: int = 0
    max_tokens: int = 800
    timeout: float = 20.0
    max_retries: int = 0

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != PLANNER_DEV_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {PLANNER_DEV_SCHEMA_VERSION!r}"
            )
        _check_hex(self.source_commit, 40, "source_commit")
        _check_hex(self.corpus_id, 12, "corpus_id")
        _check_hex(self.evaluation_set_id, 12, "evaluation_set_id")
        _check_hex(self.gate3_dataset_freeze_id, 12, "gate3_dataset_freeze_id")
        _check_hex(self.dev_jsonl_sha256, 64, "dev_jsonl_sha256")
        _check_hex(self.dev_manifest_sha256, 64, "dev_manifest_sha256")
        _check_hex(self.prompt_sha256, 64, "prompt_sha256")
        for label in ("provider", "model", "prompt_version"):
            _check_nonempty_no_ws(getattr(self, label), label)
        if type(self.temperature) is not int or isinstance(self.temperature, bool):
            raise TypeError("temperature 必须是严格 int（不允许 bool）")
        if self.temperature != 0:
            raise ValueError("temperature 必须固定 0")
        if type(self.max_tokens) is not int or isinstance(self.max_tokens, bool):
            raise TypeError("max_tokens 必须是严格 int（不允许 bool）")
        if self.max_tokens != 800:
            raise ValueError("max_tokens 必须固定 800")
        timeout = self.timeout
        if isinstance(timeout, bool) or type(timeout) not in (int, float):
            raise TypeError("timeout 必须是有限正数（不允许 bool）")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须是有限正数（不允许 NaN/inf/0）")
        if timeout != 20.0:
            raise ValueError("timeout 必须固定 20.0")
        if type(self.max_retries) is not int or isinstance(self.max_retries, bool):
            raise TypeError("max_retries 必须是严格 int（不允许 bool）")
        if self.max_retries != 0:
            raise ValueError("max_retries 必须固定 0")

    def identity_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "gate3_dataset_freeze_id": self.gate3_dataset_freeze_id,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
            "dev_manifest_sha256": self.dev_manifest_sha256,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    @property
    def run_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.identity_payload()))[:12]

    def to_dict(self) -> dict:
        return {
            **self.identity_payload(),
            "run_id": self.run_id,
        }


def _v1_identity_payload(config_dict: dict) -> dict:
    """重建 R0 历史 v1 的 run 身份 payload（用于校验 R0 run_id）。"""
    return {
        "schema_version": PLANNER_DEV_SCHEMA_VERSION_V1,
        "source_commit": config_dict["source_commit"],
        "corpus_id": config_dict["corpus_id"],
        "evaluation_set_id": config_dict["evaluation_set_id"],
        "dev_jsonl_sha256": config_dict["dev_jsonl_sha256"],
        "provider": config_dict["provider"],
        "model": config_dict["model"],
        "prompt_version": config_dict["prompt_version"],
        "prompt_sha256": config_dict["prompt_sha256"],
        "temperature": config_dict["temperature"],
        "max_tokens": config_dict["max_tokens"],
        "timeout": config_dict["timeout"],
        "max_retries": config_dict["max_retries"],
    }


def _v1_run_id(config_dict: dict) -> str:
    return _sha256_bytes(_canonical_json(_v1_identity_payload(config_dict)))[:12]


# ---------------------------------------------------------------------------
# 每 Case 结果与指标（v2）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate3PlannerCaseResult:
    case_id: str
    query: str
    gold_query_type: str
    gold_answerability: str
    gold_retrieval_required: bool
    gold_decomposition_expected: str
    gold_action: str
    predicted_query_type: Optional[str]
    predicted_retrieval_required: Optional[bool]
    predicted_action: Optional[str]
    reason_code: Optional[str]
    fallback_used: bool
    failure_code: Optional[str]
    query_type_correct: bool
    retrieval_required_correct: bool
    action_correct: bool
    unnecessary_decomposition: bool
    missed_decomposition: bool
    duplicate_subquery: bool
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: Optional[float]
    call_metadata: dict
    plan: dict

    def to_dict(self) -> dict:
        return {
            "schema_version": PLANNER_RESULTS_SCHEMA_VERSION,
            "case_id": self.case_id,
            "query": self.query,
            "gold": {
                "query_type": self.gold_query_type,
                "answerability": self.gold_answerability,
                "retrieval_required": self.gold_retrieval_required,
                "decomposition_expected": self.gold_decomposition_expected,
                "action": self.gold_action,
            },
            "predicted": {
                "query_type": self.predicted_query_type,
                "retrieval_required": self.predicted_retrieval_required,
                "action": self.predicted_action,
                "reason_code": self.reason_code,
            },
            "fallback_used": self.fallback_used,
            "failure_code": self.failure_code,
            "correctness": {
                "query_type_correct": self.query_type_correct,
                "retrieval_required_correct": self.retrieval_required_correct,
                "action_correct": self.action_correct,
                "unnecessary_decomposition": self.unnecessary_decomposition,
                "missed_decomposition": self.missed_decomposition,
                "duplicate_subquery": self.duplicate_subquery,
            },
            "call_metadata": self.call_metadata,
            "plan": self.plan,
        }


@dataclass(frozen=True)
class Gate3PlannerMetrics:
    schema_version: str = PLANNER_METRICS_SCHEMA_VERSION
    case_count: int = 0
    completed_outcome_count: int = 0
    schema_valid_count: int = 0
    schema_validity_rate: float = 0.0
    fallback_count: int = 0
    fallback_rate: float = 0.0
    failure_code_distribution: dict = field(default_factory=dict)
    query_type_exact_correct_count: int = 0
    query_type_exact_accuracy_all: float = 0.0
    query_type_exact_accuracy_non_fallback: float = 0.0
    retrieval_required_correct_count: int = 0
    retrieval_required_accuracy: float = 0.0
    action_correct_count: int = 0
    action_accuracy: float = 0.0
    unnecessary_decomposition_count: int = 0
    unnecessary_decomposition_eligible_count: int = 0
    unnecessary_decomposition_rate: Optional[float] = None
    unnecessary_decomposition_overall_case_rate: float = 0.0
    missed_decomposition_count: int = 0
    missed_decomposition_eligible_count: int = 0
    missed_decomposition_rate: Optional[float] = None
    missed_decomposition_overall_case_rate: float = 0.0
    exact_duplicate_subquery_case_count: int = 0
    exact_duplicate_subquery_rate: float = 0.0
    planner_call_count: int = 0
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    missing_usage_count: int = 0
    latency_p50_ms: Optional[float] = None
    latency_p95_ms: Optional[float] = None
    timeout_count: int = 0
    timeout_rate: float = 0.0
    provider_error_count: int = 0
    provider_error_rate: float = 0.0
    stratified: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "case_count": self.case_count,
            "completed_outcome_count": self.completed_outcome_count,
            "schema_valid_count": self.schema_valid_count,
            "schema_validity_rate": self.schema_validity_rate,
            "fallback_count": self.fallback_count,
            "fallback_rate": self.fallback_rate,
            "failure_code_distribution": self.failure_code_distribution,
            "query_type_exact_correct_count": self.query_type_exact_correct_count,
            "query_type_exact_accuracy_all": self.query_type_exact_accuracy_all,
            "query_type_exact_accuracy_non_fallback": (
                self.query_type_exact_accuracy_non_fallback
            ),
            "retrieval_required_correct_count": self.retrieval_required_correct_count,
            "retrieval_required_accuracy": self.retrieval_required_accuracy,
            "action_correct_count": self.action_correct_count,
            "action_accuracy": self.action_accuracy,
            "unnecessary_decomposition_count": self.unnecessary_decomposition_count,
            "unnecessary_decomposition_eligible_count": (
                self.unnecessary_decomposition_eligible_count
            ),
            "unnecessary_decomposition_rate": self.unnecessary_decomposition_rate,
            "unnecessary_decomposition_overall_case_rate": (
                self.unnecessary_decomposition_overall_case_rate
            ),
            "missed_decomposition_count": self.missed_decomposition_count,
            "missed_decomposition_eligible_count": (
                self.missed_decomposition_eligible_count
            ),
            "missed_decomposition_rate": self.missed_decomposition_rate,
            "missed_decomposition_overall_case_rate": (
                self.missed_decomposition_overall_case_rate
            ),
            "exact_duplicate_subquery_case_count": (
                self.exact_duplicate_subquery_case_count
            ),
            "exact_duplicate_subquery_rate": self.exact_duplicate_subquery_rate,
            "planner_call_count": self.planner_call_count,
            "input_tokens_total": self.input_tokens_total,
            "output_tokens_total": self.output_tokens_total,
            "missing_usage_count": self.missing_usage_count,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "timeout_count": self.timeout_count,
            "timeout_rate": self.timeout_rate,
            "provider_error_count": self.provider_error_count,
            "provider_error_rate": self.provider_error_rate,
            "stratified": self.stratified,
        }


@dataclass(frozen=True)
class Gate3PlannerDevResult:
    run_id: str
    config: Gate3PlannerDevConfig
    metrics: Gate3PlannerMetrics
    case_results: tuple[Gate3PlannerCaseResult, ...]


# ---------------------------------------------------------------------------
# Runner（v2）
# ---------------------------------------------------------------------------


class ProviderFailFast(RuntimeError):
    """首条 Case 发生 Provider 错误/超时时停止，携带首个 outcome（不再二次调用）。"""

    def __init__(self, message: str, case_id: str, failure_code: str,
                 outcome: PlannerOutcome):
        super().__init__(message)
        self.case_id = case_id
        self.failure_code = failure_code
        self.outcome = outcome


def _has_duplicate_subquery(plan: QueryPlan, failure_code: Optional[str]) -> bool:
    if failure_code == "PLAN_DUPLICATE_SUBQUERY":
        return True
    queries = [s["query"] for s in plan.to_dict()["subqueries"]]
    return len(set(queries)) != len(queries)


def _build_call_metadata_dict(config: Gate3PlannerDevConfig,
                              outcome: Optional[PlannerOutcome]) -> dict:
    if outcome is not None and outcome.call_metadata is not None:
        return outcome.call_metadata.to_dict()
    return {
        "provider": config.provider,
        "model": config.model,
        "prompt_version": config.prompt_version,
        "prompt_sha256": config.prompt_sha256,
        "call_count": 1,
        "input_tokens": None,
        "output_tokens": None,
        "latency_ms": None,
    }


class Gate3PlannerDevRunner:
    """按 case_id 升序对每个 Dev Case 调用 planner.plan(case.query) 恰好一次。"""

    def __init__(
        self,
        config: Gate3PlannerDevConfig,
        planner: BaseQueryPlanner,
        evaluation_set: Gate3EvaluationSet,
    ):
        if not isinstance(config, Gate3PlannerDevConfig):
            raise TypeError("config 必须是 Gate3PlannerDevConfig")
        if not isinstance(planner, BaseQueryPlanner):
            raise TypeError("planner 必须是 BaseQueryPlanner")
        if not isinstance(evaluation_set, Gate3EvaluationSet):
            raise TypeError("evaluation_set 必须是 Gate3EvaluationSet")
        self._config = config
        self._planner = planner
        self._evaluation_set = evaluation_set

    def run(self, fail_fast_on_provider_error: bool = False) -> Gate3PlannerDevResult:
        cases = sorted(self._evaluation_set.cases, key=lambda c: c.case_id)
        case_results: list[Gate3PlannerCaseResult] = []
        for index, case in enumerate(cases):
            outcome = self._planner.plan(case.query)
            if (
                fail_fast_on_provider_error
                and index == 0
                and outcome.failure_code
                in ("PLANNER_PROVIDER_ERROR", "PLANNER_TIMEOUT")
            ):
                raise ProviderFailFast(
                    f"首条 Case {case.case_id} 发生 {outcome.failure_code}，"
                    "停止正式运行",
                    case_id=case.case_id,
                    failure_code=outcome.failure_code,
                    outcome=outcome,
                )
            case_results.append(self._evaluate_case(case, outcome))
        metrics = self._compute_metrics(case_results)
        return Gate3PlannerDevResult(
            run_id=self._config.run_id,
            config=self._config,
            metrics=metrics,
            case_results=tuple(case_results),
        )

    def _evaluate_case(
        self, case: Gate3Case, outcome: PlannerOutcome
    ) -> Gate3PlannerCaseResult:
        plan: QueryPlan = outcome.plan
        predicted_action = plan.action
        predicted_qt = plan.query_type
        predicted_rr = plan.retrieval_required
        gold_action = gold_action_for(case)

        query_type_correct = predicted_qt == case.query_type
        retrieval_required_correct = predicted_rr == case.retrieval_required
        action_correct = predicted_action == gold_action
        unnecessary_decomposition = (
            predicted_action == "decomposed_retrieval"
            and gold_action != "decomposed_retrieval"
        )
        missed_decomposition = (
            gold_action == "decomposed_retrieval"
            and predicted_action != "decomposed_retrieval"
        )
        duplicate_subquery = _has_duplicate_subquery(plan, outcome.failure_code)
        call_metadata = _build_call_metadata_dict(self._config, outcome)

        return Gate3PlannerCaseResult(
            case_id=case.case_id,
            query=case.query,
            gold_query_type=case.query_type,
            gold_answerability=case.answerability,
            gold_retrieval_required=case.retrieval_required,
            gold_decomposition_expected=case.decomposition_expected,
            gold_action=gold_action,
            predicted_query_type=predicted_qt,
            predicted_retrieval_required=predicted_rr,
            predicted_action=predicted_action,
            reason_code=plan.reason_code,
            fallback_used=outcome.fallback_used,
            failure_code=outcome.failure_code,
            query_type_correct=query_type_correct,
            retrieval_required_correct=retrieval_required_correct,
            action_correct=action_correct,
            unnecessary_decomposition=unnecessary_decomposition,
            missed_decomposition=missed_decomposition,
            duplicate_subquery=duplicate_subquery,
            input_tokens=call_metadata.get("input_tokens"),
            output_tokens=call_metadata.get("output_tokens"),
            latency_ms=call_metadata.get("latency_ms"),
            call_metadata=call_metadata,
            plan=plan.to_dict(),
        )

    @staticmethod
    def _compute_metrics(
        case_results: Sequence[Gate3PlannerCaseResult],
    ) -> Gate3PlannerMetrics:
        n = len(case_results)
        non_fallback = [c for c in case_results if not c.fallback_used]
        schema_valid = len(non_fallback)
        fallback_count = n - schema_valid
        qt_correct_all = sum(c.query_type_correct for c in case_results)
        qt_correct_non_fb = sum(c.query_type_correct for c in non_fallback)
        rr_correct = sum(c.retrieval_required_correct for c in case_results)
        action_correct = sum(c.action_correct for c in case_results)
        unnecessary = sum(c.unnecessary_decomposition for c in case_results)
        missed = sum(c.missed_decomposition for c in case_results)
        duplicate = sum(c.duplicate_subquery for c in case_results)
        unnecessary_eligible = sum(
            1 for c in case_results
            if c.gold_decomposition_expected == "forbidden"
        )
        missed_eligible = sum(
            1 for c in case_results
            if c.gold_decomposition_expected == "required"
        )
        latencies = [
            c.latency_ms for c in case_results if c.latency_ms is not None
        ]
        input_total = sum(
            c.input_tokens for c in case_results if c.input_tokens is not None
        )
        output_total = sum(
            c.output_tokens for c in case_results if c.output_tokens is not None
        )
        missing_usage = sum(
            1
            for c in case_results
            if c.input_tokens is None or c.output_tokens is None
        )
        timeout_count = sum(
            1 for c in case_results if c.failure_code == "PLANNER_TIMEOUT"
        )
        provider_error_count = sum(
            1 for c in case_results if c.failure_code == "PLANNER_PROVIDER_ERROR"
        )

        return Gate3PlannerMetrics(
            case_count=n,
            completed_outcome_count=n,
            schema_valid_count=schema_valid,
            schema_validity_rate=_safe_rate(schema_valid, n),
            fallback_count=fallback_count,
            fallback_rate=_safe_rate(fallback_count, n),
            failure_code_distribution=dict(
                sorted(
                    Counter(
                        c.failure_code for c in case_results if c.failure_code
                    ).items()
                )
            ),
            query_type_exact_correct_count=qt_correct_all,
            query_type_exact_accuracy_all=_safe_rate(qt_correct_all, n),
            query_type_exact_accuracy_non_fallback=_safe_rate(
                qt_correct_non_fb, len(non_fallback)
            ),
            retrieval_required_correct_count=rr_correct,
            retrieval_required_accuracy=_safe_rate(rr_correct, n),
            action_correct_count=action_correct,
            action_accuracy=_safe_rate(action_correct, n),
            unnecessary_decomposition_count=unnecessary,
            unnecessary_decomposition_eligible_count=unnecessary_eligible,
            unnecessary_decomposition_rate=_conditional_rate(
                unnecessary, unnecessary_eligible
            ),
            unnecessary_decomposition_overall_case_rate=_safe_rate(
                unnecessary, n
            ),
            missed_decomposition_count=missed,
            missed_decomposition_eligible_count=missed_eligible,
            missed_decomposition_rate=_conditional_rate(missed, missed_eligible),
            missed_decomposition_overall_case_rate=_safe_rate(missed, n),
            exact_duplicate_subquery_case_count=duplicate,
            exact_duplicate_subquery_rate=_safe_rate(duplicate, n),
            planner_call_count=n,
            input_tokens_total=input_total,
            output_tokens_total=output_total,
            missing_usage_count=missing_usage,
            latency_p50_ms=_percentile_ms(latencies, 50),
            latency_p95_ms=_percentile_ms(latencies, 95),
            timeout_count=timeout_count,
            timeout_rate=_safe_rate(timeout_count, n),
            provider_error_count=provider_error_count,
            provider_error_rate=_safe_rate(provider_error_count, n),
            stratified=Gate3PlannerDevRunner._stratified_metrics(case_results),
        )

    @staticmethod
    def _stratified_metrics(
        case_results: Sequence[Gate3PlannerCaseResult],
    ) -> dict:
        def summary(group: Sequence[Gate3PlannerCaseResult]) -> dict:
            m = len(group)
            valid = sum(not c.fallback_used for c in group)
            fb = sum(c.fallback_used for c in group)
            qt = sum(c.query_type_correct for c in group)
            rr = sum(c.retrieval_required_correct for c in group)
            ac = sum(c.action_correct for c in group)
            un = sum(c.unnecessary_decomposition for c in group)
            mi = sum(c.missed_decomposition for c in group)
            dup = sum(c.duplicate_subquery for c in group)
            un_eligible = sum(
                1 for c in group if c.gold_decomposition_expected == "forbidden"
            )
            mi_eligible = sum(
                1 for c in group if c.gold_decomposition_expected == "required"
            )
            return {
                "case_count": m,
                "schema_valid_count": valid,
                "schema_validity_rate": _safe_rate(valid, m),
                "fallback_count": fb,
                "fallback_rate": _safe_rate(fb, m),
                "query_type_exact_correct_count": qt,
                "query_type_exact_accuracy_all": _safe_rate(qt, m),
                "retrieval_required_correct_count": rr,
                "retrieval_required_accuracy": _safe_rate(rr, m),
                "action_correct_count": ac,
                "action_accuracy": _safe_rate(ac, m),
                "unnecessary_decomposition_count": un,
                "unnecessary_decomposition_eligible_count": un_eligible,
                "unnecessary_decomposition_rate": _conditional_rate(un, un_eligible),
                "unnecessary_decomposition_overall_case_rate": _safe_rate(un, m),
                "missed_decomposition_count": mi,
                "missed_decomposition_eligible_count": mi_eligible,
                "missed_decomposition_rate": _conditional_rate(mi, mi_eligible),
                "missed_decomposition_overall_case_rate": _safe_rate(mi, m),
                "exact_duplicate_subquery_case_count": dup,
                "exact_duplicate_subquery_rate": _safe_rate(dup, m),
            }

        return {
            "query_type": {
                qt: summary([c for c in case_results if c.gold_query_type == qt])
                for qt in sorted({c.gold_query_type for c in case_results})
            },
            "answerability": {
                a: summary([c for c in case_results if c.gold_answerability == a])
                for a in sorted({c.gold_answerability for c in case_results})
            },
            "decomposition_expected": {
                d: summary(
                    [c for c in case_results if c.gold_decomposition_expected == d]
                )
                for d in sorted(
                    {c.gold_decomposition_expected for c in case_results}
                )
            },
        }


# ---------------------------------------------------------------------------
# Artifact 写入（canonical JSON、原子、防覆盖）
# ---------------------------------------------------------------------------


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp-", suffix=".part"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _artifact_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def write_planner_dev_artifacts(
    result: Gate3PlannerDevResult,
    output_root: Path,
) -> dict:
    """写入 run_config/planner_results/planner_metrics；返回 {filename: sha256}。"""
    output_root = Path(output_root)
    run_dir = output_root / result.run_id
    if run_dir.exists():
        raise FileExistsError(f"输出目录已存在，禁止覆盖: {run_dir}")

    run_config = _canonical_json(result.config.to_dict()).decode("utf-8") + "\n"
    results_lines = "".join(
        _canonical_json(c.to_dict()).decode("utf-8") + "\n"
        for c in result.case_results
    )
    metrics = _canonical_json(result.metrics.to_dict()).decode("utf-8") + "\n"

    write_text_atomic(run_dir / "run_config.json", run_config)
    write_text_atomic(run_dir / "planner_results.jsonl", results_lines)
    write_text_atomic(run_dir / "planner_metrics.json", metrics)

    return {
        "run_config.json": _sha256_bytes(_artifact_bytes(run_config)),
        "planner_results.jsonl": _sha256_bytes(_artifact_bytes(results_lines)),
        "planner_metrics.json": _sha256_bytes(_artifact_bytes(metrics)),
    }


def write_abort_artifact(
    run_dir: Path,
    config: Gate3PlannerDevConfig,
    case_id: str,
    outcome: PlannerOutcome,
) -> dict:
    """首条 Provider 失败时保留脱敏 abort Artifact（不入 git，防覆盖）。

    只使用首次调用产生的 outcome；严禁再次调用 planner。
    """
    run_dir = Path(run_dir)
    if run_dir.exists():
        raise FileExistsError(f"输出目录已存在，禁止覆盖: {run_dir}")
    abort = {
        "schema_version": PLANNER_ABORT_SCHEMA_VERSION,
        "status": "ABORTED_FIRST_PROVIDER_FAILURE",
        "run_id": config.run_id,
        "config": config.to_dict(),
        "completed_case_count": 1,
        "planner_call_count": 1,
        "case_id": case_id,
        "failure_code": outcome.failure_code,
        "call_metadata": _build_call_metadata_dict(config, outcome),
        "fallback_plan": outcome.plan.to_dict(),
    }
    text = _canonical_json(abort).decode("utf-8") + "\n"
    write_text_atomic(run_dir / "abort.json", text)
    return {"abort.json": _sha256_bytes(_artifact_bytes(text))}


def finalize_planner_dev_run(run_dir: Path) -> dict:
    """读取 4 个 Artifact，写 result.json（不自引用自身哈希）。"""
    run_dir = Path(run_dir)
    run_config_path = run_dir / "run_config.json"
    results_path = run_dir / "planner_results.jsonl"
    metrics_path = run_dir / "planner_metrics.json"
    review_path = run_dir / "planner_semantic_review.md"
    for path in (run_config_path, results_path, metrics_path, review_path):
        if not path.is_file():
            raise FileNotFoundError(f"缺少 Artifact: {path}")

    config = json.loads(run_config_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    artifact_sha = {
        "run_config.json": _sha256_bytes(run_config_path.read_bytes()),
        "planner_results.jsonl": _sha256_bytes(results_path.read_bytes()),
        "planner_metrics.json": _sha256_bytes(metrics_path.read_bytes()),
        "planner_semantic_review.md": _sha256_bytes(review_path.read_bytes()),
    }
    summary = {
        "schema_version": PLANNER_RESULT_SUMMARY_SCHEMA_VERSION,
        "run_id": config["run_id"],
        "config": config,
        "metrics": metrics,
        "artifact_sha256": artifact_sha,
    }
    result_path = run_dir / "result.json"
    if result_path.exists():
        raise FileExistsError(f"result.json 已存在，禁止覆盖: {result_path}")
    text = _canonical_json(summary).decode("utf-8") + "\n"
    write_text_atomic(result_path, text)
    return {
        "result.json": _sha256_bytes(_artifact_bytes(text)),
        **artifact_sha,
    }


# ---------------------------------------------------------------------------
# R1 离线重分析
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate3PlannerAnalysisConfig:
    schema_version: str = PLANNER_DEV_ANALYSIS_SCHEMA_VERSION
    analysis_source_commit: str = ""
    parent_run_id: str = ""
    parent_source_commit: str = ""
    parent_planner_results_sha256: str = ""
    parent_result_json_sha256: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    dev_jsonl_sha256: str = ""
    dev_manifest_sha256: str = ""
    gate3_dataset_freeze_id: str = ""
    metrics_schema_version: str = PLANNER_METRICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != PLANNER_DEV_ANALYSIS_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version 必须是 {PLANNER_DEV_ANALYSIS_SCHEMA_VERSION!r}"
            )
        _check_hex(self.analysis_source_commit, 40, "analysis_source_commit")
        _check_hex(self.parent_source_commit, 40, "parent_source_commit")
        _check_hex(self.parent_run_id, 12, "parent_run_id")
        _check_hex(self.corpus_id, 12, "corpus_id")
        _check_hex(self.evaluation_set_id, 12, "evaluation_set_id")
        _check_hex(self.gate3_dataset_freeze_id, 12, "gate3_dataset_freeze_id")
        _check_hex(self.parent_planner_results_sha256, 64,
                   "parent_planner_results_sha256")
        _check_hex(self.parent_result_json_sha256, 64,
                   "parent_result_json_sha256")
        _check_hex(self.dev_jsonl_sha256, 64, "dev_jsonl_sha256")
        _check_hex(self.dev_manifest_sha256, 64, "dev_manifest_sha256")
        if type(self.metrics_schema_version) is not str or \
                self.metrics_schema_version != PLANNER_METRICS_SCHEMA_VERSION:
            raise ValueError(
                "metrics_schema_version 必须是实际发射的 "
                f"{PLANNER_METRICS_SCHEMA_VERSION!r}"
            )

    def identity_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "analysis_source_commit": self.analysis_source_commit,
            "parent_run_id": self.parent_run_id,
            "parent_source_commit": self.parent_source_commit,
            "parent_planner_results_sha256": self.parent_planner_results_sha256,
            "parent_result_json_sha256": self.parent_result_json_sha256,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
            "dev_manifest_sha256": self.dev_manifest_sha256,
            "gate3_dataset_freeze_id": self.gate3_dataset_freeze_id,
            "metrics_schema_version": self.metrics_schema_version,
        }

    @property
    def analysis_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.identity_payload()))[:12]

    def to_dict(self) -> dict:
        return {**self.identity_payload(), "analysis_id": self.analysis_id}


@dataclass(frozen=True)
class Gate3PlannerAnalysisResult:
    analysis_id: str
    config: Gate3PlannerAnalysisConfig
    metrics: Gate3PlannerMetrics
    case_results: tuple[Gate3PlannerCaseResult, ...]


def _case_result_from_record(
    record: dict,
    gold_case: Gate3Case,
    config_identity: dict,
) -> Gate3PlannerCaseResult:
    """从 R0 planner_results 记录 + 已验证 Dev Gold 重建 CaseResult。

    使用 QueryPlan.from_dict 严格重建计划，不信任旧 correctness/predicted 派生字段；
    predicted 必须与重建后的 QueryPlan 一致。
    """
    plan_dict = record.get("plan")
    if not isinstance(plan_dict, dict):
        raise ValueError(f"{gold_case.case_id} 缺 plan")
    plan = QueryPlan.from_dict(plan_dict)
    predicted = record.get("predicted", {})
    if plan.original_query != record.get("query"):
        raise ValueError(f"{gold_case.case_id} plan.original_query 与 record.query 不一致")
    if predicted.get("query_type") != plan.query_type:
        raise ValueError(f"{gold_case.case_id} predicted.query_type 与 plan 不一致")
    if predicted.get("retrieval_required") != plan.retrieval_required:
        raise ValueError(f"{gold_case.case_id} predicted.retrieval_required 与 plan 不一致")
    if predicted.get("action") != plan.action:
        raise ValueError(f"{gold_case.case_id} predicted.action 与 plan 不一致")
    if predicted.get("reason_code") != plan.reason_code:
        raise ValueError(f"{gold_case.case_id} predicted.reason_code 与 plan 不一致")

    fallback_used = record.get("fallback_used")
    failure_code = record.get("failure_code")
    if type(fallback_used) is not bool:
        raise ValueError(f"{gold_case.case_id} fallback_used 必须是 bool")
    if fallback_used:
        if not failure_code:
            raise ValueError(f"{gold_case.case_id} fallback 必须带 failure_code")
        if not (
            plan.reason_code == "PLANNER_FALLBACK"
            and plan.query_type == "unknown"
            and plan.action == "single_retrieval"
            and not plan.subqueries
        ):
            raise ValueError(f"{gold_case.case_id} fallback plan 形状不合法")
    else:
        if failure_code is not None:
            raise ValueError(f"{gold_case.case_id} 正常结果不允许带 failure_code")

    gold_action = gold_action_for(gold_case)
    query_type_correct = plan.query_type == gold_case.query_type
    retrieval_required_correct = plan.retrieval_required == gold_case.retrieval_required
    action_correct = plan.action == gold_action
    unnecessary = (
        plan.action == "decomposed_retrieval"
        and gold_action != "decomposed_retrieval"
    )
    missed = (
        gold_action == "decomposed_retrieval"
        and plan.action != "decomposed_retrieval"
    )
    queries = [s["query"] for s in plan.to_dict()["subqueries"]]
    duplicate = failure_code == "PLAN_DUPLICATE_SUBQUERY" or (
        len(set(queries)) != len(queries)
    )

    call = record.get("call_metadata") or {
        "input_tokens": record.get("call", {}).get("input_tokens"),
        "output_tokens": record.get("call", {}).get("output_tokens"),
        "latency_ms": record.get("call", {}).get("latency_ms"),
    }
    call_metadata = {
        "provider": config_identity["provider"],
        "model": config_identity["model"],
        "prompt_version": config_identity["prompt_version"],
        "prompt_sha256": config_identity["prompt_sha256"],
        "call_count": 1,
        "input_tokens": call.get("input_tokens"),
        "output_tokens": call.get("output_tokens"),
        "latency_ms": call.get("latency_ms"),
    }
    return Gate3PlannerCaseResult(
        case_id=gold_case.case_id,
        query=record["query"],
        gold_query_type=gold_case.query_type,
        gold_answerability=gold_case.answerability,
        gold_retrieval_required=gold_case.retrieval_required,
        gold_decomposition_expected=gold_case.decomposition_expected,
        gold_action=gold_action,
        predicted_query_type=plan.query_type,
        predicted_retrieval_required=plan.retrieval_required,
        predicted_action=plan.action,
        reason_code=plan.reason_code,
        fallback_used=fallback_used,
        failure_code=failure_code,
        query_type_correct=query_type_correct,
        retrieval_required_correct=retrieval_required_correct,
        action_correct=action_correct,
        unnecessary_decomposition=unnecessary,
        missed_decomposition=missed,
        duplicate_subquery=duplicate,
        input_tokens=call_metadata["input_tokens"],
        output_tokens=call_metadata["output_tokens"],
        latency_ms=call_metadata["latency_ms"],
        call_metadata=call_metadata,
        plan=plan.to_dict(),
    )


def reanalyze_planner_dev_run(
    parent_run_dir: Path,
    expected_r0_sha256: dict,
    evaluation_set: Gate3EvaluationSet,
    dev_manifest_sha256: str,
    gate3_dataset_freeze_id: str,
    analysis_source_commit: str,
) -> Gate3PlannerAnalysisResult:
    """读取 R0 Artifact，验证 SHA/run_id/身份后重算 v2 metrics；不调用模型。"""
    parent_run_dir = Path(parent_run_dir)
    run_config_path = parent_run_dir / "run_config.json"
    results_path = parent_run_dir / "planner_results.jsonl"
    result_json_path = parent_run_dir / "result.json"

    for name in ("run_config.json", "planner_results.jsonl",
                 "planner_metrics.json", "planner_semantic_review.md",
                 "result.json"):
        p = parent_run_dir / name
        if not p.is_file():
            raise FileNotFoundError(f"R0 Artifact 缺失: {p}")
        if _sha256_bytes(p.read_bytes()) != expected_r0_sha256[name]:
            raise ValueError(f"R0 Artifact SHA 变化: {name}")

    config = json.loads(run_config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != PLANNER_DEV_SCHEMA_VERSION_V1:
        raise ValueError("R0 run_config 必须是历史 v1")
    parent_run_id = _v1_run_id(config)
    if parent_run_id != config.get("run_id"):
        raise ValueError("R0 run_id 与重建身份不一致")

    result_json = json.loads(result_json_path.read_text(encoding="utf-8"))
    if result_json.get("run_id") != parent_run_id:
        raise ValueError("R0 result.json run_id 不一致")

    case_by_id = {c.case_id: c for c in evaluation_set.cases}
    dev_case_ids = set(case_by_id)
    case_results = []
    seen = set()
    with results_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            cid = record.get("case_id")
            if cid not in dev_case_ids:
                raise ValueError(
                    f"第 {lineno} 行 case_id 不在 Dev EvaluationSet: {cid!r}"
                )
            if cid in seen:
                raise ValueError(f"case_id 重复: {cid}")
            seen.add(cid)
            gold = case_by_id[cid]
            if record.get("query") != gold.query:
                raise ValueError(f"{cid} query 与 Dev Gold 不一致")
            case_results.append(_case_result_from_record(record, gold, config))

    if seen != dev_case_ids:
        missing = sorted(dev_case_ids - seen)
        raise ValueError(f"R0 遗漏 Case（即便总数相同）: {missing}")

    if len(case_results) != len(evaluation_set.cases):
        raise ValueError(
            f"R0 结果条数 {len(case_results)} != Dev Case 数 "
            f"{len(evaluation_set.cases)}"
        )

    metrics = Gate3PlannerDevRunner._compute_metrics(case_results)
    analysis_config = Gate3PlannerAnalysisConfig(
        analysis_source_commit=analysis_source_commit,
        parent_run_id=parent_run_id,
        parent_source_commit=config.get("source_commit", ""),
        parent_planner_results_sha256=expected_r0_sha256["planner_results.jsonl"],
        parent_result_json_sha256=expected_r0_sha256["result.json"],
        corpus_id=evaluation_set.corpus_id,
        evaluation_set_id=evaluation_set.evaluation_set_id,
        dev_jsonl_sha256=config.get("dev_jsonl_sha256", ""),
        dev_manifest_sha256=dev_manifest_sha256,
        gate3_dataset_freeze_id=gate3_dataset_freeze_id,
    )
    return Gate3PlannerAnalysisResult(
        analysis_id=analysis_config.analysis_id,
        config=analysis_config,
        metrics=metrics,
        case_results=tuple(case_results),
    )


def write_analysis_artifacts(
    analysis_result: Gate3PlannerAnalysisResult,
    analysis_root: Path,
) -> dict:
    """写 analysis_config.json + planner_metrics.json；返回 {filename: sha256}。"""
    analysis_root = Path(analysis_root)
    analysis_dir = analysis_root / analysis_result.analysis_id
    if analysis_dir.exists():
        raise FileExistsError(f"分析目录已存在，禁止覆盖: {analysis_dir}")

    cfg_text = _canonical_json(analysis_result.config.to_dict()).decode("utf-8") + "\n"
    metrics_text = (
        _canonical_json(analysis_result.metrics.to_dict()).decode("utf-8") + "\n"
    )
    write_text_atomic(analysis_dir / "analysis_config.json", cfg_text)
    write_text_atomic(analysis_dir / "planner_metrics.json", metrics_text)
    return {
        "analysis_config.json": _sha256_bytes(_artifact_bytes(cfg_text)),
        "planner_metrics.json": _sha256_bytes(_artifact_bytes(metrics_text)),
    }


def finalize_analysis(analysis_dir: Path) -> dict:
    """读取 analysis_config/planner_metrics/planner_semantic_review，写 result.json。

    校验 declared metrics_schema_version 与 emitted metrics.schema_version 一致；
    result.json 已存在时防覆盖。
    """
    analysis_dir = Path(analysis_dir)
    cfg_path = analysis_dir / "analysis_config.json"
    metrics_path = analysis_dir / "planner_metrics.json"
    review_path = analysis_dir / "planner_semantic_review.md"
    for path in (cfg_path, metrics_path, review_path):
        if not path.is_file():
            raise FileNotFoundError(f"缺少 R1 Artifact: {path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if cfg.get("metrics_schema_version") != metrics.get("schema_version"):
        raise ValueError(
            "analysis_config.metrics_schema_version "
            f"({cfg.get('metrics_schema_version')!r}) 与 "
            f"planner_metrics.schema_version "
            f"({metrics.get('schema_version')!r}) 不一致"
        )
    artifact_sha = {
        "analysis_config.json": _sha256_bytes(cfg_path.read_bytes()),
        "planner_metrics.json": _sha256_bytes(metrics_path.read_bytes()),
        "planner_semantic_review.md": _sha256_bytes(review_path.read_bytes()),
    }
    summary = {
        "schema_version": PLANNER_DEV_ANALYSIS_RESULT_SCHEMA_VERSION,
        "analysis_id": cfg["analysis_id"],
        "analysis_config": cfg,
        "metrics": metrics,
        "artifact_sha256": artifact_sha,
    }
    result_path = analysis_dir / "result.json"
    if result_path.exists():
        raise FileExistsError(f"result.json 已存在，禁止覆盖: {result_path}")
    text = _canonical_json(summary).decode("utf-8") + "\n"
    write_text_atomic(result_path, text)
    return {
        "result.json": _sha256_bytes(_artifact_bytes(text)),
        **artifact_sha,
    }
