"""Minimal rollback contract for ARCH-PROD-16C.

The 16A recovery-repair mechanism was a VALID experiment that was NOT
PROMOTED; the four Production files were restored byte-for-byte to the
pre-16A baseline.  These tests pin the rollback contract without reimplementing
the deleted 16A suite: the recovery symbols are gone, the frozen main prompt
identity did not regress, the pre-existing bounded parse repair and the hard
budget still work, and no premature terminal action triggers a second model
call.
"""

from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace

import pytest

from core.engineering_requirements import ROUTER_VERSION, route_engineering_evidence_requirement
from core.tool_agent.actions import FinalAnswerAction, RefuseAction
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
    build_action_repair_instruction,
    max_parse_repairs_for_profile,
)
from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import DecisionControlState, ToolAgentBudget
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC


class _ScriptedChatClient:
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
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
        )


def _provider(client) -> OpenAICompatibleAgentDecisionProvider:
    return OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="sk-test",
        client=client,
        prompt_profile=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
    )


def _registry():
    registry = _make_registry()
    return registry


def _make_registry():
    from core.tool_agent.registry import ToolRegistry

    class _NoExecHandler:
        def execute(self, arguments):
            raise AssertionError("rollback contract tests never execute Tools")

    registry = ToolRegistry()
    for spec in (CALCULATOR_SPEC, CODE_SEARCH_SPEC, READ_PROJECT_CONTEXT_SPEC):
        registry.register(spec, _NoExecHandler())
    return registry


def _blocked_control_state() -> DecisionControlState:
    """Pre-16A blocked control state: recovery fields exist, repair names do not."""

    return DecisionControlState(
        iteration=2,
        remaining_iterations=3,
        remaining_tool_calls=3,
        tool_call_allowed=True,
        must_terminate=False,
        finalization_blocked=True,
        missing_evidence_groups=(("project_code",),),
        current_distinct_project_code_paths=0,
        required_min_distinct_project_code_paths=1,
    )


# ---- A. DecisionControlState no longer exposes recovery_tool_names ----


def test_control_state_has_no_recovery_tool_names_field():
    assert "recovery_tool_names" not in DecisionControlState.__dataclass_fields__
    with pytest.raises(TypeError):
        DecisionControlState(
            2, 3, 3, True, False, recovery_tool_names=("code_search",)
        )
    blocked = _blocked_control_state()
    payload = blocked.to_dict()
    assert payload["finalization_blocked"] is True
    assert "recovery_tool_names" not in payload


# ---- B. current Production no longer exposes the recovery repair symbols ----


def test_recovery_repair_symbols_absent_from_current_product():
    decision_prompt = importlib.import_module("core.tool_agent.decision_prompt")
    for symbol in (
        "ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION",
        "ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_TEMPLATE",
        "ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256",
        "ENGINEERING_RECOVERY_REPAIR_ENABLED_PROFILE_VERSIONS",
        "build_recovery_action_repair_instruction",
    ):
        assert not hasattr(decision_prompt, symbol), symbol
    for module_name in (
        "core.tool_agent.runtime",
        "core.tool_agent.runtime_models",
        "core.tool_agent.openai_compatible",
    ):
        module = importlib.import_module(module_name)
        assert not hasattr(module, "project_decision_repair_observability")
        source = inspect.getsource(module)
        for token in (
            "recovery_tool_names",
            "_EVIDENCE_RECOVERY_TOOLS",
            "recovery action repair",
        ):
            assert token not in source, (module_name, token)


def test_deleted_16a_promotion_suite_is_gone_from_current_tree():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    assert not (
        repo_root / "tests" / "test_arch_prod_16a_missing_evidence_recovery.py"
    ).exists()


# ---- C. the kind-aware main prompt identity did not regress with the rollback ----


def test_kind_aware_main_prompt_identity_is_unchanged():
    profile = ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE
    assert profile.version == "engineering_agent_decision_prompt_unified_kind_aware_v1"
    assert profile.sha256 == (
        "de7a0eeb4beaea5ed93e0e4196f55b5253f73408c3e5216379aba0d8a7abd85f"
    )
    assert profile.render_control_state is True
    assert max_parse_repairs_for_profile(profile) == 1


# ---- D. the pre-existing bounded parse repair still works ----


def test_parse_invalid_action_still_gets_bounded_parse_repair():
    client = _ScriptedChatClient(
        ["{", '{"action": "final_answer", "answer": "recovered parse"}']
    )
    outcome = _provider(client).decide(
        _registry(), "synthetic question", control_state=_blocked_control_state()
    )
    assert isinstance(outcome.action, FinalAnswerAction)
    assert outcome.action.answer == "recovered parse"
    assert client.calls == 2
    metadata = outcome.call_metadata
    assert metadata.call_count == 2
    assert metadata.repair_attempted is True
    assert metadata.repair_succeeded is True
    assert metadata.initial_parse_category == "INVALID_JSON"
    assert callable(build_action_repair_instruction)


# ---- E/F. parse-valid terminal actions never trigger a second call ----


@pytest.mark.parametrize(
    "terminal_json,expected_type",
    [
        ('{"action": "final_answer", "answer": "premature terminal"}', FinalAnswerAction),
        ('{"action": "refuse", "reason_code": "INSUFFICIENT_INFORMATION"}', RefuseAction),
    ],
)
def test_blocked_terminal_action_gets_no_recovery_second_call(
    terminal_json, expected_type
):
    client = _ScriptedChatClient([terminal_json])
    outcome = _provider(client).decide(
        _registry(), "synthetic question", control_state=_blocked_control_state()
    )
    assert isinstance(outcome.action, expected_type)
    assert client.calls == 1
    metadata = outcome.call_metadata
    assert metadata.call_count == 1
    assert metadata.repair_attempted is False
    assert metadata.repair_succeeded is False


# ---- G. no Runtime-side parameter synthesis or automatic ToolCall ----


def test_runtime_has_no_tool_argument_synthesis_path():
    runtime_source = inspect.getsource(ToolAgentRuntime)
    assert "arguments[" not in runtime_source.replace("arguments=action.arguments", "")
    # 24B wraps the existing bounded loop with lifecycle metrics; the sole
    # ToolCall construction remains inside that loop, not in the wrapper.
    assert inspect.getsource(ToolAgentRuntime._run_bounded).count("ToolCall.create") == 1


# ---- H. the 5/4/2 budget is untouched ----


def test_frozen_budget_is_unchanged():
    budget = ToolAgentBudget()
    assert budget == ToolAgentBudget(5, 4, 2)
    assert budget.max_agent_iterations == 5
    assert budget.max_tool_calls == 4
    assert budget.max_tool_errors == 2


# ---- I. Router / Verifier / Guard seams survived the rollback ----


def test_router_verifier_and_guard_seams_are_intact():
    assert ROUTER_VERSION == "engineering_requirement_router_v1"
    requirement = route_engineering_evidence_requirement("当前实现如何处理 config?")
    assert requirement.required_evidence_groups == (("project_code",),)
    runtime_module = importlib.import_module("core.tool_agent.runtime")
    source = inspect.getsource(runtime_module)
    for seam in (
        "_run_finalization_verifier",
        "_recovery_is_feasible",
        "_EVIDENCE_PRODUCER_TOOLS",
        "INSUFFICIENT_EVIDENCE_TO_FINALIZE",
    ):
        assert seam in source, seam
    verification = importlib.import_module("core.engineering_verification")
    assert hasattr(verification, "EngineeringVerificationResult")
