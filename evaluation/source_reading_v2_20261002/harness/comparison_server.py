"""One reader variant per process; passive observations over the real app."""
import importlib.util
import os
from pathlib import Path
import sys
import types

if os.environ.get("READER_NAVIGATION_SNAPSHOT"):
    navigation_path = Path(os.environ["READER_NAVIGATION_SNAPSHOT"])
    navigation = types.ModuleType("core.tool_agent.tools.source_navigation")
    sys.modules[navigation.__name__] = navigation
    exec(compile(navigation_path.read_text(encoding="utf-8"), str(navigation_path), "exec"), navigation.__dict__)

import core.tool_agent.default_tools as defaults

snapshot_variable = "READER_BASELINE_SNAPSHOT" if os.environ["READER_ARM"] == "v1" else "READER_CANDIDATE_SNAPSHOT"
if os.environ.get(snapshot_variable):
    snapshot = Path(os.environ[snapshot_variable])
    baseline = types.ModuleType("reader_baseline")
    sys.modules[baseline.__name__] = baseline
    exec(compile(snapshot.read_text(encoding="utf-8"), str(snapshot), "exec"), baseline.__dict__)
    defaults.READ_PROJECT_CONTEXT_SPEC = baseline.READ_PROJECT_CONTEXT_SPEC
    defaults.ReadProjectContextHandler = baseline.ReadProjectContextHandler

observer_path = Path(os.environ["READER_OBSERVER_SOURCE"])
spec = importlib.util.spec_from_file_location("reader_observers", observer_path)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
app = observer.app

from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider

original_execute = ToolExecutor.execute
def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    if call.tool_name == "read_project_context" and result.status == "ok":
        observer.write("source_read", {"arguments": call.arguments_copy(), "result": result.result,
            "characters": len("\n".join(item["text"] for item in result.result["lines"]))})
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
