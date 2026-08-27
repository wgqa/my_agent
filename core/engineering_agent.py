"""Thin product entry adapter for the unified Engineering Agent.

The ToolAgentRuntime remains the only Decision -> Tool -> Observation loop.
This facade only gives the product API a stable boundary for future evolution.
"""

from __future__ import annotations

from typing import Callable

from core.engineering_requirements import route_engineering_evidence_requirement
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult


class EngineeringAgentFacade:
    """Expose the existing bounded Tool Agent as the engineering product entry."""

    def __init__(self, runtime: ToolAgentRuntime) -> None:
        if not isinstance(runtime, ToolAgentRuntime):
            raise TypeError("runtime 必须是 ToolAgentRuntime")
        self._runtime = runtime

    def run(
        self,
        question: str,
        *,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        """Route once, then delegate the single bounded Runtime loop."""

        requirement = route_engineering_evidence_requirement(question)
        if trace_sink is None:
            return self._runtime.run(
                question,
                evidence_requirement=requirement,
            )
        return self._runtime.run(
            question,
            evidence_requirement=requirement,
            trace_sink=trace_sink,
        )


__all__ = ["EngineeringAgentFacade"]
