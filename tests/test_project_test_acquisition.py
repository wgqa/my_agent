"""Test evidence acquisition through the existing bounded Engineering chain."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.engineering_requirements import (
    CHANGE_TEST_V1, NO_ADDITIONAL_REQUIREMENT, PROJECT_CODE_V1, PROJECT_DOC_V1,
    PROJECT_TEST_V1, evaluate_evidence_requirement, route_engineering_evidence_requirement,
)
from core.tool_agent import INVALID_TOOL_ARGUMENTS, ToolCall, ToolExecutor
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE as LEGACY_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE as TEST_PROFILE,
    max_output_tokens_for_profile, max_parse_repairs_for_profile,
)
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.integration import build_tool_agent_runtime
from core.tool_agent.runtime import ToolAgentRuntime, _evidence_from_project_context
from core.tool_agent.runtime_models import ToolAgentBudget
from core.tool_agent.tools.code_search import (
    CODE_SEARCH_SPEC, CODE_SEARCH_TEST_SPEC, CODE_SEARCH_TEST_VERSION,
    CodeSearchHandler, code_search_spec,
)
from core.tool_agent.tools.read_project_context import ReadProjectContextHandler
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime


@pytest.mark.parametrize("question", [
    "Which repository tests cover the rule against parallel finalization? Read the relevant test.",
    "当前仓库有哪些测试覆盖工具参数校验？阅读相关测试并引用断言。",
    "Locate existing project tests for invalid inputs and cite them.",
    "Read tests/test_actions.py and cite its assertions.",
    "Read tests/code_test.py and explain the test.",
    "阅读 tests\\test_actions.py，引用断言。",
])
def test_existing_repository_test_inspection_requires_test_evidence(question):
    requirement = route_engineering_evidence_requirement(question)
    assert requirement.requirement_profile is PROJECT_TEST_V1
    assert requirement.required_evidence_groups == (("project_test",),)
    assert requirement.min_distinct_project_code_paths == 0


@pytest.mark.parametrize("question", [
    "How should I design unit tests?",
    "如何提高单元测试覆盖率？",
    "Explain test coverage in software projects.",
    "How should I write tests/test_actions.py?",
    "Read ../tests/test_actions.py.",
    "Read D:/external/tests/test_actions.py.",
    "Read https://example.org/tests/test_actions.py.",
    "Read tests/test_docs.md.",
])
def test_generic_design_and_nonlocal_references_do_not_force_repository_test_reads(question):
    assert route_engineering_evidence_requirement(question).requirement_profile is NO_ADDITIONAL_REQUIREMENT


@pytest.mark.parametrize("question,expected", [
    ("Explain the current project source code and its tests", PROJECT_CODE_V1),
    ("Review current changes and recommend regression tests", CHANGE_TEST_V1),
    ("Read README.md and cite its test instructions", PROJECT_DOC_V1),
])
def test_existing_source_change_and_document_priorities_remain(question, expected):
    assert route_engineering_evidence_requirement(question).requirement_profile is expected


def _repo(root):
    for directory in ("src", "docs", "tests"):
        (root / directory).mkdir()
    literal = "cannot_finalize_in_parallel"
    (root / "src/actions.py").write_text(f"def {literal}():\n    return True\n", encoding="utf-8")
    (root / "docs/guide.md").write_text(f"# {literal}\n", encoding="utf-8")
    (root / "tests/test_actions.py").write_text(
        f"def test_{literal}():\n    assert error.message == 'no parallel final answer'\n", encoding="utf-8",
    )
    return literal


@pytest.mark.parametrize("kind", [None, "any", "project_code", "project_doc"])
def test_new_search_preserves_legacy_discovery_for_every_old_domain(tmp_path, kind):
    literal = _repo(tmp_path)
    arguments = {"query": literal}
    if kind is not None:
        arguments["artifact_kind"] = kind
    assert CodeSearchHandler(tmp_path).execute(arguments) == CodeSearchHandler(
        tmp_path, version=CODE_SEARCH_TEST_VERSION,
    ).execute(arguments)


def test_test_filter_and_public_reader_share_classification(tmp_path):
    literal = _repo(tmp_path)
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(), code_search_version=CODE_SEARCH_TEST_VERSION)
    result = ToolExecutor(registry).execute(ToolCall.create(
        "code_search", {"query": literal, "artifact_kind": "project_test"},
    ))
    assert result.status == "ok"
    assert [m["path"] for m in result.result["matches"]] == ["tests/test_actions.py"]
    read = ReadProjectContextHandler(tmp_path).execute({"path": "tests/test_actions.py", "line": 1, "context_lines": 5})
    evidence = _evidence_from_project_context(SimpleNamespace(status="ok", tool_name="read_project_context", result=read))
    assert evidence.kind == "project_test"
    requirement = route_engineering_evidence_requirement("Read tests/test_actions.py and cite its assertions")
    assert evaluate_evidence_requirement(requirement, [evidence]).satisfied
    assert not evaluate_evidence_requirement(requirement, [replace(evidence, kind="project_code", path="src/actions.py")]).satisfied


def test_legacy_registry_still_rejects_test_filter_and_v7_rejects_unknown_arguments(tmp_path):
    _repo(tmp_path)
    arguments = {"query": "cannot_finalize_in_parallel", "artifact_kind": "project_test"}
    old = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort())
    new = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(), code_search_version=CODE_SEARCH_TEST_VERSION)
    assert old.get_spec("code_search").version == "code_search_v5"
    assert CODE_SEARCH_SPEC.input_schema["properties"]["artifact_kind"]["enum"] == ["any", "project_code", "project_doc"]
    assert ToolExecutor(old).execute(ToolCall.create("code_search", arguments)).error_code == INVALID_TOOL_ARGUMENTS
    for extra in ({"scope": "tests"}, {"repo_root": "../"}, {"artifact_kind": "arbitrary"}):
        assert ToolExecutor(new).execute(ToolCall.create("code_search", dict(arguments, **extra))).error_code == INVALID_TOOL_ARGUMENTS
    assert len(old) == len(new) == 7
    assert CODE_SEARCH_TEST_SPEC.output_schema == CODE_SEARCH_SPEC.output_schema


@pytest.mark.parametrize("version", [None, {}, "code_search_v6", "unknown"])
def test_search_profile_selection_is_closed_and_not_a_model_argument(version):
    with pytest.raises(ValueError, match="Unsupported code_search version"):
        code_search_spec(version)


def test_test_search_keeps_file_safety_and_output_bounds(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "tests/api_key_test.py").write_text("needle", encoding="utf-8")
    (tmp_path / "tests/test_huge.py").write_text("needle" + "x" * (1024 * 1024), encoding="utf-8")
    (tmp_path / ".hidden/test_actions.py").write_text("needle", encoding="utf-8")
    (tmp_path / "tests/test_visible.py").write_text(("needle" + "x" * 400 + "\n") * 20, encoding="utf-8")
    matches = CodeSearchHandler(tmp_path, version=CODE_SEARCH_TEST_VERSION).execute(
        {"query": "needle", "artifact_kind": "project_test"},
    )["matches"]
    assert len(matches) == 10
    assert {m["path"] for m in matches} == {"tests/test_visible.py"}
    assert all(len(m["text"]) == 300 for m in matches)


class _Decisions:
    def __init__(self, actions):
        self.actions = actions
        self.states = []
        self.contexts = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.states.append(control_state)
        self.contexts.append(context)
        action = self.actions[min(len(self.states) - 1, len(self.actions) - 1)]
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def _call(tool, **arguments):
    return ToolCallAction(action="tool_call", tool_name=tool, arguments=arguments)


def _answer(text):
    return FinalAnswerAction(action="final_answer", answer=text)


@pytest.mark.parametrize("answer,status", [
    ("The test asserts an error for parallel finalization [E2]. Suggested command: pytest tests/test_actions.py -k cannot_finalize_in_parallel. Not run.", "completed"),
    ("The test asserts an error [E99].", "refused"),
    ("The test asserts an error.", "refused"),
])
def test_search_then_read_uses_existing_guard_and_citation_binding(tmp_path, answer, status):
    literal = _repo(tmp_path)
    provider = _Decisions([
        _call("code_search", query=literal, artifact_kind="project_test"),
        _call("read_project_context", path="tests/test_actions.py", line=1, context_lines=5),
        _answer(answer),
    ])
    runtime = build_tool_agent_runtime(repo_root=tmp_path, retrieval_port=EmptyRetrievalPort(), provider=provider,
                                       code_search_version=CODE_SEARCH_TEST_VERSION, prompt_profile=TEST_PROFILE)
    result = build_full_unified_runtime(runtime).run("Which repository tests cover parallel finalization? Read and cite the test.")
    assert result.status == status
    assert result.tool_calls_used == 2
    assert result.tool_errors_used == 0
    assert provider.states[0].missing_evidence_groups == provider.states[1].missing_evidence_groups == (("project_test",),)
    assert provider.states[2].missing_evidence_groups == ()
    assert result.evidence[-1].kind == "project_test"
    assert "assert error.message" in result.evidence[-1].snippet
    assert runtime._budget == ToolAgentBudget(5, 4, 2)


@pytest.mark.parametrize("actions", [
    [_answer("Unverified test claim.")],
    [_call("read_project_context", path="src/actions.py", line=1, context_lines=5), _answer("Test claim [E1].")],
    [_call("code_search", query="cannot_finalize_in_parallel", artifact_kind="project_test"), _answer("Test claim [E1].")],
])
def test_direct_plan_source_read_and_search_hits_cannot_replace_test_evidence(tmp_path, actions):
    _repo(tmp_path)
    provider = _Decisions(actions)
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(), code_search_version=CODE_SEARCH_TEST_VERSION)
    result = build_full_unified_runtime(ToolAgentRuntime(registry=registry, provider=provider)).run(
        "Which repository tests cover parallel finalization? Read and cite the test."
    )
    assert result.status == "refused"
    assert result.answer is None
    assert all(s.missing_evidence_groups == (("project_test",),) for s in provider.states)
    assert result.iterations_used <= 5 and result.tool_calls_used <= 4


def test_test_acquisition_cannot_extend_decision_or_tool_budget(tmp_path):
    _repo(tmp_path)
    provider = _Decisions([
        *[_call("code_search", query=f"missing_test_{n}", artifact_kind="project_test") for n in range(4)],
        _answer("Unsupported test claim."),
    ])
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(), code_search_version=CODE_SEARCH_TEST_VERSION)
    result = build_full_unified_runtime(ToolAgentRuntime(registry=registry, provider=provider)).run(
        "Which repository tests cover parallel finalization? Read and cite the test."
    )
    assert result.status == "refused" and result.answer is None
    assert (result.iterations_used, result.tool_calls_used, result.tool_errors_used) == (5, 4, 0)
    assert provider.states[-1].must_terminate is True


def test_function_read_acquires_test_name_setup_and_tail_assertions_together(tmp_path):
    (tmp_path / "tests").mkdir()
    content = (
        "class TestRules:\n    def test_parallel_finalize(self):\n"
        "        calls = ['normal', 'finish']\n"
        + "        # intervening test setup\n" * 70
        + "        assert calls == ['normal', 'finish']\n"
    )
    (tmp_path / "tests/test_rules.py").write_text(content, encoding="utf-8")
    provider = _Decisions([
        _call("read_project_context", path="tests/test_rules.py", line=2, context_lines=0, mode="definition"),
        _answer("TestRules.test_parallel_finalize asserts both prepared calls [E1]."),
    ])
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(), code_search_version=CODE_SEARCH_TEST_VERSION)
    result = build_full_unified_runtime(ToolAgentRuntime(registry=registry, provider=provider)).run(
        "Read tests/test_rules.py and cite its test assertions."
    )
    assert result.status == "completed"
    read = provider.contexts[1][-1].observation_result
    assert read["content_complete"] is True
    assert read["definition"]["name"] == "TestRules.test_parallel_finalize"
    assert result.evidence[-1].kind == "project_test"
    assert "calls = ['normal', 'finish']" in result.evidence[-1].snippet
    assert "assert calls == ['normal', 'finish']" in result.evidence[-1].snippet
    assert result.tool_calls_used == 1 and result.tool_errors_used == 0


def test_prompt_revision_keeps_old_identity_and_transport_limits():
    assert LEGACY_PROFILE.sha256 == "c465defe7f9504d7cfb137748ba96fb90cf7bf049c7ca7a93d3f7f56945ebcdf"
    assert TEST_PROFILE.render_control_state and TEST_PROFILE.render_evidence_reference_control
    assert max_output_tokens_for_profile(TEST_PROFILE) == max_output_tokens_for_profile(LEGACY_PROFILE) == 1200
    assert max_parse_repairs_for_profile(TEST_PROFILE) == max_parse_repairs_for_profile(LEGACY_PROFILE) == 1
    assert "artifact_kind 必须为 project_test" in TEST_PROFILE.template
    assert "测试已执行或已通过" in TEST_PROFILE.template
    assert "优先用现有 mode=definition" in TEST_PROFILE.template
    assert "definition.name" in TEST_PROFILE.template
    assert "不要用 code_search 的 artifact_kind 模拟 project_test" not in TEST_PROFILE.template
