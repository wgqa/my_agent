"""PRODUCT-REPAIR-23B contracts: requirement-guided next-hop acquisition.

The successor grounded profile (v2) adds prompt-only guidance: when the
trusted control state names a missing evidence kind, the next Tool hop must
produce that kind's evidence (find_tests candidate → read test path;
project_doc → search + read doc chain) instead of spending the remaining
budget on unrelated artifacts. No new loop, tool, budget, or second LLM
call; the historical grounded_v1 identity stays frozen.
"""

from __future__ import annotations

import hashlib

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE as GROUNDED_V1,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE as GROUNDED_V2,
    ENGINEERING_OUTPUT_CAP_PROFILE_VERSIONS,
    ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS,
    max_output_tokens_for_profile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.runtime_models import DecisionControlState
from core.engineering_requirements import EngineeringEvidenceRequirement


GROUNDED_V1_SHA256 = (
    "c465defe7f9504d7cfb137748ba96fb90cf7bf049c7ca7a93d3f7f56945ebcdf"
)


def _blocked_state(missing_groups):
    return DecisionControlState(
        iteration=2,
        remaining_iterations=3,
        remaining_tool_calls=2,
        tool_call_allowed=True,
        must_terminate=False,
        finalization_blocked=True,
        missing_evidence_groups=missing_groups,
        current_distinct_project_code_paths=0,
        required_min_distinct_project_code_paths=0,
        citation_required_evidence_groups=missing_groups,
        citation_required_min_distinct_project_code_paths=0,
    )


def _system_message(profile, control_state, tool_specs=()):
    return profile.build_messages(
        tool_specs, "synthetic question", control_state=control_state
    )[0]["content"]


class TestGroundedV2Identity:
    def test_historical_grounded_v1_identity_is_unchanged(self):
        assert GROUNDED_V1.version == (
            "engineering_agent_decision_prompt_unified_kind_aware_grounded_v1"
        )
        assert GROUNDED_V1.sha256 == GROUNDED_V1_SHA256
        assert (
            hashlib.sha256(GROUNDED_V1.template.encode("utf-8")).hexdigest()
            == GROUNDED_V1_SHA256
        )

    def test_v2_is_pure_successor_with_own_identity(self):
        assert GROUNDED_V2.version == (
            "engineering_agent_decision_prompt_unified_kind_aware_grounded_v2"
        )
        assert GROUNDED_V2.sha256 != GROUNDED_V1.sha256
        assert (
            hashlib.sha256(GROUNDED_V2.template.encode("utf-8")).hexdigest()
            == GROUNDED_V2.sha256
        )
        assert GROUNDED_V2.template.startswith(GROUNDED_V1.template)
        assert GROUNDED_V2.render_control_state is True
        assert GROUNDED_V2.render_evidence_reference_control is True
        assert GROUNDED_V2.version in ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS
        assert GROUNDED_V2.version in ENGINEERING_OUTPUT_CAP_PROFILE_VERSIONS
        assert max_output_tokens_for_profile(GROUNDED_V2) == 1200
        assert max_parse_repairs_for_profile(GROUNDED_V2) == 1


class TestNextHopGuidance:
    def test_missing_project_test_directs_read_of_test_candidates(self):
        state = _blocked_state((("project_test",),))
        system = _system_message(GROUNDED_V2, state)
        assert "missing_evidence_groups" in system
        assert "project_test" in system
        assert "find_tests" in system
        assert "read_project_context" in system
        assert "候选测试文件路径" in system

    def test_missing_project_doc_directs_doc_search_read_chain(self):
        state = _blocked_state((("project_doc",),))
        system = _system_message(GROUNDED_V2, state)
        assert "project_doc" in system
        assert "artifact_kind=project_doc" in system
        assert "doc 证据链" in system

    def test_missing_project_code_directs_code_read(self):
        state = _blocked_state((("project_code",),))
        system = _system_message(GROUNDED_V2, state)
        assert "project_code" in system
        assert "distinct code path" in system

    def test_unblocked_control_state_does_not_demand_next_hop(self):
        state = DecisionControlState(
            iteration=1,
            remaining_iterations=4,
            remaining_tool_calls=4,
            tool_call_allowed=True,
            must_terminate=False,
        )
        system = _system_message(GROUNDED_V2, state)
        # The suffix text always explains the policy; what must stay absent
        # is any blocked/missing evidence state for a satisfied run.
        assert '"finalization_blocked": true' not in system
        assert '"missing_evidence_groups":' not in system
        assert "Missing-Evidence Next-Hop Acquisition policy" in system

    def test_v1_profile_does_not_carry_next_hop_suffix(self):
        state = _blocked_state((("project_test",),))
        system = _system_message(GROUNDED_V1, state)
        assert "Missing-Evidence Next-Hop Acquisition policy" not in system


class TestFrozenInvariants:
    def test_budget_and_requirement_contract_unchanged(self):
        from core.engineering_requirements import FROZEN_PROFILE_SPECS, PROJECT_CODE_V1
        from core.tool_agent.runtime_models import ToolAgentBudget

        budget = ToolAgentBudget()
        assert (
            budget.max_agent_iterations,
            budget.max_tool_calls,
            budget.max_tool_errors,
        ) == (5, 4, 2)
        assert FROZEN_PROFILE_SPECS[PROJECT_CODE_V1] == ((("project_code",),), 1)
        requirement = EngineeringEvidenceRequirement(
            requirement_profile=PROJECT_CODE_V1,
            required_evidence_groups=(("project_code",),),
            min_distinct_project_code_paths=1,
        )
        assert requirement.required_evidence_groups == (("project_code",),)

    def test_next_hop_guidance_has_no_scenario_specific_words(self):
        for marker in ("vanna", "instructor", "ToolRegistry", "from_openai", "HyDE"):
            assert marker not in GROUNDED_V2.template, marker
            assert marker not in GROUNDED_V2.version, marker
