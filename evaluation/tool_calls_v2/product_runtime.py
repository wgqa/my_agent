"""Reuse the actual product assembly; scripted mode explicitly replaces models."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


def build_evaluation_registry(project_root: Path, retrieval_port):
    """Mirror the current product's bound, enabled tool identities."""
    from core.tool_agent.default_tools import build_readonly_tool_registry
    from core.tool_agent.tools.code_search import CODE_SEARCH_TEST_VERSION
    from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
    from core.tool_agent.tools.project_info import ProjectBinding, PROJECT_INFO_DOCUMENTATION_VERSION

    return build_readonly_tool_registry(
        project_root, retrieval_port, code_search_version=CODE_SEARCH_TEST_VERSION,
        read_project_context_version=READ_PROJECT_TARGETS_VERSION,
        project_binding=ProjectBinding(project_root, project_root.name, "configured"),
        project_info_version=PROJECT_INFO_DOCUMENTATION_VERSION,
    )


def build_product_runtime(project_root: Path, library, *, scripted_provider=None):
    import api.app as app_module
    from api.project_workspace import EngineeringProject

    project = EngineeringProject(root=project_root.resolve(strict=True), project_name=project_root.name, source="configured")
    with ExitStack() as stack:
        stack.enter_context(patch.object(app_module, "engineering_knowledge_backend", library))
        if scripted_provider is not None:
            from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan

            class NoRetrievalPlanner(BaseQueryPlanner):
                def __init__(self, **kwargs):
                    pass

                def plan(self, original_query):
                    return PlannerOutcome(plan=QueryPlan.create(original_query=original_query,
                        query_type="unanswerable_or_no_retrieval", retrieval_required=False,
                        action="no_retrieval", reason_code="NO_RETRIEVAL_NEEDED"), fallback_used=False, failure_code=None)

            original_builder = app_module.build_tool_agent_runtime

            def scripted_builder(**kwargs):
                return original_builder(**kwargs, provider=scripted_provider)

            stack.enter_context(patch.object(app_module, "build_tool_agent_runtime", scripted_builder))
            stack.enter_context(patch.object(app_module, "OpenAICompatibleQueryPlanner", NoRetrievalPlanner))
            stack.enter_context(patch.object(app_module, "OpenAICompatibleConversationQueryResolver", lambda **kwargs: None))
        # No lifespan, pipeline initialization, server, production DB or registry.
        return app_module._build_engineering_project_runtime(project)


class ScriptedReferenceProvider:
    """An offline wiring probe, never a model-quality measurement."""
    def __init__(self, case: dict):
        self.calls = iter(case["reference_calls"])
        self.status = case["terminal_statuses"][0]
        self.refusal = case["refusal_codes"][0] if case["refusal_codes"] else None

    def decide(self, registry, user_query, *, context=(), control_state=None):
        from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, RefuseAction, ToolCallAction

        step = next(self.calls, None)
        if step is not None:
            action = ToolCallAction(action="tool_call", tool_name=step["tool"], arguments=step["arguments"])
        elif self.status == "refused":
            action = RefuseAction(action="refuse", reason_code=self.refusal)
        else:
            references = " ".join(f"[{ref.evidence_id}]" for ref in (control_state.available_evidence_refs if control_state else ()))
            action = FinalAnswerAction(action="final_answer", answer=f"离线装配检查已取得以下工具材料。{references}")
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)
