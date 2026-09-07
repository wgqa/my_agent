"""Synthetic, provider-free ARCH-PROD-16A tests.

Covers: the trusted DecisionControlState.recovery_tool_names lifecycle and
derivation (per missing evidence kind, OR-group union, distinct path floor,
registry intersection without resurrection), the bounded recovery action
repair on the OpenAI-compatible Decision Provider (trigger conditions,
success/failure metadata, mutual exclusion with the existing parse repair,
no argument rewriting, profile opt-in), an end-to-end blocked loop where one
repair converts a premature refuse into a real ToolCall, and a static
assertion that no evaluator metadata leaked into the Production files.
No Dev/Holdout case is read; no real Provider is called.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.engineering_requirements import (
    DIAGNOSIS_CROSS_FILE_V1,
    CHANGE_TEST_V1,
    EngineeringEvidenceRequirement,
    EvidenceRequirementState,
    PROJECT_CODE_V1,
    THEORY_CODE_V1,
    evaluate_evidence_requirement,
)
from core.tool_agent.actions import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256,
    ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_TEMPLATE,
    ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION,
    ENGINEERING_RECOVERY_REPAIR_ENABLED_PROFILE_VERSIONS,
    LEGACY_DECISION_PROMPT_PROFILE,
    build_recovery_action_repair_instruction,
    max_parse_repairs_for_profile,
)
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime, _available_recovery_tool_names
from core.tool_agent.runtime_models import (
    DecisionControlState,
    EngineeringEvidence,
    ToolAgentBudget,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC, CodeSearchHandler
from core.tool_agent.tools.git_change import (
    CHANGED_FILES_SPEC,
    GIT_DIFF_SPEC,
)
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
    ReadProjectContextHandler,
)
from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC


# ---------------------------------------------------------------------------
# synthetic helpers
# ---------------------------------------------------------------------------


class _NoExecHandler:
    """Derivation-only handler: 16A mapping tests must never execute Tools."""

    def execute(self, arguments):
        raise AssertionError("this synthetic test must not execute Tools")


def _derivation_registry(*names: str) -> ToolRegistry:
    specs = {
        "knowledge_search": KNOWLEDGE_SEARCH_SPEC,
        "changed_files": CHANGED_FILES_SPEC,
        "git_diff": GIT_DIFF_SPEC,
        "find_tests": FIND_TESTS_SPEC,
        "code_search": CODE_SEARCH_SPEC,
        "read_project_context": READ_PROJECT_CONTEXT_SPEC,
        "calculator": CALCULATOR_SPEC,
    }
    registry = ToolRegistry()
    for name in names:
        registry.register(specs[name], _NoExecHandler())
    return registry


def _requirement(
    profile, groups, min_paths
) -> EngineeringEvidenceRequirement:
    return EngineeringEvidenceRequirement(
        requirement_profile=profile,
        required_evidence_groups=groups,
        min_distinct_project_code_paths=min_paths,
    )


def _state_from_requirement(
    requirement: EngineeringEvidenceRequirement, evidence=()
) -> EvidenceRequirementState:
    return evaluate_evidence_requirement(requirement, evidence)


def _direct_state(
    *groups: str, distinct_paths: int = 0, required_paths: int = 0
) -> EvidenceRequirementState:
    return EvidenceRequirementState(
        satisfied=False,
        missing_evidence_groups=tuple((group,) for group in groups),
        evidence_kind_counts={},
        distinct_project_code_paths=distinct_paths,
        required_min_distinct_project_code_paths=required_paths,
    )


def _blocked_control_state(
    *,
    groups=(("project_code",),),
    names=("code_search", "read_project_context"),
    **overrides,
) -> DecisionControlState:
    kwargs = dict(
        iteration=2,
        remaining_iterations=3,
        remaining_tool_calls=3,
        tool_call_allowed=True,
        must_terminate=False,
        finalization_blocked=True,
        missing_evidence_groups=groups,
        current_distinct_project_code_paths=0,
        required_min_distinct_project_code_paths=1,
        recovery_tool_names=names,
    )
    kwargs.update(overrides)
    return DecisionControlState(**kwargs)


class _StateCapturingProvider:
    """Loop-level Fake Decision Provider that records every control state."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.calls += 1
        self.states.append(control_state)
        item = self._decisions[min(self.calls - 1, len(self._decisions) - 1)]
        if isinstance(item, str):
            return AgentDecisionOutcome(
                action=None, failure_code=item, call_metadata=None
            )
        return AgentDecisionOutcome(action=item, failure_code=None, call_metadata=None)


class _ScriptedChatClient:
    """OpenAI-compatible Fake Client returning scripted JSON contents."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0
        self.requests = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        content = self._contents[min(self.calls - 1, len(self._contents) - 1)]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def _chat_provider(client, profile=None) -> OpenAICompatibleAgentDecisionProvider:
    return OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="sk-test",
        client=client,
        prompt_profile=(
            profile
            if profile is not None
            else ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE
        ),
    )


def _decision_registry() -> ToolRegistry:
    """Parse-level registry: only ToolSpecs matter, handlers never execute."""
    return _derivation_registry(
        "knowledge_search",
        "changed_files",
        "git_diff",
        "find_tests",
        "code_search",
        "read_project_context",
        "calculator",
    )


REFUSE_JSON = '{"action": "refuse", "reason_code": "INSUFFICIENT_INFORMATION"}'
FINAL_JSON = '{"action": "final_answer", "answer": "premature terminal answer"}'
CODE_SEARCH_REPAIR_JSON = (
    '{"action": "tool_call", "tool_name": "code_search", '
    '"arguments": {"query": "EngineeringVerificationResult", '
    '"artifact_kind": "project_code"}}'
)


# ---------------------------------------------------------------------------
# DecisionControlState recovery_tool_names contract
# ---------------------------------------------------------------------------


class TestRecoveryToolNamesControlState:
    def test_default_is_empty_and_allowed_without_blocking(self):
        state = DecisionControlState(1, 4, 4, True, False)
        assert state.recovery_tool_names == ()
        assert "recovery_tool_names" not in state.to_dict()

    def test_blocked_state_round_trips_names_in_to_dict(self):
        state = _blocked_control_state()
        payload = state.to_dict()
        assert payload["recovery_tool_names"] == [
            "code_search",
            "read_project_context",
        ]
        assert state.recovery_tool_names == ("code_search", "read_project_context")

    def test_names_forbidden_when_not_blocked(self):
        with pytest.raises(ValueError):
            DecisionControlState(
                1, 4, 4, True, False, recovery_tool_names=("code_search",)
            )
        with pytest.raises(ValueError):
            DecisionControlState(
                1,
                4,
                4,
                True,
                False,
                finalization_blocked=False,
                recovery_tool_names=("code_search",),
            )

    def test_names_must_be_unique_nonempty_strings(self):
        base = dict(
            finalization_blocked=True,
            missing_evidence_groups=(("project_code",),),
        )
        with pytest.raises(ValueError):
            DecisionControlState(
                2, 3, 3, True, False,
                recovery_tool_names=("code_search", "code_search"), **base,
            )
        with pytest.raises(ValueError):
            DecisionControlState(
                2, 3, 3, True, False, recovery_tool_names=("code_search", " "), **base
            )
        with pytest.raises(ValueError):
            DecisionControlState(
                2, 3, 3, True, False, recovery_tool_names=("code_search", 5), **base
            )
        with pytest.raises(TypeError):
            DecisionControlState(
                2, 3, 3, True, False, recovery_tool_names="code_search", **base
            )


# ---------------------------------------------------------------------------
# canonical recovery mapping derivation (task cases A-G + OR union)
# ---------------------------------------------------------------------------


class TestRecoveryToolNameDerivation:
    def test_project_code_maps_to_code_search_and_read(self):
        registry = _derivation_registry("code_search", "read_project_context", "calculator")
        requirement = _requirement(PROJECT_CODE_V1, (("project_code",),), 1)
        names = _available_recovery_tool_names(
            registry, requirement, _state_from_requirement(requirement)
        )
        assert names == ("code_search", "read_project_context")

    def test_project_doc_maps_to_code_search_and_read(self):
        registry = _derivation_registry("code_search", "read_project_context")
        names = _available_recovery_tool_names(
            registry, None, _direct_state("project_doc", required_paths=0)
        )
        assert names == ("code_search", "read_project_context")

    def test_project_test_maps_to_find_tests_not_code_search(self):
        registry = _derivation_registry(
            "code_search", "read_project_context", "find_tests"
        )
        names = _available_recovery_tool_names(
            registry, None, _direct_state("project_test")
        )
        assert names == ("find_tests", "read_project_context")
        assert "code_search" not in names

    def test_project_change_maps_to_changed_files_and_git_diff(self):
        registry = _derivation_registry("changed_files", "git_diff")
        names = _available_recovery_tool_names(
            registry, None, _direct_state("project_change")
        )
        assert names == ("changed_files", "git_diff")

    def test_distinct_path_floor_keeps_project_code_recovery(self):
        registry = _derivation_registry("code_search", "read_project_context")
        requirement = _requirement(DIAGNOSIS_CROSS_FILE_V1, (("project_code",),), 2)
        evidence = (
            EngineeringEvidence(
                evidence_id="E1",
                kind="project_code",
                path="src/only.py",
                start_line=1,
                end_line=2,
                snippet="x = 1",
            ),
        )
        state = _state_from_requirement(requirement, evidence)
        assert state.missing_evidence_groups == ()
        assert state.distinct_project_code_paths == 1
        names = _available_recovery_tool_names(registry, requirement, state)
        assert names == ("code_search", "read_project_context")

    def test_missing_kind_tool_must_exist_in_run_registry(self):
        registry = _derivation_registry("code_search", "calculator")
        names = _available_recovery_tool_names(
            registry, None, _direct_state("project_code")
        )
        assert names == ("code_search",)

    def test_disabled_knowledge_search_is_not_resurrected(self):
        registry = _derivation_registry("code_search", "read_project_context")
        names = _available_recovery_tool_names(
            registry, None, _direct_state("knowledge")
        )
        assert names == ()

    def test_or_group_union_and_deterministic_order(self):
        registry = _derivation_registry(
            "knowledge_search",
            "code_search",
            "read_project_context",
        )
        requirement = _requirement(
            THEORY_CODE_V1,
            (("knowledge",), ("project_code", "project_doc")),
            1,
        )
        names = _available_recovery_tool_names(
            registry, requirement, _state_from_requirement(requirement)
        )
        assert names == (
            "knowledge_search",
            "code_search",
            "read_project_context",
        )

    def test_change_test_requirement_unions_change_and_test_tools(self):
        registry = _derivation_registry(
            "changed_files", "git_diff", "find_tests", "read_project_context"
        )
        requirement = _requirement(
            CHANGE_TEST_V1, (("project_change",), ("project_test",)), 0
        )
        names = _available_recovery_tool_names(
            registry, requirement, _state_from_requirement(requirement)
        )
        assert names == (
            "changed_files",
            "git_diff",
            "find_tests",
            "read_project_context",
        )


# ---------------------------------------------------------------------------
# runtime loop exposes trusted recovery_tool_names on blocked control states
# ---------------------------------------------------------------------------


class TestRuntimeExposesRecoveryToolNames:
    def _write_repo(self, tmp_path: Path) -> None:
        (tmp_path / "sample.py").write_text("NEEDLE_TOKEN = 1\n", encoding="utf-8")

    def _loop_registry(self, tmp_path: Path) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(CALCULATOR_SPEC, _NoExecHandler())
        registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(repo_root=tmp_path))
        registry.register(
            READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(repo_root=tmp_path)
        )
        return registry

    def test_blocked_loop_control_state_carries_recovery_tool_names(self, tmp_path):
        self._write_repo(tmp_path)
        registry = self._loop_registry(tmp_path)
        requirement = _requirement(PROJECT_CODE_V1, (("project_code",),), 1)
        provider = _StateCapturingProvider(
            [
                RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION"),
                ToolCallAction(
                    action="tool_call",
                    tool_name="read_project_context",
                    arguments={"path": "sample.py", "line": 1, "context_lines": 0},
                ),
                FinalAnswerAction(action="final_answer", answer="grounded answer"),
            ]
        )
        result = ToolAgentRuntime(registry=registry, provider=provider).run(
            "synthetic project code question",
            evidence_requirement=requirement,
            enforce_evidence_acquisition=True,
        )
        assert result.status == "completed"
        first = provider.states[0].to_dict()
        assert first["finalization_blocked"] is True
        assert first["recovery_tool_names"] == [
            "code_search",
            "read_project_context",
        ]
        final_state = provider.states[-1].to_dict()
        assert "recovery_tool_names" not in final_state
        assert "finalization_blocked" not in final_state

    def test_disabled_tool_is_excluded_from_loop_recovery_names(self, tmp_path):
        self._write_repo(tmp_path)
        registry = self._loop_registry(tmp_path)
        requirement = _requirement(PROJECT_CODE_V1, (("project_code",),), 1)
        provider = _StateCapturingProvider(
            [
                RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION"),
                ToolCallAction(
                    action="tool_call",
                    tool_name="read_project_context",
                    arguments={"path": "sample.py", "line": 1, "context_lines": 0},
                ),
                FinalAnswerAction(action="final_answer", answer="grounded answer"),
            ]
        )
        result = ToolAgentRuntime(registry=registry, provider=provider).run(
            "synthetic project code question",
            evidence_requirement=requirement,
            disabled_tools=frozenset({"code_search"}),
            enforce_evidence_acquisition=True,
        )
        assert result.status == "completed"
        first = provider.states[0].to_dict()
        assert first["recovery_tool_names"] == ["read_project_context"]


# ---------------------------------------------------------------------------
# bounded recovery action repair on the OpenAI-compatible provider
# ---------------------------------------------------------------------------


class TestRecoveryActionRepair:
    def test_premature_refuse_is_repaired_into_model_tool_call(self):
        client = _ScriptedChatClient([REFUSE_JSON, CODE_SEARCH_REPAIR_JSON])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, ToolCallAction)
        assert outcome.action.tool_name == "code_search"
        assert dict(outcome.action.arguments) == {
            "query": "EngineeringVerificationResult",
            "artifact_kind": "project_code",
        }
        assert outcome.failure_code is None
        metadata = outcome.call_metadata
        assert metadata.call_count == 2
        assert metadata.repair_attempted is True
        assert metadata.repair_succeeded is True
        assert metadata.initial_parse_category is None
        assert client.calls == 2

    def test_repair_instruction_names_tools_and_kinds_without_model_output(self):
        client = _ScriptedChatClient([REFUSE_JSON, CODE_SEARCH_REPAIR_JSON])
        _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        instruction = client.requests[1]["messages"][-1]["content"]
        assert "tool_call" in instruction
        assert "code_search" in instruction
        assert "read_project_context" in instruction
        assert "project_code" in instruction
        assert REFUSE_JSON not in instruction
        assert '"artifact_kind"' not in instruction

    def test_premature_final_answer_is_repaired_too(self):
        second = (
            '{"action": "tool_call", "tool_name": "read_project_context", '
            '"arguments": {"path": "src/a.py", "line": 2, "context_lines": 1}}'
        )
        client = _ScriptedChatClient([FINAL_JSON, second])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, ToolCallAction)
        assert outcome.action.tool_name == "read_project_context"
        assert outcome.call_metadata.repair_succeeded is True
        assert outcome.call_metadata.call_count == 2

    def test_valid_tool_call_never_triggers_recovery_repair(self):
        first = (
            '{"action": "tool_call", "tool_name": "code_search", '
            '"arguments": {"query": "Adapter"}}'
        )
        client = _ScriptedChatClient([first])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, ToolCallAction)
        assert client.calls == 1
        assert outcome.call_metadata.call_count == 1
        assert outcome.call_metadata.repair_attempted is False

    def test_unblocked_state_never_repairs_terminal(self):
        client = _ScriptedChatClient([REFUSE_JSON])
        outcome = _chat_provider(client).decide(
            _decision_registry(),
            "synthetic question",
            control_state=DecisionControlState(2, 3, 3, True, False),
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 1
        assert outcome.call_metadata.call_count == 1

    def test_must_terminate_and_budget_denial_block_repair(self):
        terminating = _blocked_control_state(
            tool_call_allowed=False, must_terminate=True
        )
        client = _ScriptedChatClient([REFUSE_JSON])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=terminating
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 1
        assert outcome.call_metadata.call_count == 1

    def test_empty_recovery_tool_names_never_calls_second_model(self):
        client = _ScriptedChatClient([REFUSE_JSON])
        outcome = _chat_provider(client).decide(
            _decision_registry(),
            "synthetic question",
            control_state=_blocked_control_state(names=()),
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 1
        assert outcome.call_metadata.call_count == 1

    def test_repair_that_stays_terminal_falls_back_without_third_call(self):
        client = _ScriptedChatClient([REFUSE_JSON, REFUSE_JSON])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, RefuseAction)
        assert outcome.action.reason_code == "INSUFFICIENT_INFORMATION"
        assert client.calls == 2
        metadata = outcome.call_metadata
        assert metadata.call_count == 2
        assert metadata.repair_attempted is True
        assert metadata.repair_succeeded is False
        assert metadata.initial_parse_category is None

    def test_repair_with_invalid_json_falls_back_without_third_call(self):
        client = _ScriptedChatClient([REFUSE_JSON, '{"action": "refuse"'])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 2
        assert outcome.call_metadata.repair_succeeded is False
        assert outcome.call_metadata.repair_attempted is True

    def test_repair_tool_outside_recovery_names_is_rejected(self):
        second = (
            '{"action": "tool_call", "tool_name": "calculator", '
            '"arguments": {"expression": "1 + 1"}}'
        )
        client = _ScriptedChatClient([REFUSE_JSON, second])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 2
        assert outcome.call_metadata.repair_succeeded is False

    def test_repair_model_arguments_are_never_rewritten(self):
        second = (
            '{"action": "tool_call", "tool_name": "code_search", '
            '"arguments": {"query": "synthetic literal"}}'
        )
        client = _ScriptedChatClient([REFUSE_JSON, second])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, ToolCallAction)
        assert outcome.call_metadata.repair_succeeded is True
        assert dict(outcome.action.arguments) == {"query": "synthetic literal"}

    def test_parse_repair_and_recovery_repair_never_stack(self):
        client = _ScriptedChatClient(["{", FINAL_JSON])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, FinalAnswerAction)
        assert client.calls == 2
        metadata = outcome.call_metadata
        assert metadata.call_count == 2
        assert metadata.repair_attempted is True
        assert metadata.repair_succeeded is True
        assert metadata.initial_parse_category == "INVALID_JSON"

    def test_parse_repair_failure_stops_without_recovery_repair(self):
        client = _ScriptedChatClient(["{", "still not json"])
        outcome = _chat_provider(client).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert outcome.action is None
        assert outcome.failure_code == "ACTION_PARSE_FAILED"
        assert client.calls == 2
        assert outcome.call_metadata.repair_succeeded is False

    def test_legacy_profile_is_not_recovery_repair_enabled(self):
        client = _ScriptedChatClient([REFUSE_JSON])
        outcome = _chat_provider(client, profile=LEGACY_DECISION_PROMPT_PROFILE).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 1
        assert outcome.call_metadata.call_count == 1

    def test_unified_profile_is_not_recovery_repair_enabled(self):
        client = _ScriptedChatClient([REFUSE_JSON])
        outcome = _chat_provider(
            client, profile=ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
        ).decide(
            _decision_registry(), "synthetic question", control_state=_blocked_control_state()
        )
        assert isinstance(outcome.action, RefuseAction)
        assert client.calls == 1

    def test_kind_aware_profile_renders_recovery_names_to_the_model(self):
        messages = ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.build_messages(
            [CODE_SEARCH_SPEC, READ_PROJECT_CONTEXT_SPEC],
            "synthetic question",
            control_state=_blocked_control_state(),
        )
        system = messages[0]["content"]
        assert '"recovery_tool_names": ["code_search", "read_project_context"]' in system


# ---------------------------------------------------------------------------
# end-to-end: one repair converts a premature refuse into a real ToolCall
# ---------------------------------------------------------------------------


class TestEndToEndBlockedLoopRepair:
    def test_blocked_loop_repairs_refuse_into_code_search_then_completes(
        self, tmp_path
    ):
        (tmp_path / "sample.py").write_text("NEEDLE_TOKEN = 1\n", encoding="utf-8")
        registry = ToolRegistry()
        registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(repo_root=tmp_path))
        registry.register(
            READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(repo_root=tmp_path)
        )
        requirement = _requirement(PROJECT_CODE_V1, (("project_code",),), 1)
        client = _ScriptedChatClient(
            [
                REFUSE_JSON,
                CODE_SEARCH_REPAIR_JSON,
                (
                    '{"action": "tool_call", "tool_name": "read_project_context", '
                    '"arguments": {"path": "sample.py", "line": 1, "context_lines": 0}}'
                ),
                '{"action": "final_answer", "answer": "grounded synthetic answer"}',
            ]
        )
        runtime = ToolAgentRuntime(
            registry=registry,
            provider=_chat_provider(client),
            budget=ToolAgentBudget(),
        )
        result = runtime.run(
            "synthetic project code question",
            evidence_requirement=requirement,
            enforce_evidence_acquisition=True,
        )
        assert result.status == "completed"
        assert result.answer == "grounded synthetic answer"
        assert result.tool_calls_used == 2
        assert [item.kind for item in result.evidence] == ["project_code"]
        assert client.calls == 4
        decisions = [
            event for event in result.trace if event.event_type == "decision_completed"
        ]
        assert [event.provider_call_count for event in decisions] == [2, 1, 1]
        assert decisions[0].repair_attempted is True
        assert decisions[0].repair_succeeded is True
        assert not any(
            event.error_code == "INSUFFICIENT_EVIDENCE_TO_FINALIZE"
            for event in result.trace
        )


# ---------------------------------------------------------------------------
# repair prompt identity and builder boundaries
# ---------------------------------------------------------------------------


class TestRecoveryRepairPrompt:
    def test_prompt_identity_is_frozen_v1(self):
        assert ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION == (
            "engineering_recovery_action_repair_prompt_v1"
        )
        assert ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256 == hashlib.sha256(
            ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_TEMPLATE.encode("utf-8")
        ).hexdigest()

    def test_main_kind_aware_prompt_template_identity_is_untouched(self):
        assert (
            ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version
            == "engineering_agent_decision_prompt_unified_kind_aware_v1"
        )
        assert max_parse_repairs_for_profile(
            ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE
        ) == 1
        assert ENGINEERING_RECOVERY_REPAIR_ENABLED_PROFILE_VERSIONS == frozenset(
            {"engineering_agent_decision_prompt_unified_kind_aware_v1"}
        )

    def test_instruction_contains_boundary_without_generated_arguments(self):
        instruction = build_recovery_action_repair_instruction(
            tool_names=("code_search", "read_project_context"),
            missing_kinds=("project_code",),
        )
        assert "本次必须输出 tool_call" in instruction
        assert "code_search, read_project_context" in instruction
        assert "project_code" in instruction
        assert "不要输出 final_answer" in instruction
        assert "不要输出 refuse" in instruction
        assert '"query"' not in instruction
        assert '"artifact_kind"' not in instruction

    def test_instruction_rejects_invalid_inputs(self):
        with pytest.raises(ValueError):
            build_recovery_action_repair_instruction(
                tool_names=(), missing_kinds=("project_code",)
            )
        with pytest.raises(ValueError):
            build_recovery_action_repair_instruction(
                tool_names=("code_search", "code_search"),
                missing_kinds=("project_code",),
            )
        with pytest.raises(ValueError):
            build_recovery_action_repair_instruction(
                tool_names=("code_search",), missing_kinds=()
            )
        with pytest.raises(ValueError):
            build_recovery_action_repair_instruction(
                tool_names=("code_search",), missing_kinds=("not_a_kind",)
            )
        with pytest.raises(ValueError):
            build_recovery_action_repair_instruction(
                tool_names=("code_search",), missing_kinds=("project_code", "project_code")
            )


# ---------------------------------------------------------------------------
# anti-dev-hack: Production files carry no evaluator metadata
# ---------------------------------------------------------------------------


class TestNoEvaluatorMetadataInProduction:
    def test_modified_production_files_stay_free_of_evaluator_contract(self):
        forbidden = (
            "v7d",
            "integration_dev",
            "gold_obligation",
            "expected_outcome",
            "accepted_test_paths",
            "base_ref",
            "head_ref",
        )
        repo_root = Path(__file__).resolve().parents[1]
        for relative in (
            "core/tool_agent/runtime_models.py",
            "core/tool_agent/runtime.py",
            "core/tool_agent/decision_prompt.py",
            "core/tool_agent/openai_compatible.py",
        ):
            source = (repo_root / relative).read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in source, (relative, token)
