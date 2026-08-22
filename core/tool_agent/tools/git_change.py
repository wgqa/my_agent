"""Bounded, read-only Git change evidence for the injected Engineering Project.

The model can choose a comparison mode and a repo-relative path, but it never
chooses a repository root, shell command, or arbitrary Git arguments. Git refs
are resolved to commit IDs before they are used for a diff. ``changed_files``
locates changed paths; ``git_diff`` reads one already changed tracked path.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.tool_agent.models import (
    GIT_COMMAND_FAILED,
    GIT_DIFF_UNAVAILABLE,
    GIT_PATH_NOT_ALLOWED,
    GIT_REF_INVALID,
    GIT_REPOSITORY_UNAVAILABLE,
    ToolExecutionError,
    ToolSpec,
)
from core.tool_agent.tools.code_search import _is_secret_file, is_path_within


CHANGED_FILES_VERSION = "changed_files_v1"
GIT_DIFF_VERSION = "git_diff_v1"
MAX_CHANGED_FILES = 100
MAX_REF_LENGTH = 200
MAX_PATH_LENGTH = 500
MAX_DIFF_CHARS = 20_000
MAX_DIFF_LINES = 400
MAX_GIT_CAPTURE_BYTES = MAX_DIFF_CHARS * 8
GIT_MODES = ("working_tree", "commit_range")
CHANGE_STATUSES = ("modified", "added", "deleted", "renamed", "untracked")


def _mode_schema() -> dict:
    return {"type": "string", "enum": list(GIT_MODES)}


def _ref_schema() -> dict:
    return {"type": "string", "minLength": 1, "maxLength": MAX_REF_LENGTH}


def _mode_input_schema(*, include_path: bool) -> dict:
    properties: dict[str, Any] = {"mode": _mode_schema()}
    if include_path:
        properties["path"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PATH_LENGTH,
        }
    properties.update({"base_ref": _ref_schema(), "head_ref": _ref_schema()})
    working: dict[str, Any] = {
        "properties": {"mode": {"const": "working_tree"}},
        "required": ["mode"],
        "not": {
            "anyOf": [
                {"required": ["base_ref"]},
                {"required": ["head_ref"]},
            ]
        },
    }
    commit_range: dict[str, Any] = {
        "properties": {"mode": {"const": "commit_range"}},
        "required": ["mode", "base_ref", "head_ref"],
    }
    if include_path:
        working["required"].append("path")
        commit_range["required"].append("path")
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "oneOf": [working, commit_range],
    }


CHANGED_FILES_INPUT_SCHEMA = _mode_input_schema(include_path=False)
GIT_DIFF_INPUT_SCHEMA = _mode_input_schema(include_path=True)

CHANGED_FILES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "maxItems": MAX_CHANGED_FILES,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "status": {
                        "type": "string",
                        "enum": list(CHANGE_STATUSES),
                    },
                    "old_path": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
                "required": ["path", "status"],
            },
        },
        "total_count": {"type": "integer", "minimum": 0},
        "returned_count": {"type": "integer", "minimum": 0},
        "truncated": {"type": "boolean"},
        "omitted_sensitive_count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
    "required": [
        "changes",
        "total_count",
        "returned_count",
        "truncated",
        "omitted_sensitive_count",
    ],
}

GIT_DIFF_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "mode": {"type": "string", "enum": list(GIT_MODES)},
        "truncated": {"type": "boolean"},
        "diff": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_DIFF_CHARS,
        },
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
    },
    "additionalProperties": False,
    "required": [
        "path",
        "mode",
        "truncated",
        "diff",
        "start_line",
        "end_line",
    ],
}

CHANGED_FILES_SPEC = ToolSpec(
    name="changed_files",
    description=(
        "列出当前绑定 Engineering Project 的有限 Git 变更文件。mode=working_tree "
        "比较 HEAD 与当前 tracked working tree，并标记 untracked path；"
        "mode=commit_range 比较已解析的 base_ref 到 head_ref。只返回 repo-relative "
        "path + status，不读取 untracked 文件正文，也不返回整个 diff。敏感文件只计入 "
        "omitted_sensitive_count。发现具体文件后，再调用 git_diff 读取单文件变更。"
    ),
    input_schema=CHANGED_FILES_INPUT_SCHEMA,
    output_schema=CHANGED_FILES_OUTPUT_SCHEMA,
    version=CHANGED_FILES_VERSION,
)

GIT_DIFF_SPEC = ToolSpec(
    name="git_diff",
    description=(
        "读取当前绑定 Engineering Project 中一个已由 changed_files 定位的、"
        "repo-relative tracked path 的 bounded unified diff。一次只能读取一个文件，"
        "固定限制输出字符数和行数；支持 working_tree 与 commit_range。不要传绝对路径、"
        "..、敏感文件、untracked path 或整个仓库。"
    ),
    input_schema=GIT_DIFF_INPUT_SCHEMA,
    output_schema=GIT_DIFF_OUTPUT_SCHEMA,
    version=GIT_DIFF_VERSION,
)


@dataclass(frozen=True)
class _Change:
    path: str
    status: str
    old_path: str | None = None


def _safe_repo_path(raw_path: object) -> str:
    if (
        type(raw_path) is not str
        or not raw_path.strip()
        or raw_path != raw_path.strip()
        or len(raw_path) > MAX_PATH_LENGTH
        or any(ord(char) < 32 for char in raw_path)
    ):
        raise ToolExecutionError(GIT_PATH_NOT_ALLOWED)
    raw_parts = raw_path.split("/")
    if "\\" in raw_path or any(part in ("", ".", "..") for part in raw_parts):
        raise ToolExecutionError(GIT_PATH_NOT_ALLOWED)
    posix = PurePosixPath(raw_path)
    windows = PureWindowsPath(raw_path)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ToolExecutionError(GIT_PATH_NOT_ALLOWED)
    return posix.as_posix()


def _safe_ref(raw_ref: object) -> str:
    if (
        type(raw_ref) is not str
        or not raw_ref.strip()
        or raw_ref != raw_ref.strip()
        or len(raw_ref) > MAX_REF_LENGTH
        or raw_ref.startswith("-")
        or any(char.isspace() or ord(char) < 32 for char in raw_ref)
    ):
        raise ToolExecutionError(GIT_REF_INVALID)
    return raw_ref


def _path_is_sensitive(path: str) -> bool:
    return _is_secret_file(PurePosixPath(path).name)


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _capture_process(
    args: list[str],
    root: Path,
    *,
    max_bytes: int,
) -> tuple[bytes, int, bool]:
    """Run a fixed argv process while bounding stdout retained in memory."""

    try:
        process = subprocess.Popen(
            args,
            cwd=os.fspath(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise ToolExecutionError(GIT_REPOSITORY_UNAVAILABLE) from None

    chunks: list[bytes] = []
    size = 0
    truncated = False
    assert process.stdout is not None
    while True:
        chunk = process.stdout.read(8192)
        if not chunk:
            break
        remaining = max_bytes - size
        if len(chunk) > remaining:
            if remaining > 0:
                chunks.append(chunk[:remaining])
                size += remaining
            truncated = True
            process.kill()
            break
        chunks.append(chunk)
        size += len(chunk)

    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
    return b"".join(chunks), process.returncode, truncated


class _GitHandlerBase:
    def __init__(self, repo_root: str | os.PathLike) -> None:
        root = Path(repo_root)
        if not root.is_dir():
            raise ValueError(f"repo_root 不是目录：{root}")
        self._root = root.resolve()

    def _ensure_repository(self) -> None:
        output, returncode, _ = _capture_process(
            ["git", "rev-parse", "--is-inside-work-tree"],
            self._root,
            max_bytes=1024,
        )
        if returncode != 0 or _decode(output).strip() != "true":
            raise ToolExecutionError(GIT_REPOSITORY_UNAVAILABLE)
        top_level, top_returncode, top_truncated = _capture_process(
            ["git", "rev-parse", "--show-toplevel"],
            self._root,
            max_bytes=1024,
        )
        if top_returncode != 0 or top_truncated:
            raise ToolExecutionError(GIT_REPOSITORY_UNAVAILABLE)
        try:
            resolved_top_level = Path(_decode(top_level).strip()).resolve()
        except OSError:
            raise ToolExecutionError(GIT_REPOSITORY_UNAVAILABLE) from None
        if resolved_top_level != self._root:
            raise ToolExecutionError(GIT_REPOSITORY_UNAVAILABLE)

    def _resolve_commit(self, raw_ref: object) -> str:
        ref = _safe_ref(raw_ref)
        output, returncode, truncated = _capture_process(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            self._root,
            max_bytes=1024,
        )
        if returncode != 0 or truncated:
            raise ToolExecutionError(GIT_REF_INVALID)
        commit = _decode(output).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise ToolExecutionError(GIT_REF_INVALID)
        return commit

    def _comparison(
        self, arguments: Mapping[str, Any]
    ) -> tuple[str, str, str | None]:
        mode = arguments["mode"]
        self._ensure_repository()
        if mode == "working_tree":
            return mode, self._resolve_commit("HEAD"), None
        if mode == "commit_range":
            return (
                mode,
                self._resolve_commit(arguments["base_ref"]),
                self._resolve_commit(arguments["head_ref"]),
            )
        raise ToolExecutionError(GIT_REF_INVALID)

    def _name_status(
        self, mode: str, base_commit: str, head_commit: str | None
    ) -> tuple[list[_Change], bool]:
        args = [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--name-status",
            "-z",
            "--find-renames=50%",
            base_commit,
        ]
        if mode == "commit_range":
            assert head_commit is not None
            args.append(head_commit)
        args.append("--")
        output, returncode, truncated = _capture_process(
            args, self._root, max_bytes=MAX_GIT_CAPTURE_BYTES
        )
        if returncode != 0:
            raise ToolExecutionError(GIT_COMMAND_FAILED)
        changes = _parse_name_status(output)
        if mode == "working_tree":
            untracked_output, untracked_code, untracked_truncated = _capture_process(
                ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
                self._root,
                max_bytes=MAX_GIT_CAPTURE_BYTES,
            )
            if untracked_code != 0:
                raise ToolExecutionError(GIT_COMMAND_FAILED)
            truncated = truncated or untracked_truncated
            for raw_path in untracked_output.split(b"\0"):
                if not raw_path:
                    continue
                path = _decode(raw_path)
                if _valid_git_output_path(path):
                    changes.append(_Change(path=path, status="untracked"))
        return changes, truncated

    def _visible_changes(
        self, mode: str, base_commit: str, head_commit: str | None
    ) -> tuple[list[_Change], int, bool, int]:
        changes, capture_truncated = self._name_status(mode, base_commit, head_commit)
        changes.sort(key=lambda item: (item.path, item.status, item.old_path or ""))
        omitted_sensitive = 0
        visible: list[_Change] = []
        for change in changes:
            if _path_is_sensitive(change.path) or (
                change.old_path is not None and _path_is_sensitive(change.old_path)
            ):
                omitted_sensitive += 1
                continue
            visible.append(change)
        truncated = capture_truncated or len(visible) > MAX_CHANGED_FILES
        return visible[:MAX_CHANGED_FILES], len(changes), truncated, omitted_sensitive

    def _path_is_bound_change(
        self,
        path: str,
        mode: str,
        base_commit: str,
        head_commit: str | None,
    ) -> bool:
        changes, _ = self._name_status(mode, base_commit, head_commit)
        return any(path == change.path or path == change.old_path for change in changes)

    def _check_existing_path(self, path: str) -> None:
        candidate = self._root.joinpath(*PurePosixPath(path).parts)
        if not candidate.exists() and not candidate.is_symlink():
            return
        if candidate.is_symlink():
            raise ToolExecutionError(GIT_PATH_NOT_ALLOWED)
        try:
            resolved = candidate.resolve()
        except OSError:
            raise ToolExecutionError(GIT_PATH_NOT_ALLOWED) from None
        if not is_path_within(resolved, self._root):
            raise ToolExecutionError(GIT_PATH_NOT_ALLOWED)


def _valid_git_output_path(path: str) -> bool:
    if not path or "\\" in path or any(ord(char) < 32 for char in path):
        return False
    raw_parts = path.split("/")
    posix = PurePosixPath(path)
    return not (
        any(part in ("", ".", "..") for part in raw_parts)
        or posix.is_absolute()
    )


def _parse_name_status(output: bytes) -> list[_Change]:
    parts = output.split(b"\0")
    changes: list[_Change] = []
    index = 0
    while index < len(parts):
        if not parts[index]:
            index += 1
            continue
        status_token = _decode(parts[index])
        index += 1
        if status_token.startswith(("R", "C")):
            if index + 1 >= len(parts):
                break
            old_path = _decode(parts[index])
            new_path = _decode(parts[index + 1])
            index += 2
            if _valid_git_output_path(old_path) and _valid_git_output_path(new_path):
                changes.append(
                    _Change(
                        path=new_path,
                        status="renamed" if status_token.startswith("R") else "added",
                        old_path=old_path,
                    )
                )
            continue
        if index >= len(parts):
            break
        path = _decode(parts[index])
        index += 1
        if not _valid_git_output_path(path):
            continue
        status = {
            "M": "modified",
            "T": "modified",
            "U": "modified",
            "A": "added",
            "D": "deleted",
        }.get(status_token[:1])
        if status is not None:
            changes.append(_Change(path=path, status=status))
    return changes


def _sanitize_diff(text: str, root: Path) -> str:
    for source in (str(root), str(root).replace("\\", "/")):
        text = text.replace(source, "<repo>")
    return re.sub(
        r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\)[^\r\n\s]+",
        "<absolute-path>",
        text,
    )


def _diff_line_range(diff: str) -> tuple[int, int]:
    matches = list(
        re.finditer(
            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@",
            diff,
            flags=re.MULTILINE,
        )
    )
    if not matches:
        return 1, 1
    start = min(int(match.group(1)) for match in matches)
    end = start
    for match in matches:
        new_start = int(match.group(1))
        new_count = int(match.group(2) or "1")
        end = max(end, new_start + max(new_count, 1) - 1)
    return max(start, 1), max(end, start)


class ChangedFilesHandler(_GitHandlerBase):
    """Return bounded status/path records without reading file contents."""

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        mode, base_commit, head_commit = self._comparison(arguments)
        changes, total_count, truncated, omitted_sensitive = self._visible_changes(
            mode, base_commit, head_commit
        )
        serialized = []
        for change in changes:
            item = {"path": change.path, "status": change.status}
            if change.old_path is not None:
                item["old_path"] = change.old_path
            serialized.append(item)
        return {
            "changes": serialized,
            "total_count": total_count,
            "returned_count": len(serialized),
            "truncated": truncated,
            "omitted_sensitive_count": omitted_sensitive,
        }


class GitDiffHandler(_GitHandlerBase):
    """Return a bounded diff for exactly one already changed tracked path."""

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        path = _safe_repo_path(arguments["path"])
        if _path_is_sensitive(path):
            raise ToolExecutionError(GIT_PATH_NOT_ALLOWED)
        self._check_existing_path(path)
        mode, base_commit, head_commit = self._comparison(arguments)
        if not self._path_is_bound_change(path, mode, base_commit, head_commit):
            raise ToolExecutionError(GIT_DIFF_UNAVAILABLE)

        args = [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--find-renames=50%",
            "--unified=3",
            base_commit,
        ]
        if mode == "commit_range":
            assert head_commit is not None
            args.append(head_commit)
        args.extend(["--", path])
        raw_output, returncode, capture_truncated = _capture_process(
            args, self._root, max_bytes=MAX_GIT_CAPTURE_BYTES
        )
        if returncode != 0:
            raise ToolExecutionError(GIT_COMMAND_FAILED)
        raw_diff = _sanitize_diff(_decode(raw_output), self._root)
        raw_lines = raw_diff.splitlines(keepends=True)
        bounded = "".join(raw_lines[:MAX_DIFF_LINES])[:MAX_DIFF_CHARS]
        if not bounded:
            raise ToolExecutionError(GIT_DIFF_UNAVAILABLE)
        truncated = (
            capture_truncated
            or len(raw_diff) > len(bounded)
            or len(raw_lines) > MAX_DIFF_LINES
        )
        start_line, end_line = _diff_line_range(bounded)
        return {
            "path": path,
            "mode": mode,
            "truncated": truncated,
            "diff": bounded,
            "start_line": start_line,
            "end_line": end_line,
        }


__all__ = [
    "CHANGE_STATUSES",
    "CHANGED_FILES_INPUT_SCHEMA",
    "CHANGED_FILES_OUTPUT_SCHEMA",
    "CHANGED_FILES_SPEC",
    "ChangedFilesHandler",
    "GIT_DIFF_INPUT_SCHEMA",
    "GIT_DIFF_OUTPUT_SCHEMA",
    "GIT_DIFF_SPEC",
    "GitDiffHandler",
    "MAX_CHANGED_FILES",
    "MAX_DIFF_CHARS",
    "MAX_DIFF_LINES",
]
