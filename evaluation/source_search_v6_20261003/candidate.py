"""Experimental code_search_v6; NOT registered in the production tool factory.

G6-VERTICAL-01：code_search —— 绑定工程项目的只读文本搜索 Tool。

模型只传 query 和可选 artifact_kind/scope；repo_root 由系统在构造 Handler 时注入，模型不能控制。
v1 做确定性的 case-insensitive literal substring search（不执行正则）。
从绑定根目录递归扫描允许后缀；跳过隐藏/排除目录、超大文件、secret/凭证文件、
不可读文件。path 一律为 repo-relative POSIX 风格，绝不返回绝对路径；
结果按 (path, line) 确定性排序。artifact_kind 缺省或为 any 时保持原有混合搜索；
project_code/project_doc 使用与 Runtime public evidence classification 相同的契约，
project_test 继续由 find_tests → read_project_context 负责。
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from core.tool_agent.models import (
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    ToolExecutionError,
    ToolSpec,
)
from core.tool_agent.project_files import (
    ALLOWED_SUFFIXES,
    classify_project_evidence_path,
)

CODE_SEARCH_VERSION = "code_search_v6"

EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "__pycache__",
        "build",
        "dist",
        "env",
        "experiments",
        "node_modules",
        "site-packages",
        "venv",
        ".venv",
    }
)

MAX_MATCHES = 10
MAX_FILE_SIZE = 1024 * 1024  # 1 MiB
MAX_LINE_LENGTH = 300
MAX_SCOPE_LENGTH = 500

CODE_SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 200},
        "artifact_kind": {
            "type": "string",
            "enum": ["any", "project_code", "project_doc"],
        },
        "scope": {
            "type": "string", "minLength": 1, "maxLength": MAX_SCOPE_LENGTH,
            "description": "可选 repo-relative 文件或目录；缺省或 . 为整个项目。",
        },
    },
    "additionalProperties": False,
    "required": ["query"],
}

CODE_SEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "text": {"type": "string", "maxLength": 300},
                },
                "additionalProperties": False,
                "required": ["path", "line", "text"],
            },
        },
        "scope": {"type": "string", "minLength": 1, "maxLength": MAX_SCOPE_LENGTH},
        "truncated": {"type": "boolean"},
    },
    "additionalProperties": False,
    "required": ["matches", "scope", "truncated"],
}

CODE_SEARCH_SPEC = ToolSpec(
    name="code_search",
    description=(
        "在当前绑定 Engineering Project 的代码、README 和技术文档中做只读、"
        "case-insensitive literal text search。query 应是简短且可能真实存在的 literal，"
        "例如 endpoint、annotation、config key、exception 名、method/symbol、SQL identifier"
        "或关键字符串；不要传整句自然语言。它只负责定位 repo-relative path + line。"
        "可选 artifact_kind 过滤 Evidence Backend 的 path discovery：缺省或 any 保持"
        "兼容的混合搜索；要求 project_code 时传 project_code 只定位 Runtime 会认可的"
        "source implementation，要求 project_doc 时传 project_doc 只定位 repo 文档；"
        "project_test 不由本 Tool 过滤，测试发现仍使用 find_tests → read_project_context。"
        "可选 scope 是 repo-relative 文件或目录（缺省或 . 搜整个项目），可依据用户给出的"
        "路径或已有匹配路径缩小范围；不要猜测不确定的目录。结果 scope 返回实际范围。"
        "最多返回 10 个匹配，truncated=true 表示该范围内还有匹配被上限截去，"
        "不是完整结果；如未定位目标，缩小 scope 或换更具体的 literal 再搜索。"
        "当匹配结果需要解释实际实现、行为、调用关系或多文件关系时，随后必须调用 "
        "read_project_context 读取上下文，不要只从单个匹配行推断答案。若已有结果，"
        "读取它或调整 scope/关键词，绝不重复完全相同的工具参数。"
    ),
    input_schema=CODE_SEARCH_INPUT_SCHEMA,
    output_schema=CODE_SEARCH_OUTPUT_SCHEMA,
    version=CODE_SEARCH_VERSION,
)


_SECRET_SUBSTRINGS = (
    "secret",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
)


def _is_secret_file(name: str) -> bool:
    low = name.lower()
    if low == ".env" or low.startswith(".env."):
        return True
    stem = Path(low).stem
    # 不能简单 `"key" in name`：keyboard.py 这类正常文件会被误伤
    return any(tok in stem for tok in _SECRET_SUBSTRINGS)


def is_path_within(resolved: Path, root_resolved: Path) -> bool:
    """containment helper：resolved 目标是否仍位于 resolved repo_root 内。"""
    try:
        return resolved.is_relative_to(root_resolved)
    except ValueError:
        return False


def _require_bounded_int(value: object, label: str, cap: int) -> None:
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(
            f"{label} 必须是严格正整数（不允许 bool），实际 {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(f"{label} 必须 > 0，实际 {value}")
    if value > cap:
        raise ValueError(f"{label} 不允许超过冻结上限 {cap}，实际 {value}")


ARTIFACT_KINDS = frozenset({"any", "project_code", "project_doc"})


def _normalize_scope(raw_scope: object) -> str:
    """Normalize a lexical repo-relative scope without permitting path escapes."""
    if (
        type(raw_scope) is not str
        or not raw_scope
        or raw_scope != raw_scope.strip()
        or len(raw_scope) > MAX_SCOPE_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in raw_scope)
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    windows = PureWindowsPath(raw_scope)
    if windows.drive or windows.root or PurePosixPath(raw_scope).is_absolute():
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    parts = raw_scope.replace("\\", "/").rstrip("/").split("/")
    if any(
        part in ("", "..") or ":" in part
        or part != "." and part.endswith((".", " "))
        for part in parts
    ):
        raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
    return PurePosixPath(*(part for part in parts if part != ".")).as_posix()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


class CodeSearchHandler:
    """ToolHandler：在注入的 repo_root 内做确定性只读文本搜索。

    锁死 filesystem sandbox：禁止 symlink 穿越（base 为 symlink 不扫、
    目录 symlink 不进、文件 symlink 不读），并在真正 stat/open 前做
    resolved containment 检查；输出只用 lexical repo-relative path。
    """

    def __init__(
        self,
        repo_root: str | os.PathLike,
        max_matches: int = MAX_MATCHES,
        max_file_size: int = MAX_FILE_SIZE,
        max_line_length: int = MAX_LINE_LENGTH,
    ) -> None:
        root = Path(repo_root)
        if not root.is_dir():
            raise ValueError(f"repo_root 不是目录：{root}")
        self._root = root.resolve()
        # 参数边界：strict positive int，且不允许超过冻结上限
        _require_bounded_int(max_matches, "max_matches", MAX_MATCHES)
        _require_bounded_int(max_file_size, "max_file_size", MAX_FILE_SIZE)
        _require_bounded_int(max_line_length, "max_line_length", MAX_LINE_LENGTH)
        self._max_matches = max_matches
        self._max_file_size = max_file_size
        self._max_line_length = max_line_length

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        query = arguments["query"]
        needle = query.lower()
        artifact_kind = arguments.get("artifact_kind", "any")
        if artifact_kind not in ARTIFACT_KINDS:
            raise ValueError(f"artifact_kind 不支持：{artifact_kind!r}")
        scope = _normalize_scope(arguments.get("scope", "."))
        root_resolved = self._root.resolve()
        candidates = self._scoped_files(scope, root_resolved)
        # 确定性：按 lexical repo-relative path 排序 → 自然顺序即 (path, line)
        candidates.sort(key=lambda p: p.relative_to(self._root).as_posix())
        matches = []
        for fpath in candidates:
            rel = fpath.relative_to(self._root).as_posix()
            if artifact_kind != "any" and classify_project_evidence_path(rel) != artifact_kind:
                continue
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > self._max_file_size:
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    for line_no, raw in enumerate(fh, 1):
                        text = raw.rstrip("\r\n")
                        if needle in text.lower():
                            # Only a further eligible match proves truncation. Exactly
                            # ten matches, or excluded/oversized hits, must return false.
                            if len(matches) == self._max_matches:
                                return {"matches": matches, "scope": scope, "truncated": True}
                            matches.append(
                                {
                                    "path": rel,
                                    "line": line_no,
                                    "text": text[: self._max_line_length],
                                }
                            )
            except (OSError, UnicodeDecodeError):
                continue
        return {"matches": matches, "scope": scope, "truncated": False}

    def _scoped_files(self, scope: str, root_resolved: Path) -> list[Path]:
        candidate = self._root
        parts = PurePosixPath(scope).parts
        try:
            for index, part in enumerate(parts):
                candidate = candidate / part
                # Check every ancestor: resolving a path alone would admit aliases
                # pointing back inside the repo and bypass hidden/excluded directories.
                if _is_link(candidate):
                    raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
                if (index < len(parts) - 1 or candidate.is_dir()) and (
                    part.startswith(".") or part.casefold() in EXCLUDED_DIR_NAMES
                ):
                    raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
            if not is_path_within(candidate.resolve(), root_resolved):
                raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
            if not candidate.exists():
                return []
            if candidate.is_dir():
                return self._collect_files(candidate, root_resolved)
            if (
                not candidate.is_file()
                or _is_secret_file(candidate.name)
                or candidate.suffix.lower() not in ALLOWED_SUFFIXES
            ):
                raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED)
            return [candidate]
        except OSError:
            raise ToolExecutionError(PROJECT_CONTEXT_PATH_NOT_ALLOWED) from None

    def _collect_files(self, search_root: Path, root_resolved: Path) -> list[Path]:
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(search_root, followlinks=False):
            current_dir = Path(dirpath)
            try:
                if not is_path_within(current_dir.resolve(), root_resolved):
                    dirnames[:] = []
                    continue
            except OSError:
                dirnames[:] = []
                continue
            # 目录 symlink 不进入；排除/隐藏目录过滤
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in EXCLUDED_DIR_NAMES
                and not d.startswith(".")
                and not _is_link(current_dir / d)
            )
            for fname in sorted(filenames):
                if Path(fname).suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                if _is_secret_file(fname):
                    continue
                fpath = current_dir / fname
                if _is_link(fpath):
                    continue  # 文件 symlink → 不读取
                # resolved containment：真正 stat/open 前必须仍位于 resolved root 内
                try:
                    resolved = fpath.resolve()
                except OSError:
                    continue
                if not is_path_within(resolved, root_resolved):
                    continue
                out.append(fpath)
        return out
