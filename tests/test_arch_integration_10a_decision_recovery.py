"""Provider-free ARCH-INTEGRATION-10A decision-contract tests."""

from __future__ import annotations

import inspect

import api.app
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    ENGINEERING_MAX_OUTPUT_TOKENS,
    ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS,
    LEGACY_DECISION_PROMPT_PROFILE,
    max_output_tokens_for_profile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.runtime_models import DecisionControlState, ToolAgentBudget
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC
from core.tool_agent.tools.git_change import GIT_DIFF_SPEC
from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC
from core.unified_engineering_runtime import UnifiedEngineeringRuntime


def _blocked_state(
    groups=("project_code",),
    *,
    current_paths=0,
    required_paths=0,
):
    return DecisionControlState(
        iteration=2,
        remaining_iterations=3,
        remaining_tool_calls=3,
        tool_call_allowed=True,
        must_terminate=False,
        finalization_blocked=True,
        missing_evidence_groups=tuple((group,) for group in groups),
        current_distinct_project_code_paths=current_paths,
        required_min_distinct_project_code_paths=required_paths,
    )


def _system_message(state=None):
    return ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.build_messages(
        [
            CALCULATOR_SPEC,
            CODE_SEARCH_SPEC,
            READ_PROJECT_CONTEXT_SPEC,
            CHANGED_FILES_SPEC,
            GIT_DIFF_SPEC,
            FIND_TESTS_SPEC,
        ],
        "Explain a generic engineering evidence request.",
        control_state=state,
    )[0]["content"]


def test_unified_profile_renders_trusted_recovery_state_and_action_policy():
    system = _system_message(
        _blocked_state(
            ("project_code", "project_doc", "project_test", "project_change"),
            current_paths=1,
            required_paths=2,
        )
    )

    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256 == (
        ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256
    )
    assert "finalization_blocked=true" in system
    assert '"finalization_blocked": true' in system
    assert '"missing_evidence_groups":' in system
    assert (
        "不能仅因为当前信息不足而选择 final_answer 或 refuse；必须优先选择一个能推进"
        in system
    )
    assert "tool_call_allowed=true" in system
    assert "must_terminate=false" in system
    assert "Trusted Runtime control state" in system


def test_recovery_policy_covers_all_public_evidence_producers_and_path_floor():
    system = _system_message(_blocked_state(("project_code",)))

    for kind in ("project_code", "project_doc", "project_test"):
        assert kind in system
    assert "read_project_context" in system
    assert "code_search" in system
    assert "find_tests" in system
    assert "project_change" in system
    assert "git_diff" in system
    assert "changed_files" in system
    assert "required_min_distinct_project_code_paths" in system
    assert "current_distinct_project_code_paths" in system
    assert "新的 distinct source-code path" in system


def test_recovery_is_conditional_and_termination_still_forbids_tools():
    normal = _system_message(DecisionControlState(1, 4, 4, True, False))
    absent = _system_message(None)
    terminating = _system_message(DecisionControlState(5, 0, 0, False, True))

    assert "普通 knowledge-only" in normal
    assert "本 recovery policy 不强迫普通 knowledge-only" in absent
    assert '"finalization_blocked": true' not in normal
    assert '"finalization_blocked": true' not in absent
    assert "当 tool_call_allowed 为 false 或 must_terminate 为 true 时，不能请求 Tool" in terminating
    assert "只有 Tool 不可用、预算禁止继续，或 Runtime 的 must_terminate=true 时" in terminating


def test_legacy_and_v2_prompt_identities_are_unchanged_and_unified_is_v2_plus_policy():
    assert LEGACY_DECISION_PROMPT_PROFILE.sha256 == DECISION_PROMPT_SHA256
    assert LEGACY_DECISION_PROMPT_PROFILE.version == "tool_agent_decision_prompt_v3"
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256 == ENGINEERING_DECISION_PROMPT_V2_SHA256
    assert ENGINEERING_DECISION_PROMPT_V2_SHA256 == (
        "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.template.startswith(
        ENGINEERING_DECISION_PROMPT_V2_PROFILE.template
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.template != (
        ENGINEERING_DECISION_PROMPT_V2_PROFILE.template
    )
    assert max_output_tokens_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE) == (
        ENGINEERING_MAX_OUTPUT_TOKENS
    )
    assert max_output_tokens_for_profile(ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE) == (
        ENGINEERING_MAX_OUTPUT_TOKENS
    )
    assert max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE) == 1
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version in (
        ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS
    )


def test_legacy_profile_ignores_control_state_while_unified_renders_it():
    state = _blocked_state(("project_test",))
    legacy = LEGACY_DECISION_PROMPT_PROFILE.build_messages(
        [CALCULATOR_SPEC], "generic question", control_state=state
    )
    unified = ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.build_messages(
        [CALCULATOR_SPEC], "generic question", control_state=state
    )
    assert legacy[0]["content"] != unified[0]["content"]
    assert "Trusted Runtime control state" not in legacy[0]["content"]
    assert "Trusted Runtime control state" in unified[0]["content"]
    assert legacy[1] == unified[1]


def test_formal_unified_assembly_uses_new_profile_and_legacy_builder_has_no_default_change():
    lifespan_source = inspect.getsource(api.app.lifespan)
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE" in lifespan_source
    assert "prompt_profile=ENGINEERING_DECISION_PROMPT_V2_PROFILE" not in lifespan_source

    from core.tool_agent.integration import build_tool_agent_runtime

    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    source = inspect.getsource(build_tool_agent_runtime)
    assert "prompt_profile" in source
    assert "LEGACY_DECISION_PROMPT_PROFILE" not in source
    legacy_runtime = build_tool_agent_runtime(
        repo_root=api.app.REPO_ROOT,
        retrieval_port=RetrievalPort(),
        api_key="sk-test",
    )
    assert legacy_runtime._provider._prompt_profile is LEGACY_DECISION_PROMPT_PROFILE


def test_unified_runtime_contract_keeps_disabled_knowledge_and_single_control_boundaries():
    source = inspect.getsource(UnifiedEngineeringRuntime.run)
    assert 'disabled_tools=("knowledge_search",)' in source
    assert "enforce_evidence_acquisition=True" in source
    assert source.count("self._execution_adapter.run(") == 1
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)


def test_unified_profile_does_not_add_or_restore_a_second_knowledge_tool():
    system = _system_message(_blocked_state(("project_code",)))
    assert "knowledge_search 仍 disabled" in system
    assert "恢复第二套 knowledge tool" in system
