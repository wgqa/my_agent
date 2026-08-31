"""G4-TOOL-02：ToolRegistry / RegisteredTool / ToolHandler（内部执行接口）。

Registry 是工具的真相来源：保存 name → RegisteredTool（spec + handler）。
模型只能通过 get_spec / list_specs 看到 ToolSpec，绝看不到 handler；
handler 只由系统实例化并注册，不序列化、不进入 ToolSpec / ToolCall。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

from core.tool_agent.models import ToolSpec


@runtime_checkable
class ToolHandler(Protocol):
    """系统内部执行接口。

    Handler 由系统实例化并注册；不进入 ToolSpec / ToolCall；不序列化；
    不暴露给模型。模型永远只能输出 tool_name + arguments。
    """

    def execute(self, arguments: Mapping[str, Any]) -> object:
        ...


@dataclass(frozen=True)
class RegisteredTool:
    """Registry 内部保存的绑定：spec（模型可见面）+ handler（系统私有）。"""

    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """name → RegisteredTool 的真相来源。

    不保存任意 callable 路径；注册时绑定 ToolSpec + ToolHandler，重复
    name fail-fast，不允许覆盖。
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if not isinstance(spec, ToolSpec):
            raise TypeError("spec 必须是 ToolSpec")
        if inspect.isclass(handler):
            raise TypeError("handler 必须是一次可调用的实例，不允许传入类")
        if not isinstance(handler, ToolHandler) or not callable(
            getattr(handler, "execute", None)
        ):
            raise TypeError("handler 必须实现 ToolHandler 协议（可调用 execute(arguments)）")
        if spec.name in self._tools:
            raise ValueError(f"工具 {spec.name!r} 已注册，不允许覆盖")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def resolve(self, name: str) -> Optional[RegisteredTool]:
        """按 name 查找；不存在返回 None（由 Executor 转成 UNKNOWN_TOOL）。"""
        return self._tools.get(name)

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        """模型可访问的只读面：只返回 ToolSpec，不暴露 handler。"""
        registered = self._tools.get(name)
        return registered.spec if registered is not None else None

    def list_specs(self) -> Sequence[ToolSpec]:
        """deterministic：按 name 排序；只返回 ToolSpec，绝不返回 handler。"""
        return tuple(self._tools[name].spec for name in sorted(self._tools))

    def without(self, disabled_tools: frozenset[str]) -> "ToolRegistry":
        """Return a run-scoped registry with the named Tools removed.

        The returned registry retains the exact registered ToolSpec/handler
        bindings. It is therefore the same capability view for Decision and
        execution, while the base registry used by legacy runs is untouched.
        """

        if not isinstance(disabled_tools, frozenset) or any(
            type(name) is not str for name in disabled_tools
        ):
            raise TypeError("disabled_tools 必须是字符串 frozenset")
        filtered = ToolRegistry()
        for name in sorted(self._tools):
            if name not in disabled_tools:
                registered = self._tools[name]
                filtered.register(registered.spec, registered.handler)
        return filtered

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
