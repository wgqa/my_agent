"""R03: discover only entrypoints, read actual documents, preserve boundaries."""

import builtins
import json
from pathlib import Path

import pytest

from core.engineering_requirements import (
    LEGACY_ROUTER_VERSION, ROUTER_VERSION, PROJECT_CODE_V1, PROJECT_DOC_V1,
    CHANGE_TEST_V1, NO_ADDITIONAL_REQUIREMENT, route_engineering_evidence_requirement,
)
from core.tool_agent.action_parser import parse_agent_action_text
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, RefuseAction, ToolCallAction
from core.tool_agent.activity import build_tool_activity_event
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_PROJECT_INFO_PROFILE,
    ENGINEERING_DECISION_PROMPT_PROJECT_OVERVIEW_PROFILE,
    max_output_tokens_for_profile, max_parse_repairs_for_profile,
)
from core.query_planning.prompt import (
    ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION, ENGINEERING_OVERVIEW_PLANNER_SYSTEM_PROMPT,
    ENGINEERING_PROJECT_INFO_PLANNER_SYSTEM_PROMPT, build_planner_messages,
)
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import INVALID_TOOL_ARGUMENTS, ToolCall
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import INSUFFICIENT_EVIDENCE_TO_FINALIZE
from core.tool_agent.tools.project_info import (
    PROJECT_INFO_DOCUMENTATION_VERSION, ProjectBinding, MAX_DOCUMENTATION_ENTRYPOINTS,
)
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime


def registry_for(root):
    return build_readonly_tool_registry(
        root, EmptyRetrievalPort(), read_project_context_version=READ_PROJECT_TARGETS_VERSION,
        project_binding=ProjectBinding(root.resolve(), root.name, "configured"),
        project_info_version=PROJECT_INFO_DOCUMENTATION_VERSION,
    )


@pytest.mark.parametrize("question", [
    "说一下目前的项目", "介绍一下当前项目。", "介绍这个项目的功能。",
    "概述当前工程", "讲一下我们这个项目", "当前项目主要做什么？",
    "咱们的项目是干什么的？", "现在的项目有哪些能力？",
    "Describe the current project.", "Tell me about this repository.",
    "What does this project do?", "What is this project for?",
])
def test_bound_project_overview_uses_existing_document_requirement(question):
    requirement = route_engineering_evidence_requirement(question)
    assert requirement.requirement_profile is PROJECT_DOC_V1
    assert requirement.required_evidence_groups == (("project_doc",),)
    assert requirement.router_version == ROUTER_VERSION


@pytest.mark.parametrize("question", [
    "说一下目前的项目绑定在哪个目录", "目前咱们的系统绑定的哪个项目目录",
    "介绍一下当前项目绑定的根目录。", "当前项目挂载在哪？",
    "我该如何介绍自己的项目？", "如何向面试官介绍这个项目？",
    "How to describe a project in an interview?", "如何设计一个 Agent 项目？",
])
def test_identity_and_generic_presentation_advice_do_not_require_overview_document(question):
    assert route_engineering_evidence_requirement(question).requirement_profile is NO_ADDITIONAL_REQUIREMENT


def test_overview_cannot_downgrade_explicit_code_or_change_test_tasks():
    assert route_engineering_evidence_requirement(
        "介绍当前项目，并结合源码解释函数调用关系",
    ).requirement_profile is PROJECT_CODE_V1
    assert route_engineering_evidence_requirement(
        "介绍当前项目并检查代码变更影响的测试",
    ).requirement_profile is CHANGE_TEST_V1
    legacy = route_engineering_evidence_requirement("说一下目前的项目", router_version=LEGACY_ROUTER_VERSION)
    assert legacy.requirement_profile is NO_ADDITIONAL_REQUIREMENT
    assert legacy.router_version == LEGACY_ROUTER_VERSION


def test_document_entrypoints_are_not_read_or_promoted_and_plain_binding_stays_compatible(tmp_path, monkeypatch):
    (tmp_path / "README.rst").write_text("PRIVATE_BODY_MARKER: a useful application\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/index.md").write_text("Other introduction\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/README.md").write_text("Nested module details\n", encoding="utf-8")
    real_open = builtins.open

    def no_document_reads(file, *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file).resolve().is_relative_to(tmp_path.resolve()):
            raise AssertionError("entrypoint discovery must not read document bodies")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", no_document_reads)
    executor = ToolExecutor(registry_for(tmp_path))
    plain = executor.execute(ToolCall.create("get_project_info", {}))
    assert set(plain.result) == {"project_name", "root", "source", "available"}
    result = executor.execute(ToolCall.create("get_project_info", {"include_documentation": True}))
    assert result.status == "ok"
    assert result.result["documentation_entrypoints"] == ["README.rst", "docs/index.md"]
    assert result.result["documentation_scope"] == "conventional_overview_entrypoints"
    assert "PRIVATE_BODY_MARKER" not in json.dumps(result.result)


@pytest.mark.parametrize("arguments", [
    {"include_documentation": "true"}, {"include_documentation": 1},
    {"include_documentation": True, "path": "../other"},
    {"include_documentation": True, "project_id": "another"},
])
def test_document_discovery_still_rejects_model_paths_and_invalid_flags(tmp_path, arguments):
    registry = registry_for(tmp_path)
    action, error = parse_agent_action_text(json.dumps({
        "action": "tool_call", "tool_name": "get_project_info", "arguments": arguments,
    }), registry)
    assert action is None and error is not None
    result = ToolExecutor(registry).execute(ToolCall.create("get_project_info", arguments))
    assert result.error_code == INVALID_TOOL_ARGUMENTS


def test_discovery_has_a_fixed_bound_and_honest_truncation(tmp_path):
    for relative in ("README.md", "README.rst", "README.txt", "docs/index.md", "docs/index.rst",
                     "docs/README.md", "docs/overview.md", "docs/overview.rst"):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("introduction\n", encoding="utf-8")
    result = ToolExecutor(registry_for(tmp_path)).execute(ToolCall.create(
        "get_project_info", {"include_documentation": True},
    ))
    assert len(result.result["documentation_entrypoints"]) == MAX_DOCUMENTATION_ENTRYPOINTS
    assert result.result["documentation_truncated"] is True


def test_resolved_escape_is_not_an_entrypoint(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("local file", encoding="utf-8")
    registry = registry_for(tmp_path)
    resolve = Path.resolve

    def redirected(path, *args, **kwargs):
        if path.name.lower() == "readme.md":
            return tmp_path.parent / "outside.md"
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    result = ToolExecutor(registry).execute(ToolCall.create("get_project_info", {"include_documentation": True}))
    assert result.result["documentation_entrypoints"] == []


def test_symlink_entrypoint_is_not_followed(tmp_path):
    target = tmp_path / "real.md"
    target.write_text("real content", encoding="utf-8")
    try:
        (tmp_path / "README.md").symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit creation of symlinks")
    result = ToolExecutor(registry_for(tmp_path)).execute(ToolCall.create("get_project_info", {"include_documentation": True}))
    assert result.result["documentation_entrypoints"] == []


@pytest.mark.parametrize("linked", ["README.md", "docs"])
def test_linked_file_or_parent_is_rejected_without_host_symlink_privilege(tmp_path, monkeypatch, linked):
    (tmp_path / "README.md").write_text("root overview", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/index.md").write_text("docs overview", encoding="utf-8")
    registry = registry_for(tmp_path)
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == tmp_path / linked or real_is_symlink(path))
    result = ToolExecutor(registry).execute(ToolCall.create("get_project_info", {"include_documentation": True}))
    expected = ["docs/index.md"] if linked == "README.md" else ["README.md"]
    assert result.result["documentation_entrypoints"] == expected


def test_overview_profile_preserves_r02_transport_and_planning_protocol():
    profile = ENGINEERING_DECISION_PROMPT_PROJECT_OVERVIEW_PROFILE
    assert profile.template.startswith(ENGINEERING_DECISION_PROMPT_PROJECT_INFO_PROFILE.template)
    assert max_parse_repairs_for_profile(profile) == 1
    assert max_output_tokens_for_profile(profile) == 1200
    assert ENGINEERING_OVERVIEW_PLANNER_SYSTEM_PROMPT.startswith(ENGINEERING_PROJECT_INFO_PLANNER_SYSTEM_PROMPT)
    query = "说一下目前的项目"
    messages = build_planner_messages(query, prompt_version=ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION)
    assert messages[0]["content"] == ENGINEERING_OVERVIEW_PLANNER_SYSTEM_PROMPT
    assert json.loads(messages[1]["content"])["original_query"] == query


class OverviewDecisions:
    def __init__(self, *, answer=None, skip_reader=False):
        self.answer, self.skip_reader = answer, skip_reader

    def decide(self, registry, question, *, context=(), control_state=None):
        info = next((item for item in context if item.tool_name == "get_project_info"), None)
        read = next((item for item in context if item.tool_name == "read_project_context"), None)
        if info is None:
            action = ToolCallAction(action="tool_call", tool_name="get_project_info", arguments={"include_documentation": True})
        elif self.skip_reader:
            action = FinalAnswerAction("final_answer", self.answer or "This project has useful features [E1].")
        elif not info.observation_result["documentation_entrypoints"]:
            action = RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION")
        elif read is None:
            action = ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={
                "path": info.observation_result["documentation_entrypoints"][0],
                "target": {"kind": "file", "start_line": 1},
            })
        else:
            lines = read.observation_result["regions"][0]["lines"]
            body = "\n".join(line["text"] for line in lines)
            action = FinalAnswerAction("final_answer", self.answer or f"The project documentation says: {body} [E1]")
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


@pytest.mark.parametrize("entry", ["README.md", "docs/index.md"])
def test_overview_reads_actual_body_and_cites_it_inside_existing_budget(tmp_path, entry):
    path = tmp_path / entry
    path.parent.mkdir(exist_ok=True)
    path.write_text("A bounded job queue with SQLite persistence.\n", encoding="utf-8")
    runtime = build_full_unified_runtime(ToolAgentRuntime(registry=registry_for(tmp_path), provider=OverviewDecisions()))
    result = runtime.run("说一下目前的项目")
    assert result.status == "completed"
    assert "job queue" in result.answer and "[E1]" in result.answer
    assert (result.iterations_used, result.tool_calls_used, result.tool_errors_used) == (3, 2, 0)
    assert len(result.evidence) == 1
    assert result.evidence[0].kind == "project_doc"
    assert result.evidence[0].path == entry


def test_entrypoints_and_fabricated_citation_cannot_complete_an_overview(tmp_path):
    (tmp_path / "README.md").write_text("A job queue\n", encoding="utf-8")
    runtime = build_full_unified_runtime(ToolAgentRuntime(
        registry=registry_for(tmp_path), provider=OverviewDecisions(skip_reader=True),
    ))
    result = runtime.run("说一下目前的项目")
    assert result.status == "refused"
    assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
    assert result.answer is None and result.evidence == ()
    assert result.tool_calls_used == 1


def test_missing_conventional_docs_refuses_without_fabricating_project_content(tmp_path):
    runtime = build_full_unified_runtime(ToolAgentRuntime(registry=registry_for(tmp_path), provider=OverviewDecisions()))
    result = runtime.run("说一下目前的项目")
    assert result.status == "refused"
    assert result.answer is None and result.evidence == ()
    assert result.tool_calls_used == 1
    assert result.tool_errors_used == 0
    assert result.iterations_used <= 5


def test_document_reader_limits_are_retained_and_activity_exposes_only_count(tmp_path):
    (tmp_path / "README.md").write_text("intro\n" * 200 + "UNREAD_FOOTER\n", encoding="utf-8")
    executor = ToolExecutor(registry_for(tmp_path))
    info = executor.execute(ToolCall.create("get_project_info", {"include_documentation": True}))
    read = executor.execute(ToolCall.create("read_project_context", {
        "path": info.result["documentation_entrypoints"][0], "target": {"kind": "file", "start_line": 1},
    }))
    assert read.result["targets"][0]["content_complete"] is False
    assert read.result["targets"][0]["next_line"] == 121
    assert len(read.result["regions"][0]["lines"]) == 120
    assert "UNREAD_FOOTER" not in json.dumps(read.result)
    event = build_tool_activity_event(activity_id="A1", iteration=1, tool_name="get_project_info",
        state="completed", arguments={"include_documentation": True}, observation=info).to_dict()
    assert event["result_summary"] == {"available": True, "document_entrypoint_count": 1, "truncated": False}
    assert "README.md" not in json.dumps(event) and str(tmp_path) not in json.dumps(event)
