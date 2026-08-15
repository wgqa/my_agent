"""G4-AGENT-04：结构化 Tool 决策的强类型 Action 契约。

定义 ToolCallAction / FinalAnswerAction / RefuseAction 三个独立类型（强
判别联合），AgentDecisionOutcome（不用异常代表"模型输出错了"）与
AgentDecisionCallMetadata（Provider 调用身份/观测）。本模块只做形状与取值
校验；tool_name 是否在 Registry、arguments 是否过 input_schema 由
action_parser 在拿到 Registry 后完成（Decision 层第一道 schema 校验）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Union

from core.tool_agent.models import ACTION_PARSE_FAILED

# Agent-level 稳定错误码（Provider / 决策层，不是 ToolObservation.error_code）。
ACTION_PROVIDER_ERROR = "ACTION_PROVIDER_ERROR"
ACTION_TIMEOUT = "ACTION_TIMEOUT"
AGENT_DECISION_FAILURE_CODES = (
    ACTION_PARSE_FAILED,
    ACTION_PROVIDER_ERROR,
    ACTION_TIMEOUT,
)

ACTION_NAMES = ("tool_call", "final_answer", "refuse")

REFUSE_REASON_CODES = (
    "UNSUPPORTED_REQUEST",
    "UNSAFE_REQUEST",
    "INSUFFICIENT_INFORMATION",
)

MAX_ANSWER_CHARS = 4000

# 每种 action 允许的顶层字段集合（exact，不能多也不能少）。
_ACTION_FIELD_SETS = {
    "tool_call": frozenset({"action", "tool_name", "arguments"}),
    "final_answer": frozenset({"action", "answer"}),
    "refuse": frozenset({"action", "reason_code"}),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ActionValidationError(ValueError):
    """AgentAction 形状/取值校验失败；由 action_parser 转 ACTION_PARSE_FAILED。"""


def _require_non_empty_str(value: object, label: str) -> None:
    if type(value) is not str:
        raise ActionValidationError(f"{label} 必须是非空字符串")
    if not value.strip():
        raise ActionValidationError(f"{label} 不能为空或只含空白")


@dataclass(frozen=True)
class ToolCallAction:
    """模型选择调用一个 Tool。只含模型有权决定的字段（无 call_id/handler 等）。"""

    action: str
    tool_name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class FinalAnswerAction:
    """模型直接给出最终答案。不得携带任何 tool 字段。"""

    action: str
    answer: str


@dataclass(frozen=True)
class RefuseAction:
    """模型拒绝回答。reason_code 必须是冻结集合之一。"""

    action: str
    reason_code: str


AgentAction = Union[ToolCallAction, FinalAnswerAction, RefuseAction]


def parse_action_object(obj: object) -> AgentAction:
    """把模型输出的 dict 解析成 AgentAction；非法一律抛 ActionValidationError。

    顶层字段必须恰好等于该 action 的字段集合（拒绝 unknown / missing）。
    """
    if not isinstance(obj, dict):
        raise ActionValidationError("必须是 JSON object")
    action = obj.get("action")
    if type(action) is not str:
        raise ActionValidationError("action 必须是非空字符串")
    if action not in _ACTION_FIELD_SETS:
        raise ActionValidationError(f"未知 action：{action!r}")
    allowed = _ACTION_FIELD_SETS[action]
    if set(obj.keys()) != allowed:
        extra = sorted(set(obj.keys()) - allowed)
        missing = sorted(allowed - set(obj.keys()))
        raise ActionValidationError(
            f"action={action!r} 字段集合必须恰好是 {sorted(allowed)}；"
            f"多余 {extra}、缺失 {missing}"
        )
    if action == "tool_call":
        _require_non_empty_str(obj["tool_name"], "tool_name")
        arguments = obj["arguments"]
        if not isinstance(arguments, dict):
            raise ActionValidationError("arguments 必须是 object")
        return ToolCallAction(action="tool_call", tool_name=obj["tool_name"],
                              arguments=dict(arguments))
    if action == "final_answer":
        _require_non_empty_str(obj["answer"], "answer")
        if len(obj["answer"]) > MAX_ANSWER_CHARS:
            raise ActionValidationError(
                f"answer 超过长度上限 {MAX_ANSWER_CHARS}"
            )
        return FinalAnswerAction(action="final_answer", answer=obj["answer"])
    # refuse
    _require_non_empty_str(obj["reason_code"], "reason_code")
    if obj["reason_code"] not in REFUSE_REASON_CODES:
        raise ActionValidationError(
            f"未知 reason_code：{obj['reason_code']!r}（只能选 "
            f"{'、'.join(REFUSE_REASON_CODES)}）"
        )
    return RefuseAction(action="refuse", reason_code=obj["reason_code"])


@dataclass(frozen=True)
class AgentDecisionCallMetadata:
    """一次 Decision 模型调用的身份/观测；绝不含 api_key / raw output / CoT。"""

    provider: str
    model: str
    prompt_version: str
    prompt_sha256: str
    call_count: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: float

    def __post_init__(self) -> None:
        for label in ("provider", "model", "prompt_version"):
            _require_non_empty_str(getattr(self, label), label)
        if not isinstance(self.prompt_sha256, str) or not _SHA256_RE.match(
            self.prompt_sha256
        ):
            raise ValueError("prompt_sha256 必须是 64 位十六进制")
        if type(self.call_count) is not int or isinstance(self.call_count, bool):
            raise TypeError("call_count 必须是严格 int")
        if self.call_count != 1:
            raise ValueError("call_count 必须等于 1（单次调用）")
        for label in ("input_tokens", "output_tokens"):
            value = getattr(self, label)
            if value is not None:
                if type(value) is not int or isinstance(value, bool):
                    raise TypeError(f"{label} 必须是严格 int 或 None")
                if value < 0:
                    raise ValueError(f"{label} 必须非负")
        if isinstance(self.latency_ms, bool) or type(self.latency_ms) not in (
            int,
            float,
        ):
            raise TypeError("latency_ms 必须是数字")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms 必须是有限非负数字")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "call_count": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class AgentDecisionOutcome:
    """单步 Decision 的结果。不用异常代表"模型输出错了"。

    - 正常：action 非 None，failure_code 为 None；
    - 模型输出非法：action 为 None，failure_code = ACTION_PARSE_FAILED；
    - Provider 层错误：failure_code = ACTION_PROVIDER_ERROR / ACTION_TIMEOUT。
    """

    action: Optional[AgentAction]
    failure_code: Optional[str]
    call_metadata: Optional[AgentDecisionCallMetadata]

    def __post_init__(self) -> None:
        if self.action is not None and self.failure_code is not None:
            raise ValueError("action 与 failure_code 不能同时非 None")
        if self.action is None and self.failure_code is None:
            raise ValueError("action 与 failure_code 不能同时为 None")
        if self.failure_code is not None and self.failure_code not in AGENT_DECISION_FAILURE_CODES:
            raise ValueError(f"未知 failure_code：{self.failure_code!r}")

    def to_dict(self) -> dict:
        """不含 raw model output / CoT / api_key / 完整 prompt。"""
        action_data: Optional[dict] = None
        if self.action is not None:
            if isinstance(self.action, ToolCallAction):
                action_data = {
                    "action": self.action.action,
                    "tool_name": self.action.tool_name,
                    "arguments": dict(self.action.arguments),
                }
            elif isinstance(self.action, FinalAnswerAction):
                action_data = {"action": self.action.action, "answer": self.action.answer}
            else:
                action_data = {"action": self.action.action, "reason_code": self.action.reason_code}
        return {
            "action": action_data,
            "failure_code": self.failure_code,
            "call_metadata": None
            if self.call_metadata is None
            else self.call_metadata.to_dict(),
        }
