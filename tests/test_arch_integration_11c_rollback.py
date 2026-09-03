"""Provider-free contract tests for the ARCH-INTEGRATION-11C rollback."""

from __future__ import annotations

import inspect

import api.app
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_V2_SHA256,
    LEGACY_DECISION_PROMPT_PROFILE,
)
from core.tool_agent.integration import build_tool_agent_runtime
from core.tool_agent.runtime_models import ToolAgentBudget
from core.unified_engineering_runtime import UnifiedEngineeringRuntime


def test_formal_unified_assembly_is_restored_to_real_validated_unified_v1():
    source = inspect.getsource(api.app.lifespan)
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE" in source
    assert "ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE" not in source


def test_unified_v2_diagnostic_candidate_identity_remains_importable_and_unchanged():
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version == (
        "engineering_agent_decision_prompt_unified_v1"
    )
    assert ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256 == (
        ENGINEERING_DECISION_PROMPT_UNIFIED_SHA256
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


def test_legacy_tool_agent_entry_keeps_its_existing_default_profile():
    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    runtime = build_tool_agent_runtime(
        repo_root=api.app.REPO_ROOT,
        retrieval_port=RetrievalPort(),
        api_key="sk-test",
    )
    assert runtime._provider._prompt_profile is LEGACY_DECISION_PROMPT_PROFILE
    assert LEGACY_DECISION_PROMPT_PROFILE.sha256 == DECISION_PROMPT_SHA256


def test_unified_runtime_budget_loop_finalization_and_knowledge_tool_are_unchanged():
    source = inspect.getsource(UnifiedEngineeringRuntime.run)
    assert 'disabled_tools=("knowledge_search",)' in source
    assert source.count("self._execution_adapter.run(") == 1
    assert source.count("self._evidence_verifier.bind(") == 1
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)
