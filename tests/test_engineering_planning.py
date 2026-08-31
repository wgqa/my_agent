"""ARCH-PLAN-04 contracts for G3 planning inside Unified Engineering Runtime."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import core.unified_engineering_runtime as unified_runtime_module
from core.conversation_context import (
    ConversationQueryResolution,
    ContextMessage,
)
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_requirements import route_engineering_evidence_requirement
from core.query_planning import (
    BaseQueryPlanner,
    OpenAICompatibleQueryPlanner,
    PlannerOutcome,
    QueryPlan,
    Subquery,
)
from core.query_planning.openai_compatible import PlannerTimeoutError
from core.tool_agent import AgentDecisionOutcome, FinalAnswerAction, ToolAgentRuntime
from core.tool_agent.activity import ActivityEvent
from core.tool_agent.registry import ToolRegistry
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)


class _RecordingPlanner(BaseQueryPlanner):
    def __init__(self, outcome: PlannerOutcome):
        self.outcome = outcome
        self.calls = []

    def plan(self, original_query: str) -> PlannerOutcome:
        self.calls.append(original_query)
        return self.outcome


class _RaisingPlanner(BaseQueryPlanner):
    def __init__(self, error: Exception):
        self.error = error
        self.calls = []

    def plan(self, original_query: str) -> PlannerOutcome:
        self.calls.append(original_query)
        raise self.error


class _ContextResolver:
    def __init__(self, resolved_query: str):
        self.resolved_query = resolved_query
        self.calls = []

    def resolve(self, history, question):
        self.calls.append((history, question))
        return ConversationQueryResolution(self.resolved_query, True, False)


class _DecisionProvider:
    def __init__(self):
        self.queries = []

    def decide(self, _registry, user_query, *, context=(), control_state=None):
        self.queries.append(user_query)
        return AgentDecisionOutcome(
            action=FinalAnswerAction("final_answer", "answer"),
            failure_code=None,
            call_metadata=None,
        )


def _single_outcome(query: str) -> PlannerOutcome:
    return PlannerOutcome(
        plan=QueryPlan.create(
            original_query=query,
            query_type="fact",
            retrieval_required=True,
            action="single_retrieval",
            reason_code="SIMPLE_FACT",
        ),
        fallback_used=False,
        failure_code=None,
    )


def _decomposed_outcome(query: str, marker: str = "secret-subquery") -> PlannerOutcome:
    return PlannerOutcome(
        plan=QueryPlan.create(
            original_query=query,
            query_type="comparison",
            retrieval_required=True,
            action="decomposed_retrieval",
            reason_code="COMPARISON_EVIDENCE",
            subqueries=(
                Subquery("sq1", marker, "first evidence", True),
                Subquery("sq2", "second subquery", "second evidence", True),
            ),
        ),
        fallback_used=False,
        failure_code=None,
    )


def _runtime(planner: BaseQueryPlanner, *, context_resolver=None, provider=None):
    provider = provider or _DecisionProvider()
    execution_runtime = ToolAgentRuntime(
        registry=ToolRegistry(),
        provider=provider,
    )
    runtime = UnifiedEngineeringRuntime(
        LegacyToolAgentExecutionAdapter(execution_runtime),
        context_resolver=context_resolver or EngineeringContextResolver(),
        evidence_planner=EngineeringEvidencePlanner(planner),
    )
    return runtime, provider


def test_engineering_planner_returns_the_exact_existing_outcome_and_plan():
    outcome = _single_outcome("what is RRF")
    planner = _RecordingPlanner(outcome)
    component = EngineeringEvidencePlanner(planner)

    actual = component.plan("what is RRF")

    assert actual is outcome
    assert actual.plan is outcome.plan
    assert actual.plan.to_dict() == outcome.plan.to_dict()
    assert planner.calls == ["what is RRF"]


def test_engineering_planner_rejects_wrong_type_or_query_identity():
    class WrongPlanner(BaseQueryPlanner):
        def plan(self, _query):
            return object()

    with pytest.raises(TypeError, match="PlannerOutcome"):
        EngineeringEvidencePlanner(WrongPlanner()).plan("question")

    with pytest.raises(ValueError, match="original_query"):
        EngineeringEvidencePlanner(_RecordingPlanner(_single_outcome("other"))).plan(
            "question"
        )


def test_resolved_input_drives_planner_router_and_tool_agent(monkeypatch):
    resolved = "RRF 在当前项目中如何实现？"
    planner = _RecordingPlanner(_single_outcome(resolved))
    context = EngineeringContextResolver(
        _ContextResolver(resolved)
    )
    runtime, provider = _runtime(planner, context_resolver=context)
    route_calls = []

    def route_once(question):
        route_calls.append(question)
        return route_engineering_evidence_requirement(question)

    monkeypatch.setattr(
        unified_runtime_module,
        "route_engineering_evidence_requirement",
        route_once,
    )

    result = runtime.run(
        "那它怎么实现？",
        conversation_context=[
            {"role": "user", "content": "我们刚才说 RRF"},
        ],
    )

    assert result.status == "completed"
    assert planner.calls == [resolved]
    assert route_calls == [resolved]
    assert provider.queries == [resolved]
    assert len(context._query_resolver.calls) == 1


def test_no_history_forms_make_zero_context_calls_and_one_plan_each():
    context_backend = _ContextResolver("unused")
    context = EngineeringContextResolver(context_backend)
    question = "What is BM25?"
    planner = _RecordingPlanner(_single_outcome(question))
    runtime, provider = _runtime(planner, context_resolver=context)

    for history in (None, (), []):
        assert runtime.run(question, conversation_context=history).status == "completed"

    assert context_backend.calls == []
    assert planner.calls == [question, question, question]
    assert provider.queries == [question, question, question]


def test_single_plan_is_trusted_but_does_not_direct_tool_selection():
    question = "single retrieval question"
    planner = _RecordingPlanner(_single_outcome(question))
    runtime, provider = _runtime(planner)

    result = runtime.run(question)

    assert result.status == "completed"
    assert result.iterations_used == 1
    assert result.tool_calls_used == 0
    assert result.tool_errors_used == 0
    assert planner.calls == [question]
    assert provider.queries == [question]


def test_decomposed_plan_is_preserved_but_subqueries_do_not_execute_yet():
    question = "compare BM25 and Dense"
    outcome = _decomposed_outcome(question)
    planner = _RecordingPlanner(outcome)
    runtime, provider = _runtime(planner)

    result = runtime.run(question)

    assert planner.calls == [question]
    assert outcome.plan.action == "decomposed_retrieval"
    assert len(outcome.plan.subqueries) == 2
    assert result.status == "completed"
    assert result.iterations_used == 1
    assert result.tool_calls_used == 0
    assert provider.queries == [question]


class _PlannerCompletions:
    def __init__(self, *, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


@pytest.mark.parametrize(
    ("content", "error", "failure_code"),
    [
        ("not-json", None, "PLAN_INVALID_SCHEMA"),
        (None, PlannerTimeoutError(), "PLANNER_TIMEOUT"),
    ],
)
def test_planner_fallback_is_deterministic_and_tool_agent_continues(
    content, error, failure_code
):
    completions = _PlannerCompletions(content=content, error=error)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    g3_planner = OpenAICompatibleQueryPlanner(
        provider="deepseek",
        model="deepseek-chat",
        api_key="test-key",
        client=client,
    )

    class CapturingPlanner(BaseQueryPlanner):
        def __init__(self):
            self.outcome = None

        def plan(self, query):
            self.outcome = g3_planner.plan(query)
            return self.outcome

    capturing = CapturingPlanner()
    runtime, provider = _runtime(capturing)
    result = runtime.run("fallback question")

    assert completions.calls and len(completions.calls) == 1
    assert capturing.outcome.fallback_used is True
    assert capturing.outcome.failure_code == failure_code
    assert capturing.outcome.plan.action == "single_retrieval"
    assert capturing.outcome.plan.reason_code == "PLANNER_FALLBACK"
    assert result.status == "completed"
    assert result.failure_code is None
    assert result.tool_errors_used == 0
    assert provider.queries == ["fallback question"]


def test_planner_programming_error_propagates_before_router_or_tool():
    planner = _RaisingPlanner(RuntimeError("planner programming bug"))
    runtime, provider = _runtime(planner)
    route_calls = []
    original_route = unified_runtime_module.route_engineering_evidence_requirement

    def recording_route(question):
        route_calls.append(question)
        return original_route(question)

    unified_runtime_module.route_engineering_evidence_requirement = recording_route
    try:
        with pytest.raises(RuntimeError, match="planner programming bug"):
            runtime.run("question")
    finally:
        unified_runtime_module.route_engineering_evidence_requirement = original_route

    assert planner.calls == ["question"]
    assert route_calls == []
    assert provider.queries == []


def test_different_plans_produce_identical_execution_result_in_this_stage():
    question = "same execution question"
    single_runtime, single_provider = _runtime(
        _RecordingPlanner(_single_outcome(question))
    )
    decomposed_runtime, decomposed_provider = _runtime(
        _RecordingPlanner(_decomposed_outcome(question))
    )

    single_result = single_runtime.run(question)
    decomposed_result = decomposed_runtime.run(question)

    assert single_result.to_dict() == decomposed_result.to_dict()
    assert single_provider.queries == [question]
    assert decomposed_provider.queries == [question]


def test_plan_and_context_content_do_not_enter_trace_or_activity():
    secret = "planner-and-context-secret"
    planner = _RecordingPlanner(
        _decomposed_outcome("resolved question", marker=secret)
    )
    context = EngineeringContextResolver(
        _ContextResolver("resolved question")
    )
    runtime, _ = _runtime(planner, context_resolver=context)
    trace = []
    activity: list[ActivityEvent] = []

    result = runtime.run(
        "question",
        conversation_context=[
            ContextMessage(role="user", content=secret),
        ],
        trace_sink=trace.append,
        activity_sink=activity.append,
    )
    payload = json.dumps(
        result.to_dict()
        | {
            "safe_trace": [event.to_dict() for event in trace],
            "activity": [event.to_dict() for event in activity],
        },
        ensure_ascii=False,
    )

    assert result.status == "completed"
    assert secret not in payload
