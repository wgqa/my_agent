"""Contract tests for bounded Git change evidence tools.

These tests use temporary repositories and scripted decisions only. They do
not call a provider, build a vector index, or execute a sealed benchmark.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from core.tool_agent import (
    AgentDecisionOutcome,
    CHANGED_FILES_SPEC,
    FinalAnswerAction,
    GIT_DIFF_SPEC,
    GIT_DIFF_UNAVAILABLE,
    GIT_PATH_NOT_ALLOWED,
    GIT_REF_INVALID,
    GIT_REPOSITORY_UNAVAILABLE,
    GitDiffHandler,
    ChangedFilesHandler,
    ToolAgentRuntime,
    ToolCall,
    ToolCallAction,
    ToolExecutionError,
    ToolExecutor,
    ToolRegistry,
    build_readonly_tool_registry,
)
from core.tool_agent.tools import git_change


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _new_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _git_executor(repo: Path) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(CHANGED_FILES_SPEC, ChangedFilesHandler(repo))
    registry.register(GIT_DIFF_SPEC, GitDiffHandler(repo))
    return ToolExecutor(registry)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = _new_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("return old\n", encoding="utf-8")
    _commit(repo, "initial")
    return repo


def test_working_tree_change_is_located_then_read(git_repo: Path):
    (git_repo / "src" / "app.py").write_text("return new\n", encoding="utf-8")
    executor = _git_executor(git_repo)

    located = executor.execute(ToolCall.create("changed_files", {"mode": "working_tree"}))
    assert located.status == "ok"
    assert located.result["changes"] == [{"path": "src/app.py", "status": "modified"}]

    diff = executor.execute(
        ToolCall.create(
            "git_diff",
            {"mode": "working_tree", "path": "src/app.py"},
        )
    )
    assert diff.status == "ok"
    assert diff.result["path"] == "src/app.py"
    assert "-return old" in diff.result["diff"]
    assert "+return new" in diff.result["diff"]
    assert diff.result["start_line"] >= 1


def test_commit_range_reports_added_deleted_and_renamed(tmp_path: Path):
    repo = _new_repo(tmp_path)
    (repo / "old.txt").write_text("rename me\n", encoding="utf-8")
    (repo / "gone.txt").write_text("delete me\n", encoding="utf-8")
    base = _commit(repo, "initial")

    (repo / "old.txt").rename(repo / "new.txt")
    (repo / "gone.txt").unlink()
    (repo / "added.txt").write_text("new file\n", encoding="utf-8")
    head = _commit(repo, "changes")

    obs = _git_executor(repo).execute(
        ToolCall.create(
            "changed_files",
            {"mode": "commit_range", "base_ref": base, "head_ref": head},
        )
    )
    assert obs.status == "ok"
    changes = {item["path"]: item for item in obs.result["changes"]}
    assert changes["added.txt"]["status"] == "added"
    assert changes["gone.txt"]["status"] == "deleted"
    assert changes["new.txt"] == {
        "path": "new.txt",
        "status": "renamed",
        "old_path": "old.txt",
    }
    diff = _git_executor(repo).execute(
        ToolCall.create(
            "git_diff",
            {
                "mode": "commit_range",
                "base_ref": base,
                "head_ref": head,
                "path": "new.txt",
            },
        )
    )
    assert diff.status == "ok"
    assert "+rename me" in diff.result["diff"]


def test_invalid_refs_option_like_refs_and_non_git_root(tmp_path: Path):
    repo = _new_repo(tmp_path)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _commit(repo, "initial")
    executor = _git_executor(repo)

    for base_ref in ("does-not-exist", "--output=/tmp/leak"):
        obs = executor.execute(
            ToolCall.create(
                "changed_files",
                {
                    "mode": "commit_range",
                    "base_ref": base_ref,
                    "head_ref": "HEAD",
                },
            )
        )
        assert obs.error_code == GIT_REF_INVALID

    non_git = tmp_path / "plain"
    non_git.mkdir()
    obs = _git_executor(non_git).execute(
        ToolCall.create("changed_files", {"mode": "working_tree"})
    )
    assert obs.error_code == GIT_REPOSITORY_UNAVAILABLE


@pytest.mark.parametrize("path", ["../a.txt", "/absolute/a.txt", "C:/absolute/a.txt"])
def test_path_escape_is_rejected(git_repo: Path, path: str):
    obs = _git_executor(git_repo).execute(
        ToolCall.create("git_diff", {"mode": "working_tree", "path": path})
    )
    assert obs.error_code == GIT_PATH_NOT_ALLOWED


def test_symlink_escape_is_rejected(git_repo: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret\n", encoding="utf-8")
    link = git_repo / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this Windows test environment")

    obs = _git_executor(git_repo).execute(
        ToolCall.create(
            "git_diff", {"mode": "working_tree", "path": "link.txt"}
        )
    )
    assert obs.error_code == GIT_PATH_NOT_ALLOWED


def test_sensitive_changes_are_counted_but_not_returned(git_repo: Path):
    (git_repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    executor = _git_executor(git_repo)

    listed = executor.execute(
        ToolCall.create("changed_files", {"mode": "working_tree"})
    )
    assert listed.status == "ok"
    assert listed.result["changes"] == []
    assert listed.result["omitted_sensitive_count"] == 1

    diff = executor.execute(
        ToolCall.create(
            "git_diff", {"mode": "working_tree", "path": ".env"}
        )
    )
    assert diff.error_code == GIT_PATH_NOT_ALLOWED
    assert "TOKEN=secret" not in str(diff.to_dict())


def test_changed_files_output_is_bounded(git_repo: Path):
    for index in range(105):
        (git_repo / f"new-{index:03d}.txt").write_text("x\n", encoding="utf-8")
    obs = _git_executor(git_repo).execute(
        ToolCall.create("changed_files", {"mode": "working_tree"})
    )
    assert obs.status == "ok"
    assert obs.result["total_count"] == 105
    assert obs.result["returned_count"] == 100
    assert len(obs.result["changes"]) == 100
    assert obs.result["truncated"] is True


def test_diff_output_is_bounded(git_repo: Path):
    path = git_repo / "src" / "large.txt"
    path.write_text("old\n", encoding="utf-8")
    _commit(git_repo, "large base")
    path.write_text("".join(f"line {i}\n" for i in range(1000)), encoding="utf-8")

    obs = _git_executor(git_repo).execute(
        ToolCall.create(
            "git_diff", {"mode": "working_tree", "path": "src/large.txt"}
        )
    )
    assert obs.status == "ok"
    assert len(obs.result["diff"]) <= git_change.MAX_DIFF_CHARS
    assert len(obs.result["diff"].splitlines()) <= git_change.MAX_DIFF_LINES
    assert obs.result["truncated"] is True


def test_binary_diff_is_bounded_and_safe(git_repo: Path):
    path = git_repo / "blob.bin"
    path.write_bytes(b"\x00\x01old\x00")
    _commit(git_repo, "binary base")
    path.write_bytes(b"\x00\x02new\x00")

    obs = _git_executor(git_repo).execute(
        ToolCall.create("git_diff", {"mode": "working_tree", "path": "blob.bin"})
    )
    assert obs.status == "ok"
    assert len(obs.result["diff"]) <= git_change.MAX_DIFF_CHARS
    assert "Binary files" in obs.result["diff"]


def test_untracked_path_is_located_but_never_read_as_diff(git_repo: Path):
    path = git_repo / "untracked.txt"
    path.write_text("DO_NOT_READ_THIS\n", encoding="utf-8")
    executor = _git_executor(git_repo)
    listed = executor.execute(
        ToolCall.create("changed_files", {"mode": "working_tree"})
    )
    assert {item["status"] for item in listed.result["changes"]} == {"untracked"}

    diff = executor.execute(
        ToolCall.create(
            "git_diff", {"mode": "working_tree", "path": "untracked.txt"}
        )
    )
    assert diff.error_code == GIT_DIFF_UNAVAILABLE
    assert "DO_NOT_READ_THIS" not in str(diff.to_dict())


def test_git_failures_have_stable_codes_and_unknown_errors_propagate(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    handler = ChangedFilesHandler(git_repo)
    monkeypatch.setattr(
        git_change, "_capture_process", lambda *args, **kwargs: (b"", 1, False)
    )
    with pytest.raises(ToolExecutionError) as exc_info:
        handler.execute({"mode": "working_tree"})
    assert exc_info.value.error_code == GIT_REPOSITORY_UNAVAILABLE

    def programming_bug(*args, **kwargs):
        raise RuntimeError("programming bug")

    monkeypatch.setattr(git_change, "_capture_process", programming_bug)
    with pytest.raises(RuntimeError, match="programming bug"):
        handler.execute({"mode": "working_tree"})


class _EmptyRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


class _ScriptedProvider:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def decide(self, registry, user_query, *, context=()):
        decision = self.decisions[self.calls]
        self.calls += 1
        if callable(decision):
            decision = decision(registry, user_query, context)
        return AgentDecisionOutcome(action=decision, failure_code=None, call_metadata=None)


def test_changed_files_git_diff_final_vertical_slice(git_repo: Path):
    (git_repo / "src" / "app.py").write_text("return changed\n", encoding="utf-8")

    def read_diff(registry, user_query, context):
        located = context[-1].observation_result
        assert located["changes"] == [{"path": "src/app.py", "status": "modified"}]
        return ToolCallAction(
            action="tool_call",
            tool_name="git_diff",
            arguments={"mode": "working_tree", "path": "src/app.py"},
        )

    provider = _ScriptedProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="changed_files",
                arguments={"mode": "working_tree"},
            ),
            read_diff,
            FinalAnswerAction("final_answer", "The change is in src/app.py."),
        ]
    )
    runtime = ToolAgentRuntime(
        registry=build_readonly_tool_registry(git_repo, _EmptyRetrievalPort()),
        provider=provider,
    )
    result = runtime.run("What changed?")

    assert result.status == "completed"
    assert result.tool_calls_used == 2
    assert result.answer == "The change is in src/app.py."
    assert len(result.evidence) == 1
    assert result.evidence[0].kind == "project_change"
    assert result.evidence[0].path == "src/app.py"
    assert "-return old" in result.evidence[0].snippet
    assert "+return changed" in result.evidence[0].snippet
