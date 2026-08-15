"""G4-RUNTIME-05：Bounded Tool Agent Loop 的强类型模型。

定义 ToolAgentBudget（v1 冻结 5/4/2）、DecisionContextItem（Observation
事实，非 CoT）、RuntimeTraceEvent（结构化 Trace）、ToolAgentRunResult
（跨字段不变量）与 AgentDecisionProvider 最小协议。本模块不调用 LLM、
不执行 Tool。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

from core.tool_agent.actions import AgentDecisionOutcome
from core.tool_agent.models import (
    AGENT_BUDGET_EXCEEDED,
    TOOL_OBSERVATION_STATUSES,
    json_deep_copy,
)

# Agent-level termination codes（系统硬停止，非模型 RefuseAction、非 ToolObservation）。
AGENT_DUPLICATE_TOOL_CALL = "AGENT_DUPLICATE_TOOL_CALL"
AGENT_TOOL_ERROR_LIMIT = "AGENT_TOOL_ERROR_LIMIT"
AGENT_TERMINATION_CODES = (
    AGENT_BUDGET_EXCEEDED,
    AGENT_DUPLICATE_TOOL_CALL,
    AGENT_TOOL_ERROR_LIMIT,
)

RUN_STATUSES = ("completed", "refused", "failed")
TRACE_EVENT_TYPES = (
    "decision_completed",
    "tool_call_created",
    "tool_observation",
    "runtime_stopped",
)


def _require_non_negative_int(value: object, label: str) -> None:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError(f"{label} 必须是严格 int（不允许 bool）")
    if value < 0:
        raise ValueError(f"{label} 必须非负")


@dataclass(frozen=True)
class ToolAgentBudget:
    """v1 冻结硬预算；系统控制，LLM 无权查看或修改。"""

    max_agent_iterations: int = 5
    max_tool_calls: int = 4
    max_tool_errors: int = 2

    def __post_init__(self) -> None:
        for label, value, cap in (
            ("max_agent_iterations", self.max_agent_iterations, 5),
            ("max_tool_calls", self.max_tool_calls, 4),
            ("max_tool_errors", self.max_tool_errors, 2),
        ):
            if type(value) is not int or isinstance(value, bool):
                raise TypeError(f"{label} 必须是严格 int（不允许 bool）")
            if value <= 0:
                raise ValueError(f"{label} 必须 > 0，实际 {value}")
            if value > cap:
                raise ValueError(
                    f"{label} 不允许超过冻结上限 {cap}（v1 冻结 5/4/2，实际 {value}）"
                )


@dataclass(frozen=True)
class DecisionContextItem:
    """一次 Tool 执行的事实反馈给模型。

    只含"模型动作事实 + Tool 执行事实"：tool_name / arguments / call_id /
    observation.status / result / error_code。不是 CoT，不含 thought/raw
    output/system prompt。arguments 与 result 是 detached 深拷贝。
    """

    tool_name: str
    arguments: Mapping[str, Any]
    call_id: str
    observation_status: str
    observation_result: Optional[Any]
    observation_error_code: Optional[str]

    def __post_init__(self) -> None:
        for label in ("tool_name", "call_id"):
            value = getattr(self, label)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{label} 必须是非空字符串")
        if self.observation_status not in TOOL_OBSERVATION_STATUSES:
            raise ValueError(
                f"observation_status 必须是 "
                f"{'、'.join(TOOL_OBSERVATION_STATUSES)} 之一"
            )
        object.__setattr__(self, "arguments", json_deep_copy(self.arguments))
        object.__setattr__(
            self,
            "observation_result",
            None if self.observation_result is None else json_deep_copy(self.observation_result),
        )

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "arguments": json_deep_copy(self.arguments),
            "call_id": self.call_id,
            "observation_status": self.observation_status,
            "observation_result": None
            if self.observation_result is None
            else json_deep_copy(self.observation_result),
            "observation_error_code": self.observation_error_code,
        }


@dataclass(frozen=True)
class RuntimeTraceEvent:
    """结构化 Trace 事件。Trace ≠ CoT：只记"发生了什么"，不记模型推理。

    不保存 raw LLM output / CoT / 完整 Prompt / API key / traceback /
    exception repr / 环境变量 / 本地绝对敏感路径。
    """

    iteration: int
    event_type: str
    action_type: Optional[str] = None
    tool_name: Optional[str] = None
    call_id: Optional[str] = None
    tool_status: Optional[str] = None
    error_code: Optional[str] = None
    iterations_used: int = 0
    tool_calls_used: int = 0
    tool_errors_used: int = 0

    def __post_init__(self) -> None:
        if self.event_type not in TRACE_EVENT_TYPES:
            raise ValueError(f"event_type 必须是 {'、'.join(TRACE_EVENT_TYPES)} 之一")
        _require_non_negative_int(self.iteration, "iteration")
        _require_non_negative_int(self.iterations_used, "iterations_used")
        _require_non_negative_int(self.tool_calls_used, "tool_calls_used")
        _require_non_negative_int(self.tool_errors_used, "tool_errors_used")

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "event_type": self.event_type,
            "action_type": self.action_type,
            "tool_name": self.tool_name,
            "call_id": self.call_id,
            "tool_status": self.tool_status,
            "error_code": self.error_code,
            "iterations_used": self.iterations_used,
            "tool_calls_used": self.tool_calls_used,
            "tool_errors_used": self.tool_errors_used,
        }


@dataclass(frozen=True)
class ToolAgentRunResult:
    """Bounded Loop 的一次运行结果。

    跨字段不变量：
    - completed → answer 非空，reason_code/failure_code 为 None；
    - refused   → answer None，reason_code（模型 reason 或系统 termination code）非空；
    - failed    → answer None，failure_code 非空。
    """

    status: str
    answer: Optional[str]
    reason_code: Optional[str]
    failure_code: Optional[str]
    iterations_used: int
    tool_calls_used: int
    tool_errors_used: int
    trace: Sequence[RuntimeTraceEvent]

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError(f"status 必须是 {'、'.join(RUN_STATUSES)} 之一")
        _require_non_negative_int(self.iterations_used, "iterations_used")
        _require_non_negative_int(self.tool_calls_used, "tool_calls_used")
        _require_non_negative_int(self.tool_errors_used, "tool_errors_used")
        if self.status == "completed":
            if type(self.answer) is not str or not self.answer.strip():
                raise ValueError("completed 要求 answer 非空")
            if self.reason_code is not None or self.failure_code is not None:
                raise ValueError("completed 要求 reason_code/failure_code 为 None")
        elif self.status == "refused":
            if self.answer is not None:
                raise ValueError("refused 要求 answer 为 None")
            if not self.reason_code:
                raise ValueError("refused 要求 reason/termination code 非空")
            if self.failure_code is not None:
                raise ValueError("refused 要求 failure_code 为 None")
        else:  # failed
            if self.answer is not None:
                raise ValueError("failed 要求 answer 为 None")
            if not self.failure_code:
                raise ValueError("failed 要求 failure_code 非空")

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "reason_code": self.reason_code,
            "failure_code": self.failure_code,
            "iterations_used": self.iterations_used,
            "tool_calls_used": self.tool_calls_used,
            "tool_errors_used": self.tool_errors_used,
            "trace": [event.to_dict() for event in self.trace],
        }


@runtime_checkable
class AgentDecisionProvider(Protocol):
    """最小 Decision Provider 协议：Runtime 只依赖它，不写死具体实现。"""

    def decide(
        self,
        registry: object,
        user_query: str,
        *,
        context: Sequence[Any] = (),
    ) -> AgentDecisionOutcome:
        ...
