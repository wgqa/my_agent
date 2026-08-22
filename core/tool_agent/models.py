"""G4-TOOL-02：Gate 4 Structured Tool Agent 核心契约（纯确定性底座）。

实现 ToolSpec / ToolCall / ToolObservation 的不可变内存快照：字段级
校验、跨字段不变量 fail-fast、schema 防外部 mutation 的独立深拷贝、
JSON 安全边界。本模块不调用 LLM、不执行任何 Handler、不实现 Tool
Loop、不注册真实工具。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from jsonschema import Draft202012Validator, SchemaError

# ---- 状态与错误码 ----

TOOL_OBSERVATION_STATUSES = ("ok", "error", "refused")

# G4-TOOL-02 本任务由 Executor 触发的错误码。
TOOL_ERROR_CODES = (
    "UNKNOWN_TOOL",
    "INVALID_TOOL_ARGUMENTS",
    "TOOL_PERMISSION_DENIED",
    "TOOL_EXECUTION_FAILED",
    "TOOL_RESULT_INVALID",
    "TOOL_BUDGET_EXCEEDED",
    "PROJECT_CONTEXT_PATH_NOT_ALLOWED",
    "PROJECT_CONTEXT_FILE_NOT_FOUND",
    "PROJECT_CONTEXT_LINE_OUT_OF_RANGE",
    "PROJECT_CONTEXT_FILE_UNREADABLE",
    "GIT_REPOSITORY_UNAVAILABLE",
    "GIT_REF_INVALID",
    "GIT_PATH_NOT_ALLOWED",
    "GIT_DIFF_UNAVAILABLE",
    "GIT_COMMAND_FAILED",
)

# Agent-level 错误码：G4-TOOL-02 只定义常量，不触发 Agent 行为。
AGENT_ERROR_CODES = (
    "ACTION_PARSE_FAILED",
    "AGENT_BUDGET_EXCEEDED",
)

TOOL_AGENT_ERROR_CODES = TOOL_ERROR_CODES + AGENT_ERROR_CODES

# ToolObservation.error_code 只允许 Tool 级错误码；Agent 级错误码（如
# ACTION_PARSE_FAILED / AGENT_BUDGET_EXCEEDED）是 Agent-level 行为，不能冒充
# 一次工具执行的 Observation 结果。
_TOOL_ERROR_CODES_SET = frozenset(TOOL_ERROR_CODES)
_STATUSES_SET = frozenset(TOOL_OBSERVATION_STATUSES)

# 具名导出（供 executor / 测试直接引用）
UNKNOWN_TOOL = "UNKNOWN_TOOL"
INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
TOOL_RESULT_INVALID = "TOOL_RESULT_INVALID"
TOOL_BUDGET_EXCEEDED = "TOOL_BUDGET_EXCEEDED"
PROJECT_CONTEXT_PATH_NOT_ALLOWED = "PROJECT_CONTEXT_PATH_NOT_ALLOWED"
PROJECT_CONTEXT_FILE_NOT_FOUND = "PROJECT_CONTEXT_FILE_NOT_FOUND"
PROJECT_CONTEXT_LINE_OUT_OF_RANGE = "PROJECT_CONTEXT_LINE_OUT_OF_RANGE"
PROJECT_CONTEXT_FILE_UNREADABLE = "PROJECT_CONTEXT_FILE_UNREADABLE"
GIT_REPOSITORY_UNAVAILABLE = "GIT_REPOSITORY_UNAVAILABLE"
GIT_REF_INVALID = "GIT_REF_INVALID"
GIT_PATH_NOT_ALLOWED = "GIT_PATH_NOT_ALLOWED"
GIT_DIFF_UNAVAILABLE = "GIT_DIFF_UNAVAILABLE"
GIT_COMMAND_FAILED = "GIT_COMMAND_FAILED"
ACTION_PARSE_FAILED = "ACTION_PARSE_FAILED"
AGENT_BUDGET_EXCEEDED = "AGENT_BUDGET_EXCEEDED"


class ToolExecutionError(Exception):
    """A Handler may return one approved code without exposing exception detail."""

    def __init__(self, error_code: str) -> None:
        if error_code not in _TOOL_ERROR_CODES_SET:
            raise ValueError(f"error_code 未知：{error_code!r}")
        self.error_code = error_code
        super().__init__(error_code)


# ---- 校验工具（类型错误统一 TypeError，值/不变量错误统一 ValueError）----


def _require_type(value: object, expected: type, label: str) -> None:
    if type(value) is not expected:
        raise TypeError(
            f"{label} 必须是 {expected.__name__}，实际 {type(value).__name__}"
        )


def _require_mapping(value: object, label: str) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} 必须是 Mapping（dict），实际 {type(value).__name__}")


def _require_non_empty_str(value: object, label: str) -> None:
    _require_type(value, str, label)
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")
    if value != value.strip():
        raise ValueError(f"{label} 首尾不允许空白")


# ---- JSON 安全边界 ----
#
# Tool arguments / results 必须是 JSON-compatible。禁止 bytes / set / Path /
# custom object / NaN / Infinity / callable；不靠 json.dumps(default=str) 偷偷
# stringify 未知对象（那会掩盖工具契约 bug）。


def json_deep_copy(value: Any) -> Any:
    """深拷贝为 JSON-compatible 结构；不可 JSON 表示的对象直接抛错。

    同时承担"防外部 mutation 的独立拷贝"与"安全归一化"两种职责：
    dict→dict、list/tuple→list、str/int/bool/None/有限 float 原样，
    其余类型一律拒绝。
    """

    if value is None or isinstance(value, (bool, str)):
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("不允许 NaN/Infinity 进入 JSON-compatible 数据")
        return value
    if isinstance(value, Mapping):
        result: dict = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"dict key 必须是 str，实际 {type(key).__name__}"
                )
            result[key] = json_deep_copy(item)
        return result
    if isinstance(value, (list, tuple)):
        return [json_deep_copy(item) for item in value]
    if callable(value):
        raise TypeError(f"不允许 callable 进入 JSON-compatible 数据：{type(value).__name__}")
    raise TypeError(f"不允许 {type(value).__name__} 进入 JSON-compatible 数据")


def _validate_schema(schema: Mapping[str, Any], label: str) -> None:
    """schema 必须是合法 JSON Schema；input_schema 另有根类型与严格策略约束。"""

    _require_mapping(schema, label)
    try:
        Draft202012Validator.check_schema(dict(schema))
    except SchemaError as exc:
        raise ValueError(f"{label} 不是合法 JSON Schema：{exc.message}") from exc
    if label == "input_schema":
        if schema.get("type") != "object":
            raise ValueError(
                f"input_schema 根类型必须是 object，实际 {schema.get('type')!r}"
            )
        if schema.get("additionalProperties") is not False:
            raise ValueError(
                "input_schema 必须是严格 object schema：additionalProperties 必须"
                "显式为 false（unknown argument 默认拒绝）"
            )


# ---- 领域模型 ----


@dataclass(frozen=True, init=False)
class ToolSpec:
    """系统允许调用的一个工具。模型唯一可见面：name / description / schemas / version。

    schema 存于私有 backing（_input_schema / _output_schema），对外通过
    property 只返回深拷贝：外部无论修改 spec.input_schema 还是嵌套值，
    都无法改动 Registry 执行时真正使用的契约（R1-1 封死 mutation）。
    """

    name: str
    description: str
    version: str
    _input_schema: Mapping[str, Any] = field(init=False, repr=False)
    _output_schema: Mapping[str, Any] = field(init=False, repr=False)

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        version: str,
    ) -> None:
        _require_non_empty_str(name, "name")
        _require_non_empty_str(description, "description")
        _require_non_empty_str(version, "version")
        _validate_schema(input_schema, "input_schema")
        _validate_schema(output_schema, "output_schema")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "version", version)
        # 私有 backing：构造时独立深拷贝，外部无法触碰。
        object.__setattr__(self, "_input_schema", json_deep_copy(input_schema))
        object.__setattr__(self, "_output_schema", json_deep_copy(output_schema))

    @property
    def input_schema(self) -> dict:
        """返回深拷贝；外部对其任何修改都只作用在拷贝上，不影响本契约。"""
        return json_deep_copy(self._input_schema)

    @property
    def output_schema(self) -> dict:
        return json_deep_copy(self._output_schema)

    def input_schema_copy(self) -> dict:
        return json_deep_copy(self._input_schema)

    def output_schema_copy(self) -> dict:
        return json_deep_copy(self._output_schema)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": json_deep_copy(self._input_schema),
            "output_schema": json_deep_copy(self._output_schema),
            "version": self.version,
        }


def _new_call_id() -> str:
    """Runtime 生成 call_id：稳定格式 + 单进程内不碰撞（UUID）。"""
    return f"call_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ToolCall:
    """一次准备执行的工具调用。

    call_id 由系统自动生成（default_factory），构造时不接受外部 call_id；
    Runtime-side 工厂是 ToolCall.create(tool_name, arguments)。模型只负责
    选工具与传参数。
    """

    tool_name: str
    arguments: Mapping[str, Any]
    # init=False：结构层禁止外部注入 call_id（R1-2），由系统 default_factory 生成。
    call_id: str = field(init=False, default_factory=_new_call_id)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.tool_name, "tool_name")
        _require_mapping(self.arguments, "arguments")
        _require_non_empty_str(self.call_id, "call_id")
        # arguments 独立深拷贝 + JSON 安全校验。
        object.__setattr__(self, "arguments", json_deep_copy(self.arguments))

    @classmethod
    def create(cls, tool_name: str, arguments: Mapping[str, Any]) -> "ToolCall":
        """Runtime-side 工厂：由系统生成 call_id，不接受外部 call_id。"""
        return cls(tool_name=tool_name, arguments=arguments)

    def arguments_copy(self) -> dict:
        return json_deep_copy(self.arguments)

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": json_deep_copy(self.arguments),
        }


@dataclass(frozen=True)
class ToolObservation:
    """工具执行后返回给 Agent 的事实结果。

    跨字段不变量：
    - status=ok        → result 非 None 且 error_code 为 None；
    - status=error/refused → result 为 None 且 error_code 非 None（已知错误码）。
    result 是独立深拷贝，不暴露 handler 原始可变引用。
    """

    call_id: str
    tool_name: str
    status: str
    result: Optional[Any]
    error_code: Optional[str]

    def __post_init__(self) -> None:
        _require_non_empty_str(self.call_id, "call_id")
        _require_non_empty_str(self.tool_name, "tool_name")
        _require_type(self.status, str, "status")
        if self.status not in _STATUSES_SET:
            raise ValueError(
                f"status 必须是 {'、'.join(TOOL_OBSERVATION_STATUSES)} 之一，"
                f"实际 {self.status!r}"
            )
        if self.error_code is not None:
            _require_type(self.error_code, str, "error_code")
            if self.error_code not in _TOOL_ERROR_CODES_SET:
                raise ValueError(f"error_code 未知：{self.error_code!r}")
        if self.status == "ok":
            if self.result is None:
                raise ValueError("status=ok 时 result 不得为 None")
            if self.error_code is not None:
                raise ValueError("status=ok 时 error_code 必须为 None")
            object.__setattr__(self, "result", json_deep_copy(self.result))
        else:
            if self.result is not None:
                raise ValueError("status=error/refused 时 result 必须为 None")
            if self.error_code is None:
                raise ValueError("status=error/refused 时 error_code 不得为 None")

    def result_copy(self) -> Optional[Any]:
        if self.result is None:
            return None
        return json_deep_copy(self.result)

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "result": None if self.result is None else json_deep_copy(self.result),
            "error_code": self.error_code,
        }
