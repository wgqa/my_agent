"""G4-TOOL-02：ToolExecutor —— 唯一执行入口。

固定顺序流水线：resolve → input_schema 校验 → allowlist/权限 → per-call
budget guard → handler.execute → output_schema 校验 → JSON 安全 + 独立
深拷贝 → ToolObservation。任何校验/执行失败都返回结构化 Observation
（status=error + 稳定 error_code），绝不抛 traceback。

本模块只做最小 per-execution guard；Agent Loop / 硬预算状态机 / 自动重试
留给 G4-RUNTIME-05。
"""

from __future__ import annotations

from typing import Any, FrozenSet, Mapping, Optional

from jsonschema import validate as js_validate

from core.tool_agent.models import (
    INVALID_TOOL_ARGUMENTS,
    TOOL_BUDGET_EXCEEDED,
    TOOL_EXECUTION_FAILED,
    TOOL_PERMISSION_DENIED,
    TOOL_RESULT_INVALID,
    UNKNOWN_TOOL,
    ToolCall,
    ToolObservation,
    json_deep_copy,
)
from core.tool_agent.registry import ToolHandler, ToolRegistry


def _error_observation(call: ToolCall, error_code: str) -> ToolObservation:
    return ToolObservation(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status="error",
        result=None,
        error_code=error_code,
    )


class ToolExecutor:
    """唯一执行入口。固定流水线见模块 docstring。"""

    def __init__(
        self,
        registry: ToolRegistry,
        allowed_tools: Optional[FrozenSet[str]] = None,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry 必须是 ToolRegistry")
        if allowed_tools is not None:
            if not isinstance(allowed_tools, frozenset):
                raise TypeError("allowed_tools 必须是 frozenset 或 None")
            for name in allowed_tools:
                if not isinstance(name, str):
                    raise TypeError("allowed_tools 必须全部是 str")
        self._registry = registry
        self._allowed_tools = allowed_tools

    def execute(
        self,
        call: ToolCall,
        tool_call_allowed: bool = True,
    ) -> ToolObservation:
        if not isinstance(call, ToolCall):
            raise TypeError("call 必须是 ToolCall")
        if type(tool_call_allowed) is not bool:
            raise TypeError(
                "tool_call_allowed 必须是 bool（不允许 None / 0 / 字符串按 truthy 静默解释）"
            )

        # 1. resolve：不存在 → UNKNOWN_TOOL
        registered = self._registry.resolve(call.tool_name)
        if registered is None:
            return _error_observation(call, UNKNOWN_TOOL)
        spec = registered.spec
        handler: ToolHandler = registered.handler

        # 2. input_schema 校验（额外参数会被 additionalProperties:false 拒绝）
        try:
            js_validate(call.arguments_copy(), spec.input_schema)
        except Exception:
            return _error_observation(call, INVALID_TOOL_ARGUMENTS)

        # 3. allowlist / permission：不在 allowlist → TOOL_PERMISSION_DENIED
        if self._allowed_tools is not None and call.tool_name not in self._allowed_tools:
            return _error_observation(call, TOOL_PERMISSION_DENIED)

        # 4. per-call budget guard：系统告知预算耗尽 → TOOL_BUDGET_EXCEEDED
        if not tool_call_allowed:
            return _error_observation(call, TOOL_BUDGET_EXCEEDED)

        # 5. handler.execute：异常 → TOOL_EXECUTION_FAILED，绝不 traceback
        #    传给 handler 的是真正 detached 深拷贝，handler 修改参数不会
        #    反向污染 ToolCall 内部 arguments（R1-3）。
        try:
            raw_result: object = handler.execute(call.arguments_copy())
        except Exception:
            return _error_observation(call, TOOL_EXECUTION_FAILED)

        # 6. output_schema 校验：非法 output 不能当 success
        try:
            js_validate(raw_result, spec.output_schema)
        except Exception:
            return _error_observation(call, TOOL_RESULT_INVALID)

        # 7. JSON 安全 + 独立深拷贝（脱离 handler 返回对象的可变引用）
        if raw_result is None:
            return _error_observation(call, TOOL_RESULT_INVALID)
        try:
            safe_result: Any = json_deep_copy(raw_result)
        except (TypeError, ValueError):
            return _error_observation(call, TOOL_RESULT_INVALID)

        return ToolObservation(
            call_id=call.call_id,
            tool_name=call.tool_name,
            status="ok",
            result=safe_result,
            error_code=None,
        )
