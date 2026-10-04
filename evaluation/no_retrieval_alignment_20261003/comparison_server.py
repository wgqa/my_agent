"""Production assembly; the two arms differ only in Engineering planner prompt."""

import os

import api.app as application
from core.query_planning.prompt import (
    ENGINEERING_PLANNER_PROMPT_VERSION, PLANNER_PROMPT_VERSION,
)

arm = os.environ["PLANNER_ALIGNMENT_ARM"]
if arm not in {"baseline", "candidate"}:
    raise ValueError("Unknown planner alignment arm")
application.ENGINEERING_PLANNER_PROMPT_VERSION = (
    PLANNER_PROMPT_VERSION if arm == "baseline" else ENGINEERING_PLANNER_PROMPT_VERSION
)

from evaluation.source_search_v6_20261003.harness import passive_observer as observer
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider

app = observer.app
original_execute = ToolExecutor.execute


def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    if call.tool_name in {"code_search", "read_project_context", "calculator"}:
        observer.write("tool_result", {
            "tool": call.tool_name, "arguments": call.arguments_copy(),
            "status": result.status, "error_code": result.error_code, "result": result.result,
        })
    return result


ToolExecutor.execute = execute
original_decide = OpenAICompatibleAgentDecisionProvider.decide


def decide(self, *args, **kwargs):
    result = original_decide(self, *args, **kwargs)
    observer.write("decision_metadata", {
        "metadata": result.call_metadata.to_dict() if result.call_metadata else None,
        "failure_code": result.failure_code,
        "selected_action": result.action.action if result.action else None,
    })
    return result


OpenAICompatibleAgentDecisionProvider.decide = decide
