"""Offline: the real Unified/Tool Runtime, fake SDK and actual Git/Reader tools."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
from core.query_planning.prompt import ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION
from core.tool_agent.integration import build_tool_agent_runtime
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime, _lightweight_open_answer_check
from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from tests._engineering_runtime_support import EmptyRetrievalPort, StaticKnowledgeRetrievalPort, build_full_unified_runtime
from tests.test_hybrid_task_contract_runtime import FakeSDK, call, typed, final, BASE, HEAD, GIT_ARGS
from tests.test_tool_agent_changed_files_typed_finalization import StaticChangedFilesHandler, _observation

ROOT = Path(__file__).resolve().parents[2] / "_task018_e2e_fixtures" / "commit_range"
PLAN = dict(query_type="unanswerable_or_no_retrieval", action="no_retrieval",
            retrieval_strategy="none", subqueries=[], reason_code="NO_RETRIEVAL_NEEDED")


def run(question, decisions, *, plan=None, observation=None, port=None):
    sdk = FakeSDK([PLAN if plan is None else plan, *decisions])
    planner = OpenAICompatibleQueryPlanner(provider="fake", model="deepseek-flash",
        api_key="fake-offline", client=sdk, prompt_version=ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION)
    provider = OpenAICompatibleAgentDecisionProvider(provider="fake", model="deepseek-flash",
        api_key="fake-offline", client=sdk, max_parse_repairs=0)
    port = port or EmptyRetrievalPort()
    if observation is None:
        runtime = build_tool_agent_runtime(repo_root=ROOT, retrieval_port=port, provider=provider,
            read_project_context_version=READ_PROJECT_TARGETS_VERSION)
    else:
        registry = ToolRegistry()
        registry.register(CHANGED_FILES_SPEC, StaticChangedFilesHandler(observation))
        runtime = ToolAgentRuntime(registry=registry, provider=provider)
    unified = build_full_unified_runtime(runtime, planner=planner, retrieval_port=port,
                                        finalization_strategy="converged_hybrid")
    return unified.run(question), sdk


def read(path):
    return call("read_project_context", {"path": path, "target": {"kind": "file", "start_line": 1}})


@pytest.mark.parametrize("plan", [PLAN, {**PLAN, "task_contract": None},
    {**PLAN, "task_contract": {"operation": "nonsense"}},
    {**PLAN, "query_type": "causal"}, {"unexpected": True}])
def test_bad_or_absent_contract_never_stops_tool_loop(plan):
    result, sdk = run(f"列出 {BASE} 到 {HEAD} 全部变更文件及状态",
                     [call("changed_files", GIT_ARGS), typed()], plan=plan)
    assert result.can_finalize and result.task_contract is None
    assert result.task_coverage == "complete" and result.tool_calls_used == 1
    assert len(sdk.requests) == 3 and result.execution.selector_llm_calls == 0
    assert "task_contract" not in sdk.requests[0]["messages"][0]["content"]


@pytest.mark.parametrize("status,term,expected", [
    ("deleted", "已删除的源码", "src/retired_source.py"),
    ("modified", "已修改", "src/main.py"), ("added", "新增", "docs/usage.md"),
    ("renamed", "重命名", "src/old_parser.py"),
])
def test_typed_filters_and_rename_remain_correct(status, term, expected):
    result, _ = run(f"列出 {BASE} 到 {HEAD} {term}文件",
                    [call("changed_files", GIT_ARGS), typed("filter_status", status=status)])
    assert result.can_finalize and expected in result.answer
    assert result.task_coverage == "complete"
    assert result.to_dict()["semantic_correctness"] == "not_evaluated"


@pytest.mark.parametrize("action,args", [
    (typed("filter_status", status="deleted"), GIT_ARGS),
    (typed(evidence_id="E99"), GIT_ARGS),
    (typed(), {"mode": "working_tree"}),
])
def test_typed_cannot_lower_scope_status_or_eid(action, args):
    result, _ = run(f"列出 {BASE} 到 {HEAD} 全部变更文件及状态",
                    [call("changed_files", args), action])
    assert not result.can_finalize and result.answer is None


def test_source_objects_do_not_include_deleted_documents():
    result, _ = run("列出当前工作区已删除的源码文件", [call("changed_files", {"mode": "working_tree"}),
        typed("filter_status", status="deleted")], observation=_observation([
            {"path": "src/old.py", "status": "deleted"}, {"path": "docs/old.md", "status": "deleted"}]))
    assert result.can_finalize and "src/old.py" in result.answer and "docs/old.md" not in result.answer


def test_truncation_delivers_only_explicit_partial_inventory():
    result, _ = run("列出当前工作区全部变更文件", [call("changed_files", {"mode": "working_tree"}), typed()],
                    observation=_observation([{"path": "src/a.py", "status": "modified"}], total=2, truncated=True))
    assert result.can_finalize and result.task_coverage == "partial" and "结果不穷举" in result.answer


def test_full_empty_inventory_is_success_not_missing_data():
    result, _ = run("列出当前工作区全部变更", [call("changed_files", {"mode": "working_tree"}), typed()])
    assert result.can_finalize and "已成功检查" in result.answer and "结果完整" in result.answer


def test_open_analysis_not_forced_to_git_or_test_execution_or_code_count():
    result, _ = run("读取 src/main.py 和 tests/test_main.py，比较源码与测试断言；不需要实际执行测试",
        [read("src/main.py"), read("tests/test_main.py"),
         final("源码 LIMIT=12，scale(2)=24 [E1]，测试断言与之对应，但尚未执行测试 [E2]")])
    assert result.can_finalize and result.tool_calls_used == 2 and result.task_coverage == "unknown"


def test_doc_and_code_keep_their_own_source_kinds():
    result, _ = run("读取 docs/usage.md 与 src/main.py，说明关系", [read("docs/usage.md"), read("src/main.py"),
        final("文档说明用 scale [E1]，当前代码返回 value * LIMIT [E2]")])
    assert result.can_finalize and {e.kind for e in result.evidence} == {"project_doc", "project_code"}


def test_premature_answer_gets_one_original_loop_acquisition_opportunity():
    result, sdk = run("读取 src/main.py，解释实现", [final("实现未知"), read("src/main.py"),
                    final("返回 value * LIMIT；LIMIT=12 [E1]")])
    assert result.can_finalize and len(sdk.requests) == 4
    assert sum(e.event_type == "finalization_guard_blocked" for e in result.trace) == 1


def test_locator_cannot_replace_explicit_source_read():
    result, _ = run("读取 src/main.py，解释源码实现", [call("code_search", {"query": "scale"}),
        final("定位行不是完整实现 [E1]"), final("定位行不是完整实现 [E1]")])
    assert not result.can_finalize and result.answer is None


def test_requested_diff_not_satisfied_by_status_list():
    result, _ = run(f"读取 {BASE} 到 {HEAD} src/main.py 的 diff",
        [call("changed_files", GIT_ARGS), final("状态不是 diff [E1]"), final("状态不是 diff [E1]")])
    assert not result.can_finalize


def test_explicit_partial_is_delivered_not_marked_complete():
    result, _ = run("读取 src/main.py 和 src/missing.py", [read("src/main.py"),
        {**final("已读取的 scale 返回 value * LIMIT [E1]"), "limitations": "未读取 src/missing.py；仅交付 main.py 的材料。"}])
    assert result.can_finalize and result.task_coverage == "partial" and "未完成事项" in result.answer


def test_missing_knowledge_cannot_silently_use_only_code():
    result, _ = run("依据知识资料，并读取 src/main.py", [read("src/main.py"), final("代码事实 [E1]")])
    assert not result.can_finalize


def test_required_knowledge_plan_failure_keeps_actual_retrieval():
    result, _ = run("依据知识资料回答", [final("资料的事实 [E1]")], plan={"bad": True},
                    port=StaticKnowledgeRetrievalPort())
    assert result.can_finalize and any(e.kind == "knowledge" for e in result.evidence)


@pytest.mark.parametrize("answer", ["测试全部通过 [E1]", "已运行 pytest [E1]"])
def test_test_source_never_proves_execution(answer):
    result, _ = run("检查 tests/test_main.py 的源码", [read("tests/test_main.py"), final(answer)])
    assert not result.can_finalize and result.trace[-1].error_code == "TEST_EXECUTION_NOT_VERIFIED"


def test_open_analysis_cannot_be_forced_into_typed_status():
    result, _ = run(f"{BASE} 到 {HEAD} 哪些变更最重要？", [call("changed_files", GIT_ARGS), typed()])
    assert not result.can_finalize


def test_function_header_does_not_prove_complete_implementation():
    result, _ = run("解释 src/main.py 中 scale 函数的源码实现", [call("read_project_context", {
        "path": "src/main.py", "target": {"kind": "window", "line": 3, "context_lines": 0}}),
        final("scale 的全部实现 [E1]")])
    assert not result.can_finalize
    assert result.tool_errors_used == 0


def test_negative_execution_boundary_is_not_a_demand_to_execute_tests():
    result, _ = run("检查 tests/test_main.py 的断言，它为何不能证明测试通过？",
        [read("tests/test_main.py"), final("只有测试源码 [E1]，不能确认 pytest 全部通过；没有执行记录。")])
    assert result.can_finalize


def test_named_git_ref_scope_cannot_be_replaced_by_working_tree():
    result, _ = run("列出 HEAD~2..HEAD 的全部变更文件", [call("changed_files", {"mode": "working_tree"}), typed()])
    assert not result.can_finalize


def test_untracked_filter_uses_real_isolated_fixture():
    from unittest.mock import patch
    with patch(__name__ + ".ROOT", ROOT.parent / "working_tree_untracked"):
        result, _ = run("列出当前工作区 untracked 文件", [call("changed_files", {"mode": "working_tree"}),
            typed("filter_status", status="untracked")])
    assert result.can_finalize and "notes/local_sample.md" in result.answer


def test_source_filter_must_preserve_explicit_path():
    result, _ = run(f"列出 {BASE} 到 {HEAD} src/main.py 的文件状态", [call("changed_files", GIT_ARGS), typed()])
    assert result.can_finalize and "src/main.py" in result.answer and "docs/usage.md" not in result.answer


def test_can_finalize_does_not_mean_semantic_correctness():
    result, _ = run("读取 src/main.py 与 src/missing.py", [read("src/main.py"),
        {**final("LIMIT = 12 [E1]"), "limitations": "尚未读取 missing.py"}])
    assert result.to_dict()["can_finalize"] and result.to_dict()["task_coverage"] == "partial"
    assert result.to_dict()["semantic_correctness"] == "not_evaluated"


def test_open_eid_is_bound_to_actual_source_hash(monkeypatch):
    import core.tool_agent.runtime as mod
    original = mod._evidence_from_tool_result
    calls = 0
    def corrupt(*args):
        nonlocal calls
        calls += 1
        values = original(*args)
        return tuple(replace(item, result_sha256="a" * 64) for item in values) if calls == 1 else values
    monkeypatch.setattr(mod, "_evidence_from_tool_result", corrupt)
    result, _ = run("只定位 scale 的文件行号", [call("code_search", {"query": "scale"}), final("定位 [E1]")])
    assert not result.can_finalize and result.trace[-1].error_code == "CURRENT_RUN_SOURCE_MISMATCH"


def test_existing_live_entry_fake_transport_uses_converged_runtime_only():
    from tests.test_task018_e2e_preflight import _worker
    results = _worker(Path(__file__).resolve().parents[1], "converged", ["case01", "case09", "case08"])
    assert results["live_mode"] is False
    for row in results["results"]:
        assert row["infrastructure_status"] == "ok"
        assert row["final"]["status"] == "completed", row["final"]
        assert row["final"]["task_contract"] is None
        assert row["final"]["semantic_correctness"] == "not_evaluated"
        assert all(request["host"] == "offline.invalid" and request["model"] == "deepseek-flash"
                   and request["thinking"] == {"type": "disabled"} for request in row["provider_requests"])
        assert row["final"]["execution"]["selector_llm_calls"] == 0
    assert results["results"][0]["typed_finalization"][0]["accepted"]


def test_existing_schedule_reuses_frozen_28_questions_and_approved_budget():
    from tests.test_task018_e2e_preflight import _live_runner_module
    runner = _live_runner_module()
    runner.configure_convergence()
    assert len(runner.PLAN) == 28 and {item["variant"] for item in runner.PLAN} == {"converged"}
    assert [item["case_id"] for item in runner.PLAN] == list(runner.TASK022_GROUPS)
    assert (runner.MAX_REQUESTS, runner.MAX_TOKENS, runner.MAX_ESTIMATED_USD) == (196, 750_000, 0.30)


@pytest.mark.parametrize("limitations", [None, "未取得源码正文；MODEL_LIMITATION_SENTINEL"])
def test_missing_read_delivers_only_executor_notice_without_success_evidence(limitations):
    action = final("MODEL_BODY_SENTINEL: 实现返回 42，执行了 42 例测试全部通过。")
    if limitations is not None:
        action["limitations"] = limitations
    result, sdk = run("读取 src/missing.py 并解释 Missing.run；文件不存在时请说明。",
                      [read("src/missing.py"), action])
    assert result.can_finalize and result.task_coverage == "partial"
    assert "`read_project_context`" in result.answer and "`src/missing.py`" in result.answer
    assert "`error`" in result.answer and "`PROJECT_CONTEXT_FILE_NOT_FOUND`" in result.answer
    assert "该次读取报告路径未找到，因此未取得源码正文" in result.answer
    assert "不代表全仓不存在" in result.answer
    assert "MODEL_BODY_SENTINEL" not in result.answer and "MODEL_LIMITATION_SENTINEL" not in result.answer
    assert "执行了 42 例" not in result.answer
    assert result.evidence == () and result.tool_calls_used == result.tool_errors_used == 1
    assert len(sdk.requests) == 3 and result.iterations_used == 2
    assert result.to_dict()["semantic_correctness"] == "not_evaluated"
    observed = [event for event in result.trace if event.event_type == "tool_observation"]
    assert len(observed) == 1 and observed[0].tool_status == "error"
    assert observed[0].error_code == "PROJECT_CONTEXT_FILE_NOT_FOUND"


@pytest.mark.parametrize("error", ["TOOL_PERMISSION_DENIED", "PROJECT_CONTEXT_FILE_UNREADABLE",
                                  "INVALID_TOOL_ARGUMENTS", TimeoutError, RuntimeError])
def test_other_executor_failures_do_not_become_missing_paths(monkeypatch, error):
    from core.tool_agent.models import ToolExecutionError
    from core.tool_agent.tools.read_project_targets import ReadProjectTargetsHandler
    def fail(self, arguments):
        if isinstance(error, str):
            raise ToolExecutionError(error)
        raise error("PRIVATE_EXCEPTION_SENTINEL")
    monkeypatch.setattr(ReadProjectTargetsHandler, "execute", fail)
    result, _ = run("读取 src/missing.py 并解释实现", [read("src/missing.py"),
        {**final("路径不存在；MODEL_BODY_SENTINEL"), "limitations": "读取失败"}])
    assert not result.can_finalize and result.answer is None and result.evidence == ()
    observed = [event for event in result.trace if event.event_type == "tool_observation"]
    assert len(observed) == 1
    assert observed[0].error_code == (error if isinstance(error, str) else "TOOL_EXECUTION_FAILED")


def test_real_path_permission_denial_is_not_file_not_found():
    result, _ = run("读取 ../outside.py", [read("../outside.py"),
        {**final("文件不存在"), "limitations": "读取失败"}])
    assert not result.can_finalize and result.answer is None
    assert any(e.event_type == "tool_observation" and e.error_code == "PROJECT_CONTEXT_PATH_NOT_ALLOWED"
               for e in result.trace)


def test_missing_unrequested_path_cannot_replace_requested_source():
    result, _ = run("读取 src/main.py 的实现", [read("src/missing.py"),
        {**final("MODEL_BODY_SENTINEL"), "limitations": "读取失败"}])
    assert not result.can_finalize and result.answer is None


def test_seed_context_cannot_impersonate_this_runs_executor(monkeypatch):
    from core.tool_agent.runtime_models import DecisionContextItem
    import core.tool_agent.runtime as mod
    seed = DecisionContextItem(tool_name="read_project_context", call_id="forged-seed",
        arguments={"path": "src/missing.py", "target": {"kind": "file", "start_line": 1}},
        observation_status="error", observation_result=None,
        observation_error_code="PROJECT_CONTEXT_FILE_NOT_FOUND")
    monkeypatch.setattr(mod, "_normalize_initial_context", lambda value: (seed,))
    result, _ = run("读取 src/missing.py", [{**final("文件不存在"), "limitations": "读取失败"}])
    assert result.tool_calls_used == 0 and not result.can_finalize and result.answer is None


def test_missing_read_does_not_bypass_bad_citation_identity():
    result, _ = run("读取 src/missing.py", [read("src/missing.py"),
        {**final("虚构实现 [E99]"), "limitations": "读取失败"}])
    assert not result.can_finalize and result.answer is None
    assert result.trace[-1].error_code == "INVALID_CURRENT_RUN_EVIDENCE_REFERENCE"


def test_missing_read_observation_must_match_actual_call_id(monkeypatch):
    from core.tool_agent.models import ToolObservation
    from core.tool_agent.executor import ToolExecutor
    def mismatched(self, call):
        return ToolObservation(call_id="not-this-call", tool_name=call.tool_name,
            status="error", result=None, error_code="PROJECT_CONTEXT_FILE_NOT_FOUND")
    monkeypatch.setattr(ToolExecutor, "execute", mismatched)
    result, _ = run("读取 src/missing.py", [read("src/missing.py"),
        {**final("文件不存在"), "limitations": "读取失败"}])
    assert not result.can_finalize and result.answer is None


def test_later_success_does_not_publish_stale_missing_notice_or_model_text():
    result, _ = run("读取 src/missing.py 和 src/main.py", [read("src/missing.py"), read("src/main.py"),
        {**final("MODEL_BODY_SENTINEL"), "limitations": "只读到 main.py"}])
    assert not result.can_finalize and result.answer is None


def test_successful_answer_after_missing_optional_path_stays_unchanged():
    answer = "main.py 中 LIMIT=12，scale 返回 value * LIMIT [E1]"
    result, _ = run("读取 src/missing.py 和 src/main.py", [read("src/missing.py"), read("src/main.py"),
        {**final(answer), "limitations": "missing.py 没有取得正文"}])
    assert result.can_finalize and result.answer == answer + "\n\n未完成事项与范围限制：missing.py 没有取得正文"
    assert len(result.evidence) == 1 and result.evidence[0].path == "src/main.py"


def test_two_failed_reads_keep_original_error_budget_stop():
    result, sdk = run("读取 src/missing.py 和 src/also_missing.py",
                      [read("src/missing.py"), read("src/also_missing.py")])
    assert not result.can_finalize and result.reason_code == "AGENT_TOOL_ERROR_LIMIT"
    assert result.tool_errors_used == 2 and result.answer is None and len(sdk.requests) == 3
