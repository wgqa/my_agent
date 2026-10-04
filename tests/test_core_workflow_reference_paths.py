"""Real tools prove bounded reference paths; a scripted provider is not an LLM eval."""

from pathlib import Path
import shutil
import subprocess

import pytest

from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import ToolAgentBudget
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime
from ui.components import build_core_workflow_question


@pytest.fixture
def project(tmp_path):
    source = Path(__file__).resolve().parents[1] / "evaluation/core_workflows_20261004/fixture"
    target = tmp_path / "project"
    shutil.copytree(source, target)
    for command in (
        ["git", "init", "-q"], ["git", "add", "."],
        ["git", "-c", "user.name=Local Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline"],
    ):
        subprocess.run(command, cwd=target, check=True, capture_output=True)
    settings = target / "support_search/settings.py"
    settings.write_text(settings.read_text(encoding="utf-8").replace("DEFAULT_RESULT_LIMIT = 4", "DEFAULT_RESULT_LIMIT = 6"), encoding="utf-8")
    return target


class Decisions:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.states = []

    def decide(self, registry, question, *, context=(), control_state=None):
        self.states.append(control_state)
        return AgentDecisionOutcome(action=next(self.actions), failure_code=None, call_metadata=None)


def tool(name, **arguments):
    return ToolCallAction(action="tool_call", tool_name=name, arguments=arguments)


def read(path, line=1):
    return tool("read_project_context", path=path, line=line, context_lines=30)


def run(project, question, actions, answer):
    provider = Decisions([*actions, FinalAnswerAction(action="final_answer", answer=answer)])
    runtime = ToolAgentRuntime(
        registry=build_readonly_tool_registry(project, EmptyRetrievalPort()),
        provider=provider,
    )
    result = build_full_unified_runtime(runtime).run(question)
    assert result.status == "completed"
    assert result.tool_calls_used == len(actions)
    assert result.iterations_used == len(actions) + 1
    assert result.tool_errors_used == 0
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
    return result, provider


def test_configuration_values_and_call_site_fit_existing_budget(project):
    question = build_core_workflow_question("configuration", "SUPPORT_RESULT_LIMIT", "support_search/settings.py 与 support_search/service.py")
    result, _ = run(project, question, [read("support_search/settings.py"), read("support_search/service.py")],
                    "默认 6，环境变量覆盖，范围 1..20；越界 ValueError [E1]。search_help 将值作为 limit 传给 retriever.search [E2]。")
    assert {e.path for e in result.evidence} == {"support_search/settings.py", "support_search/service.py"}
    assert "DEFAULT_RESULT_LIMIT = 6" in result.evidence[0].snippet
    assert "retriever.search(query, limit=limit)" in result.evidence[1].snippet


def test_document_and_source_comparison_fit_existing_budget(project):
    question = build_core_workflow_question("docs_code", "README.md 默认值与范围", "support_search/settings.py")
    result, _ = run(project, question, [read("README.md"), read("support_search/settings.py")],
                    "文档默认 4 [E1]，源码默认 6 [E2]，存在冲突；两边的合法范围 1..20 一致 [E1][E2]。")
    assert {e.kind for e in result.evidence} == {"project_doc", "project_code"}
    assert "default result limit is 4" in result.evidence[0].snippet
    assert "DEFAULT_RESULT_LIMIT = 6" in result.evidence[1].snippet


def test_change_and_actual_test_read_fit_four_tool_calls(project):
    question = build_core_workflow_question("change_test", "support_search/settings.py")
    result, provider = run(project, question, [
        tool("changed_files", mode="working_tree"),
        tool("git_diff", mode="working_tree", path="support_search/settings.py"),
        tool("find_tests", path="support_search/settings.py"),
        read("tests/test_service.py"),
    ], "默认值从 4 改为 6 [E1]；现有默认值测试仍断言 limit=4，显式覆盖测试断言 9 [E2]。建议 python -m pytest tests/test_service.py::test_search_help_passes_default_limit；未执行。")
    assert {e.kind for e in result.evidence} == {"project_change", "project_test"}
    assert "test_search_help_passes_default_limit" in result.evidence[1].snippet
    assert result.tool_calls_used == 4 and result.iterations_used == 5
    assert provider.states[-1].tool_call_allowed is False
