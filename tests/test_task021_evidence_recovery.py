"""Scripted SDK + existing Runtime + real isolated Git, never real Provider."""
from types import SimpleNamespace

import pytest

from core.engineering_task_contract import HybridTaskContract
from core.query_planning.prompt import ENGINEERING_TASK_CONTRACT_PLANNER_SYSTEM_PROMPT
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import _recovery_is_feasible
from core.tool_agent.runtime_models import ToolAgentBudget
from core.tool_agent.tools.git_change import GIT_DIFF_SPEC
from tests.test_engineering_task_contract import contract_payload
from tests.test_hybrid_task_contract_runtime import (
    BASE, HEAD, GIT_ARGS, git_fixture, run_hybrid, call, final,
)
from tests.test_tool_agent_changed_files_typed_finalization import _observation


QUESTION = f"结合 {BASE} 到 {HEAD} 的变更，判断哪项最重要并说明依据"
REFUSE = dict(action="refuse", reason_code="INSUFFICIENT_INFORMATION")


def analysis_contract(**kwargs):
    return contract_payload(**(dict(operation="change_analysis", requires_complete_list=False,
        scope_mode="commit_range", base_ref=BASE, head_ref=HEAD) | kwargs))


def test_planner_has_one_unambiguous_six_field_contract_and_no_retrieval_combination():
    prompt = ENGINEERING_TASK_CONTRACT_PLANNER_SYSTEM_PROMPT
    assert "输出 JSON 必须恰好包含以下五个字段" not in prompt
    assert "所有任务均须输出 task_contract" in prompt
    assert "query_type=unanswerable_or_no_retrieval、retrieval_required=false、action=no_retrieval" in prompt
    assert "询问最重要的变更不等于要求穷举全部实现" in prompt


@pytest.mark.parametrize("premature", [final("仅有状态列表，目前不能分析重要性 [E1]"), REFUSE])
def test_early_terminal_gets_one_real_diff_acquisition_opportunity(git_fixture, premature):
    result, sdk = run_hybrid(QUESTION, analysis_contract(), [
        call("changed_files", GIT_ARGS), premature,
        call("git_diff", GIT_ARGS | dict(path="src/main.py")),
        final("已核查 src/main.py：LIMIT 从 10 改为 12，会改变 scale 输出；未核查其他文件，"
              "不能据此声称完成全范围排名。[E2]"),
    ], root=git_fixture)
    assert result.status == "completed"
    assert result.iterations_used == 4 and result.tool_calls_used == 2
    assert len(sdk.requests) == 5  # original Planner + 4 Decisions, no new loop
    blocked = [event for event in result.trace if event.event_type == "finalization_guard_blocked"]
    assert len(blocked) == 1 and blocked[0].error_code == "REQUIRED_DIFF_MISSING"
    next_system = "\n".join(m["content"] for m in sdk.requests[3]["messages"] if m["role"] == "system")
    assert '"task_contract_recovery_attempted": true' in next_system
    assert "REQUIRED_DIFF_MISSING" in next_system and "git_diff" in next_system


def test_agent_can_choose_multiple_paths_then_finish_without_useless_calls(git_fixture):
    result, sdk = run_hybrid(QUESTION, analysis_contract(), [
        call("changed_files", GIT_ARGS),
        call("git_diff", GIT_ARGS | dict(path="src/main.py")),
        call("git_diff", GIT_ARGS | dict(path="tests/test_main.py")),
        final("在已核查的两个 diff 中，main.py 改变倍率，test_main.py 同步更新断言。"
              "该比较只限已核查范围，不代表其他文件已审查。[E2][E3]"),
    ], root=git_fixture)
    assert result.status == "completed" and result.tool_calls_used == 3
    assert len(sdk.requests) == 5
    assert not any(event.event_type == "finalization_guard_blocked" for event in result.trace)
    assert all(item.tool_name == "git_diff" for item in result.evidence if item.granularity == "diff")


def test_repeated_refusal_does_not_get_another_recovery(git_fixture):
    result, sdk = run_hybrid(QUESTION, analysis_contract(),
        [call("changed_files", GIT_ARGS), REFUSE, REFUSE], root=git_fixture)
    assert result.status == "refused" and result.answer is None
    assert len(sdk.requests) == 4 and result.tool_calls_used == 1
    assert result.trace[-1].error_code == "REQUIRED_DIFF_MISSING"
    assert sum(event.event_type == "finalization_guard_blocked" for event in result.trace) == 1


@pytest.mark.parametrize("reason", ["UNSAFE_REQUEST", "UNSUPPORTED_REQUEST"])
def test_no_recovery_for_safety_or_unsupported_refusal(git_fixture, reason):
    result, sdk = run_hybrid(QUESTION, analysis_contract(), [
        call("changed_files", GIT_ARGS), dict(action="refuse", reason_code=reason),
    ], root=git_fixture)
    assert result.status == "refused" and result.reason_code == reason
    assert len(sdk.requests) == 3


def test_missing_diff_tool_does_not_get_an_extra_model_call():
    result, sdk = run_hybrid("分析当前工作区哪些变更最重要", contract_payload(
        operation="change_analysis", requires_complete_list=False),
        [call("changed_files", dict(mode="working_tree")), final("状态足以证明重要性 [E1]")],
        observation=_observation([dict(path="src/main.py", status="modified")]))
    assert result.status == "refused" and result.answer is None
    assert result.trace[-1].error_code == "REQUIRED_DIFF_MISSING" and len(sdk.requests) == 3


def test_recovery_requires_room_for_a_tool_decision_and_a_final_decision():
    registry = ToolRegistry()
    registry.register(GIT_DIFF_SPEC, SimpleNamespace(execute=lambda arguments: None))
    requirement = HybridTaskContract.from_dict(analysis_contract(), user_request=QUESTION).to_requirement(
        SimpleNamespace(required_evidence_groups=(), min_distinct_project_code_paths=0))
    state = SimpleNamespace(missing_evidence_groups=(("project_change",),),
                            distinct_project_code_paths=0, required_min_distinct_project_code_paths=0)
    contract = HybridTaskContract.from_dict(analysis_contract(), user_request=QUESTION)
    assert _recovery_is_feasible(registry, requirement, state, iterations=3, tool_calls=1,
        tool_errors=0, budget=ToolAgentBudget(), task_contract=contract)
    for changes in (dict(iterations=4), dict(tool_calls=4), dict(tool_errors=2)):
        params = dict(iterations=3, tool_calls=1, tool_errors=0) | changes
        assert not _recovery_is_feasible(registry, requirement, state, **params,
            budget=ToolAgentBudget(), task_contract=contract)


def test_status_list_and_partial_diff_never_satisfy_diff_obligation():
    contract = HybridTaskContract.from_dict(analysis_contract(), user_request=QUESTION)
    assert contract.material_error([SimpleNamespace(granularity="status_list", completeness="complete")]) == "REQUIRED_DIFF_MISSING"
    assert contract.material_error([SimpleNamespace(granularity="diff", completeness="partial")]) == "REQUIRED_DIFF_MISSING"


def test_explicit_full_scope_remains_blocked_after_bounded_recovery(git_fixture):
    question = f"完整分析 {BASE} 到 {HEAD} 之间全部变更的影响"
    # Even a model-supplied false flag cannot cancel explicit full coverage.
    result, _ = run_hybrid(question, analysis_contract(), [
        call("changed_files", GIT_ARGS),
        call("git_diff", GIT_ARGS | dict(path="src/main.py")),
        final("我已全面分析全部变更 [E2]"),
        call("git_diff", GIT_ARGS | dict(path="tests/test_main.py")),
        final("两个 diff 证明整个提交无风险 [E2][E3]"),
    ], root=git_fixture)
    assert result.task_contract.requires_complete_list is True
    assert result.status == "refused" and result.answer is None
    assert result.trace[-1].error_code == "CHANGE_SCOPE_INCOMPLETE"
    assert result.iterations_used == 5 and result.tool_calls_used == 3


def test_ready_source_answer_is_not_forced_into_git_acquisition(git_fixture):
    from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
    result, sdk = run_hybrid("解释 src/main.py 中 scale 函数的实现", contract_payload(
        operation="source_read", object_kind="function", scope_mode="project",
        target_paths=["src/main.py"], target_symbols=["scale"]), [
        call("read_project_context", dict(path="src/main.py", target=dict(kind="file", start_line=1))),
        final("scale(value) 返回 value * LIMIT；同文件 LIMIT = 12，因此输入乘以 12。[E1]"),
    ], root=git_fixture, reader_version=READ_PROJECT_TARGETS_VERSION)
    assert result.status == "completed" and result.tool_calls_used == 1 and len(sdk.requests) == 3


def test_wrong_reference_is_not_recovered_or_published(git_fixture):
    result, sdk = run_hybrid(QUESTION, analysis_contract(), [
        call("git_diff", GIT_ARGS | dict(path="src/main.py")),
        final("main.py 的变化见 [E99]"),
    ], root=git_fixture)
    assert result.status == "refused" and result.answer is None
    assert result.trace[-1].error_code == "INVALID_CURRENT_RUN_EVIDENCE_REFERENCE"
    assert len(sdk.requests) == 3
