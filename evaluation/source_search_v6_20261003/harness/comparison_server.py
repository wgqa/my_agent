"""One frozen search variant per process over the unchanged production app."""
import importlib.util
import os
from pathlib import Path
import sys
import types

import core.tool_agent.default_tools as defaults

snapshot = Path(os.environ["SEARCH_SNAPSHOT"])
variant = types.ModuleType("search_comparison_variant")
sys.modules[variant.__name__] = variant
exec(compile(snapshot.read_text(encoding="utf-8"), str(snapshot), "exec"), variant.__dict__)
defaults.CODE_SEARCH_SPEC = variant.CODE_SEARCH_SPEC
defaults.CodeSearchHandler = variant.CodeSearchHandler

spec = importlib.util.spec_from_file_location("search_observers", Path(__file__).with_name("passive_observer.py"))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
app = observer.app

from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider

original_execute = ToolExecutor.execute


def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    if call.tool_name in {"code_search", "read_project_context"}:
        observer.write("source_search" if call.tool_name == "code_search" else "source_read", {
            "arguments": call.arguments_copy(), "status": result.status,
            "error_code": result.error_code, "result": result.result,
        })
    return result


ToolExecutor.execute = execute
original_decide = OpenAICompatibleAgentDecisionProvider.decide


def decide(self, *args, **kwargs):
    outcome = original_decide(self, *args, **kwargs)
    observer.write("decision_metadata", {
        "metadata": outcome.call_metadata.to_dict() if outcome.call_metadata else None,
        "failure_code": outcome.failure_code,
    })
    return outcome


OpenAICompatibleAgentDecisionProvider.decide = decide
