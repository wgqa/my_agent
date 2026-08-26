from __future__ import annotations

from pathlib import Path

import pytest

import api.app
import core.engineering_agent as engineering_agent_module
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_requirements import (
    CHANGE_TEST_V1,
    DIAGNOSIS_CROSS_FILE_V1,
    THEORY_CODE_V1,
    EngineeringEvidenceRequirement,
    evaluate_evidence_requirement,
)
from core.tool_agent.actions import (
    ActionValidationError,
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from core.tool_agent.models import ToolSpec
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    DecisionControlState,
    RuntimeTraceEvent,
    ToolAgentRunResult,
    INSUFFICIENT_EVIDENCE_TO_FINALIZE,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.tools.git_change import GIT_DIFF_SPEC
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC


class StaticHandler:
    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return self.result_factory(arguments)


def _read_result(arguments):
    return {
        "path": arguments["path"],
        "start_line": 1,
        "end_line": 1,
        "lines": [{"line": 1, "text": "synthetic public source evidence"}],
    }


def _diff_result(arguments):
    return {
        "path": arguments["path"],
        "mode": arguments["mode"],
        "truncated": False,
        "diff": "@@ synthetic change\n-old\n+new",
        "start_line": 1,
        "end_line": 1,
    }


def _knowledge_result(_arguments):
    return {
        "matches": [
            {
                "rank": 1,
                "source_name": "knowledge/synthetic.md",
                "chunk_id": "synthetic-1",
                "score": 1.0,
                "snippet": "synthetic public knowledge evidence",
            }
        ]
    }


class ScriptedProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
        self.states: list[DecisionControlState | None] = []
        self.contexts = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.calls += 1
        self.states.append(control_state)
        self.contexts.append(tuple(context))
        action = self.actions[min(self.calls - 1, len(self.actions) - 1)]
        if isinstance(action, AgentDecisionOutcome):
            return action
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=None,
        )


def _registry(*, read=True, diff=True, knowledge=True, calculator=True):
    registry = ToolRegistry()
    handlers = {}
    if read:
        handlers["read_project_context"] = StaticHandler(_read_result)
        registry.register(READ_PROJECT_CONTEXT_SPEC, handlers["read_project_context"])
    if diff:
        handlers["git_diff"] = StaticHandler(_diff_result)
        registry.register(GIT_DIFF_SPEC, handlers["git_diff"])
    if knowledge:
        handlers["knowledge_search"] = StaticHandler(_knowledge_result)
        registry.register(KNOWLEDGE_SEARCH_SPEC, handlers["knowledge_search"])
    if calculator:
        handlers["calculator"] = CalculatorHandler()
        registry.register(CALCULATOR_SPEC, handlers["calculator"])
    return registry, handlers


def _requirement(profile, groups, paths):
    return EngineeringEvidenceRequirement(
        requirement_profile=profile,
        required_evidence_groups=groups,
        min_distinct_project_code_paths=paths,
    )


def _read_action(path="tests/test_synthetic.py"):
    return ToolCallAction(
        action="tool_call",
        tool_name="read_project_context",
        arguments={"path": path, "line": 1, "context_lines": 0},
    )


def _diff_action():
    return ToolCallAction(
        action="tool_call",
        tool_name="git_diff",
        arguments={"mode": "working_tree", "path": "src/synthetic.py"},
    )


def _knowledge_action():
    return ToolCallAction(
        action="tool_call",
        tool_name="knowledge_search",
        arguments={"query": "synthetic mechanism"},
    )


def _final(text="synthetic answer"):
    return FinalAnswerAction(action="final_answer", answer=text)


class TestGuardRuntime:
    def test_none_requirement_preserves_legacy_direct_final_and_control_shape(self):
        registry, _ = _registry()
        provider = ScriptedProvider([_final()])
        result = ToolAgentRuntime(registry=registry, provider=provider).run(
            "ordinary synthetic question"
        )
        assert result.status == "completed"
        assert provider.states[0].to_dict() == {
            "iteration": 1,
            "remaining_iterations": 4,
            "remaining_tool_calls": 4,
            "tool_call_allowed": True,
            "must_terminate": False,
        }
        assert not any(
            event.event_type == "finalization_guard_blocked" for event in result.trace
        )

    def test_sufficient_shape_allows_semantically_unchecked_completion(self):
        registry, _ = _registry()
        requirement = _requirement(
            THEORY_CODE_V1,
            (("knowledge",), ("project_code", "project_doc")),
            1,
        )
        provider = ScriptedProvider([
            _knowledge_action(),
            _read_action("README.md"),
            _final("not a semantic verdict"),
        ])
        result = ToolAgentRuntime(
            registry=registry,
            provider=provider,
        ).run("synthetic theory and implementation question", evidence_requirement=requirement)
        assert result.status == "completed"
        assert result.answer == "not a semantic verdict"
        assert result.iterations_used == 3
        assert result.tool_calls_used == 2
        assert not any(
            event.event_type == "finalization_guard_blocked" for event in result.trace
        )
        assert evaluate_evidence_requirement(requirement, result.evidence).satisfied

    def test_insufficient_shape_blocks_then_recovers_with_test_evidence(self):
        registry, handlers = _registry()
        requirement = _requirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        provider = ScriptedProvider([
            _diff_action(),
            _final("first answer"),
            _read_action(),
            _final("grounded answer"),
        ])
        result = ToolAgentRuntime(
            registry=registry,
            provider=provider,
        ).run("synthetic change and test question", evidence_requirement=requirement)
        assert result.status == "completed"
        assert result.answer == "grounded answer"
        assert result.iterations_used == 4
        assert result.tool_calls_used == 2
        assert handlers["read_project_context"].calls == 1
        blocks = [
            event for event in result.trace
            if event.event_type == "finalization_guard_blocked"
        ]
        assert len(blocks) == 1
        assert blocks[0].missing_evidence_groups == (("project_test",),)
        assert blocks[0].distinct_project_code_paths == 0
        assert provider.states[0].to_dict() == {
            "iteration": 1,
            "remaining_iterations": 4,
            "remaining_tool_calls": 4,
            "tool_call_allowed": True,
            "must_terminate": False,
        }
        blocked_state = provider.states[2].to_dict()
        assert blocked_state["finalization_blocked"] is True
        assert blocked_state["missing_evidence_groups"] == [["project_test"]]
        assert blocked_state["current_distinct_project_code_paths"] == 0
        assert blocked_state["required_min_distinct_project_code_paths"] == 0
        assert "requirement_profile" not in blocked_state
        assert "answer" not in blocked_state
        assert "path" not in blocked_state
        assert provider.states[3].to_dict() == {
            "iteration": 4,
            "remaining_iterations": 1,
            "remaining_tool_calls": 2,
            "tool_call_allowed": True,
            "must_terminate": False,
        }

    def test_guard_never_auto_executes_tool_and_no_progress_refuses(self):
        registry, handlers = _registry()
        requirement = _requirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        provider = ScriptedProvider([_final("answer A"), _final("answer B")])
        result = ToolAgentRuntime(
            registry=registry,
            provider=provider,
        ).run("synthetic change and test question", evidence_requirement=requirement)
        assert result.status == "refused"
        assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
        assert result.answer is None
        assert handlers["read_project_context"].calls == 0
        assert len(
            [e for e in result.trace if e.event_type == "finalization_guard_blocked"]
        ) == 1
        assert result.trace[-1].error_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE

    def test_iteration_four_cannot_recover_even_with_tool_calls_left(self):
        registry, handlers = _registry()
        requirement = _requirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        provider = ScriptedProvider([
            ToolCallAction(
                action="tool_call", tool_name="calculator", arguments={"expression": "1+1"}
            ),
            ToolCallAction(
                action="tool_call", tool_name="calculator", arguments={"expression": "2+2"}
            ),
            ToolCallAction(
                action="tool_call", tool_name="calculator", arguments={"expression": "3+3"}
            ),
            _final(),
        ])
        result = ToolAgentRuntime(
            registry=registry,
            provider=provider,
        ).run("synthetic change and test question", evidence_requirement=requirement)
        assert result.status == "refused"
        assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
        assert result.iterations_used == 4
        assert result.tool_calls_used == 3
        assert handlers.get("read_project_context").calls == 0
        assert not any(
            event.event_type == "finalization_guard_blocked" for event in result.trace
        )

    def test_progress_but_still_insufficient_allows_second_block(self):
        registry, _ = _registry()
        requirement = _requirement(
            DIAGNOSIS_CROSS_FILE_V1,
            (("project_code",),),
            2,
        )
        provider = ScriptedProvider([_final("first"), _read_action("src/one.py"), _final("second"), _final("third")])
        result = ToolAgentRuntime(
            registry=registry,
            provider=provider,
        ).run("synthetic failure propagation across modules", evidence_requirement=requirement)
        blocks = [
            event for event in result.trace
            if event.event_type == "finalization_guard_blocked"
        ]
        assert len(blocks) == 2
        assert blocks[0].distinct_project_code_paths == 0
        assert blocks[1].distinct_project_code_paths == 1
        assert blocks[1].missing_evidence_groups == ()
        assert result.status == "refused"
        assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE

    def test_missing_producer_tool_refuses_without_block(self):
        registry, _ = _registry(read=False, diff=False, knowledge=False)
        requirement = _requirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        result = ToolAgentRuntime(
            registry=registry,
            provider=ScriptedProvider([_final()]),
        ).run("synthetic change and test question", evidence_requirement=requirement)
        assert result.status == "refused"
        assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
        assert not any(
            event.event_type == "finalization_guard_blocked" for event in result.trace
        )

    def test_system_reason_is_not_a_model_refuse_reason(self):
        with pytest.raises(ActionValidationError):
            RefuseAction("refuse", INSUFFICIENT_EVIDENCE_TO_FINALIZE)


class TestControlAndTraceBoundaries:
    def test_block_event_is_safe_and_legacy_trace_filters_it(self):
        event = RuntimeTraceEvent(
            iteration=2,
            event_type="finalization_guard_blocked",
            guard_status="blocked",
            missing_evidence_groups=(("project_test",),),
            distinct_project_code_paths=0,
            required_min_distinct_project_code_paths=0,
            iterations_used=2,
            tool_calls_used=1,
            tool_errors_used=0,
        )
        payload = event.to_dict()
        safe = api.app._safe_engineering_trace([payload])[0]
        assert safe["event_type"] == "finalization_guard_blocked"
        assert safe["missing_evidence_groups"] == [["project_test"]]
        assert "answer" not in safe
        assert "question" not in safe
        legacy = api.app._safe_legacy_trace([payload])[0]
        assert "guard_status" not in legacy
        assert "missing_evidence_groups" not in legacy

    def test_engineering_v2_control_state_is_conditional(self):
        from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_V2_PROFILE
        from core.tool_agent.tools.calculator import CALCULATOR_SPEC

        normal = DecisionControlState(1, 4, 4, True, False)
        blocked = DecisionControlState(
            2,
            3,
            3,
            True,
            False,
            True,
            (("project_test",),),
            0,
            0,
        )
        normal_system = ENGINEERING_DECISION_PROMPT_V2_PROFILE.build_messages(
            [CALCULATOR_SPEC], "synthetic question", control_state=normal
        )[0]["content"]
        blocked_system = ENGINEERING_DECISION_PROMPT_V2_PROFILE.build_messages(
            [CALCULATOR_SPEC], "synthetic question", control_state=blocked
        )[0]["content"]
        assert "finalization_blocked" not in normal_system
        assert "finalization_blocked" in blocked_system
        assert "requirement_profile" not in blocked_system
        assert "question" not in blocked_system


class TestFacadeBoundary:
    def test_facade_routes_once_and_does_not_accept_override(self, monkeypatch):
        requirement = _requirement(
            CHANGE_TEST_V1,
            (("project_change",), ("project_test",)),
            0,
        )
        calls = []

        def route(question):
            calls.append(question)
            return requirement

        class RecordingRuntime(ToolAgentRuntime):
            def __init__(self):
                self.received = []

            def run(self, question, *, evidence_requirement=None):
                self.received.append((question, evidence_requirement))
                return ToolAgentRunResult(
                    status="completed",
                    answer="synthetic",
                    reason_code=None,
                    failure_code=None,
                    iterations_used=1,
                    tool_calls_used=0,
                    tool_errors_used=0,
                    trace=(),
                )

        runtime = RecordingRuntime()
        monkeypatch.setattr(
            engineering_agent_module,
            "route_engineering_evidence_requirement",
            route,
        )
        result = EngineeringAgentFacade(runtime).run("synthetic question")
        assert result.status == "completed"
        assert calls == ["synthetic question"]
        assert runtime.received == [("synthetic question", requirement)]
