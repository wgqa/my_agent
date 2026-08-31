"""Planned Knowledge Retrieval component for the Unified Engineering Runtime.

This module migrates the existing G3 adaptive policy, bounded retrieval
execution, and evidence merge without introducing an Agent loop.  It produces
trusted internal retrieval state for the ToolAgent seed seam; it does not own
verification, generation, finalization, or a second budget ledger.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from core.agent_runtime.evidence import (
    DEFAULT_MERGE_RRF_K,
    SUBQUERY_RRF_MERGE_V2,
    merge_subquery_results_policy,
)
from core.agent_runtime.models import (
    Document,
    EvidenceBundle,
    EvidenceItem,
    RouteDecision,
)
from core.agent_runtime.runtime import DeterministicRouter, RetrievalPort
from core.query_planning import PlannerOutcome
from core.tool_agent.runtime_models import (
    DecisionContextItem,
    KnowledgeEvidence,
)


RETRIEVAL_TOP_K = 5
MAX_RETRIEVAL_CALLS = 4
MAX_EVIDENCE_ITEMS = 5
_SUBQUERY_IDS = ("sq1", "sq2", "sq3")


def _require_non_empty_str(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串")


def _validate_document_for_public_conversion(document: Document) -> None:
    """Fail closed before merge if any returned Document cannot be public."""

    KnowledgeEvidence(
        evidence_id="E1",
        kind="knowledge",
        source_name=document.source_name,
        chunk_id=document.chunk_id,
        score=document.score,
        rank=document.rank,
        snippet=document.content[:500],
    )


def _validate_documents(documents: Sequence[Document]) -> tuple[Document, ...]:
    normalized = tuple(documents)
    for document in normalized:
        if type(document) is not Document:
            raise TypeError(
                "retrieval_port.search 必须返回 Document 序列，实际 "
                f"{type(document).__name__}"
            )
        _validate_document_for_public_conversion(document)
    return normalized


def _convert_evidence(bundle: EvidenceBundle) -> tuple[KnowledgeEvidence, ...]:
    converted = []
    for index, item in enumerate(bundle.items, 1):
        if type(item) is not EvidenceItem:
            raise TypeError("EvidenceBundle.items 必须全部是 EvidenceItem")
        converted.append(
            KnowledgeEvidence(
                evidence_id=f"E{index}",
                kind="knowledge",
                source_name=item.source_name,
                chunk_id=item.chunk_id,
                score=item.score,
                rank=item.rank,
                snippet=item.content[:500],
            )
        )
    return tuple(converted)


def _context_matches(bundle: EvidenceBundle, query_id: str) -> list[dict]:
    return [
        {
            "rank": item.rank,
            "source_name": item.source_name,
            "chunk_id": item.chunk_id,
            "score": item.score,
            "snippet": item.content[:500],
        }
        for item in bundle.items
        if item.query_id == query_id
    ]


def _build_initial_context(
    route: RouteDecision,
    resolved_input: str,
    bundle: EvidenceBundle,
) -> tuple[DecisionContextItem, ...]:
    if route.route == "direct_answer":
        return ()
    if route.route == "single_retrieval":
        query_pairs = ((resolved_input, resolved_input, "q0"),)
    else:
        query_pairs = tuple(
            (query_id, query, query_id)
            for query_id, query in zip(_SUBQUERY_IDS, route.queries)
        )
    return tuple(
        DecisionContextItem(
            tool_name="knowledge_search",
            arguments={"query": query},
            call_id=f"planned-retrieval-{call_id}",
            observation_status="ok",
            observation_result={"matches": _context_matches(bundle, query_id)},
            observation_error_code=None,
        )
        for query_id, query, call_id in query_pairs
    )


@dataclass(frozen=True)
class EngineeringRetrievalSnapshot:
    """Trusted internal handoff produced by one finite planned retrieval."""

    resolved_input: str
    planner_outcome: PlannerOutcome
    route_decision: RouteDecision
    evidence_bundle: EvidenceBundle
    retrieval_call_count: int
    query_count: int
    upgrade_attempted: bool
    upgrade_used: bool
    merge_policy: str
    merge_rrf_k: float
    knowledge_evidence: tuple[KnowledgeEvidence, ...]
    initial_context: tuple[DecisionContextItem, ...]
    merge_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.resolved_input, "resolved_input")
        if not isinstance(self.planner_outcome, PlannerOutcome):
            raise TypeError("planner_outcome 必须是 PlannerOutcome")
        if self.planner_outcome.plan.original_query != self.resolved_input:
            raise ValueError("planner_outcome 必须属于 resolved_input")
        if not isinstance(self.route_decision, RouteDecision):
            raise TypeError("route_decision 必须是 RouteDecision")
        if not isinstance(self.evidence_bundle, EvidenceBundle):
            raise TypeError("evidence_bundle 必须是 EvidenceBundle")
        for label, value in (
            ("retrieval_call_count", self.retrieval_call_count),
            ("query_count", self.query_count),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} 必须是非负严格 int")
        if self.retrieval_call_count > MAX_RETRIEVAL_CALLS:
            raise ValueError("retrieval_call_count 不得超过冻结上限 4")
        if self.retrieval_call_count != self.evidence_bundle.retrieval_call_count:
            raise ValueError("retrieval_call_count 必须与 EvidenceBundle 一致")
        if self.query_count != self.evidence_bundle.query_count:
            raise ValueError("query_count 必须与 EvidenceBundle 一致")
        for label, value in (
            ("upgrade_attempted", self.upgrade_attempted),
            ("upgrade_used", self.upgrade_used),
        ):
            if type(value) is not bool:
                raise TypeError(f"{label} 必须是 bool")
        if self.upgrade_used and not self.upgrade_attempted:
            raise ValueError("upgrade_used=True 要求 upgrade_attempted=True")
        if self.merge_policy != SUBQUERY_RRF_MERGE_V2:
            raise ValueError("merge_policy 必须是冻结的 subquery_rrf_merge_v2")
        if self.merge_rrf_k != DEFAULT_MERGE_RRF_K:
            raise ValueError("merge_rrf_k 必须保持冻结值 60.0")
        if type(self.knowledge_evidence) is not tuple or any(
            type(item) is not KnowledgeEvidence for item in self.knowledge_evidence
        ):
            raise TypeError("knowledge_evidence 必须是 KnowledgeEvidence tuple")
        if len(self.knowledge_evidence) != len(self.evidence_bundle.items):
            raise ValueError("knowledge_evidence 必须覆盖 EvidenceBundle.items")
        if tuple(item.evidence_id for item in self.knowledge_evidence) != tuple(
            f"E{i}" for i in range(1, len(self.knowledge_evidence) + 1)
        ):
            raise ValueError("knowledge_evidence evidence_id 必须从 E1 连续编号")
        if type(self.initial_context) is not tuple or any(
            type(item) is not DecisionContextItem for item in self.initial_context
        ):
            raise TypeError("initial_context 必须是 DecisionContextItem tuple")
        if not isinstance(self.merge_metadata, Mapping):
            raise TypeError("merge_metadata 必须是 Mapping")
        object.__setattr__(
            self,
            "merge_metadata",
            MappingProxyType(dict(self.merge_metadata)),
        )

    @property
    def converted_evidence(self) -> tuple[KnowledgeEvidence, ...]:
        """Compatibility name for the public conversion handoff."""

        return self.knowledge_evidence


class EngineeringRetrievalComponent:
    """Execute the finite QueryPlan retrieval without autonomous control."""

    def __init__(self, retrieval_port: RetrievalPort) -> None:
        if not isinstance(retrieval_port, RetrievalPort):
            raise TypeError("retrieval_port 必须实现 RetrievalPort")
        self._retrieval_port = retrieval_port
        self._router = DeterministicRouter()

    @property
    def retrieval_port(self) -> RetrievalPort:
        return self._retrieval_port

    def _search(self, query: str, strategy: str) -> tuple[Document, ...]:
        documents = self._retrieval_port.search(
            query,
            strategy=strategy,
            top_k=RETRIEVAL_TOP_K,
        )
        return _validate_documents(documents)

    def _snapshot(
        self,
        resolved_input: str,
        planner_outcome: PlannerOutcome,
        route: RouteDecision,
        bundle: EvidenceBundle,
        *,
        upgrade_attempted: bool,
        upgrade_used: bool,
        merge_metadata: Mapping[str, object],
    ) -> EngineeringRetrievalSnapshot:
        return EngineeringRetrievalSnapshot(
            resolved_input=resolved_input,
            planner_outcome=planner_outcome,
            route_decision=route,
            evidence_bundle=bundle,
            retrieval_call_count=bundle.retrieval_call_count,
            query_count=bundle.query_count,
            upgrade_attempted=upgrade_attempted,
            upgrade_used=upgrade_used,
            merge_policy=SUBQUERY_RRF_MERGE_V2,
            merge_rrf_k=DEFAULT_MERGE_RRF_K,
            knowledge_evidence=_convert_evidence(bundle),
            initial_context=_build_initial_context(route, resolved_input, bundle),
            merge_metadata=merge_metadata,
        )

    def retrieve(
        self,
        resolved_input: str,
        planner_outcome: PlannerOutcome,
    ) -> EngineeringRetrievalSnapshot:
        """Route and execute one finite planned retrieval sequence."""

        _require_non_empty_str(resolved_input, "resolved_input")
        if not isinstance(planner_outcome, PlannerOutcome):
            raise TypeError("planner_outcome 必须是 PlannerOutcome")
        if planner_outcome.plan.original_query != resolved_input:
            raise ValueError("planner_outcome.plan.original_query 必须等于 resolved_input")

        supported = tuple(getattr(self._retrieval_port, "supported_strategies", ()))
        route = self._router.route(planner_outcome.plan, supported)
        frozen_merge_metadata = {
            "merge_policy": SUBQUERY_RRF_MERGE_V2,
            "merge_rrf_k": DEFAULT_MERGE_RRF_K,
        }

        if route.route == "direct_answer":
            bundle = EvidenceBundle.empty(retrieval_call_count=0, query_count=0)
            return self._snapshot(
                resolved_input,
                planner_outcome,
                route,
                bundle,
                upgrade_attempted=False,
                upgrade_used=False,
                merge_metadata={
                    **frozen_merge_metadata,
                    "input_candidate_count": 0,
                    "final_unique_count": 0,
                    "truncated": False,
                },
            )

        if route.route == "single_retrieval":
            strategy = route.retrieval_strategy
            documents = self._search(resolved_input, strategy)
            retrieval_call_count = 1
            upgrade_attempted = False
            upgrade_used = False
            if not documents and strategy == "bm25" and "hybrid" in supported:
                documents = self._search(resolved_input, "hybrid")
                retrieval_call_count += 1
                upgrade_attempted = True
                upgrade_used = bool(documents)
            if retrieval_call_count > MAX_RETRIEVAL_CALLS:  # pragma: no cover
                raise RuntimeError("retrieval call bound exceeded")
            bundle = EvidenceBundle.from_documents(
                documents,
                query_id=resolved_input,
                max_items=MAX_EVIDENCE_ITEMS,
                retrieval_call_count=retrieval_call_count,
                query_count=1,
            )
            return self._snapshot(
                resolved_input,
                planner_outcome,
                route,
                bundle,
                upgrade_attempted=upgrade_attempted,
                upgrade_used=upgrade_used,
                merge_metadata={
                    **frozen_merge_metadata,
                    "input_candidate_count": len(documents),
                    "final_unique_count": len(bundle.items),
                    "truncated": len(documents) > MAX_EVIDENCE_ITEMS,
                },
            )

        query_results: list[tuple[str, tuple[Document, ...]]] = []
        missing: list[str] = []
        for query_id, query in zip(_SUBQUERY_IDS, route.queries):
            documents = self._search(query, "bm25")
            query_results.append((query_id, documents))
            if not documents:
                missing.append(query_id)

        retrieval_call_count = len(query_results)
        upgrade_attempted = False
        upgrade_used = False
        if missing and "hybrid" in supported:
            first_missing = missing[0]
            missing_index = next(
                index for index, query_id in enumerate(_SUBQUERY_IDS) if query_id == first_missing
            )
            query = route.queries[missing_index]
            rescued = self._search(query, "hybrid")
            query_results[missing_index] = (first_missing, rescued)
            retrieval_call_count += 1
            upgrade_attempted = True
            upgrade_used = bool(rescued)

        if retrieval_call_count > MAX_RETRIEVAL_CALLS:  # pragma: no cover
            raise RuntimeError("retrieval call bound exceeded")
        merge_metadata: dict[str, object] = {}
        bundle = merge_subquery_results_policy(
            query_results,
            max_items=MAX_EVIDENCE_ITEMS,
            merge_policy=SUBQUERY_RRF_MERGE_V2,
            merge_rrf_k=DEFAULT_MERGE_RRF_K,
            retrieval_call_count=retrieval_call_count,
            query_count=len(route.queries),
            stats=merge_metadata,
        )
        merge_metadata.update(
            {
                "final_unique_count": len(bundle.items),
                "covered_query_count": sum(bool(documents) for _, documents in query_results),
                "required_query_count": len(query_results),
            }
        )
        return self._snapshot(
            resolved_input,
            planner_outcome,
            route,
            bundle,
            upgrade_attempted=upgrade_attempted,
            upgrade_used=upgrade_used,
            merge_metadata=merge_metadata,
        )


__all__ = [
    "EngineeringRetrievalComponent",
    "EngineeringRetrievalSnapshot",
    "MAX_EVIDENCE_ITEMS",
    "MAX_RETRIEVAL_CALLS",
    "RETRIEVAL_TOP_K",
]
