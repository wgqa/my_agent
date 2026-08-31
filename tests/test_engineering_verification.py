"""ARCH-VERIFY-06 contracts for unified evidence verification/finalization."""

from __future__ import annotations

from core.agent_runtime import Document
from core.engineering_requirements import (
    DIAGNOSIS_CROSS_FILE_V1,
    THEORY_CODE_V1,
    EngineeringEvidenceRequirement,
    route_engineering_evidence_requirement,
)
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_verification import (
    CITATION_STATUS_INVALID,
    CITATION_STATUS_NOT_CHECKED,
    CITATION_STATUS_NOT_PRESENT,
    CITATION_STATUS_VALID,
    INCOMPLETE_SUBQUERY_COVERAGE,
    INVALID_CITATION_REFERENCE,
    REQUIRED_EVIDENCE_MISSING,
    RETRIEVAL_EVIDENCE_INSUFFICIENT,
    EngineeringEvidenceVerifier,
)
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan, Subquery
from core.tool_agent import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    KnowledgeSearchHandler,
    ToolAgentRuntime,
    ToolCallAction,
    ToolRegistry,
)
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
)
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)


class RecordingRetrievalPort:
    def __init__(self, responses=None, *, supported_strategies=("bm25",)):
        self.responses = dict(responses or {})
        self.supported_strategies = tuple(supported_strategies)
        self.calls = []

    def search(self, query, strategy, top_k):
        self.calls.append((query, strategy, top_k))
        value = self.responses.get((query, strategy), ())
        if isinstance(value, BaseException):
            raise value
        return tuple(value)


class StaticPlanner(BaseQueryPlanner):
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def plan(self, query):
        self.calls.append(query)
        return self.outcome


class ScriptedProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
        self.registries = []
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.calls += 1
        self.registries.append(registry)
        self.states.append(control_state)
        return AgentDecisionOutcome(
            action=self.actions[min(self.calls - 1, len(self.actions) - 1)],
            failure_code=None,
            call_metadata=None,
        )


class StaticHandler:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return self.result(arguments) if callable(self.result) else self.result


def _doc(source, chunk, content="knowledge evidence", rank=1):
    return Document(
        chunk_id=chunk,
        document_id=f"doc-{chunk}",
        source_name=source,
        content=content,
        score=0.5,
        rank=rank,
    )


def _outcome(query, *, action="single_retrieval", query_type="fact", subqueries=()):
    return PlannerOutcome(
        plan=QueryPlan.create(
            original_query=query,
            query_type=query_type,
            retrieval_required=action != "no_retrieval",
            action=action,
            reason_code=(
                "NO_RETRIEVAL_NEEDED"
                if action == "no_retrieval"
                else "COMPARISON_EVIDENCE"
                if query_type == "comparison"
                else "SIMPLE_FACT"
            ),
            subqueries=tuple(subqueries),
        ),
        fallback_used=False,
        failure_code=None,
    )


def _decomposed(query, *queries):
    return _outcome(
        query,
        action="decomposed_retrieval",
        query_type="comparison",
        subqueries=tuple(
            Subquery(f"sq{i}", value, f"intent {i}", True)
            for i, value in enumerate(queries, 1)
        ),
    )


def _snapshot(query, outcome, responses, *, supported=("bm25", "hybrid")):
    port = RecordingRetrievalPort(responses, supported_strategies=supported)
    return EngineeringRetrievalComponent(port).retrieve(query, outcome), port


def _knowledge(evidence_id="E1", source="knowledge/theory.md", chunk="k1"):
    return KnowledgeEvidence(
        evidence_id=evidence_id,
        kind="knowledge",
        source_name=source,
        chunk_id=chunk,
        score=0.5,
        rank=1,
        snippet="planned knowledge",
    )


def _code(evidence_id="E2", path="core/example.py"):
    return EngineeringEvidence(
        evidence_id=evidence_id,
        kind="project_code",
        path=path,
        start_line=1,
        end_line=2,
        snippet="project implementation",
    )


def test_no_retrieval_is_not_required_and_no_citation_is_non_blocking():
    query = "direct answer"
    outcome = _outcome(
        query,
        action="no_retrieval",
        query_type="unanswerable_or_no_retrieval",
    )
    snapshot, _ = _snapshot(query, outcome, {})
    requirement = route_engineering_evidence_requirement(query)

    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, requirement, (), proposed_answer=None
    )
    assert result.retrieval_status == "not_required"
    assert result.retrieval_can_generate is True
    assert result.can_finalize is True
    assert result.citation_status == CITATION_STATUS_NOT_CHECKED

    no_citation = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, requirement, (), proposed_answer="direct answer"
    )
    assert no_citation.citation_status == CITATION_STATUS_NOT_PRESENT
    assert no_citation.can_finalize is True


def test_single_evidence_is_sufficient_and_q0_coverage_is_complete():
    query = "what is BM25?"
    outcome = _outcome(query)
    snapshot, _ = _snapshot(query, outcome, {(query, "bm25"): (_doc("k.md", "k1"),)})
    result = EngineeringEvidenceVerifier().verify(
        outcome,
        snapshot,
        route_engineering_evidence_requirement(query),
        snapshot.knowledge_evidence,
    )

    assert result.retrieval_status == "supported"
    assert result.required_query_ids == ("q0",)
    assert result.covered_query_ids == ("q0",)
    assert result.missing_query_ids == ()
    assert result.coverage_complete is True
    assert result.can_finalize is True


def test_single_empty_is_retrieval_insufficient_not_requirement_recovery():
    query = "empty knowledge"
    outcome = _outcome(query)
    snapshot, _ = _snapshot(query, outcome, {(query, "bm25"): ()}, supported=("bm25",))
    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, route_engineering_evidence_requirement(query), ()
    )

    assert result.retrieval_can_generate is False
    assert result.covered_query_ids == ()
    assert result.can_finalize is False
    assert result.recovery_allowed is False
    assert result.insufficiency_reasons == (RETRIEVAL_EVIDENCE_INSUFFICIENT,)


def test_decomposed_full_coverage_uses_sq_ids():
    query = "compare two mechanisms"
    outcome = _decomposed(query, "first mechanism", "second mechanism")
    snapshot, _ = _snapshot(
        query,
        outcome,
        {
            ("first mechanism", "bm25"): (_doc("first.md", "f1"),),
            ("second mechanism", "bm25"): (_doc("second.md", "s1"),),
        },
        supported=("bm25",),
    )
    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, route_engineering_evidence_requirement(query), snapshot.knowledge_evidence
    )

    assert result.required_query_ids == ("sq1", "sq2")
    assert result.covered_query_ids == ("sq1", "sq2")
    assert result.coverage_complete is True
    assert result.can_finalize is True


def test_decomposed_missing_coverage_is_incomplete_subquery_evidence():
    query = "compare missing mechanism"
    outcome = _decomposed(query, "first mechanism", "second mechanism", "third mechanism")
    snapshot, _ = _snapshot(
        query,
        outcome,
        {
            ("first mechanism", "bm25"): (_doc("first.md", "f1"),),
            ("second mechanism", "bm25"): (),
            ("third mechanism", "bm25"): (_doc("third.md", "t1"),),
        },
        supported=("bm25",),
    )
    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, route_engineering_evidence_requirement(query), snapshot.knowledge_evidence
    )

    assert result.required_query_ids == ("sq1", "sq2", "sq3")
    assert result.covered_query_ids == ("sq1", "sq3")
    assert result.missing_query_ids == ("sq2",)
    assert result.coverage_complete is False
    assert result.retrieval_reason_code == "INCOMPLETE_SUBQUERY_EVIDENCE"
    assert result.insufficiency_reasons == (INCOMPLETE_SUBQUERY_COVERAGE,)


def test_rrf_representative_query_id_does_not_erase_pre_merge_coverage():
    query = "compare same document"
    outcome = _decomposed(query, "first", "second")
    snapshot, _ = _snapshot(
        query,
        outcome,
        {
            ("first", "bm25"): (_doc("shared.md", "f1"),),
            ("second", "bm25"): (_doc("shared.md", "s2"),),
        },
        supported=("bm25",),
    )

    assert len(snapshot.evidence_bundle.items) == 1
    assert snapshot.evidence_bundle.items[0].query_id == "sq1"
    assert snapshot.covered_query_ids == ("sq1", "sq2")
    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, route_engineering_evidence_requirement(query), snapshot.knowledge_evidence
    )
    assert result.coverage_complete is True
    assert result.can_finalize is True


def test_theory_code_requirement_is_one_unified_check():
    query = "Explain the theory mechanism and compare it with the current implementation"
    requirement = route_engineering_evidence_requirement(query)
    assert requirement.requirement_profile is THEORY_CODE_V1
    outcome = _outcome(query)
    snapshot, _ = _snapshot(query, outcome, {(query, "bm25"): (_doc("theory.md", "k1"),)})

    missing_code = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, requirement, snapshot.knowledge_evidence
    )
    complete = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, requirement, snapshot.knowledge_evidence + (_code(),)
    )
    assert missing_code.evidence_requirement_satisfied is False
    assert missing_code.insufficiency_reasons == (REQUIRED_EVIDENCE_MISSING,)
    assert missing_code.can_finalize is False
    assert complete.evidence_requirement_satisfied is True
    assert complete.can_finalize is True


def test_cross_file_requirement_uses_distinct_project_paths():
    query = "failure propagation across modules"
    requirement = route_engineering_evidence_requirement(query)
    assert requirement.requirement_profile is DIAGNOSIS_CROSS_FILE_V1
    outcome = _outcome(query, action="no_retrieval", query_type="unanswerable_or_no_retrieval")
    snapshot, _ = _snapshot(query, outcome, {})
    verifier = EngineeringEvidenceVerifier()

    one = verifier.verify(outcome, snapshot, requirement, (_code(path="core/one.py"),))
    two = verifier.verify(
        outcome,
        snapshot,
        requirement,
        (_code(path="core/one.py"), _code("E3", path="core/two.py")),
    )
    assert one.distinct_project_code_paths == 1
    assert one.can_finalize is False
    assert two.distinct_project_code_paths == 2
    assert two.can_finalize is True


def test_citation_valid_reuses_existing_citation_id_context():
    query = "citation answer"
    outcome = _outcome(query)
    snapshot, _ = _snapshot(query, outcome, {(query, "bm25"): (_doc("source.md", "k1"),)})
    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, route_engineering_evidence_requirement(query),
        snapshot.knowledge_evidence, proposed_answer="answer [C1]"
    )

    assert result.citation_status == CITATION_STATUS_VALID
    assert result.invalid_citation_ids == ()
    assert result.can_finalize is True


def test_citation_invalid_blocks_without_semantic_claim_check():
    query = "citation answer"
    outcome = _outcome(query)
    snapshot, _ = _snapshot(query, outcome, {(query, "bm25"): (_doc("source.md", "k1"),)})
    result = EngineeringEvidenceVerifier().verify(
        outcome, snapshot, route_engineering_evidence_requirement(query),
        snapshot.knowledge_evidence, proposed_answer="answer [C9]"
    )

    assert result.citation_status == CITATION_STATUS_INVALID
    assert result.invalid_citation_ids == ("[C9]",)
    assert INVALID_CITATION_REFERENCE in result.insufficiency_reasons
    assert result.can_finalize is False
    assert result.recovery_allowed is False


def _read_result(arguments):
    return {
        "path": "core/synthetic.py",
        "start_line": 1,
        "end_line": 1,
        "lines": [{"line": 1, "text": "synthetic implementation"}],
    }


def _build_unified_runtime(query, port, provider):
    registry = ToolRegistry()
    registry.register(
        READ_PROJECT_CONTEXT_SPEC,
        StaticHandler(_read_result),
    )
    registry.register(KNOWLEDGE_SEARCH_SPEC, KnowledgeSearchHandler(port))
    return UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(
            ToolAgentRuntime(registry=registry, provider=provider)
        ),
        evidence_planner=EngineeringEvidencePlanner(
            StaticPlanner(_outcome(query))
        ),
        retrieval_component=EngineeringRetrievalComponent(port),
        context_resolver=EngineeringContextResolver(),
        evidence_verifier=EngineeringEvidenceVerifier(),
    )


def test_recoverable_requirement_shortage_recomputes_unified_result():
    query = "Explain the theory mechanism and compare it with the current implementation"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("theory.md", "k1"),)},
        supported_strategies=("bm25",),
    )
    provider = ScriptedProvider([
        FinalAnswerAction("final_answer", "first answer"),
        ToolCallAction(
            action="tool_call",
            tool_name="read_project_context",
            arguments={"path": "core/synthetic.py", "line": 1, "context_lines": 0},
        ),
        FinalAnswerAction("final_answer", "grounded answer"),
    ])
    result = _build_unified_runtime(query, port, provider).run(query)

    assert result.status == "completed"
    assert result.answer == "grounded answer"
    assert provider.calls == 3
    assert result.iterations_used == 3
    assert result.tool_calls_used == 1
    assert port.calls == [(query, "bm25", 5)]
    assert "knowledge_search" not in provider.registries[0]
    assert "knowledge_search" not in provider.registries[1]


def test_retrieval_coverage_shortage_hard_stops_without_knowledge_retry():
    query = "compare planned coverage"
    outcome = _decomposed(query, "first", "second")
    port = RecordingRetrievalPort(
        {("first", "bm25"): (_doc("first.md", "f1"),), ("second", "bm25"): ()},
        supported_strategies=("bm25",),
    )
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, StaticHandler(_read_result))
    registry.register(KNOWLEDGE_SEARCH_SPEC, KnowledgeSearchHandler(port))
    provider = ScriptedProvider([FinalAnswerAction("final_answer", "answer")])
    runtime = UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(ToolAgentRuntime(registry=registry, provider=provider)),
        evidence_planner=EngineeringEvidencePlanner(
            StaticPlanner(outcome)
        ),
        retrieval_component=EngineeringRetrievalComponent(port),
        context_resolver=EngineeringContextResolver(),
        evidence_verifier=EngineeringEvidenceVerifier(),
    )

    result = runtime.run(query)

    assert result.status == "refused"
    assert result.reason_code == "INSUFFICIENT_EVIDENCE_TO_FINALIZE"
    assert result.tool_calls_used == 0
    assert provider.calls == 1
    assert len(port.calls) == 2


def test_invalid_citation_hard_stops_without_repair_or_tool_call():
    query = "citation answer"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("source.md", "k1"),)},
        supported_strategies=("bm25",),
    )
    provider = ScriptedProvider([FinalAnswerAction("final_answer", "answer [C9]")])
    result = _build_unified_runtime(query, port, provider).run(query)

    assert result.status == "refused"
    assert result.reason_code == "INSUFFICIENT_EVIDENCE_TO_FINALIZE"
    assert result.tool_calls_used == 0
    assert provider.calls == 1
    assert len(port.calls) == 1


def test_verification_does_not_change_tool_counters():
    query = "counter answer"
    port = RecordingRetrievalPort(
        {(query, "bm25"): (_doc("source.md", "k1"),)},
        supported_strategies=("bm25",),
    )
    provider = ScriptedProvider([FinalAnswerAction("final_answer", "answer")])
    result = _build_unified_runtime(query, port, provider).run(query)

    assert result.status == "completed"
    assert result.iterations_used == 1
    assert result.tool_calls_used == 0
    assert result.tool_errors_used == 0


def test_observer_failure_does_not_change_unified_verification_outcome():
    query = "observer answer"
    def run(sink):
        port = RecordingRetrievalPort(
            {(query, "bm25"): (_doc("source.md", "k1"),)},
            supported_strategies=("bm25",),
        )
        provider = ScriptedProvider([FinalAnswerAction("final_answer", "answer")])
        return _build_unified_runtime(query, port, provider).run(query, activity_sink=sink)

    normal = run(None)
    def throwing(_event):
        raise RuntimeError("observer")
    isolated = run(throwing)
    assert isolated == normal
