"""Archived v6 candidate safety and recovery; production deliberately stays v5."""
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace
import types

import pytest

from core.tool_agent import (
    AgentDecisionOutcome, FinalAnswerAction, INVALID_TOOL_ARGUMENTS,
    PROJECT_CONTEXT_PATH_NOT_ALLOWED, ToolAgentBudget, ToolAgentRuntime,
    ToolCall, ToolCallAction, ToolExecutor, ToolRegistry,
)
from core.tool_agent.activity import build_tool_activity_event
from evaluation.source_search_v6_20261003.candidate import CODE_SEARCH_SPEC, CodeSearchHandler
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler,
)


def put(root, path, content="target\n"):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return file


def executor_for(root):
    registry = ToolRegistry()
    registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(root))
    registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(root))
    return ToolExecutor(registry)


def search(executor, **arguments):
    return executor.execute(ToolCall.create("code_search", {"query": "target", **arguments}))


@pytest.mark.parametrize("scope", ["src", "./src/", "src\\", "src/./"])
def test_directory_scope_is_normalized_and_respects_component_boundary(tmp_path, scope):
    put(tmp_path, "src/a.py", "TARGET\n")
    put(tmp_path, "src/nested/z.md")
    put(tmp_path, "src_backup/a.py")
    put(tmp_path, "docs/a.md")
    result = search(executor_for(tmp_path), scope=scope).result
    assert result["scope"] == "src" and result["truncated"] is False
    assert [item["path"] for item in result["matches"]] == ["src/a.py", "src/nested/z.md"]


def test_file_scope_and_kind_filter_compose(tmp_path):
    put(tmp_path, "src/a.py")
    put(tmp_path, "src/b.py")
    put(tmp_path, "docs/a.md")
    executor = executor_for(tmp_path)
    assert [m["path"] for m in search(executor, scope="src/a.py").result["matches"]] == ["src/a.py"]
    assert search(executor, scope="src", artifact_kind="project_doc").result["matches"] == []
    assert [m["path"] for m in search(executor, scope="docs", artifact_kind="project_doc").result["matches"]] == ["docs/a.md"]


@pytest.mark.parametrize("count", [0, 9, 10, 11, 25])
def test_truncation_requires_one_more_eligible_matching_line(tmp_path, count):
    put(tmp_path, "src/a.py", "target\n" * count + "unmatched\n" * 12)
    result = search(executor_for(tmp_path), scope="src").result
    assert len(result["matches"]) == min(count, 10)
    assert result["truncated"] is (count > 10)


def test_lookahead_crosses_files_but_not_scope_kind_or_size_boundaries(tmp_path):
    put(tmp_path, "src/a.py", "target\n" * 10)
    put(tmp_path, "src/z.md")
    put(tmp_path, "docs/a.md")
    put(tmp_path, "src/huge.py", "target\n" + "x" * (1024 * 1024))
    put(tmp_path, "src/secret_token.py")
    put(tmp_path, "src/node_modules/a.py")
    put(tmp_path, "src/.hidden/a.py")
    executor = executor_for(tmp_path)
    assert search(executor, scope="src", artifact_kind="project_code").result["truncated"] is False
    assert search(executor, scope="src").result["truncated"] is True
    put(tmp_path, "src/z.py")
    assert search(executor, scope="src", artifact_kind="project_code").result["truncated"] is True


@pytest.mark.parametrize("scope", ["missing", "missing/file.py"])
def test_missing_scope_returns_empty_without_falling_back_to_project(tmp_path, scope):
    put(tmp_path, "src/a.py")
    assert search(executor_for(tmp_path), scope=scope).result == {
        "matches": [], "scope": scope, "truncated": False,
    }


@pytest.mark.parametrize("scope", [
    "../outside", "src/../a.py", "/src", "C:/src", "C:src", "\\src",
    "\\\\server\\share", "src//a.py", "src/a.py:stream", " src", "src\n",
    "node_modules./a.py", "node_modules /a.py", "src/a.py.",
])
def test_disallowed_scopes_return_safe_error(tmp_path, scope):
    result = search(executor_for(tmp_path), scope=scope)
    assert result.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED
    assert result.result is None


@pytest.mark.parametrize("scope", [None, True, 1, "", "x" * 501])
def test_scope_schema_is_strict(tmp_path, scope):
    assert search(executor_for(tmp_path), scope=scope).error_code == INVALID_TOOL_ARGUMENTS


@pytest.mark.parametrize("scope", [
    "node_modules", "node_modules/a.py", "NODE_MODULES/a.py", ".hidden", ".hidden/a.py",
    "src/.hidden/a.py", "src/secret_token.py", ".env", "src/a.bin",
])
def test_explicit_scope_cannot_bypass_discovery_exclusions(tmp_path, scope):
    if scope in ("node_modules", ".hidden"):
        put(tmp_path, scope + "/a.py")
    else:
        put(tmp_path, scope)
    assert search(executor_for(tmp_path), scope=scope).error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("outside", [False, True])
def test_file_and_directory_links_are_rejected_even_when_pointing_inside(tmp_path, directory, outside):
    root = tmp_path / "repo"
    root.mkdir()
    target = put(tmp_path if outside else root, "src/a.py")
    link = root / ("alias" if directory else "alias.py")
    try:
        link.symlink_to(target.parent if directory else target, target_is_directory=directory)
    except OSError:
        pytest.skip("This Windows account cannot create filesystem symlinks")
    executor = executor_for(root)
    for scope in (["alias", "alias/a.py"] if directory else ["alias.py"]):
        assert search(executor, scope=scope).error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED
    assert all(not m["path"].startswith("alias") for m in search(executor).result["matches"])


def test_legacy_matches_are_identical_to_frozen_v5(tmp_path):
    snapshot = Path(__file__).resolve().parents[1] / "evaluation/source_search_v6_20261003/snapshots/code_search_v5.snapshot"
    baseline = types.ModuleType("search_v5_snapshot")
    exec(compile(snapshot.read_text(encoding="utf-8"), str(snapshot), "exec"), baseline.__dict__)
    for path, content in {
        "README.md": "target\n", "src/z.py": "TARGET\n" * 14,
        "src/a.py": "target = 1\n# other\n", "docs/a.md": "target\n",
        "examples/a.py": "target\n", "tests/test_a.py": "target\n",
        "node_modules/noise.py": "target\n", "secret_token.py": "target\n",
    }.items():
        put(tmp_path, path, content)
    old, new = baseline.CodeSearchHandler(tmp_path), CodeSearchHandler(tmp_path)
    for query in ("target", "TARGET", "other", "absent"):
        for kind in (None, "any", "project_code", "project_doc"):
            args = {"query": query, **({"artifact_kind": kind} if kind else {})}
            result = new.execute(args)
            assert result["matches"] == old.execute(args)["matches"]
            assert result == new.execute({**args, "scope": "."})


def test_unproven_candidate_is_not_promoted_into_default_registry():
    from core.tool_agent.default_tools import CODE_SEARCH_SPEC as live_spec
    assert live_spec.version == "code_search_v5"
    assert "scope" not in live_spec.input_schema["properties"]
    assert CODE_SEARCH_SPEC.version == "code_search_v6"
    assert "scope" not in CODE_SEARCH_SPEC.input_schema["required"]


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
@pytest.mark.parametrize("outside", [False, True])
def test_windows_junction_scope_cannot_bypass_ancestor_checks(tmp_path, outside):
    root = tmp_path / "repo"
    root.mkdir()
    target = put(tmp_path if outside else root, "src/a.py").parent
    junction = root / "alias"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True, check=False,
    )
    assert created.returncode == 0 and junction.is_junction()
    executor = executor_for(root)
    for scope in ("alias", "alias/a.py"):
        assert search(executor, scope=scope).error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED
    assert all(not m["path"].startswith("alias") for m in search(executor).result["matches"])


@pytest.mark.parametrize("scope", ["src/a.py", ".", "../outside", "C:/private/a.py", "api_key=secret"])
def test_activity_exposes_only_safe_scope_and_boolean_truncation(scope):
    event = build_tool_activity_event(
        activity_id="A1", iteration=1, tool_name="code_search", state="completed",
        arguments={"query": "target", "scope": scope},
        observation=SimpleNamespace(result={"matches": [], "truncated": True}, error_code=None),
    ).to_dict()
    assert event["target"] == {"query": "target", **({"scope": scope} if scope in ("src/a.py", ".") else {})}
    assert event["result_summary"] == {"match_count": 0, "top_paths": [], "truncated": True}


def test_runtime_recovers_from_truncation_then_reads_definition_with_existing_budget(tmp_path):
    put(tmp_path, "examples/a.py", "# process example\n" * 11)
    put(tmp_path, "src/service.py", "def process(value):\n    return value + 1\n")
    registry = ToolRegistry()
    registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(tmp_path))
    registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(tmp_path))

    class Provider:
        def decide(self, registry, query, *, context=()):
            if not context:
                action = ToolCallAction(action="tool_call", tool_name="code_search", arguments={"query": "process", "artifact_kind": "project_code"})
            elif len(context) == 1:
                result = context[-1].observation_result
                assert result["truncated"] is True and result["scope"] == "."
                action = ToolCallAction(action="tool_call", tool_name="code_search", arguments={"query": "process", "artifact_kind": "project_code", "scope": "src"})
            elif len(context) == 2:
                match = context[-1].observation_result["matches"][0]
                assert match["path"] == "src/service.py"
                action = ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": match["path"], "line": match["line"], "context_lines": 0, "mode": "definition"})
            else:
                assert context[-1].observation_result["content_complete"] is True
                action = FinalAnswerAction(action="final_answer", answer="process 返回 value + 1。[E1]")
            return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)

    result = ToolAgentRuntime(registry=registry, provider=Provider()).run("说明 src 内 process 的实际实现")
    assert result.status == "completed"
    assert (result.iterations_used, result.tool_calls_used, result.tool_errors_used) == (4, 3, 0)
    assert len(result.evidence) == 1 and result.evidence[0].path == "src/service.py"
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
