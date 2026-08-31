"""ARCH-RETRIEVAL-05 contracts for planned Knowledge Retrieval migration."""

from __future__ import annotations

import pytest

from core.agent_runtime import Document
from core.agent_runtime.evidence import DEFAULT_MERGE_RRF_K, SUBQUERY_RRF_MERGE_V2
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_requirements import route_engineering_evidence_requirement
from core.engineering_retrieval import (
    EngineeringRetrievalComponent,
    MAX_EVIDENCE_ITEMS,
    MAX_RETRIEVAL_CALLS,
    RETRIEVAL_TOP_K,
)
from core.engineering_verification import EngineeringEvidenceVerifier
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan, Subquery
from core.tool_agent import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    KnowledgeSearchHandler,
    ToolAgentRuntime,
    ToolRegistry,
)
from core.tool_agent.activity import EvidenceAddedActivity
from core.tool_agent.runtime_models import (
    DecisionContextItem,
    EngineeringEvidence,
    KnowledgeEvidence,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)


class RecordingRetrievalPort:
    def __init__(self, responses=None, *, supported_strategies=("bm25",)):
        self.responses = dict(responses or {})
        self.supported_strategies = tuple(supported_strategies)
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query, strategy, top_k):
        self.calls.append((query, strategy, top_k))
        response = self.responses.get((query, strategy), ())
        if isinstance(response, BaseException):
            raise response
        return tuple(response)


class RecordingPlanner(BaseQueryPlanner):
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[str] = []

    def plan(self, original_query):
        self.calls.append(original_query)
        return self.outcome


class RecordingDecisionProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
        self.registries = []
        self.contexts = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.calls += 1
        self.registries.append(registry)
        self.contexts.append(tuple(item.to_dict() for item in context))
        action = self.actions[min(self.calls - 1, len(self.actions) - 1)]
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=None,
        )


class CountingToolHandler:
    def __init__(self):
        self.calls = 0

    def execute(self, _arguments):
        self.calls += 1
        return {"matches": []}


def _doc(source, chunk, content="evidence", rank=1, score=0.5):
    return Document(
        chunk_id=chunk,
        document_id=f"doc-{chunk}",
        source_name=source,
        content=content,
        score=score,
        rank=rank,
    )


def _outcome(query, *, action="single_retrieval", query_type="fact", reason_code="SIMPLE_FACT", subqueries=()):
    return PlannerOutcome(
        plan=QueryPlan.create(
            original_query=query,
            query_type=query_type,
            retrieval_required=action != "no_retrieval",
            action=action,
            reason_code=reason_code,
            subqueries=tuple(subqueries),
        ),
        fallback_used=False,
        failure_code=None,
    )


def _decomposed(query, *subquery_texts):
    subqueries = tuple(
        Subquery(f"sq{index}", text, f"intent {index}", True)
        for index, text in enumerate(subquery_texts, 1)
    )
    return _outcome(
        query,
        action="decomposed_retrieval",
        query_type="comparison",
        reason_code="COMPARISON_EVIDENCE",
        subqueries=subqueries,
    )


def test_no_retrieval_never_calls_backend_or_falls_back_to_bm25():
    query = "direct answer"
    port = RecordingRetrievalPort(supported_strategies=("bm25", "hybrid"))
    snapshot = EngineeringRetrievalComponent(port).retrieve(
        query,
        _outcome(
            query,
            action="no_retrieval",
            query_type="unanswerable_or_no_retrieval",
            reason_code="NO_RETRIEVAL_NEEDED",
        ),
    )

    assert port.calls == []
    assert snapshot.evidence_bundle.items == ()
    assert snapshot.retrieval_call_count == 0
    assert snapshot.knowledge_evidence == ()
    assert snapshot.initial_context == ()
    assert snapshot.required_query_ids == ()
    assert snapshot.covered_query_ids == ()


def test_fact_uses_bm25_once_with_frozen_top_k():
    query = "What is BM25?"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("docs/bm25.md", "c1"),)},
        supported_strategies=("bm25", "hybrid"),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, _outcome(query))

    assert port.calls == [(query, "bm25", RETRIEVAL_TOP_K)]
    assert snapshot.route_decision.retrieval_strategy == "bm25"
    assert snapshot.retrieval_call_count == 1
    assert snapshot.query_count == 1
    assert snapshot.required_query_ids == ("q0",)
    assert snapshot.covered_query_ids == ("q0",)


def test_complex_single_uses_hybrid_directly_when_supported():
    query = "compare BM25 and Dense"
    port = RecordingRetrievalPort(
        {(query, "hybrid"): (_doc("docs/hybrid.md", "c1"),)},
        supported_strategies=("bm25", "hybrid"),
    )
    outcome = _outcome(
        query,
        query_type="comparison",
        reason_code="COMPARISON_EVIDENCE",
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, outcome)

    assert port.calls == [(query, "hybrid", 5)]
    assert snapshot.route_decision.strategy_reason_code == "COMPLEX_SEMANTIC_HYBRID"


def test_complex_single_capability_falls_back_to_bm25_without_rescue():
    query = "compare BM25 and Dense"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("docs/bm25.md", "c1"),)},
        supported_strategies=("bm25",),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(
        query,
        _outcome(query, query_type="comparison", reason_code="COMPARISON_EVIDENCE"),
    )

    assert port.calls == [(query, "bm25", 5)]
    assert snapshot.route_decision.retrieval_strategy == "bm25"
    assert snapshot.route_decision.strategy_reason_code == "CAPABILITY_FALLBACK_BM25"
    assert snapshot.upgrade_attempted is False


def test_single_empty_bm25_gets_exactly_one_hybrid_rescue():
    query = "fact with empty sparse result"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (), (query, "hybrid"): (_doc("docs/rescue.md", "c1"),)},
        supported_strategies=("bm25", "hybrid"),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, _outcome(query))

    assert port.calls == [(query, "bm25", 5), (query, "hybrid", 5)]
    assert snapshot.upgrade_attempted is True
    assert snapshot.upgrade_used is True
    assert snapshot.retrieval_call_count == 2
    assert snapshot.required_query_ids == ("q0",)
    assert snapshot.covered_query_ids == ("q0",)


def test_single_successful_bm25_does_not_rescue():
    query = "fact with sparse result"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("docs/bm25.md", "c1"),)},
        supported_strategies=("bm25", "hybrid"),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, _outcome(query))

    assert len(port.calls) == 1
    assert snapshot.upgrade_attempted is False
    assert snapshot.upgrade_used is False
    assert snapshot.required_query_ids == ("q0",)
    assert snapshot.covered_query_ids == ("q0",)


def test_decomposed_two_subqueries_run_bm25_in_stable_order():
    query = "compare two things"
    outcome = _decomposed(query, "first", "second")
    port = RecordingRetrievalPort(
        {
            ("first", "bm25"): (_doc("docs/first.md", "c1"),),
            ("second", "bm25"): (_doc("docs/second.md", "c2"),),
        },
        supported_strategies=("bm25",),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, outcome)

    assert port.calls == [("first", "bm25", 5), ("second", "bm25", 5)]
    assert snapshot.query_count == 2
    assert snapshot.retrieval_call_count == 2
    assert [item.query_id for item in snapshot.evidence_bundle.items] == ["sq1", "sq2"]
    assert snapshot.required_query_ids == ("sq1", "sq2")
    assert snapshot.covered_query_ids == ("sq1", "sq2")


def test_decomposed_three_subqueries_run_bm25_three_times():
    query = "compare three things"
    outcome = _decomposed(query, "first", "second", "third")
    port = RecordingRetrievalPort(
        {
            ("first", "bm25"): (_doc("docs/first.md", "c1"),),
            ("second", "bm25"): (_doc("docs/second.md", "c2"),),
            ("third", "bm25"): (_doc("docs/third.md", "c3"),),
        },
        supported_strategies=("bm25",),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, outcome)

    assert port.calls == [
        ("first", "bm25", 5),
        ("second", "bm25", 5),
        ("third", "bm25", 5),
    ]
    assert snapshot.retrieval_call_count == 3
    assert snapshot.retrieval_call_count <= MAX_RETRIEVAL_CALLS


def test_multiple_missing_subqueries_only_first_gets_one_rescue():
    query = "compare missing things"
    outcome = _decomposed(query, "first", "second", "third")
    port = RecordingRetrievalPort(
        {
            ("first", "bm25"): (),
            ("second", "bm25"): (),
            ("third", "bm25"): (_doc("docs/third.md", "c3"),),
            ("first", "hybrid"): (_doc("docs/first-rescue.md", "c1"),),
            ("second", "hybrid"): (_doc("docs/second-rescue.md", "c2"),),
        },
        supported_strategies=("bm25", "hybrid"),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, outcome)

    assert port.calls == [
        ("first", "bm25", 5),
        ("second", "bm25", 5),
        ("third", "bm25", 5),
        ("first", "hybrid", 5),
    ]
    assert snapshot.upgrade_attempted is True
    assert snapshot.upgrade_used is True
    assert snapshot.retrieval_call_count == 4
    assert snapshot.retrieval_call_count <= MAX_RETRIEVAL_CALLS
    assert snapshot.required_query_ids == ("sq1", "sq2", "sq3")
    assert snapshot.covered_query_ids == ("sq1", "sq3")


def test_decomposed_merge_uses_frozen_rrf_deterministic_dedup_and_cap():
    query = "compare merge"
    outcome = _decomposed(query, "first", "second")
    port = RecordingRetrievalPort(
        {
            (
                "first",
                "bm25",
            ): (
                _doc("docs/shared.md", "shared-1", rank=1),
                _doc("docs/first.md", "first-1", rank=2),
            ),
            (
                "second",
                "bm25",
            ): (
                _doc("docs/shared.md", "shared-2", rank=1),
                _doc("docs/second.md", "second-1", rank=2),
            ),
        },
        supported_strategies=("bm25",),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, outcome)

    assert snapshot.merge_policy == SUBQUERY_RRF_MERGE_V2
    assert snapshot.merge_rrf_k == DEFAULT_MERGE_RRF_K == 60.0
    assert snapshot.merge_metadata["merge_policy"] == SUBQUERY_RRF_MERGE_V2
    assert [item.source_name for item in snapshot.evidence_bundle.items] == [
        "docs/shared.md",
        "docs/first.md",
        "docs/second.md",
    ]
    assert len(snapshot.evidence_bundle.items) <= MAX_EVIDENCE_ITEMS
    assert snapshot.evidence_bundle.items[0].query_id == "sq1"
    assert [item.evidence_id for item in snapshot.knowledge_evidence] == [
        "E1",
        "E2",
        "E3",
    ]


def test_bundle_query_id_is_retained_and_public_conversion_is_bounded():
    query = "compare snippets"
    long_content = "x" * 800
    outcome = _decomposed(query, "first", "second")
    port = RecordingRetrievalPort(
        {
            ("first", "bm25"): (_doc("docs/first.md", "c1", long_content),),
            ("second", "bm25"): (_doc("docs/second.md", "c2"),),
        },
        supported_strategies=("bm25",),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, outcome)

    assert snapshot.evidence_bundle.items[0].query_id == "sq1"
    assert len(snapshot.knowledge_evidence[0].snippet) == 500
    assert snapshot.initial_context[0].observation_result["matches"][0]["snippet"]
    assert len(snapshot.initial_context[0].observation_result["matches"][0]["snippet"]) == 500


@pytest.mark.parametrize("source_name", ["/etc/passwd", "C:/secret.txt", "\\\\server\\share\\secret.txt"])
def test_unsafe_provenance_fails_closed(source_name):
    query = "unsafe provenance"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc(source_name, "c1"),)},
        supported_strategies=("bm25",),
    )

    with pytest.raises(ValueError):
        EngineeringRetrievalComponent(port).retrieve(query, _outcome(query))


def test_planned_context_and_evidence_are_seeded_before_first_decision():
    query = "What is BM25?"
    knowledge = _doc("docs/bm25.md", "c1", "bounded planned snippet")
    port = RecordingRetrievalPort(
        {(query, "bm25"): (knowledge,)},
        supported_strategies=("bm25",),
    )
    provider = RecordingDecisionProvider(
        [FinalAnswerAction("final_answer", "answer from planned evidence")]
    )
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    registry.register(KNOWLEDGE_SEARCH_SPEC, KnowledgeSearchHandler(port))
    runtime = UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(
            ToolAgentRuntime(registry=registry, provider=provider)
        ),
        evidence_planner=EngineeringEvidencePlanner(
            RecordingPlanner(_outcome(query))
        ),
        retrieval_component=EngineeringRetrievalComponent(port),
        context_resolver=EngineeringContextResolver(),
        evidence_verifier=EngineeringEvidenceVerifier(),
    )

    result = runtime.run(query)

    assert result.status == "completed"
    assert result.iterations_used == 1
    assert result.tool_calls_used == 0
    assert len(result.evidence) == 1
    assert provider.contexts[0][0]["tool_name"] == "knowledge_search"
    assert provider.contexts[0][0]["observation_result"]["matches"][0]["snippet"] == (
        "bounded planned snippet"
    )


def test_initial_evidence_participates_in_requirement_state(tmp_path):
    query = "implementation detail"
    knowledge = KnowledgeEvidence(
        evidence_id="E9",
        kind="knowledge",
        source_name="docs/theory.md",
        chunk_id="c1",
        score=0.9,
        rank=1,
        snippet="theory evidence",
    )
    project = EngineeringEvidence(
        evidence_id="E10",
        kind="project_code",
        path="core/example.py",
        start_line=1,
        end_line=1,
        snippet="code evidence",
    )
    provider = RecordingDecisionProvider(
        [FinalAnswerAction("final_answer", "grounded answer")]
    )
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    requirement = route_engineering_evidence_requirement(
        "Explain the theory mechanism and compare it with the current implementation"
    )

    result = runtime.run(
        query,
        evidence_requirement=requirement,
        initial_evidence=(knowledge, project),
    )

    assert result.status == "completed"
    assert [item.evidence_id for item in result.evidence] == ["E1", "E2"]
    assert result.tool_calls_used == 0
    activities = []
    ToolAgentRuntime(registry=registry, provider=provider).run(
        query,
        initial_evidence=(knowledge,),
        activity_sink=activities.append,
    )
    assert any(isinstance(event, EvidenceAddedActivity) for event in activities)


def test_engineering_registry_hides_knowledge_search_while_legacy_registry_stays_intact():
    query = "What is BM25?"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("docs/bm25.md", "c1"),)},
        supported_strategies=("bm25",),
    )
    knowledge_handler = CountingToolHandler()
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    registry.register(KNOWLEDGE_SEARCH_SPEC, knowledge_handler)
    provider = RecordingDecisionProvider(
        [FinalAnswerAction("final_answer", "planned answer")]
    )
    tool_runtime = ToolAgentRuntime(registry=registry, provider=provider)
    runtime = UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(tool_runtime),
        evidence_planner=EngineeringEvidencePlanner(
            RecordingPlanner(_outcome(query))
        ),
        retrieval_component=EngineeringRetrievalComponent(port),
        context_resolver=EngineeringContextResolver(),
        evidence_verifier=EngineeringEvidenceVerifier(),
    )

    result = runtime.run(query)

    assert result.status == "completed"
    assert port.calls == [(query, "bm25", 5)]
    assert knowledge_handler.calls == 0
    assert "knowledge_search" not in provider.registries[0]
    assert "knowledge_search" in registry


def test_initial_seed_validation_rejects_arbitrary_dicts():
    query = "seed validation"
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    runtime = ToolAgentRuntime(
        registry=registry,
        provider=RecordingDecisionProvider(
            [FinalAnswerAction("final_answer", "answer")]
        ),
    )

    with pytest.raises(TypeError):
        runtime.run(query, initial_context=({"bad": "context"},))
    with pytest.raises(TypeError):
        runtime.run(query, initial_evidence=({"bad": "evidence"},))


def test_retrieval_exception_fails_fast_before_tool_provider():
    query = "backend crash"
    port = RecordingRetrievalPort(
        {(query, "bm25"): RuntimeError("backend crashed")},
        supported_strategies=("bm25",),
    )
    provider = RecordingDecisionProvider(
        [FinalAnswerAction("final_answer", "must not run")]
    )
    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    runtime = UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(
            ToolAgentRuntime(registry=registry, provider=provider)
        ),
        evidence_planner=EngineeringEvidencePlanner(
            RecordingPlanner(_outcome(query))
        ),
        retrieval_component=EngineeringRetrievalComponent(port),
        context_resolver=EngineeringContextResolver(),
        evidence_verifier=EngineeringEvidenceVerifier(),
    )

    with pytest.raises(RuntimeError, match="backend crashed"):
        runtime.run(query)
    assert provider.calls == 0


def test_different_plans_can_produce_different_planned_evidence():
    query = "same question"
    single_port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("docs/single.md", "c1"),)},
        supported_strategies=("bm25",),
    )
    decomposed_port = RecordingRetrievalPort(
        {
            ("first", "bm25"): (_doc("docs/first.md", "c1"),),
            ("second", "bm25"): (_doc("docs/second.md", "c2"),),
        },
        supported_strategies=("bm25",),
    )
    single = EngineeringRetrievalComponent(single_port).retrieve(
        query,
        _outcome(query),
    )
    decomposed = EngineeringRetrievalComponent(decomposed_port).retrieve(
        query,
        _decomposed(query, "first", "second"),
    )

    assert single.evidence_bundle.items != decomposed.evidence_bundle.items
    assert single.retrieval_call_count == 1
    assert decomposed.retrieval_call_count == 2


def test_minimal_evidence_verifier_is_not_called_by_retrieval_component():
    query = "retrieval only"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("docs/evidence.md", "c1"),)},
        supported_strategies=("bm25",),
    )
    snapshot = EngineeringRetrievalComponent(port).retrieve(query, _outcome(query))

    assert snapshot.evidence_bundle.items
    assert not hasattr(snapshot, "verification")
