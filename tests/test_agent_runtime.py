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

from core.adaptive_retrieval import resolve_initial_strategy
from core.agent_runtime import (
    AGENT_ANSWER_MODES,
    AGENT_REFUSAL_ANSWER,
    AGENT_RUNTIME_ERROR_CODES,
    DEFAULT_MERGE_RRF_K,
    MERGE_POLICIES,
    SUBQUERY_ROUND_ROBIN_V1,
    SUBQUERY_RRF_MERGE_V2,
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
    merge_subquery_results,
    merge_subquery_results_policy,
    merge_subquery_results_rrf,
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


def _plan_single_type(query_type: str, reason_code: str) -> PlannerOutcome:
    """构造指定 query_type 的 single_retrieval PlannerOutcome。"""
    plan = QueryPlan.create(
        original_query="问题",
        query_type=query_type,
        retrieval_required=True,
        action="single_retrieval",
        reason_code=reason_code,
        subqueries=(),
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
    def __init__(self, documents=(), error=None, supported=()):
        self.documents = list(documents)
        self.error = error
        self.supported_strategies = tuple(supported)
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


class _SequenceRetriever:
    """按调用顺序返回预置结果；某项为 Exception 时抛异常。"""

    def __init__(self, results, supported=()):
        self._results = list(results)
        self.supported_strategies = tuple(supported)
        self.calls = 0
        self.calls_args: list[tuple] = []

    def search(self, query: str, strategy: str, top_k: int):
        self.calls += 1
        self.calls_args.append((query, strategy, top_k))
        index = self.calls - 1
        if index < len(self._results) and isinstance(self._results[index], Exception):
            raise self._results[index]
        result = self._results[index] if index < len(self._results) else ()
        return list(result)


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
    merge_policy=None,
    merge_rrf_k=None,
    run_id_factory=None,
):
    if planner_outcome is None:
        planner_outcome = _plan(action, original="问题", subqueries=subqueries)
    planner = _FakePlanner(planner_outcome, error=planner_error)
    retriever = _FakeRetriever(documents=docs, error=retriever_error)
    answerer = _FakeAnswerer(answer=answer, error=answer_error)
    kwargs = dict(
        planner=planner,
        retrieval_port=retriever,
        answer_port=answerer,
        budget=budget,
        run_id_factory=run_id_factory,
    )
    if merge_policy is not None:
        kwargs["merge_policy"] = merge_policy
    if merge_rrf_k is not None:
        kwargs["merge_rrf_k"] = merge_rrf_k
    runtime = AgentRuntime(**kwargs)
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
                schema_version="route_decision_v2",
                route="hybrid",
                retrieval_strategy="bm25",
                queries=("q",),
                reason_code="X",
                router_policy_version="adaptive_retrieval_policy_v1",
                strategy_reason_code="LEXICAL_EXACT_BM25",
            )

    def test_route_decision_rejects_invalid_strategy_for_route(self):
        with pytest.raises(ValueError):
            RouteDecision(
                schema_version="route_decision_v2",
                route="direct_answer",
                retrieval_strategy="bm25",
                queries=(),
                reason_code="X",
                router_policy_version="adaptive_retrieval_policy_v1",
                strategy_reason_code="DIRECT_NO_RETRIEVAL",
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
# 4. decomposed_retrieval → 多子问题检索执行
# ---------------------------------------------------------------------------


class TestRuntimeDecomposed:
    def test_two_subqueries_completed(self):
        docs = [
            _doc("c1", "a.md", "内容A", rank=1, document_id="d1"),
            _doc("c2", "b.md", "内容B", rank=2, document_id="d2"),
        ]
        runtime, planner, retriever, answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("子问题1", "子问题2"),
            docs=docs,
            run_id_factory=lambda: "rid-dec2",
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert result.error_code is None
        assert planner.calls == 1
        assert retriever.calls == 2
        assert answerer.calls == 1
        assert answerer.calls_args[0][1] == "grounded"
        assert result.route_decision.queries == ("子问题1", "子问题2")
        assert result.route_decision.queries != ("问题",)  # 不检索 original_query
        assert result.evidence_bundle.retrieval_call_count == 2
        assert result.evidence_bundle.query_count == 2
        assert result.sources == ("[C1]", "[C2]")

    def test_three_subqueries_completed(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, planner, retriever, answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("子问题1", "子问题2", "子问题3"),
            docs=docs,
            run_id_factory=lambda: "rid-dec3",
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert planner.calls == 1
        assert retriever.calls == 3
        assert answerer.calls == 1
        assert result.evidence_bundle.retrieval_call_count == 3
        assert result.route_decision.queries == (
            "子问题1", "子问题2", "子问题3",
        )

    def test_no_original_query_retrieval_and_bm25_only(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, _planner, retriever, _answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("甲", "乙", "丙"),
            docs=docs,
            run_id_factory=lambda: "rid-order",
        )
        runtime.run("问题")
        assert [a[0] for a in retriever.calls_args] == ["甲", "乙", "丙"]
        assert all(a[1] == "bm25" for a in retriever.calls_args)

    def test_partial_subquery_empty_refused(self):
        seq = _SequenceRetriever(
            [
                [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")],
                [],
                [_doc("c2", "b.md", "内容B", rank=1, document_id="d2")],
            ]
        )
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan(
                    "decomposed_retrieval",
                    subqueries=_subqueries("甲", "乙", "丙"),
                )
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-partial",
        )
        result = runtime.run("问题")
        assert result.status == "refused"
        assert result.answer == AGENT_REFUSAL_ANSWER
        assert result.verification.status == "insufficient_evidence"
        assert result.verification.reason_code == "INCOMPLETE_SUBQUERY_EVIDENCE"
        assert seq.calls == 3
        assert result.trace[-1].event_type == "run_completed"

    def test_subquery_exception_stops_remaining(self):
        seq = _SequenceRetriever(
            [
                [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")],
                RuntimeError("第二个子问题检索失败"),
                [_doc("c3", "c.md", "内容C", rank=1, document_id="d3")],
            ]
        )
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan(
                    "decomposed_retrieval",
                    subqueries=_subqueries("甲", "乙", "丙"),
                )
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-raise",
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "RETRIEVAL_FAILED"
        assert seq.calls == 2  # 第三个子问题不再调用
        assert result.trace[-1].event_type == "run_failed"

    def test_budget_two_retrievals_stops_third(self):
        budget = AgentRunBudget(max_retrieval_calls=2)
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, _planner, retriever, answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("甲", "乙", "丙"),
            docs=docs,
            budget=budget,
            run_id_factory=lambda: "rid-budget2",
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "BUDGET_EXCEEDED"
        assert retriever.calls == 2  # 第三次检索前停止
        assert answerer.calls == 0
        assert result.trace[-1].event_type == "run_failed"

    def test_trace_has_subquery_retrieval_events(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, _planner, _retriever, _answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("甲", "乙", "丙"),
            docs=docs,
            run_id_factory=lambda: "rid-trace-sub",
        )
        result = runtime.run("问题")
        retrieval_events = [
            t for t in result.trace if t.event_type == "retrieval_completed"
        ]
        assert len(retrieval_events) == 3
        assert [e.data["subquery_id"] for e in retrieval_events] == [
            "sq1", "sq2", "sq3",
        ]
        assert all(e.data["strategy"] == "bm25" for e in retrieval_events)

    def test_trace_has_evidence_merged(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        runtime, _planner, _retriever, _answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("甲", "乙"),
            docs=docs,
            run_id_factory=lambda: "rid-trace-merge",
        )
        result = runtime.run("问题")
        merged = [t for t in result.trace if t.event_type == "evidence_merged"]
        assert len(merged) == 1
        data = merged[0].data
        assert data["merge_policy"] == "subquery_round_robin_v1"
        assert data["covered_query_count"] == 2
        assert data["required_query_count"] == 2
        assert data["final_unique_count"] == 1

    def test_trace_excludes_query_and_evidence_body(self):
        body = "这是绝不能进 trace 的证据正文"
        docs = [_doc("c1", "a.md", body, rank=1, document_id="d1")]
        runtime, _planner, _retriever, _answerer = _runtime(
            action="decomposed_retrieval",
            subqueries=_subqueries("绝密子问题甲", "绝密子问题乙"),
            docs=docs,
            run_id_factory=lambda: "rid-trace-body",
        )
        result = runtime.run("问题")
        blob = json.dumps([t.to_dict() for t in result.trace], ensure_ascii=False)
        assert body not in blob
        assert "绝密子问题甲" not in blob
        assert "绝密子问题乙" not in blob


# ---------------------------------------------------------------------------
# 8. Evidence Merge（subquery_round_robin_v1）
# ---------------------------------------------------------------------------


class TestEvidenceMerge:
    def test_round_robin_exact_example(self):
        sq1 = [
            _doc("A", "a.md", "内容A", 1, document_id="dA", score=0.9),
            _doc("B", "b.md", "内容B", 2, document_id="dB", score=0.8),
            _doc("C", "c.md", "内容C", 3, document_id="dC", score=0.7),
        ]
        sq2 = [
            _doc("A", "a.md", "内容A", 1, document_id="dA", score=0.6),
            _doc("D", "d.md", "内容D", 2, document_id="dD", score=0.5),
            _doc("E", "e.md", "内容E", 3, document_id="dE", score=0.4),
        ]
        sq3 = [_doc("F", "f.md", "内容F", 1, document_id="dF", score=0.3)]
        bundle = merge_subquery_results(
            [("sq1", sq1), ("sq2", sq2), ("sq3", sq3)], max_items=5
        )
        assert [i.chunk_id for i in bundle.items] == ["A", "D", "F", "B", "E"]
        assert [i.query_id for i in bundle.items] == [
            "sq1", "sq2", "sq3", "sq1", "sq2",
        ]
        assert [i.citation_id for i in bundle.items] == [
            "[C1]", "[C2]", "[C3]", "[C4]", "[C5]",
        ]
        assert bundle.retrieval_call_count == 3
        assert bundle.query_count == 3

    def test_dedup_by_source_and_content_when_no_chunk_id(self):
        sq1 = [
            _doc(None, "a.md", "同一内容", 1, document_id="d1"),
            _doc(None, "b.md", "不同内容", 2, document_id="d2"),
        ]
        sq2 = [
            _doc(None, "a.md", "同一内容", 1, document_id="d1"),
            _doc(None, "c.md", "第三内容", 2, document_id="d3"),
        ]
        bundle = merge_subquery_results([("sq1", sq1), ("sq2", sq2)], max_items=5)
        assert [i.content for i in bundle.items] == [
            "同一内容", "第三内容", "不同内容",
        ]
        assert [i.query_id for i in bundle.items] == ["sq1", "sq2", "sq1"]
        assert all(i.chunk_id is None for i in bundle.items)

    def test_truncated_to_max_items(self):
        sq1 = [_doc("A", "a.md", "内容A", 1, document_id="dA")]
        sq2 = [_doc("B", "b.md", "内容B", 1, document_id="dB")]
        sq3 = [_doc("C", "c.md", "内容C", 1, document_id="dC")]
        stats = {}
        bundle = merge_subquery_results(
            [("sq1", sq1), ("sq2", sq2), ("sq3", sq3)],
            max_items=2,
            stats=stats,
        )
        assert [i.chunk_id for i in bundle.items] == ["A", "B"]
        assert stats["truncated"] is True
        assert stats["input_candidate_count"] == 3
        assert stats["duplicate_count"] == 0

    def test_no_cross_subquery_score_ranking(self):
        # 轮转保持子问题顺序；若按分数全局排序会得到 B,C,A
        sq1 = [
            _doc("A", "a.md", "低分A", 1, document_id="dA", score=0.1),
            _doc("B", "b.md", "高分B", 2, document_id="dB", score=0.9),
        ]
        sq2 = [_doc("C", "c.md", "中分C", 1, document_id="dC", score=0.5)]
        bundle = merge_subquery_results([("sq1", sq1), ("sq2", sq2)], max_items=5)
        assert [i.chunk_id for i in bundle.items] == ["A", "C", "B"]


# ---------------------------------------------------------------------------
# 8b. Evidence Merge v2（subquery_rrf_merge_v2）
# ---------------------------------------------------------------------------


class TestEvidenceMergeV2:
    def test_v1_behavior_unchanged(self):
        sq1 = [
            _doc("A", "a.md", "内容A", 1, document_id="dA"),
            _doc("B", "b.md", "内容B", 2, document_id="dB"),
        ]
        sq2 = [_doc("C", "c.md", "内容C", 1, document_id="dC")]
        direct = merge_subquery_results([("sq1", sq1), ("sq2", sq2)], max_items=5)
        dispatched = merge_subquery_results_policy(
            [("sq1", sq1), ("sq2", sq2)],
            max_items=5,
            merge_policy=SUBQUERY_ROUND_ROBIN_V1,
        )
        assert [i.chunk_id for i in dispatched.items] == ["A", "C", "B"]
        assert dispatched == direct

    def test_v2_deterministic_same_input(self):
        sq1 = [_doc("A", "a.md", "A", 1), _doc("B", "b.md", "B", 2)]
        sq2 = [_doc("B", "b.md", "B", 1), _doc("C", "c.md", "C", 2)]
        first = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        second = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        assert first == second

    def test_rrf_hand_computed_exact_example(self):
        # sq1: A@1 B@2 C@3；sq2: B@1 A@2 D@3；k=60
        # score(A)=1/61+1/62、score(B)=1/62+1/61（并列，best_rank=1）→ source ASC a<b
        # score(C)=1/63、score(D)=1/63（并列，best_rank=3）→ source ASC c<d
        sq1 = [
            _doc("A", "a.md", "A1", 1, document_id="dA"),
            _doc("B", "b.md", "B1", 2, document_id="dB"),
            _doc("C", "c.md", "C1", 3, document_id="dC"),
        ]
        sq2 = [
            _doc("B", "b.md", "B1", 1, document_id="dB"),
            _doc("A", "a.md", "A1", 2, document_id="dA"),
            _doc("D", "d.md", "D1", 3, document_id="dD"),
        ]
        bundle = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        assert [i.source_name for i in bundle.items] == [
            "a.md", "b.md", "c.md", "d.md",
        ]
        assert [i.citation_id for i in bundle.items] == [
            "[C1]", "[C2]", "[C3]", "[C4]",
        ]

    def test_cross_subquery_accumulation(self):
        # A 出现在 sq1@1 与 sq2@2 → score 高于只出现一次的 X/Y
        sq1 = [_doc("A", "a.md", "A", 1), _doc("X", "x.md", "X", 2)]
        sq2 = [_doc("A", "a.md", "A", 2), _doc("Y", "y.md", "Y", 1)]
        bundle = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        names = [i.source_name for i in bundle.items]
        assert names.index("a.md") < names.index("x.md")
        assert names.index("a.md") < names.index("y.md")

    def test_absent_subquery_contributes_zero(self):
        # A 只在 sq1；追加不含 A 的 sq2 不改变 A 的分数相对序
        sq1 = [_doc("A", "a.md", "A", 1), _doc("B", "b.md", "B", 2)]
        base = merge_subquery_results_rrf([("sq1", sq1)], max_items=5)
        sq2 = [_doc("C", "c.md", "C", 1)]
        with_extra = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        assert [i.source_name for i in base.items] == ["a.md", "b.md"]
        # A=1/61、C=1/61 并列 best_rank=1 → source ASC a<c
        assert [i.source_name for i in with_extra.items] == [
            "a.md", "c.md", "b.md",
        ]

    def test_duplicate_document_output_once(self):
        sq1 = [_doc("A", "a.md", "A", 1, document_id="dA")]
        sq2 = [_doc("A", "a.md", "A", 1, document_id="dA")]
        sq3 = [_doc("B", "b.md", "B", 1, document_id="dB")]
        bundle = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2), ("sq3", sq3)], max_items=5
        )
        assert [i.source_name for i in bundle.items] == ["a.md", "b.md"]

    def test_best_rank_tie_break(self):
        # k=1 构造精确等分：X 两次 rank1（score=1，best_rank=1）、Y 三次 rank2（score=1，best_rank=2）
        sq1 = [_doc("X", "x.md", "X", 1), _doc("Y", "y.md", "Y", 2)]
        sq2 = [_doc("X", "x.md", "X", 1), _doc("Y", "y.md", "Y", 2)]
        sq3 = [_doc("Y", "y.md", "Y", 2)]
        bundle = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2), ("sq3", sq3)],
            max_items=5, merge_rrf_k=1,
        )
        assert [i.source_name for i in bundle.items] == ["x.md", "y.md"]

    def test_source_name_tie_break_deterministic(self):
        # A 与 B 各只在一次检索出现且同为 rank1 → score 并列、best_rank 并列 → source ASC
        sq1 = [_doc("B", "b.md", "B", 1, document_id="dB")]
        sq2 = [_doc("A", "a.md", "A", 1, document_id="dA")]
        bundle = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        assert [i.source_name for i in bundle.items] == ["a.md", "b.md"]

    def test_max_items_enforced(self):
        sq1 = [_doc(chr(65 + i), f"{chr(97 + i)}.md", "x", i + 1) for i in range(4)]
        sq2 = [_doc(chr(69 + i), f"{chr(101 + i)}.md", "x", i + 1) for i in range(4)]
        bundle = merge_subquery_results_rrf(
            [("sq1", sq1), ("sq2", sq2)], max_items=5
        )
        assert len(bundle.items) == 5

    def test_input_candidate_lists_not_mutated(self):
        sq1 = [_doc("A", "a.md", "A", 1), _doc("B", "b.md", "B", 2)]
        sq2 = [_doc("A", "a.md", "A", 1)]
        snapshot = lambda lst: [(d.source_name, d.rank, d.content) for d in lst]
        sq1_before, sq2_before = snapshot(sq1), snapshot(sq2)
        merge_subquery_results_rrf([("sq1", sq1), ("sq2", sq2)], max_items=5)
        assert snapshot(sq1) == sq1_before
        assert snapshot(sq2) == sq2_before

    def test_ignores_raw_retriever_score(self):
        sq1 = [_doc("A", "a.md", "A", 1, score=0.9), _doc("B", "b.md", "B", 2, score=0.1)]
        sq2 = [_doc("C", "c.md", "C", 1, score=0.2), _doc("D", "d.md", "D", 2, score=0.9)]
        a = merge_subquery_results_rrf([("sq1", sq1), ("sq2", sq2)], max_items=5)
        sq1b = [_doc("A", "a.md", "A", 1, score=0.1), _doc("B", "b.md", "B", 2, score=0.9)]
        sq2b = [_doc("C", "c.md", "C", 1, score=0.9), _doc("D", "d.md", "D", 2, score=0.1)]
        b = merge_subquery_results_rrf([("sq1", sq1b), ("sq2", sq2b)], max_items=5)
        assert [i.source_name for i in a.items] == [i.source_name for i in b.items]

    def test_v1_and_v2_differ_on_reordering(self):
        # v1 轮转：B,A,C；v2 RRF：A,B,C（A、B 并列 score=1/61 → source ASC）
        sq1 = [_doc("B", "b.md", "B", 1), _doc("C", "c.md", "C", 2)]
        sq2 = [_doc("A", "a.md", "A", 1)]
        v1 = merge_subquery_results([("sq1", sq1), ("sq2", sq2)], max_items=5)
        v2 = merge_subquery_results_rrf([("sq1", sq1), ("sq2", sq2)], max_items=5)
        assert [i.source_name for i in v1.items] == ["b.md", "a.md", "c.md"]
        assert [i.source_name for i in v2.items] == ["a.md", "b.md", "c.md"]

    def test_unknown_policy_and_bad_rrf_k(self):
        with pytest.raises(ValueError):
            merge_subquery_results_policy(
                [("sq1", [])], max_items=5, merge_policy="bogus_v9"
            )
        with pytest.raises(ValueError):
            merge_subquery_results_rrf([], max_items=5, merge_rrf_k=0)
        with pytest.raises(TypeError):
            merge_subquery_results_rrf([], max_items=5, merge_rrf_k=True)

    def test_runtime_v2_uses_rrf_and_trace(self):
        sq1 = [
            _doc("A", "a.md", "A", 1, document_id="dA"),
            _doc("C", "c.md", "C", 2, document_id="dC"),
        ]
        sq2 = [
            _doc("B", "b.md", "B", 1, document_id="dB"),
            _doc("A", "a.md", "A", 2, document_id="dA"),
        ]
        retriever = _SequenceRetriever([sq1, sq2], supported=("bm25",))
        planner = _FakePlanner(
            _plan("decomposed_retrieval", subqueries=_subqueries("甲", "乙"))
        )
        runtime = AgentRuntime(
            planner=planner,
            retrieval_port=retriever,
            answer_port=_FakeAnswerer(),
            merge_policy=SUBQUERY_RRF_MERGE_V2,
        )
        result = runtime.run("问题")
        merged = [t for t in result.trace if t.event_type == "evidence_merged"]
        assert merged[0].data["merge_policy"] == SUBQUERY_RRF_MERGE_V2
        # A=1/61+1/62；B=1/61；C=1/62 → A,B,C
        sources = [i.source_name for i in result.evidence_bundle.items]
        assert sources == ["a.md", "b.md", "c.md"]

    def test_runtime_rejects_unknown_merge_policy(self):
        with pytest.raises(ValueError):
            AgentRuntime(
                planner=_FakePlanner(_plan("decomposed_retrieval", subqueries=_subqueries("甲"))),
                retrieval_port=_FakeRetriever(supported=("bm25",)),
                answer_port=_FakeAnswerer(),
                merge_policy="bogus_v9",
            )


# ---------------------------------------------------------------------------
# G3-ADAPT-06A：Adaptive Policy 策略表
# ---------------------------------------------------------------------------


class TestAdaptivePolicy:
    def test_policy_table(self):
        # no_retrieval
        assert resolve_initial_strategy(
            _plan("no_retrieval").plan, ("bm25", "hybrid")
        ) == ("none", "DIRECT_NO_RETRIEVAL")
        # fact / code_symbol → bm25 lexical
        assert resolve_initial_strategy(
            _plan_single_type("fact", "SIMPLE_FACT").plan, ("bm25", "hybrid")
        ) == ("bm25", "LEXICAL_EXACT_BM25")
        assert resolve_initial_strategy(
            _plan_single_type("code_symbol", "CODE_SYMBOL").plan, ("bm25", "hybrid")
        ) == ("bm25", "LEXICAL_EXACT_BM25")
        # hybrid-preferred single types
        for qtype, reason in [
            ("comparison", "COMPARISON_EVIDENCE"),
            ("causal", "CAUSAL_SYNTHESIS"),
            ("multi_entity", "MULTI_ENTITY_EVIDENCE"),
            ("troubleshooting", "TROUBLESHOOTING_EVIDENCE"),
            ("unanswerable_or_no_retrieval", "UNANSWERABLE_CHECK"),
        ]:
            assert resolve_initial_strategy(
                _plan_single_type(qtype, reason).plan, ("bm25", "hybrid")
            ) == ("hybrid", "COMPLEX_SEMANTIC_HYBRID")
            assert resolve_initial_strategy(
                _plan_single_type(qtype, reason).plan, ("bm25",)
            ) == ("bm25", "CAPABILITY_FALLBACK_BM25")

    def test_planner_fallback_fixed_bm25(self):
        fallback = build_planner_fallback_outcome("q", "PLAN_INVALID_SCHEMA")
        assert resolve_initial_strategy(
            fallback.plan, ("bm25", "hybrid")
        ) == ("bm25", "PLANNER_FALLBACK_BM25")

    def test_decomposed_primary_bm25(self):
        dec = _plan("decomposed_retrieval", subqueries=_subqueries("a", "b")).plan
        assert resolve_initial_strategy(
            dec, ("bm25", "hybrid")
        ) == ("bm25", "DECOMPOSED_BM25_PRIMARY")


# ---------------------------------------------------------------------------
# G3-ADAPT-06A：单次 Evidence Rescue（single）
# ---------------------------------------------------------------------------


class TestSingleRescue:
    def test_single_bm25_empty_upgrade_once(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        seq = _SequenceRetriever([[], docs], supported=("bm25", "hybrid"))
        runtime = AgentRuntime(
            planner=_FakePlanner(_plan("single_retrieval")),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-rescue-ok",
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert seq.calls == 2  # bm25 + 一次 hybrid rescue
        assert seq.calls_args[0][1] == "bm25"
        assert seq.calls_args[1][1] == "hybrid"
        assert result.verification.upgrade_attempted is True
        assert result.verification.upgrade_used is True
        upgraded = [
            t for t in result.trace if t.event_type == "retrieval_upgraded"
        ]
        assert len(upgraded) == 1  # 只升级一次，无循环
        assert upgraded[0].data["subquery_id"] == "q0"
        assert upgraded[0].data["upgrade_index"] == 1
        assert upgraded[0].data["from_strategy"] == "bm25"
        assert upgraded[0].data["to_strategy"] == "hybrid"

    def test_single_rescue_still_empty_refused(self):
        seq = _SequenceRetriever([[], []], supported=("bm25", "hybrid"))
        runtime = AgentRuntime(
            planner=_FakePlanner(_plan("single_retrieval")),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-rescue-fail",
        )
        result = runtime.run("问题")
        assert result.status == "refused"
        assert seq.calls == 2
        assert result.verification.upgrade_attempted is True
        assert result.verification.upgrade_used is False
        assert result.verification.reason_code == "INSUFFICIENT_EVIDENCE"

    def test_no_rescue_when_hybrid_unsupported(self):
        seq = _SequenceRetriever([[]], supported=())
        runtime = AgentRuntime(
            planner=_FakePlanner(_plan("single_retrieval")),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-no-rescue",
        )
        result = runtime.run("问题")
        assert result.status == "refused"
        assert seq.calls == 1  # 只 bm25，无补检索

    def test_single_complex_initial_hybrid_no_bm25(self):
        docs = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        seq = _SequenceRetriever([docs], supported=("bm25", "hybrid"))
        runtime = AgentRuntime(
            planner=_FakePlanner(_plan_single_type("comparison", "COMPARISON_EVIDENCE")),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-initial-hybrid",
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        assert seq.calls == 1
        assert seq.calls_args[0][1] == "hybrid"  # 初始即 hybrid，不先 bm25


# ---------------------------------------------------------------------------
# G3-ADAPT-06A：单次 Evidence Rescue（decomposed）
# ---------------------------------------------------------------------------


class TestDecomposedRescue:
    def test_decomposed_one_empty_rescued(self):
        doc1 = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        doc2 = [_doc("c2", "b.md", "内容B", rank=1, document_id="d2")]
        seq = _SequenceRetriever([[], doc2, doc1], supported=("bm25", "hybrid"))
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan("decomposed_retrieval", subqueries=_subqueries("甲", "乙"))
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-dec-rescue",
        )
        result = runtime.run("问题")
        assert result.status == "completed"
        # sq1 bm25(空) + sq2 bm25 + sq1 hybrid rescue = 3 次
        assert seq.calls == 3
        assert [a[1] for a in seq.calls_args] == ["bm25", "bm25", "hybrid"]
        assert result.verification.upgrade_attempted is True
        assert result.verification.upgrade_used is True
        assert result.verification.coverage_complete is True

    def test_decomposed_two_empty_only_first_rescued_refused(self):
        doc3 = [_doc("c3", "c.md", "内容C", rank=1, document_id="d3")]
        doc1 = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        # sq1 bm25(空) sq2 bm25(空) sq3 bm25(命中) sq1 hybrid(命中) = 4 次
        seq = _SequenceRetriever(
            [[], [], doc3, doc1], supported=("bm25", "hybrid")
        )
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan(
                    "decomposed_retrieval",
                    subqueries=_subqueries("甲", "乙", "丙"),
                )
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-two-missing",
        )
        result = runtime.run("问题")
        assert result.status == "refused"
        assert seq.calls == 4  # 3 bm25 + 1 hybrid rescue（只救第一个缺失 sq1）
        assert result.verification.reason_code == "INCOMPLETE_SUBQUERY_EVIDENCE"
        assert result.verification.missing_query_ids == ("sq2",)
        upgraded = [
            t for t in result.trace if t.event_type == "retrieval_upgraded"
        ]
        assert len(upgraded) == 1  # 只补检索一次
        assert upgraded[0].data["subquery_id"] == "sq1"

    def test_decomposed_rescue_exception_stops(self):
        doc2 = [_doc("c2", "b.md", "内容B", rank=1, document_id="d2")]
        # sq1 bm25(空) sq2 bm25(命中) sq1 hybrid(异常)
        seq = _SequenceRetriever(
            [[], doc2, RuntimeError("rescue boom")], supported=("bm25", "hybrid")
        )
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan("decomposed_retrieval", subqueries=_subqueries("甲", "乙"))
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-rescue-exc",
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "RETRIEVAL_FAILED"
        assert seq.calls == 3  # 补检索异常后不再调用
        assert result.trace[-1].event_type == "run_failed"

    def test_decomposed_budget_two_retrievals_stops_rescue(self):
        doc1 = [_doc("c1", "a.md", "内容A", rank=1, document_id="d1")]
        budget = AgentRunBudget(max_retrieval_calls=2)
        seq = _SequenceRetriever(
            [[], doc1], supported=("bm25", "hybrid")
        )
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan("decomposed_retrieval", subqueries=_subqueries("甲", "乙"))
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            budget=budget,
            run_id_factory=lambda: "rid-budget-rescue",
        )
        result = runtime.run("问题")
        assert result.status == "failed"
        assert result.error_code == "BUDGET_EXCEEDED"
        assert seq.calls == 2  # 2 bm25 后，补检索前预算超限
        assert result.trace[-1].event_type == "run_failed"

    def test_decomposed_trace_no_query_or_body(self):
        body = "这是不能进 trace 的证据正文"
        doc1 = [_doc("c1", "a.md", body, rank=1, document_id="d1")]
        seq = _SequenceRetriever(
            [[], doc1, doc1], supported=("bm25", "hybrid")
        )
        runtime = AgentRuntime(
            planner=_FakePlanner(
                _plan("decomposed_retrieval", subqueries=_subqueries("绝密子问题甲", "绝密子问题乙"))
            ),
            retrieval_port=seq,
            answer_port=_FakeAnswerer(),
            run_id_factory=lambda: "rid-rescue-body",
        )
        result = runtime.run("问题")
        blob = json.dumps([t.to_dict() for t in result.trace], ensure_ascii=False)
        assert body not in blob
        assert "绝密子问题甲" not in blob
        assert "绝密子问题乙" not in blob


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
            "context_prepared",
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
