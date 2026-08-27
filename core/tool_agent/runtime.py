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
import inspect
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Callable

from core.engineering_requirements import (
    EngineeringEvidenceRequirement,
    EvidenceRequirementState,
    evaluate_evidence_requirement,
)
from core.tool_agent.activity import (
    ActivityEvent,
    EvidenceAddedActivity,
    RunStartedActivity,
    VerificationBlockedActivity,
    build_tool_activity_event,
)
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
    INSUFFICIENT_EVIDENCE_TO_FINALIZE,
    AgentDecisionProvider,
    DecisionControlState,
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

_EVIDENCE_PRODUCER_TOOLS = {
    "knowledge": ("knowledge_search",),
    "project_change": ("git_diff",),
    "project_code": ("read_project_context",),
    "project_doc": ("read_project_context",),
    "project_test": ("read_project_context",),
}


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


def _evidence_fingerprint(
    evidence: list[EngineeringEvidence | KnowledgeEvidence],
) -> tuple[tuple]:
    """Return an order-independent identity fingerprint without content."""

    identities: list[tuple] = []
    for item in evidence:
        if isinstance(item, KnowledgeEvidence):
            identities.append(
                (
                    "knowledge",
                    item.source_name,
                    item.chunk_id if item.chunk_id is not None else item.rank,
                )
            )
        else:
            identities.append(
                (item.kind, item.path, item.start_line, item.end_line)
            )
    return tuple(sorted(identities, key=repr))


def _missing_evidence_kinds(
    requirement: EngineeringEvidenceRequirement,
    state: EvidenceRequirementState,
) -> frozenset[str]:
    """Find producer kinds without pretending that a path shortfall is a group miss."""

    kinds = {
        kind
        for group in state.missing_evidence_groups
        for kind in group
    }
    if (
        not kinds
        and state.distinct_project_code_paths
        < requirement.min_distinct_project_code_paths
    ):
        kinds.add("project_code")
    return frozenset(kinds)


def _recovery_is_feasible(
    registry: ToolRegistry,
    requirement: EngineeringEvidenceRequirement,
    state: EvidenceRequirementState,
    *,
    iterations: int,
    tool_calls: int,
    tool_errors: int,
    budget: ToolAgentBudget,
) -> bool:
    """Check whether the next Decision can still execute a producer Tool."""

    # The last Decision cannot execute a Tool: the next iteration must be
    # strictly before the hard iteration cap.
    if iterations + 1 >= budget.max_agent_iterations:
        return False
    if tool_calls >= budget.max_tool_calls or tool_errors >= budget.max_tool_errors:
        return False
    for kind in _missing_evidence_kinds(requirement, state):
        if any(tool_name in registry for tool_name in _EVIDENCE_PRODUCER_TOOLS[kind]):
            return True
    return False


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

    def run(
        self,
        user_query: str,
        *,
        evidence_requirement: EngineeringEvidenceRequirement | None = None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None = None,
        activity_sink: Callable[[ActivityEvent], None] | None = None,
    ) -> ToolAgentRunResult:
        if type(user_query) is not str or not user_query.strip():
            raise ValueError("user_query 必须是非空字符串")
        if evidence_requirement is not None and not isinstance(
            evidence_requirement, EngineeringEvidenceRequirement
        ):
            raise TypeError(
                "evidence_requirement 必须是 EngineeringEvidenceRequirement 或 None"
            )
        context: list[DecisionContextItem] = []
        executed: set[tuple[str, str]] = set()
        iterations = 0
        tool_calls = 0
        tool_errors = 0
        trace: list[RuntimeTraceEvent] = []
        evidence: list[EngineeringEvidence | KnowledgeEvidence] = []
        seen_evidence: set[tuple] = set()
        last_blocked_fingerprint: tuple[tuple] | None = None
        recovery_control_active = False
        activity_number = 0

        self._record_activity(
            RunStartedActivity(available_tool_count=len(self._registry)),
            activity_sink,
        )

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
                    trace_sink,
                )

            guard_state = (
                evaluate_evidence_requirement(evidence_requirement, evidence)
                if evidence_requirement is not None
                else None
            )
            if guard_state is None or guard_state.satisfied:
                recovery_control_active = False
            control_state = DecisionControlState(
                iteration=iterations,
                remaining_iterations=self._budget.max_agent_iterations - iterations,
                remaining_tool_calls=self._budget.max_tool_calls - tool_calls,
                tool_call_allowed=(
                    iterations < self._budget.max_agent_iterations
                    and tool_calls < self._budget.max_tool_calls
                ),
                must_terminate=(
                    iterations >= self._budget.max_agent_iterations
                    or tool_calls >= self._budget.max_tool_calls
                ),
                finalization_blocked=(
                    True
                    if recovery_control_active and guard_state is not None
                    else None
                ),
                missing_evidence_groups=(
                    guard_state.missing_evidence_groups
                    if recovery_control_active and guard_state is not None
                    else ()
                ),
                current_distinct_project_code_paths=(
                    guard_state.distinct_project_code_paths
                    if recovery_control_active and guard_state is not None
                    else None
                ),
                required_min_distinct_project_code_paths=(
                    guard_state.required_min_distinct_project_code_paths
                    if recovery_control_active and guard_state is not None
                    else None
                ),
            )
            outcome = self._decide(
                user_query, context=tuple(context), control_state=control_state
            )
            if not isinstance(outcome, AgentDecisionOutcome):
                # Provider 违反 Protocol 属于程序契约错误，fail-fast
                raise TypeError("provider.decide 必须返回 AgentDecisionOutcome")
            self._record_trace(
                trace,
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="decision_completed",
                    action_type=outcome.action.action if outcome.action is not None else None,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                    provider_call_count=(
                        outcome.call_metadata.call_count
                        if outcome.call_metadata is not None
                        else None
                    ),
                    repair_attempted=(
                        outcome.call_metadata.repair_attempted
                        if outcome.call_metadata is not None
                        else None
                    ),
                    repair_succeeded=(
                        outcome.call_metadata.repair_succeeded
                        if outcome.call_metadata is not None
                        else None
                    ),
                    parse_failure_category=(
                        outcome.call_metadata.initial_parse_category
                        if outcome.call_metadata is not None
                        else None
                    ),
                ),
                trace_sink,
            )

            if outcome.failure_code is not None:
                self._append_terminal(
                    trace,
                    iterations,
                    tool_calls,
                    tool_errors,
                    outcome.failure_code,
                    trace_sink,
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
                if evidence_requirement is not None:
                    state = evaluate_evidence_requirement(evidence_requirement, evidence)
                    if not state.satisfied:
                        fingerprint = _evidence_fingerprint(evidence)
                        if (
                            last_blocked_fingerprint is not None
                            and fingerprint == last_blocked_fingerprint
                        ):
                            return self._hard_stop(
                                trace,
                                evidence,
                                iterations,
                                tool_calls,
                                tool_errors,
                                INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                trace_sink,
                            )
                        if not _recovery_is_feasible(
                            self._registry,
                            evidence_requirement,
                            state,
                            iterations=iterations,
                            tool_calls=tool_calls,
                            tool_errors=tool_errors,
                            budget=self._budget,
                        ):
                            return self._hard_stop(
                                trace,
                                evidence,
                                iterations,
                                tool_calls,
                                tool_errors,
                                INSUFFICIENT_EVIDENCE_TO_FINALIZE,
                                trace_sink,
                            )
                        self._record_trace(
                            trace,
                            RuntimeTraceEvent(
                                iteration=iterations,
                                event_type="finalization_guard_blocked",
                                guard_status="blocked",
                                missing_evidence_groups=state.missing_evidence_groups,
                                distinct_project_code_paths=(
                                    state.distinct_project_code_paths
                                ),
                                required_min_distinct_project_code_paths=(
                                    state.required_min_distinct_project_code_paths
                                ),
                                iterations_used=iterations,
                                tool_calls_used=tool_calls,
                                tool_errors_used=tool_errors,
                            ),
                            trace_sink,
                        )
                        self._record_activity(
                            VerificationBlockedActivity(
                                iteration=iterations,
                                missing_evidence_kinds=tuple(
                                    sorted(_missing_evidence_kinds(evidence_requirement, state))
                                ),
                            ),
                            activity_sink,
                        )
                        last_blocked_fingerprint = fingerprint
                        recovery_control_active = True
                        continue
                self._append_terminal(
                    trace, iterations, tool_calls, tool_errors, None, trace_sink
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
                    trace,
                    iterations,
                    tool_calls,
                    tool_errors,
                    action.reason_code,
                    trace_sink,
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
                    trace_sink,
                )
            if tool_calls >= self._budget.max_tool_calls:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_BUDGET_EXCEEDED,
                    trace_sink,
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
                    trace_sink,
                )

            call = ToolCall.create(action.tool_name, action.arguments)
            activity_number += 1
            activity_id = f"A{activity_number}"
            self._record_activity(
                build_tool_activity_event(
                    activity_id=activity_id,
                    iteration=iterations,
                    tool_name=call.tool_name,
                    state="started",
                    arguments=action.arguments,
                ),
                activity_sink,
            )
            self._record_trace(
                trace,
                RuntimeTraceEvent(
                    iteration=iterations,
                    event_type="tool_call_created",
                    action_type="tool_call",
                    tool_name=call.tool_name,
                    call_id=call.call_id,
                    iterations_used=iterations,
                    tool_calls_used=tool_calls,
                    tool_errors_used=tool_errors,
                ),
                trace_sink,
            )
            observation = self._executor.execute(call)
            tool_calls += 1
            if observation.status != "ok":
                tool_errors += 1
            executed.add(canonical)
            self._record_trace(
                trace,
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
                ),
                trace_sink,
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
            added_evidence_ids: list[str] = []
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
                added = replace(observed, evidence_id=f"E{len(evidence) + 1}")
                evidence.append(added)
                added_evidence_ids.append(added.evidence_id)
                evidence_activity = EvidenceAddedActivity.try_from_public_evidence(added)
                if evidence_activity is not None:
                    self._record_activity(evidence_activity, activity_sink)
            self._record_activity(
                build_tool_activity_event(
                    activity_id=activity_id,
                    iteration=iterations,
                    tool_name=call.tool_name,
                    state="completed" if observation.status == "ok" else "error",
                    arguments=action.arguments,
                    observation=observation,
                    evidence_ids_added=tuple(added_evidence_ids),
                ),
                activity_sink,
            )
            if tool_errors >= self._budget.max_tool_errors:
                return self._hard_stop(
                    trace,
                    evidence,
                    iterations,
                    tool_calls,
                    tool_errors,
                    AGENT_TOOL_ERROR_LIMIT,
                    trace_sink,
                )
            # 否则继续下一次 Decision

    def _decide(
        self,
        user_query: str,
        *,
        context: tuple[DecisionContextItem, ...],
        control_state: DecisionControlState,
    ) -> AgentDecisionOutcome:
        """Pass trusted control state without breaking pre-v1 test providers.

        The production provider implements the extended protocol. Older
        injected providers that only implement the original context keyword
        remain valid; no provider exception is caught or reclassified here.
        """
        decide = self._provider.decide
        try:
            parameters = inspect.signature(decide).parameters.values()
        except (TypeError, ValueError):
            parameters = ()
        accepts_control_state = any(
            parameter.name == "control_state"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        kwargs = {"context": context}
        if accepts_control_state:
            kwargs["control_state"] = control_state
        return decide(self._registry, user_query, **kwargs)

    def _append_terminal(
        self,
        trace: list[RuntimeTraceEvent],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str | None,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None,
    ) -> None:
        """每次 run() 结束都追加 runtime_stopped 作为最后一条 Trace event。

        code 承载终止事实：completed→None、model refuse→reason_code、
        decision failure→failure_code、系统硬停止→termination code。
        """
        self._record_trace(
            trace,
            RuntimeTraceEvent(
                iteration=iterations,
                event_type="runtime_stopped",
                error_code=code,
                iterations_used=iterations,
                tool_calls_used=tool_calls,
                tool_errors_used=tool_errors,
            ),
            trace_sink,
        )

    @staticmethod
    def _record_trace(
        trace: list[RuntimeTraceEvent],
        event: RuntimeTraceEvent,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None,
    ) -> None:
        """Append the canonical trace before notifying an optional observer.

        Observability is deliberately outside the Runtime control plane. A UI
        or transport failure therefore cannot alter the result of this run.
        """

        trace.append(event)
        if trace_sink is not None:
            try:
                trace_sink(event)
            except Exception:
                pass

    @staticmethod
    def _record_activity(
        event: ActivityEvent,
        activity_sink: Callable[[ActivityEvent], None] | None,
    ) -> None:
        """Notify the optional observer without entering Runtime control flow."""

        if activity_sink is not None:
            try:
                activity_sink(event)
            except Exception:
                pass

    def _hard_stop(
        self,
        trace: list[RuntimeTraceEvent],
        evidence: list[EngineeringEvidence | KnowledgeEvidence],
        iterations: int,
        tool_calls: int,
        tool_errors: int,
        code: str,
        trace_sink: Callable[[RuntimeTraceEvent], None] | None,
    ) -> ToolAgentRunResult:
        self._append_terminal(
            trace, iterations, tool_calls, tool_errors, code, trace_sink
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
            evidence=tuple(evidence),
        )
