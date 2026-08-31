"""Unified Engineering Runtime contract.

ARCH-RUNTIME-02 deliberately establishes only the product Runtime boundary.
The existing ToolAgentRuntime remains the bounded Decision -> Tool ->
Observation executor until later component migration stages.  This module
must not grow a second loop, budget, finalization policy, or planner.
"""

from __future__ import annotations

from typing import Callable

from core.engineering_requirements import (
    EngineeringEvidenceRequirement,
    route_engineering_evidence_requirement,
)
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
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        """Delegate one run without adding control flow or policy."""

        if not isinstance(evidence_requirement, EngineeringEvidenceRequirement):
            raise TypeError(
                "evidence_requirement 必须是 EngineeringEvidenceRequirement"
            )
        kwargs = {"evidence_requirement": evidence_requirement}
        if trace_sink is not None:
            kwargs["trace_sink"] = trace_sink
        if activity_sink is not None:
            kwargs["activity_sink"] = activity_sink
        return self._runtime.run(user_input, **kwargs)


class UnifiedEngineeringRuntime:
    """The single product Runtime boundary for Engineering requests."""

    def __init__(self, execution_adapter: LegacyToolAgentExecutionAdapter) -> None:
        if not isinstance(execution_adapter, LegacyToolAgentExecutionAdapter):
            raise TypeError(
                "execution_adapter 必须是 LegacyToolAgentExecutionAdapter"
            )
        self._execution_adapter = execution_adapter

    def run(
        self,
        user_input: str,
        *,
        conversation_context=None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        """Route once, then delegate to the existing bounded executor.

        ``conversation_context`` is a reserved seam for ARCH-CONTEXT-03.  It
        is intentionally unsupported in this behavior-preserving stage so a
        caller cannot accidentally believe that history was consumed.
        """

        if conversation_context is not None:
            raise NotImplementedError(
                "conversation_context is unsupported until ARCH-CONTEXT-03"
            )

        requirement = route_engineering_evidence_requirement(user_input)
        return self._execution_adapter.run(
            user_input,
            evidence_requirement=requirement,
            trace_sink=trace_sink,
            activity_sink=activity_sink,
        )


__all__ = [
    "LegacyToolAgentExecutionAdapter",
    "UnifiedEngineeringRuntime",
]
