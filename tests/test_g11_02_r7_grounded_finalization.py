from __future__ import annotations

import scripts.run_g11_02_theory_code as runner
from core.tool_agent import (
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    ENGINEERING_DECISION_PROMPT_V3_PROFILE,
    ENGINEERING_DECISION_PROMPT_V3_SHA256,
    ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS,
    LEGACY_DECISION_PROMPT_PROFILE,
    OpenAICompatibleAgentDecisionProvider,
    ToolAgentBudget,
    build_readonly_tool_registry,
    max_parse_repairs_for_profile,
)
from core.tool_agent.decision_prompt import (
    ACTION_REPAIR_PROMPT_SHA256,
    ACTION_REPAIR_PROMPT_VERSION,
)
from core.tool_agent.runtime_models import DecisionControlState


class RetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


def _registry():
    from core.tool_agent import CALCULATOR_SPEC, CalculatorHandler, ToolRegistry

    registry = ToolRegistry()
    registry.register(CALCULATOR_SPEC, CalculatorHandler())
    return registry


def _provider(profile=None):
    return OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="sk-test",
        client=object(),
        prompt_profile=profile,
    )


def test_engineering_v3_has_grounding_policy_and_no_case_specific_terms():
    state = DecisionControlState(2, 3, 3, True, False)
    messages = ENGINEERING_DECISION_PROMPT_V3_PROFILE.build_messages(
        _registry().list_specs(), "Explain current implementation and the theory.",
        control_state=state,
    )
    system = messages[0]["content"]

    assert ENGINEERING_DECISION_PROMPT_V3_PROFILE.version == (
        "engineering_agent_decision_prompt_v3"
    )
    assert "Grounded evidence policy" in system
    assert "Project Code Evidence" in system
    assert "Knowledge Evidence" in system
    assert "grounding checklist" in system
    assert "Trusted Runtime control state" in system
    assert '"remaining_tool_calls": 3' in system
    assert messages[1] == {
        "role": "user",
        "content": "Explain current implementation and the theory.",
    }
    assert all(
        "Trusted Runtime control state" not in message["content"]
        for message in messages[1:]
    )

    forbidden_case_terms = {
        "TC01",
        "TC02",
        "TC03",
        "TC04",
        "RRF",
        "MMR",
        "Pipeline",
        "CitationValidator",
        "HybridRetriever",
        "MMRRetriever",
        "dense_rank_map",
        "sparse_rank_map",
        "all_ids",
        "sim_to_query",
        "sim_to_selected",
        "candidate_k",
        "final_k",
    }
    assert forbidden_case_terms.isdisjoint(system)


def test_prompt_identities_and_repair_matrix_are_frozen():
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256 == (
        "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
    )
    assert ENGINEERING_DECISION_PROMPT_V2_SHA256 == (
        ENGINEERING_DECISION_PROMPT_V2_PROFILE.sha256
    )
    assert ENGINEERING_DECISION_PROMPT_V3_SHA256 == (
        "0e9554cffcd7240ad394afb24cc60239d583f1f0a7218b2fad0aab09507ff917"
    )
    assert LEGACY_DECISION_PROMPT_PROFILE.version == "tool_agent_decision_prompt_v3"
    assert LEGACY_DECISION_PROMPT_PROFILE.sha256 == (
        "a6092bffdfee3236575ae0f801985e6c8d6aecedba339672bde838f1daed1dc1"
    )
    assert ACTION_REPAIR_PROMPT_VERSION == "engineering_action_repair_prompt_v1"
    assert ACTION_REPAIR_PROMPT_SHA256 == (
        "958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636"
    )
    assert ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS == {
        "engineering_agent_decision_prompt_v2",
        "engineering_agent_decision_prompt_v3",
    }
    assert max_parse_repairs_for_profile(None) == 0
    assert max_parse_repairs_for_profile(LEGACY_DECISION_PROMPT_PROFILE) == 0
    assert max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE) == 1
    assert max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_V3_PROFILE) == 1
    assert _provider()._max_parse_repairs == 0
    assert _provider(ENGINEERING_DECISION_PROMPT_V2_PROFILE)._max_parse_repairs == 1
    assert _provider(ENGINEERING_DECISION_PROMPT_V3_PROFILE)._max_parse_repairs == 1


def test_toolset_and_budget_remain_frozen(tmp_path):
    registry = build_readonly_tool_registry(tmp_path, RetrievalPort())
    assert len(registry.list_specs()) == 7
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)


def _metric_case(evidence_kinds: list[str]) -> dict:
    return {
        "status": "completed",
        "evidence_kinds": evidence_kinds,
        "tool_sequence": [],
        "tool_calls_used": 0,
        "iterations_used": 1,
        "evidence": [],
        "provider_calls_total": 1,
        "repair_attempted": False,
        "repair_succeeded": False,
        "failure_code": None,
        "initial_parse_categories": [],
    }


def test_runner_accepts_v3_and_requires_project_code_for_explicit_metric():
    assert runner.validate_prompt_identity(
        "engineering_agent_decision_prompt_v3", ENGINEERING_DECISION_PROMPT_V3_SHA256
    ) == ("engineering_agent_decision_prompt_v3", ENGINEERING_DECISION_PROMPT_V3_SHA256)

    metrics = runner._metrics(
        [
            _metric_case(["knowledge", "project_code"]),
            _metric_case(["knowledge", "project_doc"]),
        ]
    )

    assert metrics["cross_source_cases"] == 1
    assert metrics["source_code_cross_source_cases"] == 1
    assert metrics["source_code_cross_source_rate"] == 0.5
