"""Tests for Gate 3 minimal Agent Runtime vertical slice (G3-RUNTIME-05A).

Covers: the 3 route mappings, direct/single execution, refused on empty
retrieval, deferred decomposed (no silent downgrade), planner fallback,
EvidenceBundle dedup/citation/truncation, budget overrun, sanitized RunTrace,
exception mapping, and data contracts. Uses only Fake Planner / Fake
RetrievalPort / Fake AnswerPort; no network, no model calls, no Holdout.
"""

from __future__ import annotations

import json

import pytest

from core.agent_runtime import (
    AGENT_ANSWER_MODES,
    AGENT_REFUSAL_ANSWER,
    AGENT_RUNTIME_ERROR_CODES,
    AgentRunBudget,
    AgentRunResult,
    DeterministicRouter,
    Document,
    EvidenceBundle,
    EvidenceItem,
    MinimalEvidenceVerifier,
    RouteDecision,
    TraceEvent,
    validate_answer_mode,
    AgentRuntime,
)
from core.query_planning import (
    BaseQueryPlanner,
    PlannerOutcome,
    QueryPlan,
    Subquery,
    build_planner_fallback_outcome,
)


# ---------------------------------------------------------------------------
# helpers / fakes
# ---------------------------------------------------------------------------


def _subqueries(*queries: str) -> tuple[Subquery, ...]:
    return tuple(
        Subquery(
            id=f"sq{i + 1}",
            query=query,
            evidence_target="证据目标",
            required=True,
        )
        for i, query in enumerate(queries)
    )


def _plan(
    action: str,
    *,
    original: str = "问题",
    subqueries: tuple[Subquery, ...] = (),
) -> PlannerOutcome:
    """构造正常 PlannerOutcome；按 action 固定合法 query_type / reason_code。"""
    fixed = {
        "no_retrieval": ("unanswerable_or_no_retrieval", "NO_RETRIEVAL_NEEDED"),
        "single_retrieval": ("fact", "SIMPLE_FACT"),
        "decomposed_retrieval": ("comparison", "COMPARISON_EVIDENCE"),
    }
    query_type, reason_code = fixed[action]
    plan = QueryPlan.create(
        original_query=original,
        query_type=query_type,
        retrieval_required=(action != "no_retrieval"),
        action=action,
        reason_code=reason_code,
        subqueries=subqueries,
    )
    return PlannerOutcome(plan=plan, fallback_used=False, failure_code=None)


def _doc(
    chunk_id,
    source_name: str,
    content: str,
    rank: int,
    document_id=None,
    score=0.5,
) -> Document:
    return Document(
        chunk_id=chunk_id,
        document_id=document_id,
        source_name=source_name,
        content=content,
        score=score,
        rank=rank,
    )


class _FakePlanner(BaseQueryPlanner):
    def __init__(self, outcome: PlannerOutcome, error=None):
        self.outcome = outcome
        self.error = error
        self.calls = 0
        self.calls_queries: list[str] = []

    def plan(self, original_query: str) -> PlannerOutcome:
        self.calls += 1
        self.calls_queries.append(original_query)
        if self.error is not None:
            raise self.error
        return self.outcome


class _FakeRetriever:
    def __init__(self, documents=(), error=None):
        self.documents = list(documents)
        self.error = error
        self.calls = 0
        self.calls_args: list[tuple] = []

    def search(self, query: str, strategy: str, top_k: int):
        self.calls += 1
        self.calls_args.append((query, strategy, top_k))
        if self.error is not None:
            raise self.error
        return list(self.documents)


class _FakeAnswerer:
    def __init__(self, answer: str = "合成的答案。", error=None):
        self._answer_text = answer
        self.error = error
        self.calls = 0
        self.calls_args: list[tuple] = []

    def answer(self, question: str, evidence_bundle: EvidenceBundle, mode: str):
        self.calls += 1
        self.calls_args.append((question, mode))
        if self.error is not None:
            raise self.error
        return self._answer_text


def _runtime(
    action: str = "single_retrieval",
    *,
    subqueries: tuple[Subquery, ...] = (),
    docs=(),
    planner_outcome=None,
    planner_error=None,
    retriever_error=None,
    answer_error=None,
    answer="合成的答案。",
    budget=None,
    run_id_factory=None,
):
    if planner_outcome is None:
        planner_outcome = _plan(action, original="问题", subqueries=subqueries)
    planner = _FakePlanner(planner_outcome, error=planner_error)
    retriever = _FakeRetriever(documents=docs, error=retriever_error)
    answerer = _FakeAnswerer(answer=answer, error=answer_error)
    runtime = AgentRuntime(
        planner=planner,
        retrieval_port=retriever,
        answer_port=answerer,
        budget=budget,
        run_id_factory=run_id_factory,
    )
    return runtime, planner, retriever, answerer


# ---------------------------------------------------------------------------
# 10. 数据契约
# ---------------------------------------------------------------------------


class TestDataContract:
    def test_budget_rejects_bool_as_int(self):
        for kwargs in (
            {"max_steps": True},
            {"max_planner_calls": True},
            {"max_retrieval_calls": True},
            {"max_generation_calls": True},
            {"max_evidence_items": True},
        ):
            with pytest.raises(TypeError):
                AgentRunBudget(**kwargs)

    def test_budget_rejects_non_positive(self):
        with pytest.raises(ValueError):
            AgentRunBudget(max_steps=0)
        with pytest.raises(ValueError):
            AgentRunBudget(max_steps=-1)
        with pytest.raises(ValueError):
            AgentRunBudget(max_planner_calls=0)

    def test_route_decision_rejects_invalid_route(self):
        with pytest.raises(ValueError):
            RouteDecision(
                schema_version="route_decision_v1",
                route="hybrid",
                retrieval_strategy="bm25",
                queries=("q",),
                reason_code="X",
            )

    def test_route_decision_rejects_invalid_strategy_for_route(self):
        with pytest.raises(ValueError):
            RouteDecision(
                schema_version="route_decision_v1",
                route="direct_answer",
                retrieval_strategy="bm25",
                queries=(),
                reason_code="X",
            )

    def test_agent_run_result_rejects_invalid_status(self):
        outcome = _plan("single_retrieval")
        route = DeterministicRouter().route(outcome.plan)
        bundle = EvidenceBundle.empty()
        verification = MinimalEvidenceVerifier().verify(outcome.plan, bundle)
        with pytest.raises(ValueError):
            AgentRunResult(
                run_id="r",
                status="bogus",
                planner_outcome=outcome,
                route_decision=route,
                evidence_bundle=bundle,
                verification=verification,
                answer="x",
                sources=(),
                trace=(),
                error_code=None,
                warnings=(),
            )

    def test_agent_run_result_completed_requires_answer(self):
        outcome = _plan("single_retrieval")
        route = DeterministicRouter().route(outcome.plan)
        bundle = EvidenceBundle.empty()
        verification = MinimalEvidenceVerifier().verify(outcome.plan, bundle)
        with pytest.raises(ValueError):
            AgentRunResult(
                run_id="r",
                status="completed",
                planner_outcome=outcome,
                route_decision=route,
                evidence_bundle=bundle,
                verification=verification,
                answer=None,
                sources=(),
                trace=(),
                error_code=None,
                warnings=(),
            )

    def test_failed_requires_error_code(self):
        with pytest.raises(ValueError):
            AgentRunResult(
                run_id="r",
                status="failed",
                planner_outcome=None,
                route_decision=None,
                evidence_bundle=None,
                verification=None,
                answer=None,
                sources=(),
                trace=(),
                error_code=None,
                warnings=(),
            )

    def test_validate_answer_mode(self):
        validate_answer_mode("direct")
        validate_answer_mode("grounded")
        assert set(AGENT_ANSWER_MODES) == {"direct", "grounded"}
        with pytest.raises(ValueError):
            validate_answer_mode("hybrid")
        with pytest.raises(TypeError):
            validate_answer_mode(3)

    def test_evidence_citation_not_continuous_rejected(self):
        with pytest.raises(ValueError):
            EvidenceBundle(
                schema_version="evidence_bundle_v1",
                items=(
                    EvidenceItem(
                        citation_id="[C1]",
                        chunk_id="c1",
                        document_id="d1",
                        source_name="a.md",
                        content="内容1",
                        score=0.5,
                        rank=1,
                        query_id="q",
                    ),
                    EvidenceItem(
                        citation_id="[C3]",
                        chunk_id="c2",
                        document_id="d1",
                        source_name="a.md",
                        content="内容2",
                        score=0.5,
                        rank=2,
                        query_id="q",
                    ),
                ),
                retrieval_call_count=1,
                query_count=1,
                warnings=(),
            )

    def test_trace_rejects_forbidden_keys(self):
        for key in ("api_key", "authorization", "raw_output", "traceback",
                    "chain_of_thought", "system_prompt"):
            with pytest.raises(ValueError):
                TraceEvent(
                    sequence=1,
                    event_type="run_started",
                    summary="x",
                    data={key: "敏感内容"},
                )

    def test_trace_rejects_unknown_event_type(self):
        with pytest.raises(ValueError):
            TraceEvent(
                sequence=1,
                event_type="bogus_event",
                summary="x",
                data={},
            )

    def test_result_to_dict_is_json_serializable(self):
        docs = [
            _doc("c1", "a.md", "内容A", rank=1, document_id="d1"),
            _doc("c2", "b.md", "内容B", rank=2, document_id="d2"),
        ]
        runtime, _planner, _retriever, _answerer = _runtime(
            docs=docs, run_id_factory=lambda: "rid-serializable"
        )
        result = runtime.run("问题")
        payload = result.to_dict()
        text = json.dumps(payload, ensure_ascii=False)
        assert payload["status"] == "completed"
        assert payload["schema_version"] == "agent_run_result_v1"
        assert "[C1]" in text


# ---------------------------------------------------------------------------
# Router 固定映射
# ---------------------------------------------------------------------------


class TestDeterministicRouter:
    def test_no_retrieval_mapping(self):
        router = DeterministicRouter()
        decision = router.route(_plan("no_retrieval").plan)
        assert decision.route == "direct_answer"
        assert decision.retrieval_strategy == "none"
        assert decision.queries == ()

    def test_single_retrieval_mapping(self):
        router = DeterministicRouter()
        decision = router.route(_plan("single_retrieval").plan)
        assert decision.route == "single_retrieval"
        assert decision.retrieval_strategy == "bm25"
        assert decision.queries == ("问题",)

    def test_decomposed_retrieval_mapping_preserves_order(self):
        router = DeterministicRouter()
        plan = _plan(
            "decomposed_retrieval",
            subqueries=_subqueries("子问题1", "子问题2", "子问题3"),
        ).plan
        decision = router.route(plan)
        assert decision.route == "decomposed_retrieval"
        assert decision.retrieval_strategy == "bm25"
        assert decision.queries == ("子问题1", "子问题2", "子问题3")


# ---------------------------------------------------------------------------
# EvidenceBundle 契约
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    def test_dedup_by_chunk_id(self):
        docs = [
            _doc("c1", "a.md", "内容1", rank=1, document_id="d1", score=0.9),
            _doc("c1", "a.md", "内容1", rank=2, document_id="d1", score=0.7),
            _doc("c2", "b.md", "内容2", rank=3, document_id="d2", score=0.6),
        ]
        bundle = EvidenceBundle.from_documents(docs, query_id="q", max_items=5)
        assert [i.citation_id for i in bundle.items] == ["[C1]", "[C2]"]
        assert [i.chunk_id for i in bundle.items] == ["c1", "c2"]
        assert bundle.items[0].score == 0.9  # 保留首次出现

    def test_dedup_by_source_and_content_when_no_chunk_id(self):
        docs = [
            _doc(None, "a.md", "同一内容", rank=1, document_id="d1"),
            _doc(None, "a.md", "同一内容", rank=2, document_id="d2"),
            _doc(None, "b.md", "不同内容", rank=3, document_id="d3"),
        ]
        bundle = EvidenceBundle.from_documents(docs, query_id="q", max_items=5)
        assert len(bundle.items) == 2

    def test_first_occurrence_order_preserved(self):
        docs = [
            _doc("c2", "b.md", "内容2", rank=1, document_id="d2"),
            _doc("c1", "a.md", "内容1", rank=2, document_id="d1"),
            _doc("c3", "c.md", "内容3", rank=3, document_id="d3"),
        ]
        bundle = EvidenceBundle.from_documents(docs, query_id="q", max_items=5)
        assert [i.citation_id for i in bundle.items] == ["[C1]", "[C2]", "[C3]"]
        assert [i.chunk_id for i in bundle.items] == ["c2", "c1", "c3"]

    def test_truncated_to_max_items(self):
        docs = [
            _doc(f"c{i}", "a.md", f"内容{i}", rank=i, document_id="d")
            for i in range(1, 8)
        ]
        bundle = EvidenceBundle.from_documents(docs, query_id="q", max_items=3)
        assert len(bundle.items) == 3
        assert [i.citation_id for i in bundle.items] == ["[C1]", "[C2]", "[C3]"]

    def test_no_fabricated_fields(self):
        docs = [_doc(None, "a.md", "内容", rank=1, document_id=None, score=None)]
        bundle = EvidenceBundle.from_documents(docs, query_id="q", max_items=5)
        item = bundle.items[0]
        assert item.chunk_id is None
        assert item.document_id is None
        assert item.score is None
        assert item.rank == 1


# ---------------------------------------------------------------------------
# 1. no_retrieval / direct
# ---------------------------------------------------------------------------


class TestRuntimeNoRetrieval:
    def test_direct_answer_flow(self):
        runtime, planner, retriever, answerer = _runtime(
            action="no_retrieval", run_id_factory=lambda: "rid-no"
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert result.error_code is None
        assert planner.calls == 1
        assert retriever.calls == 0
        assert answerer.calls == 1
        assert answerer.calls_args[0][1] == "direct"
        assert result.answer == "合成的答案。"
        assert result.route_decision.route == "direct_answer"
        assert result.verification.status == "not_required"
        assert result.verification.can_generate is True
        assert result.sources == ()
        assert result.evidence_bundle.items == ()


# ---------------------------------------------------------------------------
# 2. single_retrieval
# ---------------------------------------------------------------------------


class TestRuntimeSingleRetrieval:
    def test_single_retrieval_completed(self):
        docs = [
            _doc("c1", "a.md", "内容A", rank=1, document_id="d1"),
            _doc("c2", "b.md", "内容B", rank=2, document_id="d2"),
        ]
        runtime, planner, retriever, answerer = _runtime(
            docs=docs, run_id_factory=lambda: "rid-single"
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert planner.calls == 1
        assert retriever.calls == 1
        assert retriever.calls_args[0] == ("问题", "bm25", 5)
        assert answerer.calls == 1
        assert answerer.calls_args[0][1] == "grounded"
        assert [i.citation_id for i in result.evidence_bundle.items] == [
            "[C1]", "[C2]",
        ]
        assert result.sources == ("[C1]", "[C2]")
        assert result.verification.status == "supported"

    def test_top_k_propagated(self):
        runtime, _planner, retriever, _answerer = _runtime(
            docs=[_doc("c1", "a.md", "内容A", rank=1, document_id="d1")],
            run_id_factory=lambda: "rid-topk",
        )
        runtime.run("问题", top_k=3)
        assert retriever.calls_args[0][2] == 3


# ---------------------------------------------------------------------------
# 3. 空检索结果 → refused
# ---------------------------------------------------------------------------


class TestRuntimeRefused:
    def test_empty_retrieval_refused(self):
        runtime, planner, retriever, answerer = _runtime(
            docs=(), run_id_factory=lambda: "rid-refused"
        )
        result = runtime.run("问题")
        assert result.status == "refused"
        assert retriever.calls == 1
        assert answerer.calls == 0
        assert result.answer == AGENT_REFUSAL_ANSWER
        assert result.verification.status == "insufficient_evidence"
        assert result.verification.can_generate is False
        assert result.error_code is None
        assert result.trace[-1].event_type == "run_completed"


# ---------------------------------------------------------------------------
# 4. decomposed_retrieval → deferred
# ---------------------------------------------------------------------------


class TestRuntimeDeferred:
    def test_deferred_three_subqueries_preserved(self):
        runtime, planner, retriever, answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("子问题1", "子问题2", "子问题3"),
            run_id_factory=lambda: "rid-deferred3",
        )
        result = runtime.run("问题")
        assert result.status == "deferred"
        assert result.error_code == "DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED"
        assert planner.calls == 1
        assert retriever.calls == 0
        assert answerer.calls == 0
        assert result.route_decision.queries == (
            "子问题1", "子问题2", "子问题3",
        )
        assert result.route_decision.queries != ("问题",)  # 不静默执行 original
        assert result.answer is None
        assert result.trace[-1].event_type == "run_deferred"

    def test_deferred_two_subqueries_preserved(self):
        runtime, _planner, retriever, answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("子问题1", "子问题2"),
            run_id_factory=lambda: "rid-deferred2",
        )
        result = runtime.run("问题")
        assert result.route_decision.queries == ("子问题1", "子问题2")
        assert retriever.calls == 0
        assert answerer.calls == 0


# ---------------------------------------------------------------------------
# 5. Planner fallback
# ---------------------------------------------------------------------------


class TestRuntimeFallback:
    def test_fallback_single_retrieval_still_bm25(self):
        fallback = build_planner_fallback_outcome("问题", "PLAN_INVALID_SCHEMA")
        runtime, planner, retriever, answerer = _runtime(
            planner_outcome=fallback,
            docs=[_doc("c1", "a.md", "内容A", rank=1, document_id="d1")],
            run_id_factory=lambda: "rid-fallback",
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert planner.calls == 1
        assert result.planner_outcome.fallback_used is True
        assert result.planner_outcome.failure_code == "PLAN_INVALID_SCHEMA"
        assert result.route_decision.route == "single_retrieval"
        assert retriever.calls == 1
        assert retriever.calls_args[0][1] == "bm25"
        assert answerer.calls == 1


# ---------------------------------------------------------------------------
# 6. Evidence（runtime 层） + 7. Budget
# ---------------------------------------------------------------------------


class TestRuntimeEvidence:
    def test_evidence_respects_budget_max_items(self):
        docs = [
            _doc(f"c{i}", "a.md", f"内容{i}", rank=i, document_id="d")
            for i in range(1, 6)
        ]
        budget = AgentRunBudget(max_evidence_items=2)
        runtime, _planner, _retriever, _answerer = _runtime(
            docs=docs, budget=budget, run_id_factory=lambda: "rid-items"
        )
        result = runtime.run("问题")
        assert len(result.evidence_bundle.items) == 2
        assert result.sources == ("[C1]", "[C2]")


class TestRuntimeBudget:
    def test_budget_exceeded_stops_before_retriever(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        budget = AgentRunBudget(max_steps=1)
        runtime, planner, retriever, answerer = _runtime(
            docs=docs, budget=budget, run_id_factory=lambda: "rid-b1"
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "BUDGET_EXCEEDED"
        assert planner.calls == 1
        assert retriever.calls == 0
        assert answerer.calls == 0
        assert result.trace[-1].event_type == "run_failed"

    def test_budget_exceeded_stops_before_generator(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        budget = AgentRunBudget(max_steps=2)
        runtime, planner, retriever, answerer = _runtime(
            docs=docs, budget=budget, run_id_factory=lambda: "rid-b2"
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "BUDGET_EXCEEDED"
        assert planner.calls == 1
        assert retriever.calls == 1
        assert answerer.calls == 0

    def test_planner_never_retried_after_port_error(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, planner, _retriever, _answerer = _runtime(
            docs=docs,
            retriever_error=RuntimeError("retriever boom"),
            run_id_factory=lambda: "rid-noretry",
        )
        result = runtime.run("问题")
        assert result.error_code == "RETRIEVAL_FAILED"
        assert planner.calls == 1  # 无隐式重试


# ---------------------------------------------------------------------------
# 8. Trace
# ---------------------------------------------------------------------------


class TestRuntimeTrace:
    def test_completed_trace_sequence_and_order(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, _planner, _retriever, _answerer = _runtime(
            docs=docs, run_id_factory=lambda: "rid-trace"
        )
        result = runtime.run("问题")
        types = [t.event_type for t in result.trace]
        assert types == [
            "run_started",
            "planning_completed",
            "routing_completed",
            "retrieval_completed",
            "verification_completed",
            "generation_completed",
            "run_completed",
        ]
        assert [t.sequence for t in result.trace] == list(
            range(1, len(result.trace) + 1)
        )

    def test_trace_sanitized(self):
        secret = "sk-这条是假的api-key-不要外泄"
        body = "这是完整文档正文内容，绝不能出现在 Trace 里"
        docs = [_doc("c1", "秘密文件.md", body, rank=1, document_id="d1")]
        runtime, _planner, _retriever, _answerer = _runtime(
            docs=docs, run_id_factory=lambda: "rid-sanitize"
        )
        result = runtime.run("问题")
        trace_blob = json.dumps(
            [t.to_dict() for t in result.trace], ensure_ascii=False
        )
        assert secret not in trace_blob
        assert body not in trace_blob  # TraceEvent.data 不复制正文
        assert "Traceback" not in trace_blob
        assert "raw_output" not in trace_blob
        assert "system_prompt" not in trace_blob

    def test_failed_terminal_event(self):
        runtime, _planner, _retriever, _answerer = _runtime(
            planner_error=RuntimeError("boom"), run_id_factory=lambda: "rid-f"
        )
        result = runtime.run("问题")
        assert result.trace[-1].event_type == "run_failed"


# ---------------------------------------------------------------------------
# 9. 异常
# ---------------------------------------------------------------------------


class TestRuntimeExceptions:
    def test_planner_exception_planning_failed(self):
        runtime, planner, retriever, answerer = _runtime(
            planner_error=RuntimeError("plan boom"), run_id_factory=lambda: "rid-pe"
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "PLANNING_FAILED"
        assert planner.calls == 1
        assert retriever.calls == 0
        assert answerer.calls == 0
        assert result.planner_outcome is None
        assert result.route_decision is None
        assert result.answer is None

    def test_retriever_exception_retrieval_failed(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, planner, retriever, answerer = _runtime(
            docs=docs,
            retriever_error=RuntimeError("ret boom"),
            run_id_factory=lambda: "rid-re",
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "RETRIEVAL_FAILED"
        assert planner.calls == 1
        assert retriever.calls == 1
        assert answerer.calls == 0
        assert result.planner_outcome is not None  # 规划已成功

    def test_answer_exception_generation_failed(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, planner, retriever, answerer = _runtime(
            docs=docs,
            answer_error=RuntimeError("gen boom"),
            run_id_factory=lambda: "rid-ge",
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "GENERATION_FAILED"
        assert answerer.calls == 1
        assert result.answer is None

    def test_exception_type_only_in_trace(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, _planner, _retriever, _answerer = _runtime(
            docs=docs,
            retriever_error=RuntimeError("secret-message-不许进trace"),
            run_id_factory=lambda: "rid-et",
        )
        result = runtime.run("问题")
        blob = json.dumps([t.to_dict() for t in result.trace], ensure_ascii=False)
        assert "RuntimeError" in blob  # 只记异常类型名
        assert "secret-message-不许进trace" not in blob  # 不记异常文本
