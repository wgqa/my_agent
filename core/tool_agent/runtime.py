"""G4-RUNTIME-05：Bounded Tool Agent Loop。

第一次把 Decision Provider → AgentAction → ToolCall → ToolExecutor →
ToolObservation 接成 Decision → Action → Observation → Decision 的有界
循环。硬预算（5/4/2）由 ToolAgentBudget 系统控制，LLM 无权修改；完全
重复 ToolCall 去重、连续失败重复阻止、最后一次 Decision 不再执行 Tool
（AGENT_BUDGET_EXCEEDED）。Tool Observation 是"不可信事实"，以
DecisionContextItem 反馈给模型，但绝不作为系统指令。本模块不调用真实 LLM。
"""

from __future__ import annotations

import json

from core.tool_agent.actions import (
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import AGENT_BUDGET_EXCEEDED, ToolCall, json_deep_copy
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime_models import (
    AGENT_DUPLICATE_TOOL_CALL,
    AGENT_TOOL_ERROR_LIMIT,
    AgentDecisionProvider,
    DecisionContextItem,
    RuntimeTraceEvent,
    ToolAgentBudget,
    ToolAgentRunResult,
)


def _canonical_call(tool_name: str, arguments) -> tuple[str, str]:
    """tool_name + canonical JSON(arguments) 作为逻辑 ToolCall 身份（不含 call_id）。"""
    canonical = json.dumps(
        json_deep_copy(arguments),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (tool_name, canonical)


class ToolAgentRuntime:
    """Bounded Decision → Tool → Observation loop。预算唯一所有者是 Runtime。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        provider: AgentDecisionProvider,
        executor: ToolExecutor | None = None,
        budget: ToolAgentBudget | None = None,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry 必须是 ToolRegistry")
        if not isinstance(provider, AgentDecisionProvider) or not callable(
            getattr(provider, "decide", None)
        ):
            raise TypeError("provider 必须实现 AgentDecisionProvider（含 decide）")
        self._registry = registry
        self._provider = provider
        self._executor = executor if executor is not None else ToolExecutor(registry)
        self._budget = budget if budget is not None else ToolAgentBudget()

    def run(self, user_query: str) -> ToolAgentRunResult:
        if type(user_query) is not str or not user_query.strip():
            raise ValueError("user_query 必须是非空字符串")
        context: list[DecisionContextItem] = []
        executed: set[tuple[str, str]] = set()
        iterations = 0
        tool_calls = 0
        tool_errors = 0
        trace: list[RuntimeTraceEvent] = []

        while True:
            iterations += 1
            if iterations > self._budget.max_agent_iterations:
                return self._hard_stop(
                    trace, iterations, tool_calls, tool_errors, AGENT_BUDGET_EXCEEDED
                )

            outcome = self._provider.decide(
                self._registry, user_query, context=tuple(context)
            )
            trace.append(
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="decision_completed",
                    action_type=outcome.action.action if outcome.action is not None else None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                )
            )

            if outcome.failure_code is not None:
                return ToolAgentRunResult(
                    status="failed",
                    answer=None,
                    reason_code=None,
                    failure_code=outcome.failure_code,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                )

            action = outcome.action
            if isinstance(action, FinalAnswerAction):
                return ToolAgentRunResult(
                    status="completed",
                    answer=action.answer,
                    reason_code=None,
                    failure_code=None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                )
            if isinstance(action, RefuseAction):
                return ToolAgentRunResult(
                    status="refused",
                    answer=None,
                    reason_code=action.reason_code,
                    failure_code=None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                )

            # ToolCallAction：执行前按 §11 顺序检查
            if iterations >= self._budget.max_agent_iterations:
                # 最后一次 Decision 若仍要 tool_call：没有下一次 Decision 读 Observation
                return self._hard_stop(
                    trace, iterations, tool_calls, tool_errors, AGENT_BUDGET_EXCEEDED
                )
            if tool_calls >= self._budget.max_tool_calls:
                return self._hard_stop(
                    trace, iterations, tool_calls, tool_errors, AGENT_BUDGET_EXCEEDED
                )
            canonical = _canonical_call(action.tool_name, action.arguments)
            if canonical in executed:
                return self._hard_stop(
                    trace, iterations, tool_calls, tool_errors, AGENT_DUPLICATE_TOOL_CALL
                )

            call = ToolCall.create(action.tool_name, action.arguments)
            trace.append(
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="tool_call_created",
                    action_type="tool_call",
                    tool_name=call.tool_name,
                    call_id=call.call_id,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                )
            )
            observation = self._executor.execute(call)
            tool_calls += 1
            if observation.status != "ok":
                tool_errors += 1
            executed.add(canonical)
            trace.append(
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="tool_observation",
                    action_type="tool_call",
                    tool_name=call.tool_name,
                    call_id=call.call_id,
                    tool_status=observation.status,
                    error_code=observation.error_code,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                )
            )
            context.append(
                DecisionContextItem(
                    tool_name=call.tool_name,
                    arguments=action.arguments,
                    call_id=call.call_id,
                    observation_status=observation.status,
                    observation_result=observation.result,
                    observation_error_code=observation.error_code,
                )
            )
            if tool_errors >= self._budget.max_tool_errors:
                return self._hard_stop(
                    trace, iterations, tool_calls, tool_errors, AGENT_TOOL_ERROR_LIMIT
                )
            # 否则继续下一次 Decision

    def _hard_stop(
        self,
        trace: list[RuntimeTraceEvent],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str,
    ) -> ToolAgentRunResult:
        trace.append(
            RuntimeTraceEvent(
                iteration=iterations,
                event_type="runtime_stopped",
                error_code=code,
                iterations_used=iterations,
                tool_calls_used=tool_calls,
                tool_errors_used=tool_errors,
            )
        )
        return ToolAgentRunResult(
            status="refused",
            answer=None,
            reason_code=code,
            failure_code=None,
            iterations_used=iterations,
            tool_calls_used=tool_calls,
            tool_errors_used=tool_errors,
            trace=tuple(trace),
        )
