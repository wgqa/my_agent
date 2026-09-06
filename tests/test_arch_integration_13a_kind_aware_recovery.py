"""Provider-free contracts for ARCH-INTEGRATION-13A."""

from __future__ import annotations

import inspect

import pytest

import api.app
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_SUFFIX,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_TEMPLATE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_MAX_OUTPUT_TOKENS,
    LEGACY_DECISION_PROMPT_PROFILE,
    max_output_tokens_for_profile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.integration import build_tool_agent_runtime
from core.tool_agent.runtime_models import DecisionControlState, ToolAgentBudget
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC, CODE_SEARCH_VERSION
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC
from core.unified_engineering_runtime import UnifiedEngineeringRuntime
from evaluation.integration_v7.runner_worker import (
    UNIFIED_DECISION_PROMPT_SELECTOR,
    UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR,
    UNIFIED_V2_DECISION_PROMPT_SELECTOR,
    _select_decision_prompt_profile,
)


def _blocked_state(*groups: str) -> DecisionControlState:
    return DecisionControlState(
        iteration=2,
        remaining_iterations=3,
        remaining_tool_calls=3,
        tool_call_allowed=True,
        must_terminate=False,
        finalization_blocked=True,
        missing_evidence_groups=tuple((group,) for group in groups),
    )


def _system_message(*groups: str) -> str:
    return ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.build_messages(
        [CODE_SEARCH_SPEC, READ_PROJECT_CONTEXT_SPEC, FIND_TESTS_SPEC],
        "Explain a generic repository evidence request.",
        control_state=_blocked_state(*groups),
    )[0]["content"]


def test_frozen_unified_v1_and_rejected_unified_v2_identities_are_unchanged():
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    assert (
        ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256
        == ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256 == (
        "0a060a3f05840a1387aa0f438edfbff37f4c9534955a4cdb834375c9c81fb19b"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v2"
    )
    assert (
        ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256
        == ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256 == (
        "63035303e2a1bfd644da5cd8f83d9bf09ebd5cf5e8d781dc30d3467ebe7872b7"
    )


def test_kind_aware_profile_is_unified_v1_plus_only_the_narrow_suffix():
    profile = ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE
    assert profile.version == "engineering_agent_decision_prompt_unified_kind_aware_v1"
    assert profile.sha256 == ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_SHA256
    assert profile.template == ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_TEMPLATE
    assert profile.template == (
        ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.template
        + ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_SUFFIX
    )
    assert "Grounded evidence policy" not in ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_SUFFIX
    assert "README、study note" not in ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_SUFFIX
    assert profile.render_control_state is True
    assert max_output_tokens_for_profile(profile) == ENGINEERING_MAX_OUTPUT_TOKENS
    assert max_parse_repairs_for_profile(profile) == 1


def test_kind_aware_suffix_maps_missing_project_code_to_code_search_filter():
    system = _system_message("project_code")
    assert '"finalization_blocked": true' in system
    assert '"missing_evidence_groups": [["project_code"]]' in system
    assert "missing_evidence_groups 是 Trusted Runtime 的 evidence intent" in system
    assert "缺失的 project_code 定位 repo path" in system
    assert "code_search.arguments.artifact_kind 必须为 project_code" in system


def test_kind_aware_suffix_maps_missing_project_doc_to_code_search_filter():
    system = _system_message("project_doc")
    assert '"missing_evidence_groups": [["project_doc"]]' in system
    assert "缺失的 project_doc 定位 repo path" in system
    assert "code_search.arguments.artifact_kind 必须为 project_doc" in system


def test_kind_aware_suffix_keeps_project_test_and_unrequired_search_behavior_distinct():
    project_test = _system_message("project_test")
    ordinary = ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.build_messages(
        [CODE_SEARCH_SPEC, READ_PROJECT_CONTEXT_SPEC, FIND_TESTS_SPEC],
        "Explain a generic knowledge-only concept.",
        control_state=DecisionControlState(1, 4, 4, True, False),
    )[0]["content"]
    assert "project_test 仍使用 find_tests → read_project_context" in project_test
    assert "不要用 code_search 的 artifact_kind 模拟 project_test discovery" in project_test
    assert "不存在对应 missing evidence obligation 时" in ordinary
    assert "不要为了“更保险”强制增加 artifact_kind" in ordinary


def test_worker_selector_is_additive_and_all_prior_identities_remain_stable():
    assert _select_decision_prompt_profile({"system": "B"}) is ENGINEERING_DECISION_PROMPT_V2_PROFILE
    assert _select_decision_prompt_profile({"system": "A"}) is ENGINEERING_DECISION_PROMPT_V2_PROFILE
    assert _select_decision_prompt_profile(
        {"system": "B", "decision_prompt_profile_selector": UNIFIED_DECISION_PROMPT_SELECTOR}
    ) is ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
    assert _select_decision_prompt_profile(
        {
            "system": "B",
            "decision_prompt_profile_selector": UNIFIED_V2_DECISION_PROMPT_SELECTOR,
        }
    ) is ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE
    assert _select_decision_prompt_profile(
        {
            "system": "B",
            "decision_prompt_profile_selector": UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR,
        }
    ) is ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE
    with pytest.raises(ValueError):
        _select_decision_prompt_profile(
            {
                "system": "A",
                "decision_prompt_profile_selector": UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR,
            }
        )
    with pytest.raises(ValueError):
        _select_decision_prompt_profile(
            {"system": "B", "decision_prompt_profile_selector": "unknown"}
        )


def test_formal_assembly_uses_kind_aware_profile_while_legacy_stays_default():
    lifespan_source = inspect.getsource(api.app.lifespan)
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE" in lifespan_source
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE" not in lifespan_source

    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    legacy_runtime = build_tool_agent_runtime(
        repo_root=api.app.REPO_ROOT,
        retrieval_port=RetrievalPort(),
        api_key="sk-test",
    )
    assert legacy_runtime._provider._prompt_profile is LEGACY_DECISION_PROMPT_PROFILE


def test_tool_schema_runtime_budget_and_unified_control_boundaries_are_unchanged():
    artifact_kind = CODE_SEARCH_SPEC.input_schema["properties"]["artifact_kind"]
    assert CODE_SEARCH_VERSION == CODE_SEARCH_SPEC.version == "code_search_v5"
    assert "artifact_kind" not in CODE_SEARCH_SPEC.input_schema["required"]
    assert artifact_kind["enum"] == ["any", "project_code", "project_doc"]

    source = inspect.getsource(UnifiedEngineeringRuntime.run)
    assert 'disabled_tools=("knowledge_search",)' in source
    assert source.count("self._execution_adapter.run(") == 1
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
