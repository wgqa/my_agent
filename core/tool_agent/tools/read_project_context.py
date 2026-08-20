"""G6-VERTICAL-02: bounded read-only source context for an injected project root."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.tool_agent.models import (
    PROJECT_CONTEXT_FILE_NOT_FOUND,
    PROJECT_CONTEXT_FILE_UNREADABLE,
    PROJECT_CONTEXT_LINE_OUT_OF_RANGE,
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    ToolExecutionError,
    ToolSpec,
)
from core.tool_agent.tools.code_search import (
    ALLOWED_SUFFIXES,
    MAX_FILE_SIZE,
    MAX_LINE_LENGTH,
    _is_secret_file,
    is_path_within,
)

READ_PROJECT_CONTEXT_VERSION = "read_project_context_v1"
MAX_CONTEXT_LINES = 30
MAX_PATH_LENGTH = 500

READ_PROJECT_CONTEXT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": MAX_PATH_LENGTH},
        "line": {"type": "integer", "minimum": 1},
        "context_lines": {
            "type": "integer",
            "minimum": 0,
            "maximum": MAX_CONTEXT_LINES,
        },
    },
    "additionalProperties": False,
    "required": ["path", "line", "context_lines"],
}

READ_PROJECT_CONTEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "lines": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2 * MAX_CONTEXT_LINES + 1,
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "minimum": 1},
                    "text": {"type": "string", "maxLength": MAX_LINE_LENGTH},
                },
                "additionalProperties": False,
                "required": ["line", "text"],
            },
        },
    },
    "additionalProperties": False,
    "required": ["path", "start_line", "end_line", "lines"],
}

READ_PROJECT_CONTEXT_SPEC = ToolSpec(
    name="read_project_context",
    description=(
        "读取当前绑定工程项目中一个已定位文件的有限源码上下文。先用 code_search "
        "定位 repo 相对 path + line，再调用本 Tool 查看该行前后实现；只读，不接受 "
        "绝对路径或 repo 外路径。"
    ),
    input_schema=READ_PROJECT_CONTEXT_INPUT_SCHEMA,
    output_schema=READ_PROJECT_CONTEXT_OUTPUT_SCHEMA,
    version=READ_PROJECT_CONTEXT_VERSION,
)


def _relative_parts(raw_path: object) -> tuple[str, ...]:
    """Parse cross-platform relative paths and reject absolute/traversal forms."""

    if type(raw_path) is not str or not raw_path.strip() or raw_path != raw_path.strip():
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    windows_path = PureWindowsPath(raw_path)
    posix_path = PurePosixPath(raw_path)
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or posix_path.is_absolute()
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    if any(part == ".." for part in windows_path.parts) or any(
        part == ".." for part in posix_path.parts
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    parts = tuple(part for part in windows_path.parts if part not in (".", ""))
    if not parts:
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    return parts


class ReadProjectContextHandler:
    """Return a bounded, line-numbered text window from the injected project.

    This is not a general filesystem reader: all accepted files must match the
    code_search text suffix allowlist, remain inside the resolved root, and be
    regular non-symlink files without secret-like names.
    """

    def __init__(self, repo_root: str | os.PathLike) -> None:
        root = Path(repo_root)
        if not root.is_dir():
            raise ValueError(f"repo_root 不是目录：{root}")
        self._root = root.resolve()

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        requested_line = arguments["line"]
        context_lines = arguments["context_lines"]
        if type(requested_line) is not int or isinstance(requested_line, bool) or requested_line < 1:
            raise ToolExecutionError(PROJECT_CONTEXT_LINE_OUT_OF_RANGE)
        if (
            type(context_lines) is not int
            or isinstance(context_lines, bool)
            or not 0 <= context_lines <= MAX_CONTEXT_LINES
        ):
            raise ToolExecutionError(PROJECT_CONTEXT_LINE_OUT_OF_RANGE)

        relative_parts = _relative_parts(arguments["path"])
        candidate = self._root.joinpath(*relative_parts)
        if candidate.is_symlink():
            raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
        try:
            resolved = candidate.resolve()
        except OSError:
            raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED) from None
        if not is_path_within(resolved, self._root):
            raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
        if not candidate.exists():
            raise ToolExecutionError(PROJECT_CONTEXT_FILE_NOT_FOUND)
        if not candidate.is_file():
            raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
        if (
            _is_secret_file(candidate.name)
            or candidate.suffix.lower() not in ALLOWED_SUFFIXES
        ):
            raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
        try:
            if candidate.stat().st_size > MAX_FILE_SIZE:
                raise ToolExecutionError(PROJECT_CONTEXT_FILE_UNREADABLE)
            with open(candidate, "r", encoding="utf-8") as source_file:
                source_lines = [raw.rstrip("\r\n") for raw in source_file]
        except ToolExecutionError:
            raise
        except (OSError, UnicodeDecodeError):
            raise ToolExecutionError(PROJECT_CONTEXT_FILE_UNREADABLE) from None

        if requested_line > len(source_lines):
            raise ToolExecutionError(PROJECT_CONTEXT_LINE_OUT_OF_RANGE)
        start_line = max(1, requested_line - context_lines)
        end_line = min(len(source_lines), requested_line + context_lines)
        return {
            "path": candidate.relative_to(self._root).as_posix(),
            "start_line": start_line,
            "end_line": end_line,
            "lines": [
                {
                    "line": line_number,
                    "text": source_lines[line_number - 1][:MAX_LINE_LENGTH],
                }
                for line_number in range(start_line, end_line + 1)
            ],
        }
