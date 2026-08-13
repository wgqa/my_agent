"""G3-RUNTIME-05A：最小 Agent Runtime 离线垂直切片。

把已存在的 QueryPlan 通过确定性 Router 转成 RouteDecision，执行
direct_answer / single_retrieval 两条路径（decomposed_retrieval 只路由
不执行），构建 EvidenceBundle、跑最小规则 Verifier、写 RunTrace 并返回
结构化 AgentRunResult。所有外部能力经 RetrievalPort / AnswerPort 注入；
本模块不调用真实模型/检索/生成，不读 Holdout。
"""

from __future__ import annotations

import uuid
from typing import Optional, Protocol, Sequence, runtime_checkable

from core.agent_runtime.models import (
    AGENT_REFUSAL_ANSWER,
    AgentRunBudget,
    AgentRunResult,
    Document,
    EvidenceBundle,
    RouteDecision,
    TraceEvent,
    VerificationResult,
)
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan


@runtime_checkable
class RetrievalPort(Protocol):
    """检索端口契约：Adapter 需实现 search 并把结果映射为 Document 序列。"""

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
    """只根据已存在的 QueryPlan 路由，不调用 LLM、不改 plan、不生成子问题。

    固定映射：
      action=no_retrieval        → direct_answer / none / ()
      action=single_retrieval    → single_retrieval / bm25 / (original_query,)
      action=decomposed_retrieval→ decomposed_retrieval / bm25 / sq1..sq3
    """

    def route(self, plan: QueryPlan) -> RouteDecision:
        if not isinstance(plan, QueryPlan):
            raise TypeError(
                f"route 输入必须是 QueryPlan，实际 {type(plan).__name__}"
            )
        action = plan.action
        if action == "no_retrieval":
            return RouteDecision(
                schema_version="route_decision_v1",
                route="direct_answer",
                retrieval_strategy="none",
                queries=(),
                reason_code=plan.reason_code,
            )
        if action == "single_retrieval":
            return RouteDecision(
                schema_version="route_decision_v1",
                route="single_retrieval",
                retrieval_strategy="bm25",
                queries=(plan.original_query,),
                reason_code=plan.reason_code,
            )
        if action == "decomposed_retrieval":
            return RouteDecision(
                schema_version="route_decision_v1",
                route="decomposed_retrieval",
                retrieval_strategy="bm25",
                queries=tuple(sub.query for sub in plan.subqueries),
                reason_code=plan.reason_code,
            )
        raise ValueError(f"未知 action {action!r}")  # pragma: no cover


class MinimalEvidenceVerifier:
    """最小规则版 Verifier：只做三条规则，不宣称 claim-level Faithfulness。

      no_retrieval               → not_required / can_generate=true
      retrieval_required + 有证据 → supported / can_generate=true
      retrieval_required + 无证据 → insufficient_evidence / can_generate=false
    """

    def verify(
        self, plan: QueryPlan, bundle: EvidenceBundle
    ) -> VerificationResult:
        if plan.action == "no_retrieval":
            return VerificationResult(
                schema_version="verification_result_v1",
                status="not_required",
                can_generate=True,
                reason_code="NOT_REQUIRED",
                evidence_count=len(bundle.items),
                warnings=(),
            )
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
        )


class AgentRuntime:
    """最小离线 Agent Runtime。

    构造注入 BaseQueryPlanner / RetrievalPort / AnswerPort / AgentRunBudget /
    可选 run_id_factory。run() 每次独立计数（每 run 各 Port 预算重置），
    外部 Port 调用前都检查预算；异常不吞掉，转成结构化 failed result，
    Trace 只记录异常类型名。

    本阶段 decomposed_retrieval 只路由为 deferred，不静默降级成单问题检索。
    """

    def __init__(
        self,
        *,
        planner: BaseQueryPlanner,
        retrieval_port: RetrievalPort,
        answer_port: AnswerPort,
        budget: Optional[AgentRunBudget] = None,
        run_id_factory=None,
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
        if run_id_factory is not None and not callable(run_id_factory):
            raise TypeError("run_id_factory 必须是可调用对象")
        self._planner = planner
        self._retrieval_port = retrieval_port
        self._answer_port = answer_port
        self._budget = budget if budget is not None else AgentRunBudget()
        self._run_id_factory = run_id_factory
        self._router = DeterministicRouter()
        self._verifier = MinimalEvidenceVerifier()

    def run(self, question: str, top_k: int = 5) -> AgentRunResult:
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
            emit(
                "run_failed",
                "run failed",
                {"error_code": error_code, "exception_type": exception_type},
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
                warnings=(),
            )

        run_id = (
            self._run_id_factory() if self._run_id_factory else uuid.uuid4().hex
        )
        emit("run_started", "run started", {"run_id": run_id})

        # ---- Planner（所有路径恰好调用一次）----
        if not ensure_budget("planner"):
            return budget_failed(None, None, None, None)
        planner_calls += 1
        steps += 1
        try:
            outcome = self._planner.plan(question)
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

        # ---- 确定性路由 ----
        route = self._router.route(plan)
        emit(
            "routing_completed",
            "routing completed",
            {
                "route": route.route,
                "retrieval_strategy": route.retrieval_strategy,
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
                answer = self._answer_port.answer(question, bundle, mode="direct")
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

        # ---- single_retrieval：单次 BM25 检索 ----
        if route.route == "single_retrieval":
            if not ensure_budget("retrieval"):
                return budget_failed(outcome, route, None, None)
            retrieval_calls += 1
            steps += 1
            try:
                documents = self._retrieval_port.search(
                    question, strategy="bm25", top_k=top_k
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
                {"strategy": "bm25", "documents_returned": len(documents)},
            )
            try:
                bundle = EvidenceBundle.from_documents(
                    documents,
                    query_id=question,
                    max_items=self._budget.max_evidence_items,
                    retrieval_call_count=retrieval_calls,
                    query_count=len(route.queries),
                )
            except Exception as exc:
                return run_failed(
                    "RETRIEVAL_FAILED", type(exc).__name__,
                    outcome, route, None, None,
                )
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
            if verification.can_generate:
                if not ensure_budget("generation"):
                    return budget_failed(outcome, route, bundle, verification)
                generation_calls += 1
                steps += 1
                try:
                    answer = self._answer_port.answer(
                        question, bundle, mode="grounded"
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

        # ---- decomposed_retrieval：只路由，不执行多子问题检索 ----
        bundle = EvidenceBundle.empty()
        verification = self._verifier.verify(plan, bundle)
        emit(
            "run_deferred",
            "decomposed retrieval not implemented",
            {
                "error_code": "DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED",
                "subquery_count": len(route.queries),
            },
        )
        return _result(
            status="deferred",
            planner_outcome=outcome,
            route_decision=route,
            bundle=bundle,
            verification=verification,
            answer=None,
            sources=(),
            error_code="DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED",
        )
