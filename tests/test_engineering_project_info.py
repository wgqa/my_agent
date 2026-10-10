"""R02: host project facts through the existing, bounded Tool chain."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from core.query_planning.prompt import (
    ENGINEERING_PROJECT_INFO_PLANNER_PROMPT_VERSION,
    ENGINEERING_REFERENCE_PLANNER_SYSTEM_PROMPT,
    ENGINEERING_PROJECT_INFO_PLANNER_SYSTEM_PROMPT,
    build_planner_messages,
)
from core.engineering_requirements import (
    CHANGE_TEST_V1, PROJECT_CODE_V1, PROJECT_DOC_V1, PROJECT_TEST_V1,
    route_engineering_evidence_requirement,
)
from core.tool_agent.action_parser import parse_agent_action_text
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.activity import build_tool_activity_event
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_CURRENT_REQUEST_PROFILE,
    ENGINEERING_DECISION_PROMPT_PROJECT_INFO_PROFILE,
    compute_toolset_sha256, max_output_tokens_for_profile, max_parse_repairs_for_profile,
)
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import (
    INVALID_TOOL_ARGUMENTS, TOOL_BUDGET_EXCEEDED, TOOL_PERMISSION_DENIED, ToolCall,
)
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import INSUFFICIENT_EVIDENCE_TO_FINALIZE, ToolAgentBudget
from core.tool_agent.tools.project_info import ProjectBinding
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime


def registry_for(root):
    return build_readonly_tool_registry(
        root, EmptyRetrievalPort(), read_project_context_version=READ_PROJECT_TARGETS_VERSION,
        project_binding=ProjectBinding(root.resolve(), root.name, "configured"),
    )


class BindingDecisions:
    """Use the real tool result, with no per-conversation state on the provider."""

    def decide(self, registry, question, *, context=(), control_state=None):
        observed = next((item for item in reversed(context)
                         if item.tool_name == "get_project_info"), None)
        if observed is None:
            action = ToolCallAction(action="tool_call", tool_name="get_project_info", arguments={})
        else:
            facts = observed.observation_result
            action = FinalAnswerAction("final_answer", f"当前项目 {facts['project_name']} 绑定在 {facts['root']}。")
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def test_binding_returns_exact_chinese_space_path_and_live_availability(tmp_path):
    root = tmp_path / "中文 空格 项目"
    root.mkdir()
    registry = registry_for(root)
    executor = ToolExecutor(registry)
    result = executor.execute(ToolCall.create("get_project_info", {}))
    assert result.status == "ok"
    assert result.result == {
        "project_name": root.name, "root": str(root.resolve()),
        "source": "configured", "available": True,
    }
    root.rmdir()
    unavailable = executor.execute(ToolCall.create("get_project_info", {}))
    assert unavailable.status == "ok"
    assert unavailable.result == {**result.result, "available": False}


@pytest.mark.parametrize("field", ["root", "path", "project_id"])
def test_parser_and_executor_both_reject_model_selected_binding(tmp_path, field):
    registry = registry_for(tmp_path)
    arguments = {field: "another-project"}
    action, failure = parse_agent_action_text(json.dumps({
        "action": "tool_call", "tool_name": "get_project_info", "arguments": arguments,
    }), registry)
    assert action is None
    assert failure is not None
    result = ToolExecutor(registry).execute(ToolCall.create("get_project_info", arguments))
    assert result.error_code == INVALID_TOOL_ARGUMENTS
    assert result.result is None


def test_binding_cannot_bypass_permissions_or_tool_budget(tmp_path):
    registry = registry_for(tmp_path)
    call = ToolCall.create("get_project_info", {})
    assert ToolExecutor(registry, allowed_tools=frozenset()).execute(call).error_code == TOOL_PERMISSION_DENIED
    assert ToolExecutor(registry).execute(call, tool_call_allowed=False).error_code == TOOL_BUDGET_EXCEEDED


def test_registry_rejects_binding_from_a_different_root(tmp_path):
    with pytest.raises(ValueError, match="must match repo_root"):
        build_readonly_tool_registry(
            tmp_path, EmptyRetrievalPort(),
            project_binding=ProjectBinding(tmp_path / "other", "other", "configured"),
        )


def test_legacy_tool_set_stays_frozen_and_new_spec_contains_no_bound_path(tmp_path):
    before = build_readonly_tool_registry(
        tmp_path, EmptyRetrievalPort(), read_project_context_version=READ_PROJECT_TARGETS_VERSION,
    )
    after = registry_for(tmp_path)
    assert len(before) == 7
    assert len(after) == 8
    assert "get_project_info" not in before
    assert compute_toolset_sha256(before.list_specs()) != compute_toolset_sha256(after.list_specs())
    assert compute_toolset_sha256(after.without(frozenset({"get_project_info"})).list_specs()) == compute_toolset_sha256(before.list_specs())
    assert str(tmp_path) not in json.dumps(after.get_spec("get_project_info").to_dict())
    binding = after.resolve("get_project_info").handler._binding
    with pytest.raises(FrozenInstanceError):
        binding.root = tmp_path / "other"


def test_selected_binding_completes_inside_existing_budget_without_fake_evidence(tmp_path):
    runtime = build_full_unified_runtime(ToolAgentRuntime(
        registry=registry_for(tmp_path), provider=BindingDecisions(),
    ))
    result = runtime.run("目前咱们的系统绑定的哪个项目目录")
    assert result.status == "completed"
    assert str(tmp_path.resolve()) in result.answer
    assert (result.iterations_used, result.tool_calls_used, result.tool_errors_used) == (2, 1, 0)
    assert result.evidence == ()
    assert "[E" not in result.answer
    assert not any(event.event_type == "evidence_added" for event in result.trace)


@pytest.mark.parametrize("question,profile", [
    ("请查看当前项目源码 config.py 的默认配置实现", PROJECT_CODE_V1),
    ("请阅读当前项目 README.md 文档", PROJECT_DOC_V1),
    ("请阅读当前项目测试文件 tests/test_config.py 的断言", PROJECT_TEST_V1),
    ("请检查当前代码变更影响的测试", CHANGE_TEST_V1),
])
def test_project_metadata_cannot_satisfy_actual_content_evidence(tmp_path, question, profile):
    assert route_engineering_evidence_requirement(question).requirement_profile == profile
    runtime = build_full_unified_runtime(ToolAgentRuntime(
        registry=registry_for(tmp_path), provider=BindingDecisions(),
    ))
    result = runtime.run(question)
    assert result.status == "refused"
    assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
    assert result.answer is None
    assert result.evidence == ()
    assert result.tool_calls_used == 1
    assert result.iterations_used <= 5


def test_same_named_projects_are_isolated_when_metadata_calls_run_concurrently(tmp_path):
    roots = (tmp_path / "a" / "same", tmp_path / "b" / "same")
    for root in roots:
        root.mkdir(parents=True)
    executors = [ToolExecutor(registry_for(root)) for root in roots]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda index: executors[index % 2].execute(
            ToolCall.create("get_project_info", {})), range(8)))
    assert [result.result["root"] for result in results] == [str(roots[index % 2].resolve()) for index in range(8)]


def test_activity_keeps_availability_without_copying_absolute_root(tmp_path):
    observation = ToolExecutor(registry_for(tmp_path)).execute(ToolCall.create("get_project_info", {}))
    payload = build_tool_activity_event(
        activity_id="A1", iteration=1, tool_name="get_project_info", state="completed",
        arguments={}, observation=observation,
    ).to_dict()
    assert payload["result_summary"] == {"available": True}
    assert payload.get("target", {}) == {}
    assert payload.get("evidence_ids_added", []) == []
    assert str(tmp_path) not in json.dumps(payload)


def test_project_info_profiles_extend_r01_and_keep_existing_transport_caps():
    profile = ENGINEERING_DECISION_PROMPT_PROJECT_INFO_PROFILE
    assert profile.template.startswith(ENGINEERING_DECISION_PROMPT_CURRENT_REQUEST_PROFILE.template)
    assert profile.sha256 != ENGINEERING_DECISION_PROMPT_CURRENT_REQUEST_PROFILE.sha256
    assert max_output_tokens_for_profile(profile) == 1200
    assert max_parse_repairs_for_profile(profile) == 1
    budget = ToolAgentBudget()
    assert (budget.max_agent_iterations, budget.max_tool_calls, budget.max_tool_errors) == (5, 4, 2)
    assert ENGINEERING_PROJECT_INFO_PLANNER_SYSTEM_PROMPT.startswith(ENGINEERING_REFERENCE_PLANNER_SYSTEM_PROMPT)
    query = '{"current_request":"当前绑定在哪？","reference_context":"old project"}'
    messages = build_planner_messages(query, prompt_version=ENGINEERING_PROJECT_INFO_PLANNER_PROMPT_VERSION)
    assert messages[0]["content"] == ENGINEERING_PROJECT_INFO_PLANNER_SYSTEM_PROMPT
    assert json.loads(messages[1]["content"])["original_query"] == query
