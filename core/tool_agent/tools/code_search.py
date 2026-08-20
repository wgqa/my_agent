"""G6-VERTICAL-01：code_search —— 绑定工程项目的只读文本搜索 Tool。

模型只传 query；repo_root 由系统在构造 Handler 时注入，模型不能控制。
v1 做确定性的 case-insensitive literal substring search（不执行正则）。
从绑定根目录递归扫描允许后缀；跳过隐藏/排除目录、超大文件、secret/凭证文件、
不可读文件。path 一律为 repo-relative POSIX 风格，绝不返回绝对路径；
结果按 (path, line) 确定性排序。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from core.tool_agent.models import ToolSpec

CODE_SEARCH_VERSION = "code_search_v3"

ALLOWED_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".php",
        ".properties",
        ".py",
        ".rb",
        ".rs",
        ".rst",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
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

CODE_SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 200},
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
    },
    "additionalProperties": False,
    "required": ["matches"],
}

CODE_SEARCH_SPEC = ToolSpec(
    name="code_search",
    description=(
        "在当前绑定工程项目的代码与技术文档中做只读文本搜索。当问题需要定位某个类/"
        "方法/符号/配置的实现位置（如 'PipelineRetrievalAdapter' 在哪定义）时 "
        "使用；只接受一个 query。它只负责定位 path + line；若要查看附近实现，"
        "随后调用 read_project_context。涉及文档与实现、配置是否一致或配置如何生效"
        "的问题时，应分别定位文档和源码并读取双方上下文。返回 repo 相对路径 + 行号"
        "+ 匹配行文本。"
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
        root_resolved = self._root.resolve()
        candidates = self._collect_files(self._root, root_resolved)
        # 确定性：按 lexical repo-relative path 排序 → 自然顺序即 (path, line)
        candidates.sort(key=lambda p: p.relative_to(self._root).as_posix())
        matches = []
        for fpath in candidates:
            if len(matches) >= self._max_matches:
                break
            rel = fpath.relative_to(self._root).as_posix()
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > self._max_file_size:
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    for line_no, raw in enumerate(fh, 1):
                        if len(matches) >= self._max_matches:
                            break
                        text = raw.rstrip("\r\n")
                        if needle in text.lower():
                            matches.append(
                                {
                                    "path": rel,
                                    "line": line_no,
                                    "text": text[: self._max_line_length],
                                }
                            )
            except (OSError, UnicodeDecodeError):
                continue
        return {"matches": matches}

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
                and not (current_dir / d).is_symlink()
            )
            for fname in sorted(filenames):
                if Path(fname).suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                if _is_secret_file(fname):
                    continue
                fpath = current_dir / fname
                if fpath.is_symlink():
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
