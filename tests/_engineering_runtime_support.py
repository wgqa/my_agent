"""Small deterministic full-assembly helpers for Unified Runtime tests."""

from __future__ import annotations

from core.agent_runtime import Document
from core.agent_runtime.runtime import RetrievalPort
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_verification import EngineeringEvidenceVerifier
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC, KnowledgeSearchHandler


class NoRetrievalPlanner(BaseQueryPlanner):
    """Use the explicit no-retrieval plan for tests that only probe wiring."""

    def plan(self, original_query: str) -> PlannerOutcome:
        return PlannerOutcome(
            plan=QueryPlan.create(
                original_query=original_query,
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=False,
                action="no_retrieval",
                reason_code="NO_RETRIEVAL_NEEDED",
            ),
            fallback_used=False,
            failure_code=None,
        )


class EmptyRetrievalPort(RetrievalPort):
    supported_strategies = ("bm25", "hybrid")

    def search(self, query: str, strategy: str, top_k: int):
        return ()


class StaticKnowledgeRetrievalPort(RetrievalPort):
    supported_strategies = ("bm25", "hybrid")

    def __init__(self, documents=()):
        self.documents = tuple(documents) or (
            Document(
                chunk_id="test-knowledge-1",
                document_id="test-knowledge",
                source_name="tests/fixtures/knowledge.md",
                content="deterministic planned knowledge evidence",
                score=0.5,
                rank=1,
            ),
        )
        self.calls = []

    def search(self, query: str, strategy: str, top_k: int):
        self.calls.append((query, strategy, top_k))
        return self.documents


def build_full_unified_runtime(
    runtime,
    *,
    context_resolver=None,
    planner: BaseQueryPlanner | None = None,
    retrieval_port: RetrievalPort | None = None,
) -> UnifiedEngineeringRuntime:
    """Construct the production-shaped assembly required after cutover."""

    planner = planner or NoRetrievalPlanner()
    if retrieval_port is None:
        retrieval_port = (
            EmptyRetrievalPort()
            if isinstance(planner, NoRetrievalPlanner)
            else StaticKnowledgeRetrievalPort()
        )
    registry = getattr(runtime, "_registry", None)
    if isinstance(runtime, ToolAgentRuntime) and isinstance(registry, ToolRegistry):
        if KNOWLEDGE_SEARCH_SPEC.name not in registry:
            registry.register(KNOWLEDGE_SEARCH_SPEC, KnowledgeSearchHandler(retrieval_port))
    return UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(runtime),
        context_resolver=context_resolver or EngineeringContextResolver(),
        evidence_planner=EngineeringEvidencePlanner(planner),
        retrieval_component=EngineeringRetrievalComponent(retrieval_port),
        evidence_verifier=EngineeringEvidenceVerifier(),
    )
