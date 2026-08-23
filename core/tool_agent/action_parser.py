"""G4-AGENT-04：严格结构化 Action 解析。

只接受"一个 JSON object"：拒绝 markdown fence、前后 prose、空输出、
数组/标量顶层、任意层级 duplicate key。随后把 object 校验成 AgentAction
（精确字段集合），并在 Decision 层完成 tool_name 必须来自 Registry 与
arguments 过 input_schema 的第一道 schema 校验（第二道是 ToolExecutor
真正执行前再校验）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple

from jsonschema import validate as js_validate

from core.tool_agent.actions import (
    ActionValidationError,
    AgentAction,
    ToolCallAction,
    parse_action_object,
)
from core.tool_agent.models import ACTION_PARSE_FAILED
from core.tool_agent.registry import ToolRegistry


class ActionParseCategory(str, Enum):
    """Safe, non-sensitive reason for a strict Action parse failure."""

    EMPTY_OUTPUT = "EMPTY_OUTPUT"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    INVALID_JSON = "INVALID_JSON"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    ACTION_SCHEMA_INVALID = "ACTION_SCHEMA_INVALID"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    ARGUMENTS_SCHEMA_INVALID = "ARGUMENTS_SCHEMA_INVALID"


@dataclass(frozen=True)
class ActionParseResult:
    """Strict parse result with a safe failure taxonomy."""

    action: Optional[AgentAction]
    failure_code: Optional[str]
    category: Optional[ActionParseCategory]

    def __post_init__(self) -> None:
        if self.action is not None and self.failure_code is not None:
            raise ValueError("action 与 failure_code 不能同时为非 None")
        if self.action is not None and self.category is not None:
            raise ValueError("成功解析不能带 parse category")
        if self.action is None and self.failure_code is None:
            raise ValueError("失败解析必须带 failure_code")
        if self.action is None and self.category is None:
            raise ValueError("失败解析必须带 parse category")


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    """json.loads 的 object_pairs_hook：任意层级重复 key 直接拒绝。"""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate key: {key!r}")
        result[key] = value
    return result


def strict_json_loads_no_duplicates(text: str) -> dict:
    """只接受单个 JSON object；否则抛 ValueError。

    拒绝：空输出、非法 JSON、markdown fence、前后 prose（"Extra data"）、
    顶层非 object（数组/标量）、任意层级 duplicate key。
    """
    if not isinstance(text, str):
        raise ValueError("必须是字符串")
    stripped = text.strip()
    if not stripped:
        raise ValueError("空输出")
    try:
        obj = json.loads(stripped, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError as exc:
        raise ValueError(str(exc)) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("非法 JSON（含 duplicate key / 多余内容）") from exc
    if not isinstance(obj, dict):
        raise ValueError("顶层必须是 object")
    return obj


def _parse_strict_object(
    text: str,
) -> tuple[Optional[dict], Optional[ActionParseCategory]]:
    if not isinstance(text, str):
        return None, ActionParseCategory.INVALID_JSON
    stripped = text.strip()
    if not stripped:
        return None, ActionParseCategory.EMPTY_OUTPUT
    try:
        obj = json.loads(stripped, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError:
        return None, ActionParseCategory.DUPLICATE_KEY
    except (json.JSONDecodeError, ValueError):
        return None, ActionParseCategory.INVALID_JSON
    if not isinstance(obj, dict):
        return None, ActionParseCategory.ACTION_SCHEMA_INVALID
    return obj, None


def diagnose_agent_action_text(
    text: str, registry: ToolRegistry
) -> ActionParseResult:
    """Strictly parse an Action and return a safe failure category."""

    obj, category = _parse_strict_object(text)
    if category is not None:
        return ActionParseResult(
            action=None, failure_code=ACTION_PARSE_FAILED, category=category
        )
    assert obj is not None
    try:
        action = parse_action_object(obj)
    except ActionValidationError:
        return ActionParseResult(
            action=None,
            failure_code=ACTION_PARSE_FAILED,
            category=ActionParseCategory.ACTION_SCHEMA_INVALID,
        )
    if isinstance(action, ToolCallAction):
        spec = registry.get_spec(action.tool_name)
        if spec is None:
            return ActionParseResult(
                action=None,
                failure_code=ACTION_PARSE_FAILED,
                category=ActionParseCategory.UNKNOWN_TOOL,
            )
        try:
            js_validate(action.arguments, spec.input_schema)
        except Exception:
            return ActionParseResult(
                action=None,
                failure_code=ACTION_PARSE_FAILED,
                category=ActionParseCategory.ARGUMENTS_SCHEMA_INVALID,
            )
    return ActionParseResult(action=action, failure_code=None, category=None)


def parse_agent_action_text(
    text: str, registry: ToolRegistry
) -> Tuple[Optional[AgentAction], Optional[str]]:
    """Backward-compatible ``(action, failure_code)`` strict parser wrapper.

    tool_name 必须存在于 Registry（模型不能发明 Tool）；arguments 在 Decision
    层就过 ToolSpec.input_schema。
    """
    result = diagnose_agent_action_text(text, registry)
    return result.action, result.failure_code
