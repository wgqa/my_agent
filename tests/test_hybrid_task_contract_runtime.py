"""Fake SDK, actual Runtime, and unchanged Task018 Git/RAG fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.engineering_requirements import route_engineering_evidence_requirement
from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
from core.query_planning.prompt import ENGINEERING_TASK_CONTRACT_PLANNER_PROMPT_VERSION
from core.tool_agent.integration import build_tool_agent_runtime
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC
from tests._engineering_runtime_support import (
    EmptyRetrievalPort, StaticKnowledgeRetrievalPort, build_full_unified_runtime,
)
from tests.test_engineering_task_contract import contract_payload, planner_payload
from tests.test_tool_agent_changed_files_typed_finalization import StaticChangedFilesHandler, _observation

BASE = "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad"
HEAD = "d6b6c100d5e2e441957d834a29a73a8bc4ac1693"
GIT_ARGS = dict(mode="commit_range", base_ref=BASE, head_ref=HEAD)


class FakeSDK:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        value = self.responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=40),
        )


def call(name, arguments):
    return dict(action="tool_call", tool_name=name, arguments=arguments)


def typed(operation="list_all", **kwargs):
    return dict(action="changed_files_finalization", evidence_id="E1", operation=operation) | kwargs


def final(answer):
    return dict(action="final_answer", answer=answer)


@pytest.fixture
def git_fixture():
    root = Path(__file__).resolve().parents[2] / "_task018_e2e_fixtures" / "commit_range"
    if not (root / ".git").exists():
        pytest.skip("Existing Task018 isolated Git fixture is unavailable")
    return root


def run_hybrid(question, contract, decisions, *, root=None, observation=None,
               plan=None, port=None, mode="hybrid_task_contract", reader_version=None):
    sdk = FakeSDK([plan or planner_payload(contract), *decisions])
    planner = OpenAICompatibleQueryPlanner(
        provider="fake", model="deepseek-flash", api_key="fake-offline-placeholder", client=sdk,
        prompt_version=ENGINEERING_TASK_CONTRACT_PLANNER_PROMPT_VERSION,
    )
    provider = OpenAICompatibleAgentDecisionProvider(
        provider="fake", model="deepseek-flash", api_key="fake-offline-placeholder",
        client=sdk, max_parse_repairs=0,
    )
    port = port or EmptyRetrievalPort()
    if root is not None:
        executor = build_tool_agent_runtime(
            repo_root=root, retrieval_port=port, provider=provider,
            **({"read_project_context_version": reader_version} if reader_version is not None else {}))
    else:
        registry = ToolRegistry()
        registry.register(CHANGED_FILES_SPEC, StaticChangedFilesHandler(observation))
        executor = ToolAgentRuntime(registry=registry, provider=provider)
    unified = build_full_unified_runtime(
        executor, planner=planner, retrieval_port=port, finalization_strategy=mode)
    return unified.run(question), sdk


def range_contract(**kwargs):
    return contract_payload(scope_mode="commit_range", base_ref=BASE, head_ref=HEAD,
                            requires_complete_list=True, **kwargs)


def test_deleted_source_task_replaces_router_mismatch_in_actual_git_runtime(git_fixture):
    question = f"列出 {BASE} 到 {HEAD} 之间已删除的源码文件路径"
    assert route_engineering_evidence_requirement(question).requirement_profile.value == "PROJECT_CODE_V1"
    result, sdk = run_hybrid(question, range_contract(object_kind="source_files", status="deleted"),
                             [call("changed_files", GIT_ARGS), typed("filter_status", status="deleted")],
                             root=git_fixture)
    assert result.status == "completed"
    assert "src/retired_source.py" in result.answer and "deleted" in result.answer
    assert "docs/usage.md" not in result.answer and "src/main.py" not in result.answer
    assert result.task_contract.requires_source_body is False
    assert result.execution.selector_llm_calls == 0 and len(sdk.requests) == 3
    assert [event.tool_name for event in result.trace if event.event_type == "tool_observation"] == ["changed_files"]
    assert any("task_contract" in msg["content"] for msg in sdk.requests[-1]["messages"] if msg["role"] == "system")


@pytest.mark.parametrize(("contract", "action", "expected"), [
    (range_contract(), typed(), "tests/test_main.py"),
    (range_contract(status="renamed"), typed("filter_status", status="renamed"), "src/old_parser.py"),
])
def test_full_inventory_and_rename_use_real_tool_facts(git_fixture, contract, action, expected):
    question = f"列出 {BASE} 到 {HEAD} 之间的完整"
    question += "重命名文件及旧、新路径" if contract["status"] == "renamed" else "变更清单"
    result, _ = run_hybrid(question, contract, [call("changed_files", GIT_ARGS), action], root=git_fixture)
    assert result.status == "completed" and expected in result.answer
    if contract["status"] == "renamed":
        assert "src/old_parser.py" in result.answer and "src/new_parser.py" in result.answer


def test_source_object_filters_documents_from_true_status_rows():
    question = "列出当前工作区已删除的源码文件"
    observation = _observation([{"path": "docs/obsolete.md", "status": "deleted"},
                                {"path": "src/old.py", "status": "deleted"}])
    result, _ = run_hybrid(question, contract_payload(status="deleted"),
                           [call("changed_files", {"mode": "working_tree"}),
                            typed("filter_status", status="deleted")], observation=observation)
    assert result.status == "completed"
    assert "src/old.py" in result.answer and "docs/obsolete.md" not in result.answer


@pytest.mark.parametrize("action", [
    typed("filter_status", status="deleted"),
    typed(evidence_id="E99"),
    final("当前变更只有 src/deleted.py [E1]"),
])
def test_legitimate_protocol_cannot_deliver_wrong_set_or_unknown_reference(action):
    observation = _observation([{"path": "src/a.py", "status": "modified"},
                                {"path": "src/deleted.py", "status": "deleted"}])
    result, _ = run_hybrid("列出当前工作区全部变更", contract_payload(),
                           [call("changed_files", {"mode": "working_tree"}), action],
                           observation=observation)
    assert result.status == "refused" and result.answer is None


def test_wrong_git_scope_is_blocked(git_fixture):
    question = f"列出 {BASE} 到 {HEAD} 之间全部变更"
    result, _ = run_hybrid(question, range_contract(),
                           [call("changed_files", {"mode": "working_tree"}), typed()], root=git_fixture)
    assert result.status == "refused"


@pytest.mark.parametrize(("question", "complete"), [
    ("列出当前工作区全部变更", True), ("列出当前工作区已返回的有限变更", False),
])
def test_truncated_sources_preserve_complete_vs_limited_delivery(question, complete):
    result, _ = run_hybrid(question, contract_payload(),
                           [call("changed_files", {"mode": "working_tree"}), typed()],
                           observation=_observation([{"path": "src/a.py", "status": "modified"}],
                                                    total=2, truncated=True))
    assert result.task_contract.requires_complete_list == complete
    if complete:
        assert result.status == "refused" and result.answer is None
    else:
        assert result.status == "completed" and "结果不穷举" in result.answer


def test_source_explanation_needs_actual_requested_body(git_fixture):
    result, sdk = run_hybrid(
        "解释 src/main.py 的源码实现",
        contract_payload(operation="source_read", object_kind="source_files",
                         scope_mode="project", target_paths=["src/main.py"]),
        [call("read_project_context", {"path": "src/main.py", "line": 1, "context_lines": 10}),
         final("src/main.py 的 scale 函数将输入 value 乘以 LIMIT 并返回结果 [E1]")], root=git_fixture)
    assert result.status == "completed"
    assert result.task_contract.requires_source_body
    assert any(item.kind == "project_code" and item.path == "src/main.py" and item.snippet for item in result.evidence)
    assert len(sdk.requests) == 3


@pytest.mark.parametrize(("arguments", "completed"), [
    ({"path": "src/main.py", "line": 3, "context_lines": 0, "mode": "definition"}, True),
    ({"path": "src/main.py", "line": 3, "context_lines": 0}, False),
])
def test_function_implementation_requires_complete_selected_definition(git_fixture, arguments, completed):
    result, _ = run_hybrid(
        "解释 src/main.py 中 scale 函数的源码实现",
        contract_payload(operation="source_read", object_kind="function", scope_mode="project",
                         target_paths=["src/main.py"], target_symbols=["scale"]),
        [call("read_project_context", arguments),
         final("scale 函数返回 value 与 LIMIT 的乘积 [E1]")], root=git_fixture)
    assert (result.status == "completed") == completed
    if not completed:
        assert result.trace[-1].error_code == "REQUESTED_FUNCTION_BODY_INCOMPLETE"


@pytest.mark.parametrize("target", [
    {"kind": "symbols", "names": ["scale"]},
    {"kind": "file", "start_line": 1},
])
def test_product_reader_supports_named_definition_and_complete_file(git_fixture, target):
    from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
    result, _ = run_hybrid(
        "解释 src/main.py 中 scale 函数的源码实现",
        contract_payload(operation="source_read", object_kind="function", scope_mode="project",
                         target_paths=["src/main.py"], target_symbols=["scale"]),
        [call("read_project_context", {"path": "src/main.py", "target": target}),
         final("scale 函数返回 value 与 LIMIT 的乘积 [E1]")],
        root=git_fixture, reader_version=READ_PROJECT_TARGETS_VERSION)
    assert result.status == "completed"


@pytest.mark.parametrize("first_call", [
    call("code_search", {"query": "def"}),
    call("read_project_context", {"path": "src/new_parser.py", "line": 1, "context_lines": 10}),
    call("read_project_context", {"path": "../private.py", "line": 1, "context_lines": 10}),
])
def test_locator_unrelated_body_and_failed_observation_never_prove_implementation(git_fixture, first_call):
    result, _ = run_hybrid(
        "解释 src/main.py 的源码实现",
        contract_payload(operation="source_read", object_kind="source_files",
                         scope_mode="project", target_paths=["src/main.py"]),
        [first_call, final("src/main.py 的实现已经验证 [E1]")], root=git_fixture)
    assert result.status in {"refused", "failed"} and result.answer is None


def test_uncited_body_cannot_be_borrowed_to_support_locator_answer(git_fixture):
    result, _ = run_hybrid(
        "解释 src/main.py 的源码实现",
        contract_payload(operation="source_read", object_kind="source_files",
                         scope_mode="project", target_paths=["src/main.py"]),
        [call("code_search", {"query": "def"}),
         call("read_project_context", {"path": "src/main.py", "line": 1, "context_lines": 10}),
         final("src/main.py 的实现已经证明 [E1]")], root=git_fixture)
    assert result.status == "refused"
    assert result.evidence[0].granularity == "locator"
    assert any(item.kind == "project_code" and getattr(item, "path", None) == "src/main.py"
               and getattr(item, "granularity", "source_body") == "source_body" for item in result.evidence)


def test_test_candidates_cannot_prove_test_execution(git_fixture):
    result, _ = run_hybrid(
        "运行 src/main.py 对应的测试并报告是否通过",
        contract_payload(operation="test_execution", object_kind="tests",
                         scope_mode="project", target_paths=["src/main.py"]),
        [call("find_tests", {"path": "src/main.py"}), final("测试全部通过 [E1]")], root=git_fixture)
    assert result.status == "refused"


def test_open_analysis_is_not_typed_and_requires_real_diff(git_fixture):
    question = f"解释 src/main.py 在 {BASE} 到 {HEAD} 的变更"
    contract = range_contract(operation="change_analysis", target_paths=["src/main.py"])
    rejected, _ = run_hybrid(
        question, contract, [call("changed_files", GIT_ARGS), typed()], root=git_fixture)
    assert rejected.status == "refused"
    accepted, _ = run_hybrid(
        question, contract,
        [call("git_diff", GIT_ARGS | {"path": "src/main.py"}),
         final("src/main.py 的修改改变了返回值，这是可核查的行为变化 [E1]")], root=git_fixture)
    assert accepted.status == "completed"
    assert any(getattr(item, "granularity", None) == "diff" for item in accepted.evidence)


def test_rag_requires_knowledge_and_records_contract(git_fixture):
    contract = contract_payload(operation="knowledge_answer", object_kind="knowledge",
                                scope_mode="knowledge")
    plan = planner_payload(contract) | dict(query_type="fact", retrieval_required=True,
                                            action="single_retrieval", reason_code="SIMPLE_FACT")
    result, sdk = run_hybrid(
        "根据知识库说明重试窗口", contract, [final("根据知识库资料回答 [E1]")],
        root=git_fixture, plan=plan, port=StaticKnowledgeRetrievalPort())
    assert result.status == "completed" and result.task_contract.requires_knowledge
    assert "task_contract" in result.to_dict() and len(sdk.requests) == 2
    missing, _ = run_hybrid(
        "根据知识库说明重试窗口", contract, [final("没有资料也能确认 [E1]")],
        root=git_fixture, plan=plan)
    assert missing.status == "refused"


def test_missing_contract_stops_before_any_agent_or_tool_request():
    result, sdk = run_hybrid("hi", None, [], plan=planner_payload(), observation=_observation())
    assert result.status == "failed" and len(sdk.requests) == 1
    assert result.iterations_used == result.tool_calls_used == 0
    assert result.trace[0].error_code == "TASK_CONTRACT_INVALID"


def test_filtered_empty_source_set_does_not_claim_entire_worktree_empty():
    result, _ = run_hybrid(
        "列出当前工作区全部源码文件变更", contract_payload(object_kind="source_files"),
        [call("changed_files", {"mode": "working_tree"}), typed()],
        observation=_observation([{"path": "docs/usage.md", "status": "modified"}]))
    assert result.status == "completed"
    assert "源码文件清单为空" in result.answer
    assert "未发现可见变更文件" not in result.answer


def test_case07_knowledge_coverage_and_missing_diff_are_independent(git_fixture, monkeypatch):
    from core.engineering_verification import EngineeringEvidenceVerifier

    checked = []
    original = EngineeringEvidenceVerifier.verify

    def record(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        checked.append(result.insufficiency_reasons)
        return result

    monkeypatch.setattr(EngineeringEvidenceVerifier, "verify", record)
    question = f"结合 {BASE} 到 {HEAD} 的变更，判断哪项最重要并说明依据"
    contract = range_contract(operation="change_analysis")
    plan = planner_payload(contract) | dict(
        query_type="causal", retrieval_required=True, action="decomposed_retrieval",
        reason_code="CAUSAL_SYNTHESIS",
        subqueries=[dict(id=f"sq{i}", query=query, evidence_target=query, required=True)
                    for i, query in enumerate(["变更内容", "影响面", "重要性依据"], 1)])
    legacy, _ = run_hybrid(
        question, contract, [call("git_diff", GIT_ARGS | {"path": "src/main.py"}),
                             final("已读取 src/main.py 的真实 diff [E1]")],
        root=git_fixture, plan=plan, mode="direct_hybrid")
    assert legacy.status == "refused"
    assert any("INCOMPLETE_SUBQUERY_COVERAGE" in reasons for reasons in checked)
    checked.clear()
    missing_diff, _ = run_hybrid(
        question, contract, [call("changed_files", GIT_ARGS),
                             final("仅凭状态不足以判断重要性 [E1]")],
        root=git_fixture, plan=plan)
    assert missing_diff.status == "refused"
    assert any("REQUIRED_EVIDENCE_MISSING" in reasons for reasons in checked)
    assert not any("INCOMPLETE_SUBQUERY_COVERAGE" in reasons for reasons in checked)
    checked.clear()
    with_diff, _ = run_hybrid(
        question, contract, [call("git_diff", GIT_ARGS | {"path": "src/main.py"}),
                             final("src/main.py 的真实 diff 可支持所述行为变化 [E1]")],
        root=git_fixture, plan=plan)
    assert with_diff.status == "refused"
    assert with_diff.trace[-1].error_code == "CHANGE_SCOPE_NOT_ESTABLISHED"
    assert not any("INCOMPLETE_SUBQUERY_COVERAGE" in reasons for reasons in checked)


def test_product_factory_can_select_hybrid_without_changing_legacy_default(monkeypatch, tmp_path):
    import api.app as application
    from tests._engineering_runtime_support import NoRetrievalPlanner
    from tests.test_tool_agent_changed_files_typed_finalization import ScriptedTypedProvider

    selected = []
    port = EmptyRetrievalPort()
    monkeypatch.setattr(application, "engineering_knowledge_backend", SimpleNamespace(retrieval_port=port))
    monkeypatch.setattr(application, "build_tool_agent_runtime",
                        lambda **_: ToolAgentRuntime(registry=ToolRegistry(),
                            provider=ScriptedTypedProvider([])))
    monkeypatch.setattr(application, "OpenAICompatibleConversationQueryResolver", lambda **_: None)

    def planner_factory(**kwargs):
        selected.append(kwargs["prompt_version"])
        return NoRetrievalPlanner()

    monkeypatch.setattr(application, "OpenAICompatibleQueryPlanner", planner_factory)
    monkeypatch.setenv("ENGINEERING_FINALIZATION_STRATEGY", "hybrid_task_contract")
    project = SimpleNamespace(root=tmp_path, project_name="offline-project", source="default_repo")
    hybrid = application._build_engineering_project_runtime(project)
    assert hybrid.runtime._finalization_strategy == "hybrid_task_contract"
    assert selected == [ENGINEERING_TASK_CONTRACT_PLANNER_PROMPT_VERSION]
    legacy = application._build_engineering_project_runtime(project, finalization_strategy="legacy")
    assert legacy.runtime._finalization_strategy == "legacy"


def test_single_file_diff_cannot_satisfy_complete_change_scope(git_fixture):
    question = f"分析 {BASE} 到 {HEAD} 之间全部变更的影响"
    result, _ = run_hybrid(
        question, range_contract(operation="change_analysis"),
        [call("changed_files", GIT_ARGS),
         call("git_diff", GIT_ARGS | {"path": "src/main.py"}),
         final("这些材料已经证明全部变更的影响 [E2]")], root=git_fixture)
    assert result.status == "refused" and result.answer is None
    assert result.trace[-1].error_code == "CHANGE_SCOPE_INCOMPLETE"
