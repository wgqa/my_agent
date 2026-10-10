"""Read only the host-selected project binding, without filesystem navigation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from core.tool_agent.models import INVALID_TOOL_ARGUMENTS, ToolExecutionError, ToolSpec
from core.tool_agent.tools.code_search import MAX_FILE_SIZE, is_path_within


PROJECT_INFO_VERSION = "get_project_info_v1"
PROJECT_INFO_DOCUMENTATION_VERSION = "get_project_info_v2"
MAX_DOCUMENTATION_ENTRYPOINTS = 6
# Fixed lookup set, not a recursive directory listing. Lowercase variants
# support case-sensitive hosts; resolved duplicates are removed on Windows.
_OVERVIEW_ENTRYPOINTS = (
    "README.md", "README.rst", "README.txt", "readme.md", "readme.rst", "readme.txt",
    "docs/index.md", "docs/index.rst", "docs/README.md", "docs/readme.md",
    "docs/overview.md", "docs/overview.rst", "docs/overview.txt",
)
PROJECT_INFO_SPEC = ToolSpec(
    name="get_project_info",
    description=(
        "查询当前会话由服务端绑定的工程项目：返回项目名、绝对根目录 root、"
        "绑定来源 source 和目录是否仍可用 available。询问当前绑定哪个项目、"
        "保存在哪个目录时使用；不能从历史、README 或用户提供的路径猜测绑定。"
        "参数必须为空对象。只读，不能选择或改变项目，不列出其他项目，不扫描文件。"
        "返回值是平台绑定信息，不是源码、文档、测试或变更 Evidence，不能替代正文取证。"
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema={
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "minLength": 1},
            "root": {"type": "string", "minLength": 1},
            "source": {"enum": ["default_repo", "configured"]},
            "available": {"type": "boolean"},
        },
        "required": ["project_name", "root", "source", "available"],
        "additionalProperties": False,
    },
    version=PROJECT_INFO_VERSION,
)

PROJECT_INFO_DOCUMENTATION_SPEC = ToolSpec(
    name=PROJECT_INFO_SPEC.name,
    description=(PROJECT_INFO_SPEC.description + (
        " 介绍当前项目用途、能力或总体概况时，传 include_documentation=true，"
        "检查有限的常见 README、docs/index、docs/overview 文档入口，返回实际存在的"
        "项目相对路径和截断状态。入口不是正文证据；选入口后必须用 read_project_context "
        "读取正文。未发现入口只表示这组常见位置没有可用候选，不表示项目没有任何文档。"
        "目录查询仍用空参数，不检查文档；可选参数只接受该布尔值，不接受路径。"
    )).replace("参数必须为空对象。", "纯绑定查询参数为空对象。")
     .replace("不扫描文件。", "不递归扫描文件。"),
    input_schema={
        "type": "object", "properties": {"include_documentation": {"type": "boolean"}},
        "additionalProperties": False,
    },
    output_schema={"oneOf": [
        PROJECT_INFO_SPEC.output_schema,
        {
            "type": "object",
            "properties": {
                **PROJECT_INFO_SPEC.output_schema["properties"],
                "documentation_scope": {"const": "conventional_overview_entrypoints"},
                "documentation_entrypoints": {
                    "type": "array", "maxItems": MAX_DOCUMENTATION_ENTRYPOINTS,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                "documentation_truncated": {"type": "boolean"},
            },
            "required": [*PROJECT_INFO_SPEC.output_schema["required"],
                         "documentation_scope", "documentation_entrypoints", "documentation_truncated"],
            "additionalProperties": False,
        },
    ]},
    version=PROJECT_INFO_DOCUMENTATION_VERSION,
)


def project_info_spec(version: str) -> ToolSpec:
    if version == PROJECT_INFO_VERSION:
        return PROJECT_INFO_SPEC
    if version == PROJECT_INFO_DOCUMENTATION_VERSION:
        return PROJECT_INFO_DOCUMENTATION_SPEC
    raise ValueError("Unsupported get_project_info version")


@dataclass(frozen=True)
class ProjectBinding:
    """One cached runtime's immutable binding, constructed only by the host."""

    root: Path
    project_name: str
    source: Literal["default_repo", "configured"]

    def __post_init__(self) -> None:
        root = Path(self.root)
        if not root.is_absolute():
            raise ValueError("ProjectBinding.root must be absolute")
        if type(self.project_name) is not str or not self.project_name.strip():
            raise ValueError("ProjectBinding.project_name must be non-empty")
        if self.source not in ("default_repo", "configured"):
            raise ValueError("Unsupported project binding source")
        object.__setattr__(self, "root", root.resolve())


class ProjectInfoHandler:
    def __init__(self, binding: ProjectBinding, *, version: str = PROJECT_INFO_VERSION) -> None:
        if not isinstance(binding, ProjectBinding):
            raise TypeError("binding must be ProjectBinding")
        self._binding = binding
        project_info_spec(version)
        self._version = version

    def execute(self, arguments: Mapping[str, Any]) -> dict:
        include_documentation = arguments.get("include_documentation", False)
        allowed = {"include_documentation"} if self._version == PROJECT_INFO_DOCUMENTATION_VERSION else set()
        if set(arguments) - allowed or type(include_documentation) is not bool:
            raise ToolExecutionError(INVALID_TOOL_ARGUMENTS)
        binding = self._binding
        try:
            available = binding.root.is_dir()
        except OSError:
            available = False
        result = {
            "project_name": binding.project_name,
            "root": str(binding.root),
            "source": binding.source,
            "available": available,
        }
        if include_documentation:
            entries = self._documentation_entrypoints() if available else []
            result.update(
                documentation_scope="conventional_overview_entrypoints",
                documentation_entrypoints=entries[:MAX_DOCUMENTATION_ENTRYPOINTS],
                documentation_truncated=len(entries) > MAX_DOCUMENTATION_ENTRYPOINTS,
            )
        return result

    def _documentation_entrypoints(self) -> list[str]:
        """Check fixed locators without opening documents or following links."""
        root, entries = self._binding.root, []
        seen: set[Path] = set()
        for relative in _OVERVIEW_ENTRYPOINTS:
            candidate = root / relative
            try:
                components = (candidate, *tuple(candidate.parents)[:len(Path(relative).parts) - 1])
                if any(part.is_symlink() or getattr(part, "is_junction", lambda: False)() for part in components):
                    continue
                resolved = candidate.resolve()
                if not is_path_within(resolved, root) or resolved in seen or not candidate.is_file():
                    continue
                if candidate.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            seen.add(resolved)
            entries.append(resolved.relative_to(root).as_posix())
        return entries
