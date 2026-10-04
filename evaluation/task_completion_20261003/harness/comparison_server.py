"""Profile-only diagnostic over the current production assembly."""

import os

import api.app as application
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_TASK_COMPLETION_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE,
)

ARM = os.environ["COMPLETION_ARM"]
if ARM not in {"baseline", "candidate"}:
    raise ValueError("Unknown diagnostic arm")
application.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE = (
    ENGINEERING_DECISION_PROMPT_TASK_COMPLETION_PROFILE
    if ARM == "candidate"
    else ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE
)

from evaluation.source_search_v6_20261003.harness import passive_observer as observer
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider

app = observer.app
original_execute = ToolExecutor.execute


def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    if call.tool_name in {"code_search", "read_project_context"}:
        observer.write(
            "source_search" if call.tool_name == "code_search" else "source_read",
            {
                "arguments": call.arguments_copy(),
                "status": result.status,
                "error_code": result.error_code,
                "result": result.result,
            },
        )
    return result


ToolExecutor.execute = execute
original_decide = OpenAICompatibleAgentDecisionProvider.decide


def decide(self, *args, **kwargs):
    outcome = original_decide(self, *args, **kwargs)
    state = kwargs.get("control_state")
    observer.write("decision_metadata", {
        "metadata": outcome.call_metadata.to_dict() if outcome.call_metadata else None,
        "failure_code": outcome.failure_code,
        "selected_action": outcome.action.action if outcome.action else None,
        "control_state": state.to_dict(include_evidence_reference_control=True) if state else None,
    })
    return outcome


OpenAICompatibleAgentDecisionProvider.decide = decide
