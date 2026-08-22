"""Contract tests for bounded candidate test discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.tool_agent import (
    AgentDecisionOutcome,
    FIND_TESTS_SPEC,
    FinalAnswerAction,
    FindTestsHandler,
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    ToolAgentRuntime,
    ToolCall,
    ToolCallAction,
    ToolExecutor,
    ToolRegistry,
    build_readonly_tool_registry,
    is_test_path,
)
from core.tool_agent.tools import test_discovery
import os
import subprocess


def _executor(repo: Path) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(FIND_TESTS_SPEC, FindTestsHandler(repo))
    return ToolExecutor(registry)


def _find(repo: Path, path: str):
    return _executor(repo).execute(ToolCall.create("find_tests", {"path": path}))


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True
    )


def test_python_filename_match_and_content_reference(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text(
        "def test_service():\n    assert Service()\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "checkout_flow.py").write_text(
        "def test_checkout():\n    service = Service()\n", encoding="utf-8"
    )

    obs = _find(tmp_path, "src/service.py")

    assert obs.status == "ok"
    assert obs.result["candidates"] == [
        {
            "path": "tests/test_service.py",
            "line": 1,
            "reasons": ["filename_match", "content_reference"],
        },
        {
            "path": "tests/checkout_flow.py",
            "line": 2,
            "reasons": ["content_reference"],
        },
    ]


def test_java_main_test_mirror_is_ranked_first(tmp_path: Path):
    source = tmp_path / "src" / "main" / "java" / "a" / "b"
    source.mkdir(parents=True)
    (source / "OwnerController.java").write_text("class OwnerController {}\n", encoding="utf-8")
    mirrored = tmp_path / "src" / "test" / "java" / "a" / "b"
    mirrored.mkdir(parents=True)
    (mirrored / "OwnerControllerTests.java").write_text(
        "class OwnerControllerTests {}\n", encoding="utf-8"
    )

    obs = _find(tmp_path, "src/main/java/a/b/OwnerController.java")

    assert obs.status == "ok"
    assert obs.result["candidates"] == [
        {
            "path": "src/test/java/a/b/OwnerControllerTests.java",
            "line": 1,
            "reasons": ["mirrored_path", "filename_match", "content_reference"],
        }
    ]


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_service.py",
        "src/test/java/a/FooTests.java",
        "src/app.test.ts",
        "src/app.spec.tsx",
        "pkg/service_test.go",
        "src/FooTest.cs",
    ],
)
def test_common_test_path_conventions(path: str):
    assert is_test_path(path)


def test_deterministic_ranking_and_maximum_ten(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    for index in range(12):
        (tests / f"test_service_{index:02d}.py").write_text(
            "def test_service():\n    pass\n", encoding="utf-8"
        )
    monkeypatch.setattr(test_discovery, "MAX_TEST_CANDIDATES", 10)

    first = _find(tmp_path, "src/service.py")
    second = _find(tmp_path, "src/service.py")

    assert first.status == "ok"
    assert first.result == second.result
    assert first.result["returned_count"] == 10
    assert len(first.result["candidates"]) == 10
    assert first.result["truncated"] is True
    assert [item["path"] for item in first.result["candidates"]] == [
        f"tests/test_service_{index:02d}.py" for index in range(10)
    ]


def test_no_test_found_returns_empty(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "unrelated.py").write_text("pass\n", encoding="utf-8")

    obs = _find(tmp_path, "src/unknown.py")

    assert obs.status == "ok"
    assert obs.result == {
        "candidates": [],
        "returned_count": 0,
        "truncated": False,
        "omitted_sensitive_count": 0,
    }


def test_deleted_or_nonexistent_source_path_still_discovers_tests(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_old_service.py").write_text(
        "def test_old_service():\n    pass\n", encoding="utf-8"
    )

    obs = _find(tmp_path, "src/OldService.java")

    assert obs.status == "ok"
    assert obs.result["candidates"][0]["path"] == "tests/test_old_service.py"


@pytest.mark.parametrize(
    "path",
    ["../service.py", "/service.py", "C:/service.py", "secret_config.py", "src/\x00service.py"],
)
def test_source_path_security_is_rejected(tmp_path: Path, path: str):
    obs = _find(tmp_path, path)
    assert obs.status == "error"
    assert obs.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED


def test_sensitive_candidates_are_omitted_without_reading(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "secret_test.py").write_text("TOKEN=do-not-read\n", encoding="utf-8")
    (tests / "test_service.py").write_text("pass\n", encoding="utf-8")

    obs = _find(tmp_path, "src/service.py")

    assert obs.status == "ok"
    assert obs.result["omitted_sensitive_count"] == 1
    assert all(item["path"] != "tests/secret_test.py" for item in obs.result["candidates"])


def test_large_binary_and_symlink_candidates_are_skipped(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_service.py").write_bytes(b"\x00\x01binary")
    (tests / "test_large_service.py").write_text(
        "x" * (test_discovery.MAX_FILE_SIZE + 1), encoding="utf-8"
    )
    outside = tmp_path / "outside.py"
    outside.write_text("Service()\n", encoding="utf-8")
    link = tests / "test_link_service.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        link = None

    obs = _find(tmp_path, "src/service.py")

    assert obs.status == "ok"
    assert obs.result["candidates"] == []
    if link is not None:
        assert all(item["path"] != "tests/test_link_service.py" for item in obs.result["candidates"])


class _EmptyRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


class _ScriptedProvider:
    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def decide(self, registry, user_query, *, context=()):
        decision = self._decisions[self.calls]
        self.calls += 1
        if callable(decision):
            decision = decision(registry, user_query, context)
        return AgentDecisionOutcome(
            action=decision, failure_code=None, call_metadata=None
        )


def test_changed_diff_find_tests_read_test_final_uses_four_calls_five_iterations(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    service = repo / "src" / "service.py"
    service.write_text("return old\n", encoding="utf-8")
    (repo / "tests" / "test_service.py").write_text(
        "def test_service():\n    assert service() == 'new'\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    service.write_text("return new\n", encoding="utf-8")

    def choose_diff(_registry, _query, context):
        assert context[-1].tool_name == "changed_files"
        return ToolCallAction(
            action="tool_call",
            tool_name="git_diff",
            arguments={"mode": "working_tree", "path": "src/service.py"},
        )

    def choose_tests(_registry, _query, context):
        assert context[-1].tool_name == "git_diff"
        return ToolCallAction(
            action="tool_call",
            tool_name="find_tests",
            arguments={"path": "src/service.py"},
        )

    def read_test(_registry, _query, context):
        result = context[-1].observation_result
        assert context[-1].tool_name == "find_tests"
        candidate = result["candidates"][0]
        assert candidate["path"] == "tests/test_service.py"
        return ToolCallAction(
            action="tool_call",
            tool_name="read_project_context",
            arguments={
                "path": candidate["path"],
                "line": candidate["line"],
                "context_lines": 1,
            },
        )

    provider = _ScriptedProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="changed_files",
                arguments={"mode": "working_tree"},
            ),
            choose_diff,
            choose_tests,
            read_test,
            FinalAnswerAction("final_answer", "The change has a candidate test."),
        ]
    )
    result = ToolAgentRuntime(
        registry=build_readonly_tool_registry(repo, _EmptyRetrievalPort()),
        provider=provider,
    ).run("Which test may relate to this change?")

    assert result.status == "completed"
    assert result.tool_calls_used == 4
    assert result.iterations_used == 5
    assert [item.kind for item in result.evidence] == ["project_change", "project_test"]
    assert [item.path for item in result.evidence] == [
        "src/service.py",
        "tests/test_service.py",
    ]
    assert all("\\" not in item.path for item in result.evidence)
