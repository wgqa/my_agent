"""G3-DECOMP-04B-02A：可复现 Dev Planner 校准 Runner。

对公开 Gate 3 Dev 24 Case 运行已审计的 BaseQueryPlanner，建立调优前
真实模型 baseline 与 Planning 指标。只做 Planning 层（不检索、不回答、
不算 obligation coverage / Hit@5 / Recall / MRR / nDCG）。Gold 标签只
在模型调用完成后用于指标计算，绝不传入 Planner。

本模块不访问 sealed/Holdout；输出 Artifact 用 canonical JSON + 原子写入。
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

from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan
from evaluation.gate3.evaluation_set import Gate3Case, Gate3EvaluationSet

PLANNER_DEV_SCHEMA_VERSION = "gate3_planner_dev_run_v1"
PLANNER_RESULTS_SCHEMA_VERSION = "gate3_planner_dev_results_v1"
PLANNER_METRICS_SCHEMA_VERSION = "gate3_planner_dev_metrics_v1"
PLANNER_RESULT_SUMMARY_SCHEMA_VERSION = "gate3_planner_dev_result_v1"


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


def _percentile_ms(values: Sequence[float], p: int) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    k = math.ceil(p / 100 * len(ordered))
    return float(ordered[k - 1])


def gold_action_for(case: Gate3Case) -> str:
    """Gold action 映射（任务七固定口径）。

    decomposition_expected=required → decomposed_retrieval；
    forbidden 且 retrieval_required=true → single_retrieval；
    forbidden 且 retrieval_required=false → no_retrieval。
    未来出现 optional 时必须单独报告，不得归入 required/forbidden。
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
    """一次 Dev Planner 校准运行的固定配置；run_id 由身份 payload 计算。"""

    schema_version: str = PLANNER_DEV_SCHEMA_VERSION
    source_commit: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    dev_jsonl_sha256: str = ""
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    prompt_sha256: str = ""
    temperature: int = 0
    max_tokens: int = 800
    timeout: float = 20.0
    max_retries: int = 0

    def identity_payload(self) -> dict:
        """run_id 身份载荷：排除 run_id 自身，不绑定 API Key/base_url/路径/时间/latency。"""
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
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
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "run_id": self.run_id,
        }


# ---------------------------------------------------------------------------
# 每 Case 结果与指标
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
            "call": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "latency_ms": self.latency_ms,
            },
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
    unnecessary_decomposition_rate: float = 0.0
    missed_decomposition_count: int = 0
    missed_decomposition_rate: float = 0.0
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
            "unnecessary_decomposition_rate": self.unnecessary_decomposition_rate,
            "missed_decomposition_count": self.missed_decomposition_count,
            "missed_decomposition_rate": self.missed_decomposition_rate,
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
# Runner
# ---------------------------------------------------------------------------


class ProviderFailFast(RuntimeError):
    """首条 Case 发生 Provider 错误/超时时停止正式运行，避免连续浪费请求。"""


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
            # 只传 original_query；Gold 标签在模型调用之后用于指标。
            outcome = self._planner.plan(case.query)
            if (
                fail_fast_on_provider_error
                and index == 0
                and outcome.failure_code
                in ("PLANNER_PROVIDER_ERROR", "PLANNER_TIMEOUT")
            ):
                raise ProviderFailFast(
                    f"首条 Case {case.case_id} 发生 {outcome.failure_code}，"
                    "停止正式运行，避免连续浪费 24 次请求"
                )
            case_results.append(self._evaluate_case(case, outcome))
        metrics = self._compute_metrics(case_results)
        return Gate3PlannerDevResult(
            run_id=self._config.run_id,
            config=self._config,
            metrics=metrics,
            case_results=tuple(case_results),
        )

    @staticmethod
    def _evaluate_case(
        case: Gate3Case, outcome: PlannerOutcome
    ) -> Gate3PlannerCaseResult:
        plan: QueryPlan = outcome.plan
        predicted_action = plan.action
        predicted_qt = plan.query_type
        predicted_rr = plan.retrieval_required
        gold_action = gold_action_for(case)

        query_type_correct = predicted_qt == case.query_type
        retrieval_required_correct = predicted_rr == case.retrieval_required
        action_correct = predicted_action == gold_action

        # unnecessary：gold 不该分解而模型分解；missed：gold 该分解而模型没分解。
        unnecessary_decomposition = (
            predicted_action == "decomposed_retrieval"
            and gold_action != "decomposed_retrieval"
        )
        missed_decomposition = (
            gold_action == "decomposed_retrieval"
            and predicted_action != "decomposed_retrieval"
        )
        queries = [s["query"] for s in plan.to_dict()["subqueries"]]
        duplicate_subquery = len(set(queries)) != len(queries)

        metadata = outcome.call_metadata
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
            input_tokens=metadata.input_tokens if metadata else None,
            output_tokens=metadata.output_tokens if metadata else None,
            latency_ms=metadata.latency_ms if metadata else None,
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
            unnecessary_decomposition_rate=_safe_rate(unnecessary, n),
            missed_decomposition_count=missed,
            missed_decomposition_rate=_safe_rate(missed, n),
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
            ac = sum(c.action_correct for c in group)
            un = sum(c.unnecessary_decomposition for c in group)
            mi = sum(c.missed_decomposition for c in group)
            return {
                "case_count": m,
                "schema_valid_count": valid,
                "schema_validity_rate": _safe_rate(valid, m),
                "fallback_count": fb,
                "fallback_rate": _safe_rate(fb, m),
                "query_type_exact_correct_count": qt,
                "query_type_exact_accuracy_all": _safe_rate(qt, m),
                "action_correct_count": ac,
                "action_accuracy": _safe_rate(ac, m),
                "unnecessary_decomposition_count": un,
                "unnecessary_decomposition_rate": _safe_rate(un, m),
                "missed_decomposition_count": mi,
                "missed_decomposition_rate": _safe_rate(mi, m),
            }

        return {
            "query_type": {
                qt: summary([c for c in case_results if c.gold_query_type == qt])
                for qt in sorted({c.gold_query_type for c in case_results})
            },
            "answerability": {
                a: summary(
                    [c for c in case_results if c.gold_answerability == a]
                )
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
    """写入 run_config/planner_results/planner_metrics；返回 {filename: sha256}。

    输出目录已存在时 fail-fast，不静默覆盖。canonical JSON + UTF-8 + 原子写入。
    """
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


def finalize_planner_dev_run(run_dir: Path) -> dict:
    """读取已写入的 4 个 Artifact，写 result.json（汇总身份、指标与 SHA-256）。

    result.json 不自引用自身哈希。缺少任何 Artifact 时 fail-fast。
    """
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
    text = _canonical_json(summary).decode("utf-8") + "\n"
    write_text_atomic(run_dir / "result.json", text)
    return {
        "result.json": _sha256_bytes(_artifact_bytes(text)),
        **artifact_sha,
    }
