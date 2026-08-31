"""Thin API/product adapter for the unified Engineering Agent Runtime."""

from __future__ import annotations

from typing import Callable

from core.tool_agent.activity import ActivityEvent
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult
from core.unified_engineering_runtime import UnifiedEngineeringRuntime


class EngineeringAgentFacade:
    """Expose UnifiedEngineeringRuntime at the product/API boundary."""

    def __init__(self, runtime: UnifiedEngineeringRuntime) -> None:
        if not isinstance(runtime, UnifiedEngineeringRuntime):
            raise TypeError("runtime 必须是 UnifiedEngineeringRuntime")
        self._runtime = runtime

    def run(
        self,
        question: str,
        *,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        """Forward the request and observers without owning control logic."""

        kwargs = {}
        if trace_sink is not None:
            kwargs["trace_sink"] = trace_sink
        if activity_sink is not None:
            kwargs["activity_sink"] = activity_sink
        return self._runtime.run(
            question,
            **kwargs,
        )


__all__ = ["EngineeringAgentFacade"]
