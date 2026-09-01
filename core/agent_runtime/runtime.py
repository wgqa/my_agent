"""G3-RUNTIME-05A/05C + G3-ADAPT-06A：Agent Runtime 执行与自适应检索。

把 QueryPlan 通过确定性 Router（Adaptive Policy v1）转成 RouteDecision v2，
执行 direct_answer / single_retrieval / decomposed_retrieval（多子问题）；
BM25 证据为空时最多一次 Hybrid 补检索；构建 EvidenceBundle、跑结构化
Verifier、写脱敏 RunTrace 并返回 AgentRunResult。外部能力经 RetrievalPort /
AnswerPort 注入；本模块不调用真实模型/检索/生成，不读 Holdout。
"""

from __future__ import annotations

import math
import uuid
from typing import Optional, Protocol, Sequence, runtime_checkable

from core.adaptive_retrieval import (
    ADAPTIVE_RETRIEVAL_POLICY_VERSION,
    resolve_initial_strategy,
)
from core.agent_runtime.evidence import (
    DEFAULT_MERGE_RRF_K,
    MERGE_POLICIES,
    SUBQUERY_ROUND_ROBIN_V1,
    merge_subquery_results_policy,
)
from core.agent_runtime.models import (
    AGENT_REFUSAL_ANSWER,
    ROUTE_DECISION_SCHEMA_VERSION,
    AgentRunBudget,
    AgentRunResult,
    Document,
    EvidenceBundle,
    RouteDecision,
    TraceEvent,
    VerificationResult,
)
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan
from core.conversation_context import (
    ConversationQueryResolution,
    RecentContextWindow,
)

# decomposed 路径的子问题稳定标识（QueryPlan 已保证 sq1/sq2/sq3 顺序）。
_SUBQUERY_IDS = ("sq1", "sq2", "sq3")


@runtime_checkable
class RetrievalPort(Protocol):
    """检索端口契约：Adapter 需实现 search 与只读能力声明 supported_strategies。"""

    supported_strategies: tuple[str, ...]

    def search(self, query: str, strategy: str, top_k: int) -> Sequence[Document]:
        """执行一次检索；strategy 与 top_k 由调用方给定。"""
        ...


@runtime_checkable
class AnswerPort(Protocol):
    """答案端口契约：根据证据生成答案；mode 只允许 direct / grounded。"""

    def answer(
        self,
        question: str,
        evidence_bundle: EvidenceBundle,
        mode: str,
    ) -> str:
        """生成答案；direct 模式可忽略 evidence_bundle。"""
        ...


class DeterministicRouter:
    """只根据 QueryPlan + Adaptive Policy v1 路由，不调用 LLM、不改 plan。

    初始检索策略由 resolve_initial_strategy 按 query_type/action 与
    supported_strategies 确定性选择；策略原因单独记录在
    strategy_reason_code，不与 Planner 的 reason_code 混用。
    """

    def route(
        self, plan: QueryPlan, supported_strategies=()
    ) -> RouteDecision:
        if not isinstance(plan, QueryPlan):
            raise TypeError(
                f"route 输入必须是 QueryPlan，实际 {type(plan).__name__}"
            )
        strategy, strategy_reason = resolve_initial_strategy(
            plan, supported_strategies
        )
        action = plan.action
        if action == "no_retrieval":
            return RouteDecision(
                schema_version=ROUTE_DECISION_SCHEMA_VERSION,
                route="direct_answer",
                retrieval_strategy="none",
                queries=(),
                reason_code=plan.reason_code,
                router_policy_version=ADAPTIVE_RETRIEVAL_POLICY_VERSION,
                strategy_reason_code=strategy_reason,
            )
        if action == "single_retrieval":
            return RouteDecision(
                schema_version=ROUTE_DECISION_SCHEMA_VERSION,
                route="single_retrieval",
                retrieval_strategy=strategy,
                queries=(plan.original_query,),
                reason_code=plan.reason_code,
                router_policy_version=ADAPTIVE_RETRIEVAL_POLICY_VERSION,
                strategy_reason_code=strategy_reason,
            )
        if action == "decomposed_retrieval":
            return RouteDecision(
                schema_version=ROUTE_DECISION_SCHEMA_VERSION,
                route="decomposed_retrieval",
                retrieval_strategy="bm25",
                queries=tuple(sub.query for sub in plan.subqueries),
                reason_code=plan.reason_code,
                router_policy_version=ADAPTIVE_RETRIEVAL_POLICY_VERSION,
                strategy_reason_code=strategy_reason,
            )
        raise ValueError(f"未知 action {action!r}")  # pragma: no cover


class MinimalEvidenceVerifier:
    """结构化 Verifier：query-level evidence coverage，不宣称 claim-level
    Faithfulness。

      no_retrieval               → not_required / can_generate=true
      single / decomposed 覆盖齐  → supported / can_generate=true
      single 无证据               → insufficient_evidence（INSUFFICIENT_EVIDENCE）
      decomposed 有 required 子问题缺证据 → insufficient_evidence
        （INCOMPLETE_SUBQUERY_EVIDENCE）

    当调用方传入 required_query_ids / covered_query_ids 时按覆盖计算
    missing / coverage_complete；未传时回退到“Bundle 有无证据”的历史行为。
    """

    def verify(
        self,
        plan: QueryPlan,
        bundle: EvidenceBundle,
        *,
        required_query_ids=(),
        covered_query_ids=(),
        upgrade_attempted: bool = False,
        upgrade_used: bool = False,
        retrieval_required: bool = True,
    ) -> VerificationResult:
        if type(retrieval_required) is not bool:
            raise TypeError("retrieval_required 必须是严格 bool")
        if not retrieval_required:
            return VerificationResult(
                schema_version="verification_result_v1",
                status="not_required",
                can_generate=True,
                reason_code="NOT_REQUIRED",
                evidence_count=len(bundle.items),
                warnings=(),
            )
        if plan.action == "no_retrieval":
            return VerificationResult(
                schema_version="verification_result_v1",
                status="not_required",
                can_generate=True,
                reason_code="NOT_REQUIRED",
                evidence_count=len(bundle.items),
                warnings=(),
            )
        if required_query_ids:
            missing = [
                qid for qid in required_query_ids if qid not in covered_query_ids
            ]
            coverage_complete = (not missing) and bool(bundle.items)
            if coverage_complete:
                return VerificationResult(
                    schema_version="verification_result_v1",
                    status="supported",
                    can_generate=True,
                    reason_code="SUPPORTED",
                    evidence_count=len(bundle.items),
                    warnings=(),
                    required_query_ids=tuple(required_query_ids),
                    covered_query_ids=tuple(covered_query_ids),
                    missing_query_ids=(),
                    coverage_complete=True,
                    upgrade_attempted=upgrade_attempted,
                    upgrade_used=upgrade_used,
                )
            reason = (
                "INCOMPLETE_SUBQUERY_EVIDENCE"
                if plan.action == "decomposed_retrieval"
                else "INSUFFICIENT_EVIDENCE"
            )
            return VerificationResult(
                schema_version="verification_result_v1",
                status="insufficient_evidence",
                can_generate=False,
                reason_code=reason,
                evidence_count=len(bundle.items),
                warnings=(),
                required_query_ids=tuple(required_query_ids),
                covered_query_ids=tuple(covered_query_ids),
                missing_query_ids=tuple(missing),
                coverage_complete=False,
                upgrade_attempted=upgrade_attempted,
                upgrade_used=upgrade_used,
            )
        # 历史回退：未提供覆盖信息时按 Bundle 有无证据判断。
        if bundle.items:
            return VerificationResult(
                schema_version="verification_result_v1",
                status="supported",
                can_generate=True,
                reason_code="SUPPORTED",
                evidence_count=len(bundle.items),
                warnings=(),
            )
        return VerificationResult(
            schema_version="verification_result_v1",
            status="insufficient_evidence",
            can_generate=False,
            reason_code="INSUFFICIENT_EVIDENCE",
            evidence_count=0,
            warnings=(),
            coverage_complete=False,
        )


class AgentRuntime:
    """Agent Runtime：执行 direct/single/decomposed，自适应检索 + 单次补检索。

    构造注入 BaseQueryPlanner / RetrievalPort / AnswerPort / AgentRunBudget /
    可选 run_id_factory。run() 每次独立计数（每 run 各 Port 预算重置），
    外部 Port 调用前都检查预算；异常不吞掉，转成结构化 failed result，
    Trace 只记录异常类型名。decomposed 多子问题执行；BM25 证据为空时最多
    一次 Hybrid 补检索，不静默降级、不无限循环。
    """

    def __init__(
        self,
        *,
        planner: BaseQueryPlanner,
        retrieval_port: RetrievalPort,
        answer_port: AnswerPort,
        budget: Optional[AgentRunBudget] = None,
        merge_policy: str = SUBQUERY_ROUND_ROBIN_V1,
        merge_rrf_k: float = DEFAULT_MERGE_RRF_K,
        run_id_factory=None,
        context_window: Optional[RecentContextWindow] = None,
        query_resolver=None,
    ) -> None:
        if not isinstance(planner, BaseQueryPlanner):
            raise TypeError(
                f"planner 必须是 BaseQueryPlanner，实际 {type(planner).__name__}"
            )
        if not isinstance(retrieval_port, RetrievalPort):
            raise TypeError("retrieval_port 必须实现 RetrievalPort")
        if not isinstance(answer_port, AnswerPort):
            raise TypeError("answer_port 必须实现 AnswerPort")
        if budget is not None and not isinstance(budget, AgentRunBudget):
            raise TypeError(
                f"budget 必须是 AgentRunBudget，实际 {type(budget).__name__}"
            )
        if merge_policy not in MERGE_POLICIES:
            raise ValueError(
                f"merge_policy 必须是 {'、'.join(MERGE_POLICIES)} 之一，"
                f"实际 {merge_policy!r}"
            )
        if isinstance(merge_rrf_k, bool) or type(merge_rrf_k) not in (int, float):
            raise TypeError("merge_rrf_k 必须是数字（不允许 bool）")
        if not math.isfinite(merge_rrf_k) or merge_rrf_k <= 0:
            raise ValueError("merge_rrf_k 必须是有限正数")
        if run_id_factory is not None and not callable(run_id_factory):
            raise TypeError("run_id_factory 必须是可调用对象")
        self._planner = planner
        self._retrieval_port = retrieval_port
        self._answer_port = answer_port
        self._budget = budget if budget is not None else AgentRunBudget()
        self._merge_policy = merge_policy
        self._merge_rrf_k = float(merge_rrf_k)
        self._run_id_factory = run_id_factory
        self._context_window = context_window or RecentContextWindow()
        self._query_resolver = query_resolver
        self._router = DeterministicRouter()
        self._verifier = MinimalEvidenceVerifier()

    def run(
        self, question: str, history=(), top_k: int = 5
    ) -> AgentRunResult:
        # Keep the old positional run(question, top_k) form working while the
        # public API uses run(question, history, top_k).
        if type(history) is int and not isinstance(history, bool) and top_k == 5:
            top_k = history
            history = ()
        if type(question) is not str or not question.strip():
            raise ValueError("question 必须是非空字符串")
        if type(top_k) is not int or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k 必须是严格正整数")

        trace: list[TraceEvent] = []

        def emit(event_type: str, summary: str, data: dict) -> None:
            trace.append(
                TraceEvent(
                    sequence=len(trace) + 1,
                    event_type=event_type,
                    summary=summary,
                    data=data,
                )
            )

        # 每次 run 独立计数：外部 Port 调用前检查预算。
        steps = 0
        planner_calls = 0
        retrieval_calls = 0
        generation_calls = 0
        runtime_warnings: list[str] = []

        def ensure_budget(port: str) -> bool:
            if steps >= self._budget.max_steps:
                return False
            if port == "planner" and planner_calls >= self._budget.max_planner_calls:
                return False
            if (
                port == "retrieval"
                and retrieval_calls >= self._budget.max_retrieval_calls
            ):
                return False
            if (
                port == "generation"
                and generation_calls >= self._budget.max_generation_calls
            ):
                return False
            return True

        def budget_failed(
            planner_outcome, route_decision, bundle, verification
        ) -> AgentRunResult:
            emit(
                "run_failed",
                "budget exceeded",
                {"error_code": "BUDGET_EXCEEDED"},
            )
            return _result(
                status="failed",
                planner_outcome=planner_outcome,
                route_decision=route_decision,
                bundle=bundle,
                verification=verification,
                answer=None,
                sources=(),
                error_code="BUDGET_EXCEEDED",
            )

        def run_failed(
            error_code: str, exception_type: str, planner_outcome, route_decision,
            bundle, verification,
        ) -> AgentRunResult:
            # Generator implementation details are not part of the public
            # Agent trace. Keep the stable runtime failure contract while
            # preserving diagnostic type names for planner/retrieval faults.
            safe_exception_type = (
                "GENERATION_FAILED"
                if error_code == "GENERATION_FAILED"
                else exception_type
            )
            emit(
                "run_failed",
                "run failed",
                {"error_code": error_code, "exception_type": safe_exception_type},
            )
            return _result(
                status="failed",
                planner_outcome=planner_outcome,
                route_decision=route_decision,
                bundle=bundle,
                verification=verification,
                answer=None,
                sources=(),
                error_code=error_code,
            )

        def _result(
            *,
            status: str,
            planner_outcome,
            route_decision,
            bundle,
            verification,
            answer,
            sources,
            error_code,
        ) -> AgentRunResult:
            return AgentRunResult(
                run_id=run_id,
                status=status,
                planner_outcome=planner_outcome,
                route_decision=route_decision,
                evidence_bundle=bundle,
                verification=verification,
                answer=answer,
                sources=sources,
                trace=tuple(trace),
                error_code=error_code,
                warnings=tuple(runtime_warnings),
            )

        run_id = (
            self._run_id_factory() if self._run_id_factory else uuid.uuid4().hex
        )
        emit("run_started", "run started", {"run_id": run_id})

        context = self._context_window.prepare(history)
        resolution = ConversationQueryResolution(question, False, False)
        if context.selected_messages and self._query_resolver is not None:
            resolution = self._query_resolver.resolve(
                context.selected_messages, question
            )
        if resolution.fallback:
            runtime_warnings.append("CONTEXT_RESOLUTION_FALLBACK")
        emit(
            "context_prepared",
            "conversation context prepared",
            {
                "history_messages_received": context.received_count,
                "history_messages_used": context.used_count,
                "history_tokens_used": context.used_tokens,
                "history_truncated": context.truncated,
                "resolver_used": resolution.resolver_used,
                "resolver_fallback": resolution.fallback,
            },
        )
        resolved_question = resolution.standalone_query

        # ---- Planner（所有路径恰好调用一次）----
        if not ensure_budget("planner"):
            return budget_failed(None, None, None, None)
        planner_calls += 1
        steps += 1
        try:
            outcome = self._planner.plan(resolved_question)
        except Exception as exc:
            return run_failed(
                "PLANNING_FAILED",
                type(exc).__name__,
                None,
                None,
                None,
                None,
            )
        if not isinstance(outcome, PlannerOutcome):
            return run_failed(
                "PLANNING_FAILED", "InvalidPlannerOutcome", None, None, None, None
            )
        emit(
            "planning_completed",
            "planning completed",
            {
                "fallback_used": outcome.fallback_used,
                "failure_code": outcome.failure_code,
                "action": outcome.plan.action,
                "query_type": outcome.plan.query_type,
            },
        )
        plan = outcome.plan

        # ---- 确定性路由（Adaptive Policy v1）----
        supported_strategies = tuple(
            getattr(self._retrieval_port, "supported_strategies", ())
        )
        route = self._router.route(plan, supported_strategies)
        emit(
            "routing_completed",
            "routing completed",
            {
                "route": route.route,
                "retrieval_strategy": route.retrieval_strategy,
                "strategy_reason_code": route.strategy_reason_code,
                "router_policy_version": route.router_policy_version,
                "query_count": len(route.queries),
            },
        )

        # ---- direct_answer：不检索，直接生成 ----
        if route.route == "direct_answer":
            bundle = EvidenceBundle.empty()
            verification = self._verifier.verify(plan, bundle)
            emit(
                "verification_completed",
                "verification completed",
                {
                    "status": verification.status,
                    "can_generate": verification.can_generate,
                    "evidence_count": verification.evidence_count,
                },
            )
            if not ensure_budget("generation"):
                return budget_failed(outcome, route, bundle, verification)
            generation_calls += 1
            steps += 1
            try:
                answer = self._answer_port.answer(
                    resolved_question, bundle, mode="direct"
                )
            except Exception as exc:
                return run_failed(
                    "GENERATION_FAILED", type(exc).__name__,
                    outcome, route, bundle, verification,
                )
            if type(answer) is not str or not answer.strip():
                return run_failed(
                    "GENERATION_FAILED", "InvalidAnswer",
                    outcome, route, bundle, verification,
                )
            emit(
                "generation_completed",
                "generation completed",
                {"mode": "direct", "answer_length": len(answer)},
            )
            emit("run_completed", "run completed", {"status": "completed"})
            return _result(
                status="completed",
                planner_outcome=outcome,
                route_decision=route,
                bundle=bundle,
                verification=verification,
                answer=answer,
                sources=(),
                error_code=None,
            )

        # ---- single_retrieval：初始策略检索 + 至多一次 Hybrid 补检索 ----
        if route.route == "single_retrieval":
            initial_strategy = route.retrieval_strategy
            upgrade_attempted = False
            upgrade_used = False
            if not ensure_budget("retrieval"):
                return budget_failed(outcome, route, None, None)
            retrieval_calls += 1
            steps += 1
            try:
                documents = self._retrieval_port.search(
                    resolved_question, strategy=initial_strategy, top_k=top_k
                )
                documents = tuple(documents)
            except Exception as exc:
                return run_failed(
                    "RETRIEVAL_FAILED", type(exc).__name__,
                    outcome, route, None, None,
                )
            emit(
                "retrieval_completed",
                "retrieval completed",
                {
                    "strategy": initial_strategy,
                    "documents_returned": len(documents),
                    "retrieval_call_index": retrieval_calls,
                },
            )
            if (
                not documents
                and initial_strategy == "bm25"
                and "hybrid" in supported_strategies
            ):
                if not ensure_budget("retrieval"):
                    return budget_failed(outcome, route, None, None)
                retrieval_calls += 1
                steps += 1
                upgrade_attempted = True
                try:
                    documents = self._retrieval_port.search(
                        resolved_question, strategy="hybrid", top_k=top_k
                    )
                    documents = tuple(documents)
                except Exception as exc:
                    return run_failed(
                        "RETRIEVAL_FAILED", type(exc).__name__,
                        outcome, route, None, None,
                    )
                upgrade_used = bool(documents)
                emit(
                    "retrieval_upgraded",
                    "retrieval upgraded",
                    {
                        "from_strategy": "bm25",
                        "to_strategy": "hybrid",
                        "subquery_id": "q0",
                        "upgrade_index": 1,
                        "documents_returned": len(documents),
                    },
                )
            try:
                bundle = EvidenceBundle.from_documents(
                    documents,
                    query_id=resolved_question,
                    max_items=self._budget.max_evidence_items,
                    retrieval_call_count=retrieval_calls,
                    query_count=len(route.queries),
                )
            except Exception as exc:
                return run_failed(
                    "RETRIEVAL_FAILED", type(exc).__name__,
                    outcome, route, None, None,
                )
            verification = self._verifier.verify(
                plan,
                bundle,
                required_query_ids=("q0",),
                covered_query_ids=("q0",) if bundle.items else (),
                upgrade_attempted=upgrade_attempted,
                upgrade_used=upgrade_used,
            )
            emit(
                "verification_completed",
                "verification completed",
                {
                    "status": verification.status,
                    "can_generate": verification.can_generate,
                    "evidence_count": verification.evidence_count,
                    "coverage_complete": verification.coverage_complete,
                    "missing_query_ids": list(verification.missing_query_ids),
                },
            )
            if verification.can_generate:
                if not ensure_budget("generation"):
                    return budget_failed(outcome, route, bundle, verification)
                generation_calls += 1
                steps += 1
                try:
                    answer = self._answer_port.answer(
                        resolved_question, bundle, mode="grounded"
                    )
                except Exception as exc:
                    return run_failed(
                        "GENERATION_FAILED", type(exc).__name__,
                        outcome, route, bundle, verification,
                    )
                if type(answer) is not str or not answer.strip():
                    return run_failed(
                        "GENERATION_FAILED", "InvalidAnswer",
                        outcome, route, bundle, verification,
                    )
                emit(
                    "generation_completed",
                    "generation completed",
                    {"mode": "grounded", "answer_length": len(answer)},
                )
                sources = tuple(item.citation_id for item in bundle.items)
                emit("run_completed", "run completed", {"status": "completed"})
                return _result(
                    status="completed",
                    planner_outcome=outcome,
                    route_decision=route,
                    bundle=bundle,
                    verification=verification,
                    answer=answer,
                    sources=sources,
                    error_code=None,
                )
            emit("run_completed", "run completed", {"status": "refused"})
            return _result(
                status="refused",
                planner_outcome=outcome,
                route_decision=route,
                bundle=bundle,
                verification=verification,
                answer=AGENT_REFUSAL_ANSWER,
                sources=(),
                error_code=None,
            )

        # ---- decomposed_retrieval：多子问题串行检索 + 至多一次 Hybrid 补检索 ----
        query_results = []
        missing = []
        sub_ids = _SUBQUERY_IDS[: len(route.queries)]
        sub_queries = list(route.queries)
        for sub_id, sub_query in zip(sub_ids, sub_queries):
            if not ensure_budget("retrieval"):
                return budget_failed(outcome, route, None, None)
            retrieval_calls += 1
            steps += 1
            try:
                documents = self._retrieval_port.search(
                    sub_query, strategy="bm25", top_k=top_k
                )
                documents = tuple(documents)
            except Exception as exc:
                return run_failed(
                    "RETRIEVAL_FAILED", type(exc).__name__,
                    outcome, route, None, None,
                )
            emit(
                "retrieval_completed",
                "subquery retrieval completed",
                {
                    "subquery_id": sub_id,
                    "strategy": "bm25",
                    "documents_returned": len(documents),
                    "retrieval_call_index": retrieval_calls,
                },
            )
            query_results.append((sub_id, documents))
            if not documents:
                missing.append(sub_id)

        upgrade_attempted = False
        upgrade_used = False
        if missing and "hybrid" in supported_strategies:
            first_missing = missing[0]
            idx = sub_ids.index(first_missing)
            if not ensure_budget("retrieval"):
                return budget_failed(outcome, route, None, None)
            retrieval_calls += 1
            steps += 1
            upgrade_attempted = True
            try:
                rescued = self._retrieval_port.search(
                    sub_queries[idx], strategy="hybrid", top_k=top_k
                )
                rescued = tuple(rescued)
            except Exception as exc:
                return run_failed(
                    "RETRIEVAL_FAILED", type(exc).__name__,
                    outcome, route, None, None,
                )
            upgrade_used = bool(rescued)
            emit(
                "retrieval_upgraded",
                "subquery retrieval upgraded",
                {
                    "from_strategy": "bm25",
                    "to_strategy": "hybrid",
                    "subquery_id": first_missing,
                    "upgrade_index": 1,
                    "documents_returned": len(rescued),
                },
            )
            query_results[idx] = (first_missing, rescued)

        merge_stats: dict = {}
        try:
            bundle = merge_subquery_results_policy(
                query_results,
                max_items=self._budget.max_evidence_items,
                merge_policy=self._merge_policy,
                merge_rrf_k=self._merge_rrf_k,
                stats=merge_stats,
            )
        except Exception as exc:
            return run_failed(
                "RETRIEVAL_FAILED", type(exc).__name__,
                outcome, route, None, None,
            )
        covered_ids = tuple(
            sub_id for sub_id, _docs in query_results if _docs
        )
        emit(
            "evidence_merged",
            "evidence merged",
            {
                "merge_policy": merge_stats.get(
                    "merge_policy", SUBQUERY_ROUND_ROBIN_V1
                ),
                "input_candidate_count": merge_stats.get(
                    "input_candidate_count", 0
                ),
                "final_unique_count": len(bundle.items),
                "duplicate_count": merge_stats.get("duplicate_count", 0),
                "truncated": merge_stats.get("truncated", False),
                "covered_query_count": len(covered_ids),
                "required_query_count": len(query_results),
            },
        )
        verification = self._verifier.verify(
            plan,
            bundle,
            required_query_ids=tuple(sub_ids),
            covered_query_ids=covered_ids,
            upgrade_attempted=upgrade_attempted,
            upgrade_used=upgrade_used,
        )
        emit(
            "verification_completed",
            "verification completed",
            {
                "status": verification.status,
                "can_generate": verification.can_generate,
                "evidence_count": verification.evidence_count,
                "coverage_complete": verification.coverage_complete,
                "missing_query_ids": list(verification.missing_query_ids),
            },
        )
        if verification.can_generate:
            if not ensure_budget("generation"):
                return budget_failed(outcome, route, bundle, verification)
            generation_calls += 1
            steps += 1
            try:
                answer = self._answer_port.answer(
                    resolved_question, bundle, mode="grounded"
                )
            except Exception as exc:
                return run_failed(
                    "GENERATION_FAILED", type(exc).__name__,
                    outcome, route, bundle, verification,
                )
            if type(answer) is not str or not answer.strip():
                return run_failed(
                    "GENERATION_FAILED", "InvalidAnswer",
                    outcome, route, bundle, verification,
                )
            emit(
                "generation_completed",
                "generation completed",
                {"mode": "grounded", "answer_length": len(answer)},
            )
            sources = tuple(item.citation_id for item in bundle.items)
            emit("run_completed", "run completed", {"status": "completed"})
            return _result(
                status="completed",
                planner_outcome=outcome,
                route_decision=route,
                bundle=bundle,
                verification=verification,
                answer=answer,
                sources=sources,
                error_code=None,
            )
        emit("run_completed", "run completed", {"status": "refused"})
        return _result(
            status="refused",
            planner_outcome=outcome,
            route_decision=route,
            bundle=bundle,
            verification=verification,
            answer=AGENT_REFUSAL_ANSWER,
            sources=(),
            error_code=None,
        )
