"""Unified Engineering Runtime contract.

The existing ToolAgentRuntime remains the bounded Decision -> Tool ->
Observation executor. Context, planning, and finite Knowledge Retrieval are
components at the front of this boundary; this module must not grow a second
loop, budget, finalization policy, or autonomous controller.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Callable

from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_requirements import (
    EngineeringEvidenceRequirement,
    route_engineering_evidence_requirement,
)
from core.engineering_verification import EngineeringEvidenceVerifier
from core.query_planning import (
    BaseQueryPlanner,
    PlannerOutcome,
    build_planner_fallback_outcome,
)
from core.tool_agent.activity import ActivityEvent
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult


class _CompatibilityFallbackPlanner(BaseQueryPlanner):
    """No-provider compatibility seam for legacy direct Runtime construction."""

    def plan(self, original_query: str) -> PlannerOutcome:
        return build_planner_fallback_outcome(
            original_query,
            "PLANNER_PROVIDER_ERROR",
        )


def _default_evidence_planner() -> EngineeringEvidencePlanner:
    """Keep no-history legacy construction usable outside production wiring."""

    return EngineeringEvidencePlanner(_CompatibilityFallbackPlanner())


class LegacyToolAgentExecutionAdapter:
    """Adapt the existing ToolAgentRuntime as a pure execution component."""

    def __init__(self, runtime: ToolAgentRuntime) -> None:
        if not isinstance(runtime, ToolAgentRuntime):
            raise TypeError("runtime 必须是 ToolAgentRuntime")
        self._runtime = runtime

    def run(
        self,
        user_input: str,
        *,
        evidence_requirement: EngineeringEvidenceRequirement,
        initial_context: Sequence = (),
        initial_evidence: Sequence = (),
        disabled_tools: Collection[str] = (),
        finalization_verifier=None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        """Delegate one run without adding control flow or policy."""

        if not isinstance(evidence_requirement, EngineeringEvidenceRequirement):
            raise TypeError(
                "evidence_requirement 必须是 EngineeringEvidenceRequirement"
            )
        kwargs = {"evidence_requirement": evidence_requirement}
        if initial_context:
            kwargs["initial_context"] = initial_context
        if initial_evidence:
            kwargs["initial_evidence"] = initial_evidence
        if disabled_tools:
            kwargs["disabled_tools"] = disabled_tools
        if finalization_verifier is not None:
            kwargs["finalization_verifier"] = finalization_verifier
        if trace_sink is not None:
            kwargs["trace_sink"] = trace_sink
        if activity_sink is not None:
            kwargs["activity_sink"] = activity_sink
        return self._runtime.run(user_input, **kwargs)


class UnifiedEngineeringRuntime:
    """The single product Runtime boundary for Engineering requests."""

    def __init__(
        self,
        execution_adapter: LegacyToolAgentExecutionAdapter,
        *,
        context_resolver: EngineeringContextResolver | None = None,
        evidence_planner: EngineeringEvidencePlanner | None = None,
        retrieval_component: EngineeringRetrievalComponent | None = None,
        evidence_verifier: EngineeringEvidenceVerifier | None = None,
    ) -> None:
        if not isinstance(execution_adapter, LegacyToolAgentExecutionAdapter):
            raise TypeError(
                "execution_adapter 必须是 LegacyToolAgentExecutionAdapter"
            )
        if context_resolver is not None and not isinstance(
            context_resolver, EngineeringContextResolver
        ):
            raise TypeError("context_resolver 必须是 EngineeringContextResolver")
        if evidence_planner is not None and not isinstance(
            evidence_planner, EngineeringEvidencePlanner
        ):
            raise TypeError("evidence_planner must be EngineeringEvidencePlanner")
        if retrieval_component is not None and not isinstance(
            retrieval_component, EngineeringRetrievalComponent
        ):
            raise TypeError(
                "retrieval_component must be EngineeringRetrievalComponent"
            )
        if evidence_verifier is not None and not isinstance(
            evidence_verifier, EngineeringEvidenceVerifier
        ):
            raise TypeError("evidence_verifier must be EngineeringEvidenceVerifier")
        self._execution_adapter = execution_adapter
        # Keep the constructor compatible for no-history callers while the
        # production wiring injects the real provider-backed component.
        self._context_resolver = context_resolver or EngineeringContextResolver()
        # Production always injects the G3-backed Planner.  The deterministic
        # fallback keeps older direct construction sites behavior-compatible;
        # it is not an Agent, provider, loop, or second budget owner.
        self._evidence_planner = evidence_planner or _default_evidence_planner()
        # Production injects the planned Knowledge Retrieval component. Keeping
        # this seam optional preserves older direct construction sites until
        # they opt into the component, without changing their legacy behavior.
        self._retrieval_component = retrieval_component
        self._evidence_verifier = evidence_verifier or (
            EngineeringEvidenceVerifier() if retrieval_component is not None else None
        )

    def run(
        self,
        user_input: str,
        *,
        conversation_context=None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        """Resolve context, route once, then delegate to the bounded executor."""

        context_snapshot = self._context_resolver.resolve(
            user_input,
            conversation_context,
        )
        resolved_input = context_snapshot.resolved_input
        # Form trusted planning state exactly once. ARCH-PLAN-04 kept this
        # passive; ARCH-RETRIEVAL-05 interprets it only through the finite
        # Knowledge Retrieval component below.
        planner_outcome = self._evidence_planner.plan(resolved_input)
        requirement = route_engineering_evidence_requirement(resolved_input)
        if self._retrieval_component is None:
            return self._execution_adapter.run(
                resolved_input,
                evidence_requirement=requirement,
                trace_sink=trace_sink,
                activity_sink=activity_sink,
            )
        retrieval_snapshot = self._retrieval_component.retrieve(
            resolved_input,
            planner_outcome,
        )
        if self._evidence_verifier is None:  # pragma: no cover - constructor guard
            raise RuntimeError("retrieval component requires an evidence verifier")
        finalization_verifier = self._evidence_verifier.bind(
            planner_outcome,
            retrieval_snapshot,
            requirement,
        )
        return self._execution_adapter.run(
            resolved_input,
            evidence_requirement=requirement,
            initial_context=retrieval_snapshot.initial_context,
            initial_evidence=retrieval_snapshot.knowledge_evidence,
            disabled_tools=("knowledge_search",),
            finalization_verifier=finalization_verifier,
            trace_sink=trace_sink,
            activity_sink=activity_sink,
        )


__all__ = [
    "LegacyToolAgentExecutionAdapter",
    "UnifiedEngineeringRuntime",
]
