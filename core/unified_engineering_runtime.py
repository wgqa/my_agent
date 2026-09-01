"""Unified Engineering Runtime contract.

The existing ToolAgentRuntime remains the bounded Decision -> Tool ->
Observation executor. Context, planning, and finite Knowledge Retrieval are
components at the front of this boundary; this module must not grow a second
loop, budget, finalization policy, or autonomous controller.
"""

from __future__ import annotations

import inspect
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
from core.tool_agent.activity import ActivityEvent
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult


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
        enforce_evidence_acquisition: bool = False,
    ) -> ToolAgentRunResult:
        """Delegate one run without adding control flow or policy."""

        if not isinstance(evidence_requirement, EngineeringEvidenceRequirement):
            raise TypeError(
                "evidence_requirement 必须是 EngineeringEvidenceRequirement"
            )
        if type(enforce_evidence_acquisition) is not bool:
            raise TypeError("enforce_evidence_acquisition 必须是 bool")
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
        if enforce_evidence_acquisition:
            # Keep test doubles and older execution adapters source-compatible
            # during migration. The production ToolAgentRuntime exposes this
            # opt-in policy; no extra loop or budget is introduced here.
            parameters = inspect.signature(self._runtime.run).parameters
            if (
                "enforce_evidence_acquisition" in parameters
                or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
            ):
                kwargs["enforce_evidence_acquisition"] = True
        return self._runtime.run(user_input, **kwargs)


class UnifiedEngineeringRuntime:
    """The single product Runtime boundary for Engineering requests."""

    def __init__(
        self,
        execution_adapter: LegacyToolAgentExecutionAdapter,
        *,
        context_resolver: EngineeringContextResolver,
        evidence_planner: EngineeringEvidencePlanner,
        retrieval_component: EngineeringRetrievalComponent,
        evidence_verifier: EngineeringEvidenceVerifier,
    ) -> None:
        if not isinstance(execution_adapter, LegacyToolAgentExecutionAdapter):
            raise TypeError(
                "execution_adapter 必须是 LegacyToolAgentExecutionAdapter"
            )
        if not isinstance(context_resolver, EngineeringContextResolver):
            raise TypeError("context_resolver 必须是 EngineeringContextResolver")
        if not isinstance(evidence_planner, EngineeringEvidencePlanner):
            raise TypeError("evidence_planner must be EngineeringEvidencePlanner")
        if not isinstance(retrieval_component, EngineeringRetrievalComponent):
            raise TypeError(
                "retrieval_component must be EngineeringRetrievalComponent"
            )
        if not isinstance(evidence_verifier, EngineeringEvidenceVerifier):
            raise TypeError("evidence_verifier must be EngineeringEvidenceVerifier")
        self._execution_adapter = execution_adapter
        self._context_resolver = context_resolver
        self._evidence_planner = evidence_planner
        self._retrieval_component = retrieval_component
        self._evidence_verifier = evidence_verifier

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
        # Requirement is a domain contract, not a post-retrieval observation.
        # Establish it before planned Knowledge Retrieval so the later
        # finalization binding can keep Knowledge supplementary for Project-only
        # tasks while preserving it as required for Theory-Code tasks.
        requirement = route_engineering_evidence_requirement(resolved_input)
        retrieval_snapshot = self._retrieval_component.retrieve(
            resolved_input,
            planner_outcome,
        )
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
            enforce_evidence_acquisition=True,
        )


__all__ = [
    "LegacyToolAgentExecutionAdapter",
    "UnifiedEngineeringRuntime",
]
