"""Unified Runtime evidence-planning component.

The G3 QueryPlan and Planner contracts remain the source of truth.  This
module only places an existing BaseQueryPlanner behind the Unified Engineering
Runtime boundary; it does not copy schemas or execute a plan.
"""

from __future__ import annotations

from core.query_planning import BaseQueryPlanner, PlannerOutcome


class EngineeringEvidencePlanner:
    """Form one trusted G3 PlannerOutcome for one resolved input."""

    def __init__(self, planner: BaseQueryPlanner) -> None:
        if not isinstance(planner, BaseQueryPlanner):
            raise TypeError("planner must be a BaseQueryPlanner")
        self._planner = planner

    def plan(self, resolved_input: str) -> PlannerOutcome:
        """Delegate exactly once and return the original validated outcome."""

        outcome = self._planner.plan(resolved_input)
        if not isinstance(outcome, PlannerOutcome):
            raise TypeError("planner.plan must return PlannerOutcome")
        if outcome.plan.original_query != resolved_input:
            raise ValueError(
                "PlannerOutcome.plan.original_query must equal resolved_input"
            )
        return outcome


__all__ = ["EngineeringEvidencePlanner"]
