"""G4-AGENT-04：严格结构化 Action 解析。

只接受"一个 JSON object"：拒绝 markdown fence、前后 prose、空输出、
数组/标量顶层、任意层级 duplicate key。随后把 object 校验成 AgentAction
（精确字段集合），并在 Decision 层完成 tool_name 必须来自 Registry 与
arguments 过 input_schema 的第一道 schema 校验（第二道是 ToolExecutor
真正执行前再校验）。
"""

from __future__ import annotations

import json
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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    """json.loads 的 object_pairs_hook：任意层级重复 key 直接拒绝。"""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key!r}")
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
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("非法 JSON（含 duplicate key / 多余内容）") from exc
    if not isinstance(obj, dict):
        raise ValueError("顶层必须是 object")
    return obj


def parse_agent_action_text(
    text: str, registry: ToolRegistry
) -> Tuple[Optional[AgentAction], Optional[str]]:
    """把模型输出解析成 (action, failure_code)。模型输出非法时 failure_code 非 None。

    tool_name 必须存在于 Registry（模型不能发明 Tool）；arguments 在 Decision
    层就过 ToolSpec.input_schema。
    """
    try:
        obj = strict_json_loads_no_duplicates(text)
    except ValueError:
        return None, ACTION_PARSE_FAILED
    try:
        action = parse_action_object(obj)
    except ActionValidationError:
        return None, ACTION_PARSE_FAILED
    if isinstance(action, ToolCallAction):
        spec = registry.get_spec(action.tool_name)
        if spec is None:
            return None, ACTION_PARSE_FAILED  # 模型发明 Tool → 拒绝
        try:
            js_validate(action.arguments, spec.input_schema)
        except Exception:
            return None, ACTION_PARSE_FAILED  # arguments 不合 schema → 拒绝
    return action, None
