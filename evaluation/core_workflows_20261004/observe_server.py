"""Passive current-app observation, with an explicit development-only arm."""

import os
from pathlib import Path
import sys
import types


def snapshot_module(name, directory, filename):
    """Load an archived experiment only in this isolated evaluation process."""
    path = Path(__file__).with_name(directory) / filename
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


prompt_candidate = os.environ.get("CORE_WORKFLOW_CANDIDATE") == "1"
reader_candidate = os.environ.get("CORE_WORKFLOW_READER_CANDIDATE") == "1"
planner_candidate = os.environ.get("CORE_WORKFLOW_PLANNER_CANDIDATE") == "1"
if sum((prompt_candidate, reader_candidate, planner_candidate)) > 1:
    raise ValueError("Only one experimental arm may be selected")
if prompt_candidate:
    prompts = snapshot_module("_workflow_prompt_candidate", "prompt_candidate", "decision_prompt.snapshot")
if reader_candidate:
    reader = snapshot_module("_workflow_reader_candidate", "reader_candidate", "read_project_context.snapshot")
if planner_candidate:
    planner_prompts = snapshot_module("_workflow_planner_candidate", "planner_candidate", "prompt.snapshot")

import api.app as application

if prompt_candidate:
    import core.tool_agent.decision_prompt as current_prompts
    profile = prompts.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V3_PROFILE
    application.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE = current_prompts.DecisionPromptProfile(
        version=profile.version, sha256=profile.sha256, template=profile.template,
        render_control_state=True, render_evidence_reference_control=True,
    )
    current_prompts.ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS |= {profile.version}
    current_prompts.ENGINEERING_OUTPUT_CAP_PROFILE_VERSIONS |= {profile.version}
if reader_candidate:
    import core.tool_agent.integration as integration
    from core.tool_agent.registry import ToolRegistry
    original_builder = application.build_tool_agent_runtime
    original_registry_factory = integration.build_readonly_tool_registry

    def reader_registry(*args, **kwargs):
        original = original_registry_factory(*args, **kwargs)
        root = args[0] if args else kwargs["repo_root"]
        registry = ToolRegistry()
        for spec in original.list_specs():
            handler = original.resolve(spec.name).handler
            if spec.name == "read_project_context":
                spec = reader.READ_PROJECT_CONTEXT_DIRECT_SPEC
                handler = reader.ReadProjectContextHandler(root)
            registry.register(spec, handler)
        return registry

    def build_runtime(**kwargs):
        if kwargs.get("prompt_profile") is not None:
            integration.build_readonly_tool_registry = reader_registry
        try:
            return original_builder(**kwargs)
        finally:
            integration.build_readonly_tool_registry = original_registry_factory

    application.build_tool_agent_runtime = build_runtime
if planner_candidate:
    import core.query_planning.prompt as current_planner_prompts
    version = planner_prompts.ENGINEERING_KNOWLEDGE_PLANNER_PROMPT_VERSION
    current_planner_prompts._PROMPTS[version] = planner_prompts._PROMPTS[version]
    application.ENGINEERING_PLANNER_PROMPT_VERSION = version

# Historical arms retain their recorded Reader/prompt pair after the main
# application promotes the later object Reader. This stays evaluation-only.
if prompt_candidate or reader_candidate or planner_candidate:
    from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE
    from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_VERSION
    archived_builder = application.build_tool_agent_runtime

    def build_archived_runtime(**kwargs):
        if kwargs.get("prompt_profile") is not None:
            kwargs["prompt_profile"] = (
                application.ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE
                if prompt_candidate else ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE
            )
            kwargs["read_project_context_version"] = READ_PROJECT_CONTEXT_VERSION
        return archived_builder(**kwargs)

    application.build_tool_agent_runtime = build_archived_runtime

from evaluation.source_search_v6_20261003.harness import passive_observer as observer
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider

app = observer.app
original_execute = ToolExecutor.execute
original_decide = OpenAICompatibleAgentDecisionProvider.decide


def execute(self, call, tool_call_allowed=True):
    result = original_execute(self, call, tool_call_allowed)
    observer.write("tool_result", {
        "tool": call.tool_name, "arguments": call.arguments_copy(),
        "status": result.status, "error_code": result.error_code,
        "result": result.result,
    })
    if call.tool_name in {"code_search", "read_project_context"}:
        observer.write("source_search" if call.tool_name == "code_search" else "source_read", {
            "arguments": call.arguments_copy(), "status": result.status,
            "error_code": result.error_code, "result": result.result,
        })
    return result


def decide(self, *args, **kwargs):
    result = original_decide(self, *args, **kwargs)
    observer.write("decision_metadata", {
        "metadata": result.call_metadata.to_dict() if result.call_metadata else None,
        "failure_code": result.failure_code,
        "selected_action": result.action.action if result.action else None,
    })
    return result


ToolExecutor.execute = execute
OpenAICompatibleAgentDecisionProvider.decide = decide
