"""Passive observations plus explicit, isolated object Reader development arm."""

import os

from evaluation.core_workflows_20261004.observe_server import app, application

if os.environ.get("CORE_WORKFLOW_OBJECT_READER") == "1":
    from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE
    from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
    original_builder = application.build_tool_agent_runtime

    def build_runtime(**kwargs):
        if kwargs.get("prompt_profile") is not None:
            kwargs["prompt_profile"] = ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE
            kwargs["read_project_context_version"] = READ_PROJECT_TARGETS_VERSION
        return original_builder(**kwargs)

    application.build_tool_agent_runtime = build_runtime
