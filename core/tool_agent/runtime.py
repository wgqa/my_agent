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
from dataclasses import replace
from pathlib import PurePosixPath

from core.tool_agent.actions import (
    AgentDecisionOutcome,
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
    EngineeringEvidence,
    KnowledgeEvidence,
    MAX_EVIDENCE_SNIPPET_LENGTH,
    RuntimeTraceEvent,
    ToolAgentBudget,
    ToolAgentRunResult,
)
from core.tool_agent.tools.test_discovery import is_test_path


_PROJECT_CODE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".ts",
        ".tsx",
    }
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


def _evidence_from_project_context(observation) -> EngineeringEvidence | None:
    """Convert one successful context read into bounded public evidence.

    The executor has already validated the Tool output schema. The defensive
    checks here keep the runtime fail-closed if a future handler violates that
    contract: malformed observations never become API-visible evidence.
    """
    if observation.status != "ok" or observation.tool_name != "read_project_context":
        return None
    result = observation.result
    if type(result) is not dict:
        return None
    path = result.get("path")
    start_line = result.get("start_line")
    end_line = result.get("end_line")
    lines = result.get("lines")
    if type(lines) is not list:
        return None
    texts: list[str] = []
    for item in lines:
        if type(item) is not dict or type(item.get("text")) is not str:
            return None
        texts.append(item["text"])
    snippet = "\n".join(texts)[:MAX_EVIDENCE_SNIPPET_LENGTH]
    if not snippet:
        return None
    try:
        if is_test_path(path):
            kind = "project_test"
        else:
            kind = (
                "project_code"
                if PurePosixPath(path).suffix.lower() in _PROJECT_CODE_SUFFIXES
                else "project_doc"
            )
        return EngineeringEvidence(
            evidence_id="E1",
            kind=kind,
            path=path,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
        )
    except (TypeError, ValueError):
        return None


def _evidence_from_git_diff(observation) -> EngineeringEvidence | None:
    """Convert one successful bounded git_diff observation into public evidence."""

    if observation.status != "ok" or observation.tool_name != "git_diff":
        return None
    result = observation.result
    if type(result) is not dict:
        return None
    path = result.get("path")
    start_line = result.get("start_line")
    end_line = result.get("end_line")
    snippet = result.get("diff")
    if (
        type(path) is not str
        or type(start_line) is not int
        or type(end_line) is not int
        or type(snippet) is not str
        or not snippet
    ):
        return None
    try:
        return EngineeringEvidence(
            evidence_id="E1",
            kind="project_change",
            path=path,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet[:MAX_EVIDENCE_SNIPPET_LENGTH],
        )
    except (TypeError, ValueError):
        return None


def _evidence_from_knowledge_search(observation) -> tuple[KnowledgeEvidence, ...]:
    """Convert only valid matches from one successful knowledge observation."""

    if observation.status != "ok" or observation.tool_name != "knowledge_search":
        return ()
    result = observation.result
    if type(result) is not dict or type(result.get("matches")) is not list:
        return ()
    evidence: list[KnowledgeEvidence] = []
    for match in result["matches"]:
        if type(match) is not dict:
            continue
        try:
            evidence.append(
                KnowledgeEvidence(
                    evidence_id="E1",
                    kind="knowledge",
                    source_name=match.get("source_name"),
                    chunk_id=match.get("chunk_id"),
                    score=match.get("score"),
                    rank=match.get("rank"),
                    snippet=match.get("snippet"),
                )
            )
        except (TypeError, ValueError):
            # Invalid backend data is not public evidence.
            continue
    return tuple(evidence)


class ToolAgentRuntime:
    """Bounded Decision → Tool → Observation loop。预算唯一所有者是 Runtime。

    Executor 固定为 ToolExecutor(registry)：Decision 与执行始终绑定同一个
    registry，杜绝 "模型看到的能力" 与 "系统实际执行的能力" 分裂。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        provider: AgentDecisionProvider,
        budget: ToolAgentBudget | None = None,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry 必须是 ToolRegistry")
        if not isinstance(provider, AgentDecisionProvider) or not callable(
            getattr(provider, "decide", None)
        ):
            raise TypeError("provider 必须实现 AgentDecisionProvider（含 decide）")
        if budget is None:
            budget = ToolAgentBudget()
        elif type(budget) is not ToolAgentBudget:
            raise TypeError(
                "budget 必须是 ToolAgentBudget 或 None（不接受 duck typing / dict / bool / 自定义对象）"
            )
        self._registry = registry
        self._provider = provider
        self._executor = ToolExecutor(registry)
        self._budget = budget

    def run(self, user_query: str) -> ToolAgentRunResult:
        if type(user_query) is not str or not user_query.strip():
            raise ValueError("user_query 必须是非空字符串")
        context: list[DecisionContextItem] = []
        executed: set[tuple[str, str]] = set()
        iterations = 0
        tool_calls = 0
        tool_errors = 0
        trace: list[RuntimeTraceEvent] = []
        evidence: list[EngineeringEvidence | KnowledgeEvidence] = []
        seen_evidence: set[tuple] = set()

        while True:
            iterations += 1
            if iterations > self._budget.max_agent_iterations:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                )

            outcome = self._provider.decide(
                self._registry, user_query, context=tuple(context)
            )
            if not isinstance(outcome, AgentDecisionOutcome):
                # Provider 违反 Protocol 属于程序契约错误，fail-fast
                raise TypeError("provider.decide 必须返回 AgentDecisionOutcome")
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
                self._append_terminal(
                    trace, iterations, tool_calls, tool_errors, outcome.failure_code
                )
                return ToolAgentRunResult(
                    status="failed",
                    answer=None,
                    reason_code=None,
                    failure_code=outcome.failure_code,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                    evidence=tuple(evidence),
                )

            action = outcome.action
            if isinstance(action, FinalAnswerAction):
                self._append_terminal(
                    trace, iterations, tool_calls, tool_errors, None
                )
                return ToolAgentRunResult(
                    status="completed",
                    answer=action.answer,
                    reason_code=None,
                    failure_code=None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                    evidence=tuple(evidence),
                )
            if isinstance(action, RefuseAction):
                self._append_terminal(
                    trace, iterations, tool_calls, tool_errors, action.reason_code
                )
                return ToolAgentRunResult(
                    status="refused",
                    answer=None,
                    reason_code=action.reason_code,
                    failure_code=None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    trace=tuple(trace),
                    evidence=tuple(evidence),
                )

            # ToolCallAction：执行前按 §11 顺序检查
            if iterations >= self._budget.max_agent_iterations:
                # 最后一次 Decision 若仍要 tool_call：没有下一次 Decision 读 Observation
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                )
            if tool_calls >= self._budget.max_tool_calls:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                )
            canonical = _canonical_call(action.tool_name, action.arguments)
            if canonical in executed:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_DUPLICATE_TOOL_CALL,
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
            observed_evidence = list(_evidence_from_knowledge_search(observation))
            observed_evidence.extend(
                item
                for item in (
                    _evidence_from_project_context(observation),
                    _evidence_from_git_diff(observation),
                )
                if item is not None
            )
            for observed in observed_evidence:
                if isinstance(observed, KnowledgeEvidence):
                    key = (
                        "knowledge",
                        observed.source_name,
                        observed.chunk_id or observed.snippet,
                    )
                else:
                    key = (
                        observed.kind,
                        observed.path,
                        observed.start_line,
                        observed.end_line,
                    )
                if key in seen_evidence:
                    continue
                seen_evidence.add(key)
                evidence.append(replace(observed, evidence_id=f"E{len(evidence) + 1}"))
            if tool_errors >= self._budget.max_tool_errors:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_TOOL_ERROR_LIMIT,
                )
            # 否则继续下一次 Decision

    def _append_terminal(
        self,
        trace: list[RuntimeTraceEvent],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str | None,
    ) -> None:
        """每次 run() 结束都追加 runtime_stopped 作为最后一条 Trace event。

        code 承载终止事实：completed→None、model refuse→reason_code、
        decision failure→failure_code、系统硬停止→termination code。
        """
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

    def _hard_stop(
        self,
        trace: list[RuntimeTraceEvent],
        evidence: list[EngineeringEvidence | KnowledgeEvidence],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str,
    ) -> ToolAgentRunResult:
        self._append_terminal(trace, iterations, tool_calls, tool_errors, code)
        return ToolAgentRunResult(
            status="refused",
            answer=None,
            reason_code=code,
            failure_code=None,
            iterations_used=iterations,
            tool_calls_used=tool_calls,
            tool_errors_used=tool_errors,
            trace=tuple(trace),
            evidence=tuple(evidence),
        )
