"""Thin product entry adapter for the unified Engineering Agent.

The ToolAgentRuntime remains the only Decision -> Tool -> Observation loop.
This facade only gives the product API a stable boundary for future evolution.
"""

from __future__ import annotations

from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import ToolAgentRunResult


class EngineeringAgentFacade:
    """Expose the existing bounded Tool Agent as the engineering product entry."""

    def __init__(self, runtime: ToolAgentRuntime) -> None:
        if not isinstance(runtime, ToolAgentRuntime):
            raise TypeError("runtime 必须是 ToolAgentRuntime")
        self._runtime = runtime

    def run(self, question: str) -> ToolAgentRunResult:
        """Delegate to ToolAgentRuntime without implementing a second loop."""

        return self._runtime.run(question)


__all__ = ["EngineeringAgentFacade"]
