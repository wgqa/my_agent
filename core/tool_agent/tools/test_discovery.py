"""Bounded, deterministic candidate test discovery for the bound project.

This tool answers only "where might related tests be?". It does not claim
impact, build a dependency graph, run tests, or read source-file evidence.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.tool_agent.models import (
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    ToolExecutionError,
    ToolSpec,
)
from core.tool_agent.tools.code_search import (
    ALLOWED_SUFFIXES,
    EXCLUDED_DIR_NAMES,
    MAX_FILE_SIZE,
    _is_secret_file,
    is_path_within,
)


FIND_TESTS_VERSION = "find_tests_v1"
MAX_TEST_CANDIDATES = 10
MAX_PATH_LENGTH = 500
TEST_DISCOVERY_REASONS = (
    "mirrored_path",
    "filename_match",
    "content_reference",
)

FIND_TESTS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": MAX_PATH_LENGTH},
    },
    "additionalProperties": False,
    "required": ["path"],
}

FIND_TESTS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": MAX_TEST_CANDIDATES,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "line": {"type": "integer", "minimum": 1},
                    "reasons": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": len(TEST_DISCOVERY_REASONS),
                        "items": {
                            "type": "string",
                            "enum": list(TEST_DISCOVERY_REASONS),
                        },
                    },
                },
                "additionalProperties": False,
                "required": ["path", "line", "reasons"],
            },
        },
        "returned_count": {"type": "integer", "minimum": 0},
        "truncated": {"type": "boolean"},
        "omitted_sensitive_count": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
    "required": [
        "candidates",
        "returned_count",
        "truncated",
        "omitted_sensitive_count",
    ],
}

FIND_TESTS_SPEC = ToolSpec(
    name="find_tests",
    description=(
        "根据一个 repo-relative 源码或配置 path，确定性寻找 bounded candidate related tests。"
        "只返回候选测试 path、后续 read_project_context 使用的 anchor line 和稳定 reasons；"
        "candidate 不等于已证明受影响，也不运行测试。支持常见 tests/、src/main↔src/test、"
        "test_foo.py、foo_test.go、foo.test/spec.js/ts、FooTest(s).java/cs 等约定。"
        "输入 path 不要求当前存在，以支持 deleted source；不要传绝对路径、..、secret path。"
    ),
    input_schema=FIND_TESTS_INPUT_SCHEMA,
    output_schema=FIND_TESTS_OUTPUT_SCHEMA,
    version=FIND_TESTS_VERSION,
)


_TEST_DIR_NAMES = frozenset({"test", "tests", "__tests__"})
_PYTHON_SUFFIXES = frozenset({".py", ".rb"})
_JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx"})
_REASON_RANK = {name: index for index, name in enumerate(TEST_DISCOVERY_REASONS)}


@dataclass(frozen=True)
class _Candidate:
    path: str
    line: int
    reasons: tuple[str, ...]


def _normalise_path(raw_path: object) -> str:
    if (
        type(raw_path) is not str
        or not raw_path.strip()
        or raw_path != raw_path.strip()
        or len(raw_path) > MAX_PATH_LENGTH
        or any(ord(char) < 32 for char in raw_path)
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    windows_path = PureWindowsPath(raw_path)
    posix_path = PurePosixPath(raw_path)
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or posix_path.is_absolute()
        or "\\" in raw_path and any(part == "" for part in raw_path.split("\\"))
        or any(part == "" for part in raw_path.replace("\\", "/").split("/"))
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    if any(part == ".." for part in windows_path.parts) or any(
        part == ".." for part in posix_path.parts
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    parts = tuple(part for part in windows_path.parts if part not in (".", ""))
    if not parts or _is_secret_file(parts[-1]):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    return PurePosixPath(*parts).as_posix()


def is_test_path(path: str) -> bool:
    """Return whether a repo-relative path follows a conventional test shape."""

    normalised = path.replace("\\", "/")
    parsed = PurePosixPath(normalised)
    name = parsed.name.lower()
    suffix = parsed.suffix.lower()
    parts = {part.lower() for part in parsed.parts[:-1]}
    if suffix not in ALLOWED_SUFFIXES:
        return False
    if parts & _TEST_DIR_NAMES:
        return True
    if suffix == ".go":
        return name.endswith("_test.go")
    if suffix in _PYTHON_SUFFIXES:
        return name.startswith("test_") or name.endswith("_test" + suffix)
    if suffix in _JS_SUFFIXES:
        return ".test." in name or ".spec." in name
    stem = parsed.stem.lower()
    if suffix in {".java", ".cs"}:
        return stem.endswith("test") or stem.endswith("tests")
    return name.endswith("_test" + suffix)


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _source_stem(path: str) -> str:
    return PurePosixPath(path).stem


def _filename_matches(source_stem: str, candidate_path: str) -> bool:
    source = _compact(source_stem)
    if len(source) < 3:
        return False
    candidate = _compact(PurePosixPath(candidate_path).stem)
    return source in candidate


def _mirrored_paths(source_path: str) -> frozenset[str]:
    source = PurePosixPath(source_path)
    parts = source.parts
    suffix = source.suffix
    if suffix.lower() != ".java":
        return frozenset()
    for index in range(len(parts) - 1):
        if parts[index : index + 2] != ("src", "main"):
            continue
        stem = source.stem
        names = (f"{stem}Test{suffix}", f"{stem}Tests{suffix}")
        prefix = parts[:index] + ("src", "test") + parts[index + 2 : -1]
        return frozenset(PurePosixPath(*(prefix + (name,))).as_posix() for name in names)
    return frozenset()


def _collect_test_files(root: Path) -> tuple[list[Path], int]:
    files: list[Path] = []
    omitted_sensitive = 0
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current_dir = Path(dirpath)
        try:
            if not is_path_within(current_dir.resolve(), root_resolved):
                dirnames[:] = []
                continue
        except OSError:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            directory
            for directory in dirnames
            if directory not in EXCLUDED_DIR_NAMES
            and not directory.startswith(".")
            and not (current_dir / directory).is_symlink()
        )
        for filename in sorted(filenames):
            if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            candidate = current_dir / filename
            relative = candidate.relative_to(root).as_posix()
            if not is_test_path(relative):
                continue
            if _is_secret_file(filename):
                omitted_sensitive += 1
                continue
            if candidate.is_symlink():
                continue
            try:
                if not is_path_within(candidate.resolve(), root_resolved):
                    continue
            except OSError:
                continue
            files.append(candidate)
    return files, omitted_sensitive


def _read_candidate(candidate: Path) -> list[str] | None:
    try:
        if candidate.stat().st_size > MAX_FILE_SIZE:
            return None
        with open(candidate, "r", encoding="utf-8") as source_file:
            lines = source_file.readlines()
            if any("\x00" in line for line in lines):
                return None
            return lines
    except (OSError, UnicodeDecodeError):
        return None


class FindTestsHandler:
    """Return bounded lexical test candidates without executing or mutating files."""

    def __init__(self, repo_root: str | os.PathLike) -> None:
        root = Path(repo_root)
        if not root.is_dir():
            raise ValueError(f"repo_root 不是目录：{root}")
        self._root = root.resolve()

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        source_path = _normalise_path(arguments["path"])
        source_stem = _source_stem(source_path)
        mirrored_paths = _mirrored_paths(source_path)
        test_files, omitted_sensitive = _collect_test_files(self._root)
        candidates: list[_Candidate] = []
        for file_path in test_files:
            relative = file_path.relative_to(self._root).as_posix()
            candidate_lines = _read_candidate(file_path)
            if candidate_lines is None:
                continue
            reasons: list[str] = []
            if relative in mirrored_paths:
                reasons.append("mirrored_path")
            if _filename_matches(source_stem, relative):
                reasons.append("filename_match")
            content_line = None
            if len(source_stem) >= 3:
                needle = source_stem.lower()
                content_line = next(
                    (
                        line_number
                        for line_number, raw_line in enumerate(candidate_lines, 1)
                        if needle in raw_line.lower()
                    ),
                    None,
                )
            if content_line is not None:
                reasons.append("content_reference")
            if not reasons:
                continue
            candidates.append(
                _Candidate(
                    path=relative,
                    line=content_line or 1,
                    reasons=tuple(
                        reason
                        for reason in TEST_DISCOVERY_REASONS
                        if reason in reasons
                    ),
                )
            )
        candidates.sort(
            key=lambda candidate: (
                min(_REASON_RANK[reason] for reason in candidate.reasons),
                candidate.path,
            )
        )
        visible = candidates[:MAX_TEST_CANDIDATES]
        return {
            "candidates": [
                {
                    "path": candidate.path,
                    "line": candidate.line,
                    "reasons": list(candidate.reasons),
                }
                for candidate in visible
            ],
            "returned_count": len(visible),
            "truncated": len(candidates) > MAX_TEST_CANDIDATES,
            "omitted_sensitive_count": omitted_sensitive,
        }


__all__ = [
    "FIND_TESTS_INPUT_SCHEMA",
    "FIND_TESTS_OUTPUT_SCHEMA",
    "FIND_TESTS_SPEC",
    "FindTestsHandler",
    "MAX_TEST_CANDIDATES",
    "TEST_DISCOVERY_REASONS",
    "is_test_path",
]
