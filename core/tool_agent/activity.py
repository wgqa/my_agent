"""Immutable, product-safe Rich Tool Activity events.

Activity events are a post-G12 observability plane. They deliberately do not
reuse ``RuntimeTraceEvent`` and never contain prompts, model reasoning, raw
observations, or complete tool arguments. Summaries are derived from the
allowlisted public Tool schemas only.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence, TypeAlias

from core.tool_agent.models import TOOL_ERROR_CODES, json_deep_copy
from core.tool_agent.runtime_models import EVIDENCE_KINDS


ACTIVITY_STATES = ("started", "completed", "error")
ACTIVITY_TOOL_NAMES = (
    "knowledge_search",
    "code_search",
    "read_project_context",
    "changed_files",
    "git_diff",
    "find_tests",
    "calculator",
)
MAX_ACTIVITY_TEXT_LENGTH = 120
MAX_ACTIVITY_TOP_PATHS = 5
MAX_ACTIVITY_TOP_SOURCES = 3

_TOOL_ERROR_CODES = frozenset(TOOL_ERROR_CODES)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)")
_POSIX_ABSOLUTE_PATH = re.compile(r"(?:^|(?<=[\s=(:,]))/(?!/)[^\s]+")
_SENSITIVE_TEXT = re.compile(
    r"(?:api[ _-]?key|secret|password|token)\s*[:=]|\bsk-[A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)
_TARGET_KEYS_BY_TOOL = {
    "knowledge_search": frozenset({"query"}),
    "code_search": frozenset({"query"}),
    "read_project_context": frozenset({"path", "line", "context_lines"}),
    "changed_files": frozenset({"mode"}),
    "git_diff": frozenset({"path", "mode"}),
    "find_tests": frozenset({"path"}),
    "calculator": frozenset({"expression"}),
}
_RESULT_SUMMARY_KEYS_BY_TOOL = {
    "knowledge_search": frozenset({"match_count", "top_sources"}),
    "code_search": frozenset({"match_count", "top_paths"}),
    "read_project_context": frozenset({"path", "start_line", "end_line"}),
    "changed_files": frozenset({"file_count", "top_paths", "truncated"}),
    "git_diff": frozenset({"path", "mode", "truncated"}),
    "find_tests": frozenset({"test_file_count", "top_paths", "truncated"}),
    "calculator": frozenset({"status", "result_preview"}),
}


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _clean_text(value: object, *, max_length: int = MAX_ACTIVITY_TEXT_LENGTH) -> str | None:
    if type(value) is not str:
        return None
    value = "".join(
        character
        for character in value
        if unicodedata.category(character) != "Cc"
    )
    value = " ".join(value.split()).strip()
    if (
        not value
        or _WINDOWS_ABSOLUTE_PATH.search(value)
        or _POSIX_ABSOLUTE_PATH.search(value)
        or _SENSITIVE_TEXT.search(value)
    ):
        return None
    return value[:max_length]


def _safe_repo_path(value: object) -> str | None:
    cleaned = _clean_text(value)
    if (
        cleaned is None
        or type(value) is not str
        or len(value) > MAX_ACTIVITY_TEXT_LENGTH
        or cleaned != value
    ):
        return None
    if "\\" in cleaned:
        return None
    posix = PurePosixPath(cleaned)
    windows = PureWindowsPath(cleaned)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in ("", ".", "..") for part in posix.parts)
    ):
        return None
    return posix.as_posix()


def _safe_positive_int(value: object) -> int | None:
    if type(value) is int and value >= 1:
        return value
    return None


def _safe_non_negative_int(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _safe_bool(value: object) -> bool | None:
    return value if type(value) is bool else None


def _safe_public_value(key: str, value: object) -> Any:
    if key in {"path", "top_paths"}:
        if key == "top_paths":
            if not isinstance(value, (list, tuple)):
                return None
            paths = []
            for item in value[:MAX_ACTIVITY_TOP_PATHS]:
                path = _safe_repo_path(item)
                if path is not None and path not in paths:
                    paths.append(path)
            return paths
        return _safe_repo_path(value)
    if key == "top_sources":
        if not isinstance(value, (list, tuple)):
            return None
        sources = []
        for item in value[:MAX_ACTIVITY_TOP_SOURCES]:
            source = _clean_text(item)
            if source is not None and source not in sources:
                sources.append(source)
        return sources
    if key in {"query", "expression", "mode", "status"}:
        return _clean_text(value)
    if key in {"line", "context_lines", "match_count", "start_line", "end_line", "file_count", "test_file_count"}:
        return _safe_non_negative_int(value)
    if key == "truncated":
        return _safe_bool(value)
    if key == "result_preview":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return None


def _safe_mapping(
    value: object,
    *,
    allowed_keys: frozenset[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return MappingProxyType({})
    normalized = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in allowed_keys:
            continue
        safe_value = _safe_public_value(key, item)
        if safe_value is not None:
            normalized[key] = safe_value
    try:
        return _freeze_json(json_deep_copy(normalized))
    except (TypeError, ValueError):
        return MappingProxyType({})


def _safe_evidence_ids(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    result = []
    for item in value:
        if (
            type(item) is str
            and re.fullmatch(r"E[1-9][0-9]*", item)
            and item not in result
        ):
            result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class RunStartedActivity:
    """The single-agent identity and available Tool count for one run."""

    available_tool_count: int
    execution_model: str = "single_agent"

    def __post_init__(self) -> None:
        if type(self.available_tool_count) is not int or self.available_tool_count < 0:
            raise ValueError("available_tool_count must be a non-negative integer")
        if self.execution_model != "single_agent":
            raise ValueError("activity execution_model must be single_agent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "run_started",
            "execution_model": self.execution_model,
            "available_tool_count": self.available_tool_count,
        }


@dataclass(frozen=True)
class ToolActivityEvent:
    """One safe lifecycle event for one real Tool execution."""

    activity_id: str
    iteration: int
    tool_name: str
    state: str
    purpose: str
    target: Mapping[str, Any] = field(default_factory=dict)
    result_summary: Mapping[str, Any] | None = None
    evidence_ids_added: tuple[str, ...] = ()
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"A[1-9][0-9]*", self.activity_id):
            raise ValueError("activity_id must be A1-style")
        if type(self.iteration) is not int or self.iteration < 1:
            raise ValueError("iteration must be positive")
        if type(self.tool_name) is not str or not self.tool_name.strip():
            raise ValueError("tool_name must be non-empty")
        if any(unicodedata.category(character) == "Cc" for character in self.tool_name):
            raise ValueError("tool_name must not contain control characters")
        if self.state not in ACTIVITY_STATES:
            raise ValueError("unknown activity state")
        if (
            type(self.purpose) is not str
            or not self.purpose.strip()
            or len(self.purpose) > MAX_ACTIVITY_TEXT_LENGTH
            or any(unicodedata.category(character) == "Cc" for character in self.purpose)
            or _clean_text(self.purpose) != self.purpose
        ):
            raise ValueError("purpose must be a bounded public description")
        if self.state == "started":
            if self.result_summary is not None or self.evidence_ids_added or self.error_code is not None:
                raise ValueError("started activity must not include a result")
        elif self.state == "completed" and self.error_code is not None:
            raise ValueError("completed activity must not include an error_code")
        elif self.state == "error" and self.evidence_ids_added:
            raise ValueError("error activity must not include evidence ids")

        object.__setattr__(
            self,
            "target",
            _safe_mapping(
                self.target,
                allowed_keys=_TARGET_KEYS_BY_TOOL.get(self.tool_name, frozenset()),
            ),
        )
        if self.result_summary is not None:
            summary_keys = (
                frozenset({"status"})
                if self.state == "error"
                else _RESULT_SUMMARY_KEYS_BY_TOOL.get(self.tool_name, frozenset())
            )
            object.__setattr__(
                self,
                "result_summary",
                _safe_mapping(
                    self.result_summary,
                    allowed_keys=frozenset(summary_keys),
                ),
            )
        object.__setattr__(
            self,
            "evidence_ids_added",
            _safe_evidence_ids(self.evidence_ids_added),
        )
        if self.error_code is not None and self.error_code not in _TOOL_ERROR_CODES:
            raise ValueError("error_code is not an allowlisted Tool error code")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "activity",
            "activity_id": self.activity_id,
            "iteration": self.iteration,
            "tool_name": self.tool_name,
            "state": self.state,
            "purpose": self.purpose,
        }
        if self.target:
            result["target"] = _thaw_json(self.target)
        if self.result_summary is not None:
            result["result_summary"] = _thaw_json(self.result_summary)
        if self.evidence_ids_added:
            result["evidence_ids_added"] = list(self.evidence_ids_added)
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result


@dataclass(frozen=True)
class EvidenceAddedActivity:
    """A public identity event emitted only after evidence enters the run list."""

    evidence_id: str
    kind: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    source_name: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"E[1-9][0-9]*", self.evidence_id):
            raise ValueError("evidence_id must be E1-style")
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError("unknown public evidence kind")
        if self.path is not None and _safe_repo_path(self.path) != self.path:
            raise ValueError("path must be a safe repo-relative POSIX path")
        if self.source_name is not None and _clean_text(self.source_name) != self.source_name:
            raise ValueError("source_name must be bounded and safe")
        for value in (self.start_line, self.end_line):
            if value is not None and _safe_positive_int(value) is None:
                raise ValueError("evidence line must be positive")
        if self.kind == "knowledge":
            if not self.source_name or self.path is not None:
                raise ValueError("knowledge evidence requires source_name only")
        elif (
            not self.path
            or self.start_line is None
            or self.end_line is None
            or self.source_name is not None
            or self.end_line < self.start_line
        ):
            raise ValueError("project evidence requires a bounded path and line range")

    @classmethod
    def from_public_evidence(cls, evidence: object) -> "EvidenceAddedActivity":
        kind = getattr(evidence, "kind", None)
        evidence_id = getattr(evidence, "evidence_id", None)
        if kind == "knowledge":
            return cls(
                evidence_id=evidence_id,
                kind=kind,
                source_name=getattr(evidence, "source_name", None),
            )
        return cls(
            evidence_id=evidence_id,
            kind=kind,
            path=getattr(evidence, "path", None),
            start_line=getattr(evidence, "start_line", None),
            end_line=getattr(evidence, "end_line", None),
        )

    @classmethod
    def try_from_public_evidence(
        cls,
        evidence: object,
    ) -> "EvidenceAddedActivity | None":
        """Return an event only when public evidence fits the activity boundary.

        Runtime evidence is an older public contract with wider path and source
        fields than the bounded activity presentation. Observability must omit
        an unrepresentable event rather than alter the Runtime control plane.
        """

        try:
            return cls.from_public_evidence(evidence)
        except Exception:
            return None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "evidence_added",
            "evidence_id": self.evidence_id,
            "kind": self.kind,
        }
        if self.kind == "knowledge":
            result["source_name"] = self.source_name
        else:
            result.update(
                {
                    "path": self.path,
                    "start_line": self.start_line,
                    "end_line": self.end_line,
                }
            )
        return result


@dataclass(frozen=True)
class VerificationBlockedActivity:
    """A safe Guard explanation containing only missing public evidence kinds."""

    iteration: int
    missing_evidence_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.iteration) is not int or self.iteration < 1:
            raise ValueError("iteration must be positive")
        normalized = tuple(
            dict.fromkeys(
                kind for kind in self.missing_evidence_kinds if kind in EVIDENCE_KINDS
            )
        )
        object.__setattr__(self, "missing_evidence_kinds", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "verification",
            "state": "blocked",
            "iteration": self.iteration,
            "missing_evidence_kinds": list(self.missing_evidence_kinds),
        }


ActivityEvent: TypeAlias = (
    RunStartedActivity
    | ToolActivityEvent
    | EvidenceAddedActivity
    | VerificationBlockedActivity
)


_PURPOSES = {
    "knowledge_search": "检索相关技术知识",
    "code_search": "定位与指定目标相关的项目代码",
    "read_project_context": "读取项目上下文，确认实际实现",
    "changed_files": "检查项目变更文件",
    "git_diff": "分析指定文件的代码变更",
    "find_tests": "定位与目标实现相关的测试",
    "calculator": "计算受限的数值表达式",
}


def tool_activity_purpose(tool_name: str) -> str:
    return _PURPOSES.get(tool_name, "执行一个受控的工程工具操作")


def _target_for_tool(tool_name: str, arguments: object) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        return {}
    if tool_name in {"knowledge_search", "code_search"}:
        query = _clean_text(arguments.get("query"))
        return {"query": query} if query is not None else {}
    if tool_name == "read_project_context":
        path = _safe_repo_path(arguments.get("path"))
        result: dict[str, Any] = {}
        if path is not None:
            result["path"] = path
        for key in ("line", "context_lines"):
            value = _safe_non_negative_int(arguments.get(key))
            if value is not None:
                result[key] = value
        return result
    if tool_name == "changed_files":
        result = {}
        mode = arguments.get("mode")
        if mode in {"working_tree", "commit_range"}:
            result["mode"] = mode
        return result
    if tool_name == "git_diff":
        result = {}
        path = _safe_repo_path(arguments.get("path"))
        if path is not None:
            result["path"] = path
        mode = arguments.get("mode")
        if mode in {"working_tree", "commit_range"}:
            result["mode"] = mode
        return result
    if tool_name == "find_tests":
        path = _safe_repo_path(arguments.get("path"))
        return {"path": path} if path is not None else {}
    if tool_name == "calculator":
        expression = _clean_text(arguments.get("expression"))
        return {"expression": expression} if expression is not None else {}
    return {}


def _unique_safe_values(items: object, key: str, limit: int) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = _safe_repo_path(item.get(key))
        if value is None:
            value = _clean_text(item.get(key))
        if value is not None and value not in result:
            result.append(value)
        if len(result) >= limit:
            break
    return result


def summarize_knowledge_result(result: object) -> dict[str, Any]:
    matches = result.get("matches") if isinstance(result, Mapping) else None
    if not isinstance(matches, list):
        return {}
    return {
        "match_count": len(matches),
        "top_sources": _unique_safe_values(matches, "source_name", MAX_ACTIVITY_TOP_SOURCES),
    }


def summarize_code_search_result(result: object) -> dict[str, Any]:
    matches = result.get("matches") if isinstance(result, Mapping) else None
    if not isinstance(matches, list):
        return {}
    return {
        "match_count": len(matches),
        "top_paths": _unique_safe_values(matches, "path", MAX_ACTIVITY_TOP_PATHS),
    }


def summarize_read_project_context_result(result: object) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    summary: dict[str, Any] = {}
    path = _safe_repo_path(result.get("path"))
    if path is not None:
        summary["path"] = path
    for key in ("start_line", "end_line"):
        value = _safe_positive_int(result.get(key))
        if value is not None:
            summary[key] = value
    return summary


def summarize_changed_files_result(result: object) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    changes = result.get("changes")
    if not isinstance(changes, list):
        return {}
    returned_count = _safe_non_negative_int(result.get("returned_count"))
    summary: dict[str, Any] = {
        "file_count": returned_count if returned_count is not None else len(changes),
        "top_paths": _unique_safe_values(changes, "path", MAX_ACTIVITY_TOP_PATHS),
    }
    truncated = _safe_bool(result.get("truncated"))
    if truncated is not None:
        summary["truncated"] = truncated
    return summary


def summarize_git_diff_result(result: object) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    summary: dict[str, Any] = {}
    path = _safe_repo_path(result.get("path"))
    if path is not None:
        summary["path"] = path
    mode = result.get("mode")
    if mode in {"working_tree", "commit_range"}:
        summary["mode"] = mode
    truncated = _safe_bool(result.get("truncated"))
    if truncated is not None:
        summary["truncated"] = truncated
    return summary


def summarize_find_tests_result(result: object) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return {}
    returned_count = _safe_non_negative_int(result.get("returned_count"))
    summary: dict[str, Any] = {
        "test_file_count": returned_count if returned_count is not None else len(candidates),
        "top_paths": _unique_safe_values(candidates, "path", MAX_ACTIVITY_TOP_PATHS),
    }
    truncated = _safe_bool(result.get("truncated"))
    if truncated is not None:
        summary["truncated"] = truncated
    return summary


def summarize_calculator_result(result: object) -> dict[str, Any]:
    value = result.get("value") if isinstance(result, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"status": "completed"}
    if isinstance(value, float) and not math.isfinite(value):
        return {"status": "completed"}
    return {"status": "completed", "result_preview": value}


_RESULT_SUMMARIZERS = {
    "knowledge_search": summarize_knowledge_result,
    "code_search": summarize_code_search_result,
    "read_project_context": summarize_read_project_context_result,
    "changed_files": summarize_changed_files_result,
    "git_diff": summarize_git_diff_result,
    "find_tests": summarize_find_tests_result,
    "calculator": summarize_calculator_result,
}


def summarize_tool_result(tool_name: str, result: object) -> dict[str, Any]:
    """Summarize one allowlisted Tool result without generic stringification."""

    summarizer = _RESULT_SUMMARIZERS.get(tool_name)
    if summarizer is None:
        return {"status": "completed"}
    return summarizer(result)


def build_tool_activity_event(
    *,
    activity_id: str,
    iteration: int,
    tool_name: str,
    state: str,
    arguments: object,
    observation: object | None = None,
    evidence_ids_added: Sequence[str] = (),
) -> ToolActivityEvent:
    """Build a safe lifecycle event from real call/observation data."""

    purpose = tool_activity_purpose(tool_name)
    target = _target_for_tool(tool_name, arguments)
    if state == "started":
        summary = None
        error_code = None
    elif state == "completed":
        summary = summarize_tool_result(
            tool_name,
            getattr(observation, "result", None),
        )
        error_code = None
    elif state == "error":
        summary = {"status": "error"}
        candidate = getattr(observation, "error_code", None)
        error_code = candidate if candidate in _TOOL_ERROR_CODES else None
    else:
        raise ValueError("unknown activity state")
    try:
        return ToolActivityEvent(
            activity_id=activity_id,
            iteration=iteration,
            tool_name=tool_name,
            state=state,
            purpose=purpose,
            target=target,
            result_summary=summary,
            evidence_ids_added=tuple(evidence_ids_added),
            error_code=error_code,
        )
    except (TypeError, ValueError):
        # A future schema drift must degrade to a safe bounded event rather
        # than affecting the Runtime control plane.
        return ToolActivityEvent(
            activity_id=activity_id,
            iteration=iteration,
            tool_name=tool_name if isinstance(tool_name, str) and tool_name else "unknown_tool",
            state=state,
            purpose="执行一个受控的工程工具操作",
            target={},
            result_summary=(None if state == "started" else {"status": state}),
            evidence_ids_added=(),
            error_code=None,
        )


__all__ = [
    "ACTIVITY_STATES",
    "ACTIVITY_TOOL_NAMES",
    "ActivityEvent",
    "EvidenceAddedActivity",
    "RunStartedActivity",
    "ToolActivityEvent",
    "VerificationBlockedActivity",
    "build_tool_activity_event",
    "summarize_calculator_result",
    "summarize_changed_files_result",
    "summarize_code_search_result",
    "summarize_find_tests_result",
    "summarize_git_diff_result",
    "summarize_knowledge_result",
    "summarize_read_project_context_result",
    "summarize_tool_result",
    "tool_activity_purpose",
]
