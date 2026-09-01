"""Provider-free ARCH-INTEGRATION-11A prompt-composition contract tests."""

from __future__ import annotations

import inspect

import api.app
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    ENGINEERING_DECISION_PROMPT_V3_PROFILE,
    ENGINEERING_DECISION_PROMPT_V3_SHA256,
    ENGINEERING_MAX_OUTPUT_TOKENS,
    LEGACY_DECISION_PROMPT_PROFILE,
    max_output_tokens_for_profile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.runtime_models import DecisionControlState, ToolAgentBudget
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC
from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC, GIT_DIFF_SPEC
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC
from core.unified_engineering_runtime import UnifiedEngineeringRuntime


def _system_message(state=None):
    return ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.build_messages(
        [
            CALCULATOR_SPEC,
            CODE_SEARCH_SPEC,
            READ_PROJECT_CONTEXT_SPEC,
            CHANGED_FILES_SPEC,
            GIT_DIFF_SPEC,
            FIND_TESTS_SPEC,
        ],
        "Explain a generic source-grounded engineering question.",
        control_state=state,
    )[0]["content"]


def test_unified_v2_composes_grounding_and_recovery_contracts():
    state = DecisionControlState(
        2,
        3,
        3,
        True,
        False,
        True,
        (("project_code",),),
        0,
        2,
    )
    system = _system_message(state)

    assert "Grounded evidence policy" in system
    assert "Evidence Recovery Control policy" in system
    assert '"finalization_blocked": true' in system
    assert '"missing_evidence_groups": [["project_code"]]' in system
    assert "不能仅因为当前信息不足而选择 final_answer 或 refuse" in system
    assert "必须优先选择一个能推进missing_evidence_groups 的可用只读 Tool" in system
    assert "Runtime 仍是最终 hard enforcement owner" in system

    forbidden_case_or_evaluator_terms = {"v7d", "Gold", "evaluator", "Dev question"}
    assert all(term not in system for term in forbidden_case_or_evaluator_terms)


def test_composed_policy_keeps_source_over_doc_and_continues_acquisition():
    system = _system_message(
        DecisionControlState(
            2,
            3,
            3,
            True,
            False,
            True,
            (("project_code",),),
            0,
            2,
        )
    )

    assert "README、study note、design doc 和历史文档只能补充设计意图，不能替代 source code" in system
    assert "要求 project_code 时，读取 project_doc 不算满足 project_code" in system
    assert "missing_evidence_groups 表示仍缺失的 public evidence kind" in system
    assert "required_min_distinct_project_code_paths 大于 current_distinct_project_code_paths" in system
    assert "继续取得新的 distinct source-code path" in system
    assert "code_search 返回多个命中时，优先选择 function/method body" in system
    assert "read_project_context 必须读取" in system
    assert "如果读取窗口未覆盖回答所需逻辑且仍有 Tool budget，继续读取" in system
    assert "project_code、project_doc、project_test" in system
    assert "public evidence producer" in system
    assert "read_project_context" in system
    assert "project_change 需要 git_diff 产生 public evidence" in system


def test_knowledge_only_is_not_forced_to_repo_and_termination_remains_hard():
    ordinary = _system_message(DecisionControlState(1, 4, 4, True, False))
    absent = _system_message(None)
    terminating = _system_message(DecisionControlState(5, 0, 0, False, True))

    assert '"finalization_blocked": true' not in ordinary
    assert '"finalization_blocked": true' not in absent
    assert "本 recovery policy 不强迫普通 knowledge-only请求调用 Repo Tool" in absent
    assert "当 tool_call_allowed 为 false 或 must_terminate 为 true 时，不能请求 Tool" in terminating
    assert "只有 Tool 不可用、预算禁止继续，或 Runtime 的 must_terminate=true 时" in terminating
    assert "Unified Runtime 中 knowledge_search 仍 disabled" in terminating


def test_frozen_profile_identities_remain_unchanged_and_new_identity_is_independent():
    assert LEGACY_DECISION_PROMPT_PROFILE.version == "tool_agent_decision_prompt_v3"
    assert LEGACY_DECISION_PROMPT_PROFILE.sha256 == DECISION_PROMPT_SHA256
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.version == "engineering_agent_decision_prompt_v2"
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256 == ENGINEERING_DECISION_PROMPT_V2_SHA256
    assert ENGINEERING_DECISION_PROMPT_V2_SHA256 == (
        "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
    )
    assert ENGINEERING_DECISION_PROMPT_V3_PROFILE.version == "engineering_agent_decision_prompt_v3"
    assert ENGINEERING_DECISION_PROMPT_V3_PROFILE.sha256 == ENGINEERING_DECISION_PROMPT_V3_SHA256
    assert ENGINEERING_DECISION_PROMPT_V3_SHA256 == (
        "0e9554cffcd7240ad394afb24cc60239d583f1f0a7218b2fad0aab09507ff917"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256 == (
        "0a060a3f05840a1387aa0f438edfbff37f4c9534955a4cdb834375c9c81fb19b"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v2"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256 == (
        ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256 == (
        "63035303e2a1bfd644da5cd8f83d9bf09ebd5cf5e8d781dc30d3467ebe7872b7"
    )
    recovery_suffix = ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.template[
        len(ENGINEERING_DECISION_PROMPT_V2_PROFILE.template) :
    ]
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.template == (
        ENGINEERING_DECISION_PROMPT_V3_PROFILE.template + recovery_suffix
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.template != (
        ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.template
    )
    assert max_output_tokens_for_profile(ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE) == (
        ENGINEERING_MAX_OUTPUT_TOKENS
    )
    assert max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE) == 1


def test_formal_unified_assembly_uses_v2_and_legacy_entry_remains_default():
    source = inspect.getsource(api.app.lifespan)
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE" in source
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE" not in source
    assert "prompt_profile=ENGINEERING_DECISION_PROMPT_V2_PROFILE" not in source

    from core.tool_agent.integration import build_tool_agent_runtime

    builder_source = inspect.getsource(build_tool_agent_runtime)
    assert "prompt_profile" in builder_source
    assert "LEGACY_DECISION_PROMPT_PROFILE" not in builder_source


def test_unified_runtime_still_has_one_loop_one_budget_and_disabled_knowledge_tool():
    source = inspect.getsource(UnifiedEngineeringRuntime.run)
    assert 'disabled_tools=("knowledge_search",)' in source
    assert "enforce_evidence_acquisition=True" in source
    assert source.count("self._execution_adapter.run(") == 1
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
