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
from core.engineering_requirements import (
    EngineeringEvidenceRequirement,
    route_engineering_evidence_requirement,
)
from core.engineering_verification import EngineeringEvidenceVerifier
from core.engineering_task_contract import HybridTaskContract
from core.tool_agent.actions import ACTION_PARSE_FAILED
from core.tool_agent.activity import ActivityEvent
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    ENGINEERING_RUN_DEADLINE_SECONDS,
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
        finalization_strategy: str = "legacy",
        deadline_seconds: float | None = None,
        cancel_requested: Callable[[], bool] | None = None,
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
        if finalization_strategy != "legacy":
            parameters = inspect.signature(self._runtime.run).parameters
            accepts_var_keyword = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            if "finalization_strategy" not in parameters and not accepts_var_keyword:
                raise TypeError("ToolAgentRuntime 不支持 finalization_strategy")
            kwargs["finalization_strategy"] = finalization_strategy
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
        finalization_strategy: str = "legacy",
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
        if finalization_strategy not in ("legacy", "direct_hybrid", "hybrid_task_contract"):
            raise ValueError("Unsupported finalization_strategy")
        self._execution_adapter = execution_adapter
        self._context_resolver = context_resolver
        self._evidence_planner = evidence_planner
        self._retrieval_component = retrieval_component
        self._evidence_verifier = evidence_verifier
        self._finalization_strategy = finalization_strategy

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
        requirement = route_engineering_evidence_requirement(context_snapshot.lexical_query)
        task_contract = None
        if self._finalization_strategy == "hybrid_task_contract":
            if planner_outcome.task_contract is None:
                # Invalid/missing intent cannot silently fall back to a weaker
                # task or enter the tool loop. No second model request.
                return ToolAgentRunResult(
                    status="failed", answer=None, reason_code=None,
                    failure_code=ACTION_PARSE_FAILED, iterations_used=0,
                    tool_calls_used=0, tool_errors_used=0,
                    trace=(RuntimeTraceEvent(iteration=0, event_type="runtime_stopped",
                                             error_code="TASK_CONTRACT_INVALID"),),
                    execution=ToolAgentExecutionMetrics(
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        decision_llm_calls=0),
                )
            payload = planner_outcome.task_contract.to_dict()
            payload.pop("version")
            task_contract = HybridTaskContract.from_dict(
                payload, user_request=resolved_input,
                current_request=context_snapshot.original_input,
            )
            requirement = task_contract.to_requirement(requirement)
        retrieval_snapshot = self._retrieval_component.retrieve(
            resolved_input,
            planner_outcome,
            retrieval_query=context_snapshot.lexical_query,
        )
        finalization_verifier = self._evidence_verifier.bind(
            planner_outcome,
            retrieval_snapshot,
            requirement,
            **({"task_contract": task_contract} if task_contract is not None else {}),
        )
        result = self._execution_adapter.run(
            resolved_input,
            evidence_requirement=requirement,
            initial_context=retrieval_snapshot.initial_context,
            initial_evidence=retrieval_snapshot.knowledge_evidence,
            disabled_tools=("knowledge_search",),
            finalization_verifier=finalization_verifier,
            finalization_strategy=("direct_hybrid" if task_contract is not None
                                   else self._finalization_strategy),
            trace_sink=trace_sink,
            activity_sink=activity_sink,
            enforce_evidence_acquisition=True,
            deadline_seconds=ENGINEERING_RUN_DEADLINE_SECONDS,
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
            selector_llm_calls=(
                inner.selector_llm_calls if inner is not None else 0
            ),
            selector_latency_ms=(
                inner.selector_latency_ms if inner is not None else None
            ),
        )
        return replace(result, execution=execution, task_contract=task_contract)


__all__ = [
    "LegacyToolAgentExecutionAdapter",
    "UnifiedEngineeringRuntime",
]
