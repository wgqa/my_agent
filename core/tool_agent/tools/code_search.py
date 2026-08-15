"""G4-TOOLS-03：code_search —— 当前项目代码/技术文件的只读文本搜索 Tool。

模型只传 query；repo_root 由系统在构造 Handler 时注入，模型不能控制。
v1 做确定性的 case-insensitive literal substring search（不执行正则）。
只扫描固定允许目录与后缀；跳过隐藏/排除目录、超大文件、secret/凭证文件、
不可读文件。path 一律为 repo-relative POSIX 风格，绝不返回绝对路径；
结果按 (path, line) 确定性排序。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from core.tool_agent.models import ToolSpec

CODE_SEARCH_VERSION = "code_search_v1"

ALLOWED_DIRS = ("core", "api", "evaluation", "scripts", "tests", "docs")
ALLOWED_SUFFIXES = frozenset(
    {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"}
)
EXCLUDED_DIR_NAMES = frozenset(
    {".git", "__pycache__", "experiments", "venv", ".venv", "node_modules"}
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
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "text": {"type": "string"},
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
        "在当前项目的代码与技术文档中做只读文本搜索。当问题需要定位某个类/"
        "方法/符号/配置的实现位置（如 'PipelineRetrievalAdapter' 在哪定义）时 "
        "使用；只接受一个 query。返回 repo 相对路径 + 行号 + 匹配行文本。"
    ),
    input_schema=CODE_SEARCH_INPUT_SCHEMA,
    output_schema=CODE_SEARCH_OUTPUT_SCHEMA,
    version=CODE_SEARCH_VERSION,
)


def _is_secret_file(name: str) -> bool:
    low = name.lower()
    if low == ".env" or low.startswith(".env."):
        return True
    return "secret" in low or "credential" in low


class CodeSearchHandler:
    """ToolHandler：在注入的 repo_root 内做确定性只读文本搜索。"""

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
        self._max_matches = max_matches
        self._max_file_size = max_file_size
        self._max_line_length = max_line_length

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        query = arguments["query"]
        needle = query.lower()
        found: list[tuple[str, int, str]] = []
        for base in ALLOWED_DIRS:
            base_dir = self._root / base
            if not base_dir.is_dir():
                continue
            found.extend(self._search_dir(base_dir, needle))
        # 确定性排序：path → line
        found.sort(key=lambda item: (item[0], item[1]))
        matches = [
            {"path": path, "line": line, "text": text}
            for path, line, text in found[: self._max_matches]
        ]
        return {"matches": matches}

    def _search_dir(self, base_dir: Path, needle: str) -> list[tuple[str, int, str]]:
        out: list[tuple[str, int, str]] = []
        for dirpath, dirnames, filenames in os.walk(base_dir):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")
            )
            for fname in sorted(filenames):
                if Path(fname).suffix.lower() not in ALLOWED_SUFFIXES:
                    continue
                if _is_secret_file(fname):
                    continue
                fpath = Path(dirpath) / fname
                rel = fpath.relative_to(self._root).as_posix()
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue
                if size > self._max_file_size:
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        lines = fh.readlines()
                except (OSError, UnicodeDecodeError):
                    # 单个文件不可读则安全跳过，不让整个 repo 搜索 crash
                    continue
                for line_no, raw in enumerate(lines, 1):
                    text = raw.rstrip("\r\n")
                    if needle in text.lower():
                        out.append(
                            (
                                rel,
                                line_no,
                                text[: self._max_line_length],
                            )
                        )
        return out
