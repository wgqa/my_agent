"""Unified Engineering Runtime contract.

The existing ToolAgentRuntime remains the bounded Decision -> Tool ->
Observation executor. Context, planning, and finite Knowledge Retrieval are
components at the front of this boundary; this module must not grow a second
loop, budget, finalization policy, or autonomous controller.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Collection, Sequence
from dataclasses import replace
from typing import Callable

from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_requirements import EngineeringEvidenceRequirement
from core.engineering_requirement_planning import (
    BaseRequirementProvider, RequirementPlanningOutcome, RuleRequirementProvider,
)
from core.engineering_verification import EngineeringEvidenceVerifier
from core.engineering_requirement_contract import RequirementContract
from core.engineering_candidate_verification import CandidateEvidenceVerifier, BoundCandidateEvidenceVerifier
from core.engineering_candidate_models import CandidateToolAgentRunResult, CandidateFinalizationSummary
from core.tool_agent.activity import ActivityEvent
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    ENGINEERING_RUN_DEADLINE_SECONDS,
    ENGINEERING_RUN_CANCELLED,
    ENGINEERING_RUN_DEADLINE_EXCEEDED,
    RuntimeTraceEvent,
    ToolAgentExecutionMetrics,
    ToolAgentRunResult,
)


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
        deadline_seconds: float | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ToolAgentRunResult:
        """Delegate one run without adding control flow or policy."""

        if type(evidence_requirement) is RequirementContract:
            if (type(finalization_verifier) is not BoundCandidateEvidenceVerifier
                    or finalization_verifier.contract != evidence_requirement):
                raise TypeError("candidate adapter requires a bound candidate verifier")
        elif not isinstance(evidence_requirement, EngineeringEvidenceRequirement):
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
            accepts_var_keyword = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            if "enforce_evidence_acquisition" in parameters or accepts_var_keyword:
                kwargs["enforce_evidence_acquisition"] = True
            if deadline_seconds is not None and (
                "deadline_seconds" in parameters or accepts_var_keyword
            ):
                kwargs["deadline_seconds"] = deadline_seconds
            if cancel_requested is not None and (
                "cancel_requested" in parameters or accepts_var_keyword
            ):
                kwargs["cancel_requested"] = cancel_requested
        return self._runtime.run(user_input, **kwargs)

    def candidate_capabilities(self):
        from core.engineering_materials import capability_manifest
        return capability_manifest([s for s in self._runtime._registry.list_specs() if s.name != "knowledge_search"])


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
        requirement_provider: BaseRequirementProvider | None = None,
        candidate_verifier: CandidateEvidenceVerifier | None = None,
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
        if requirement_provider is not None and not isinstance(requirement_provider, BaseRequirementProvider):
            raise TypeError("requirement_provider must be BaseRequirementProvider")
        # Rule/shadow retain the old verifier. Candidate contracts may control
        # execution only with their explicit material/submission verifier.
        if candidate_verifier is not None and type(candidate_verifier) is not CandidateEvidenceVerifier:
            raise TypeError("candidate_verifier must be CandidateEvidenceVerifier")
        if (requirement_provider is not None and requirement_provider.evidence_policy != "legacy"
                and candidate_verifier is None):
            raise ValueError("goal_v2 execution is not enabled: material/goal verification must be implemented first")
        if candidate_verifier is not None:
            if requirement_provider is None or requirement_provider.evidence_policy != "goal_v2":
                raise ValueError("candidate verification requires goal_v2 requirements")
            execution_adapter.candidate_capabilities()  # fail on a missing adapter before a model call
        self._execution_adapter = execution_adapter
        self._context_resolver = context_resolver
        self._evidence_planner = evidence_planner
        self._retrieval_component = retrieval_component
        self._evidence_verifier = evidence_verifier
        self._requirement_provider = requirement_provider or RuleRequirementProvider()
        self._record_requirement_planning = requirement_provider is not None
        self._candidate_verifier = candidate_verifier

    def run(
        self,
        user_input: str,
        *,
        conversation_context=None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ToolAgentRunResult:
        """Resolve context, route once, then delegate to the bounded executor.

        The product deadline is system-owned
        (``ENGINEERING_RUN_DEADLINE_SECONDS``) and cooperative; the optional
        ``cancel_requested`` probe is only consulted at the executor's safe
        boundaries. ``elapsed_ms`` in the returned execution summary covers
        the whole product request (context resolution, planning, retrieval,
        bounded loop).
        """

        started = time.monotonic()
        if cancel_requested is not None and not callable(cancel_requested):
            raise TypeError("cancel_requested must be callable or None")
        requirement_outcome = None

        def lifecycle_boundary(force_reason=None):
            # New opt-in planning consumes the same request deadline. Preserve
            # the legacy default's lifecycle behavior for the frozen comparison.
            if not self._record_requirement_planning:
                return None
            reason = force_reason
            if cancel_requested is not None and cancel_requested():
                reason = ENGINEERING_RUN_CANCELLED
            elif reason is None and time.monotonic() - started >= ENGINEERING_RUN_DEADLINE_SECONDS:
                reason = ENGINEERING_RUN_DEADLINE_EXCEEDED
            if reason is None:
                return None
            event = RuntimeTraceEvent(iteration=0, event_type="runtime_stopped", error_code=reason)
            if trace_sink is not None:
                trace_sink(event)
            result_type = CandidateToolAgentRunResult if self._candidate_verifier else ToolAgentRunResult
            extra = {"finalization": CandidateFinalizationSummary(self._candidate_verifier.policy)} if self._candidate_verifier else {}
            return result_type(
                status="refused", answer=None, reason_code=reason, failure_code=None,
                iterations_used=0, tool_calls_used=0, tool_errors_used=0,
                trace=(event,), evidence=(),
                execution=ToolAgentExecutionMetrics(
                    elapsed_ms=int((time.monotonic() - started) * 1000), decision_llm_calls=0,
                ), requirement_planning=requirement_outcome, **extra,
            )

        stopped = lifecycle_boundary()
        if stopped is not None:
            return stopped
        context_snapshot = self._context_resolver.resolve(
            user_input,
            conversation_context,
        )
        resolved_input = context_snapshot.resolved_input
        stopped = lifecycle_boundary()
        if stopped is not None:
            return stopped
        # Form trusted planning state exactly once. ARCH-PLAN-04 kept this
        # passive; ARCH-RETRIEVAL-05 interprets it only through the finite
        # Knowledge Retrieval component below.
        planner_outcome = self._evidence_planner.plan(resolved_input)
        stopped = lifecycle_boundary()
        if stopped is not None:
            return stopped
        # Requirement is a domain contract, not a post-retrieval observation.
        # Establish it before planned Knowledge Retrieval so the later
        # finalization binding can keep Knowledge supplementary for Project-only
        # tasks while preserving it as required for Theory-Code tasks.
        plan_kwargs = {}
        if "timeout_seconds" in inspect.signature(self._requirement_provider.plan).parameters:
            plan_kwargs["timeout_seconds"] = min(20.0, ENGINEERING_RUN_DEADLINE_SECONDS - (time.monotonic() - started))
        if plan_kwargs.get("timeout_seconds", 1) <= 0:
            return lifecycle_boundary(ENGINEERING_RUN_DEADLINE_EXCEEDED)
        requirement_outcome = self._requirement_provider.plan(context_snapshot, **plan_kwargs)
        if type(requirement_outcome) is not RequirementPlanningOutcome:
            raise TypeError("requirement_provider must return RequirementPlanningOutcome")
        requirement_outcome.validate_input(context_snapshot)
        requirement = requirement_outcome.requirement
        if self._candidate_verifier is not None and requirement is None:
            failure = requirement_outcome.metadata.failure_code
            event = RuntimeTraceEvent(iteration=0, event_type="runtime_stopped", error_code=failure)
            if trace_sink is not None:
                trace_sink(event)
            return CandidateToolAgentRunResult(status="failed", answer=None, reason_code=None, failure_code=failure,
                iterations_used=0, tool_calls_used=0, tool_errors_used=0, trace=(event,),
                requirement_planning=requirement_outcome,
                execution=ToolAgentExecutionMetrics(int((time.monotonic() - started) * 1000), 0),
                finalization=CandidateFinalizationSummary(self._candidate_verifier.policy, failure_code=failure))
        if self._candidate_verifier is not None:
            if requirement_outcome.metadata.evidence_policy != "goal_v2" or type(requirement) is not RequirementContract:
                raise TypeError("candidate execution requires exactly the frozen candidate contract")
        elif (requirement_outcome.metadata.evidence_policy != "legacy"
                or type(requirement) is not EngineeringEvidenceRequirement):
            raise TypeError("legacy execution must receive exactly the frozen rule requirement")
        stopped = lifecycle_boundary()
        if stopped is not None:
            return stopped
        retrieval_snapshot = self._retrieval_component.retrieve(
            resolved_input,
            planner_outcome,
            retrieval_query=context_snapshot.lexical_query,
        )
        finalization_verifier = (self._candidate_verifier.bind(context_snapshot, requirement_outcome,
                                  planner_outcome, retrieval_snapshot) if self._candidate_verifier is not None
                                else self._evidence_verifier.bind(
            planner_outcome,
            retrieval_snapshot,
            requirement,
        ))
        stopped = lifecycle_boundary()
        if stopped is not None:
            return stopped
        execution_deadline = ENGINEERING_RUN_DEADLINE_SECONDS
        if self._record_requirement_planning:
            execution_deadline -= time.monotonic() - started
            if execution_deadline <= 0:
                return lifecycle_boundary(ENGINEERING_RUN_DEADLINE_EXCEEDED)
        result = self._execution_adapter.run(
            resolved_input,
            evidence_requirement=requirement,
            initial_context=retrieval_snapshot.initial_context,
            initial_evidence=retrieval_snapshot.knowledge_evidence,
            disabled_tools=("knowledge_search",),
            finalization_verifier=finalization_verifier,
            trace_sink=trace_sink,
            activity_sink=activity_sink,
            enforce_evidence_acquisition=True,
            deadline_seconds=execution_deadline,
            cancel_requested=cancel_requested,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        inner = result.execution
        execution = ToolAgentExecutionMetrics(
            elapsed_ms=elapsed_ms,
            decision_llm_calls=(
                inner.decision_llm_calls if inner is not None else 0
            ),
            input_tokens=inner.input_tokens if inner is not None else None,
            output_tokens=inner.output_tokens if inner is not None else None,
        )
        return replace(result, execution=execution,
                       requirement_planning=requirement_outcome if self._record_requirement_planning else None)


__all__ = [
    "LegacyToolAgentExecutionAdapter",
    "UnifiedEngineeringRuntime",
]
