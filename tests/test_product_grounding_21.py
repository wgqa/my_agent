"""PRODUCT-GROUNDING-21 provider-free contracts for Answer ↔ Evidence binding.

Covers the trusted evidence reference catalog (Tests A-D), the grounded
prompt profile (Test E), the structural [E#] binding validator (Tests F-M),
runtime-level finalization behavior (no extra model call / hard stops), and
frozen-identity guards (prompt SHA, budget 5/4/2, requirement profiles).
"""

from __future__ import annotations

import hashlib

import pytest

import core.unified_engineering_runtime as unified_runtime_module
from core.agent_runtime import Document
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_requirements import (
    CHANGE_TEST_V1,
    DIAGNOSIS_CROSS_FILE_V1,
    DIAGNOSIS_SINGLE_V1,
    DOCS_CODE_V1,
    FROZEN_PROFILE_SPECS,
    NO_ADDITIONAL_REQUIREMENT,
    PROJECT_CODE_V1,
    THEORY_CODE_V1,
    EngineeringEvidenceRequirement,
)
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_verification import (
    ANSWER_BINDING_STATUS_INCOMPLETE,
    ANSWER_BINDING_STATUS_INVALID,
    ANSWER_BINDING_STATUS_MISSING,
    ANSWER_BINDING_STATUS_NOT_CHECKED,
    ANSWER_BINDING_STATUS_NOT_REQUIRED,
    ANSWER_BINDING_STATUS_VALID,
    ANSWER_EVIDENCE_REFERENCE_INCOMPLETE,
    ANSWER_EVIDENCE_REFERENCE_INVALID,
    ANSWER_EVIDENCE_REFERENCE_MISSING,
    EngineeringEvidenceVerifier,
    parse_answer_evidence_references,
)
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE,
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
    ENGINEERING_OUTPUT_CAP_PROFILE_VERSIONS,
    ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS,
    max_output_tokens_for_profile,
    max_parse_repairs_for_profile,
)
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    DecisionControlState,
    DecisionEvidenceReference,
    EngineeringEvidence,
    KnowledgeEvidence,
    ToolAgentBudget,
    INSUFFICIENT_EVIDENCE_TO_FINALIZE,
)
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
from tests._engineering_runtime_support import build_full_unified_runtime


HISTORICAL_KIND_AWARE_SHA256 = (
    "de7a0eeb4beaea5ed93e0e4196f55b5253f73408c3e5216379aba0d8a7abd85f"
)


class _RecordingProvider:
    """Deterministic provider that records every trusted control state."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.calls += 1
        self.states.append(control_state)
        action = self.actions[min(self.calls - 1, len(self.actions) - 1)]
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


class _StaticHandler:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return self.result


_READ_RESULT = {
    "path": "core/example.py",
    "start_line": 1,
    "end_line": 2,
    "lines": [{"line": 1, "text": "synthetic implementation"}],
}


def _knowledge(evidence_id="E1"):
    return KnowledgeEvidence(
        evidence_id=evidence_id,
        kind="knowledge",
        source_name="knowledge/theory.md",
        chunk_id="k1",
        score=0.5,
        rank=1,
        snippet="planned knowledge evidence",
    )


def _code(evidence_id="E1", path="core/example.py"):
    return EngineeringEvidence(
        evidence_id=evidence_id,
        kind="project_code",
        path=path,
        start_line=1,
        end_line=2,
        snippet="project implementation",
    )


def _change(evidence_id="E1"):
    return EngineeringEvidence(
        evidence_id=evidence_id,
        kind="project_change",
        path="src/service.py",
        start_line=1,
        end_line=1,
        snippet="@@ synthetic change",
    )


def _test_evidence(evidence_id="E2"):
    return EngineeringEvidence(
        evidence_id=evidence_id,
        kind="project_test",
        path="tests/test_service.py",
        start_line=1,
        end_line=1,
        snippet="def test_service(): pass",
    )


def _requirement(profile):
    groups, min_paths = FROZEN_PROFILE_SPECS[profile]
    return EngineeringEvidenceRequirement(
        requirement_profile=profile,
        required_evidence_groups=groups,
        min_distinct_project_code_paths=min_paths,
    )


class _NoRetrievalPlanner(BaseQueryPlanner):
    def plan(self, original_query: str) -> PlannerOutcome:
        return PlannerOutcome(
            plan=QueryPlan.create(
                original_query=original_query,
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=False,
                action="no_retrieval",
                reason_code="NO_RETRIEVAL_NEEDED",
            ),
            fallback_used=False,
            failure_code=None,
        )


class _SingleRetrievalPlanner(BaseQueryPlanner):
    def plan(self, original_query: str) -> PlannerOutcome:
        return PlannerOutcome(
            plan=QueryPlan.create(
                original_query=original_query,
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
            ),
            fallback_used=False,
            failure_code=None,
        )


class _StaticPort:
    supported_strategies = ("bm25",)

    def __init__(self, docs=()):
        self.docs = tuple(docs)

    def search(self, query, strategy, top_k):
        return self.docs


def _bound(requirement, *, planner=None, docs=()):
    """Bind the real verifier to a deterministic planner + snapshot."""

    planner = planner or _NoRetrievalPlanner()
    outcome = planner.plan("synthetic grounding question")
    snapshot = EngineeringRetrievalComponent(_StaticPort(docs)).retrieve(
        outcome.plan.original_query, outcome
    )
    return EngineeringEvidenceVerifier().bind(outcome, snapshot, requirement)


# ---------------------------------------------------------------------------
# Tests A-C: trusted evidence reference catalog
# ---------------------------------------------------------------------------


def test_a_seed_knowledge_evidence_is_in_first_decision_catalog():
    provider = _RecordingProvider([FinalAnswerAction("final_answer", "done")])
    runtime = ToolAgentRuntime(registry=ToolRegistry(), provider=provider)
    result = runtime.run(
        "synthetic question",
        initial_evidence=(_knowledge("E1"),),
    )

    assert result.status == "completed"
    state = provider.states[0]
    assert [(ref.evidence_id, ref.kind) for ref in state.available_evidence_refs] == [
        ("E1", "knowledge")
    ]
    knowledge_ref = state.available_evidence_refs[0]
    assert knowledge_ref.to_dict() == {
        "evidence_id": "E1",
        "kind": "knowledge",
        "source_name": "knowledge/theory.md",
        "chunk_id": "k1",
        "rank": 1,
    }


def test_b_project_evidence_enters_catalog_on_next_decision():
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, _StaticHandler(_READ_RESULT))
    provider = _RecordingProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={"path": "core/example.py", "line": 1, "context_lines": 0},
            ),
            FinalAnswerAction("final_answer", "done"),
        ]
    )
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    result = runtime.run("synthetic question")

    assert result.status == "completed"
    assert provider.states[0].available_evidence_refs == ()
    refs = provider.states[1].available_evidence_refs
    assert [(ref.evidence_id, ref.kind) for ref in refs] == [("E1", "project_code")]
    assert refs[0].to_dict() == {
        "evidence_id": "E1",
        "kind": "project_code",
        "path": "core/example.py",
        "start_line": 1,
        "end_line": 2,
    }


def test_c_trusted_catalog_carries_metadata_only():
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, _StaticHandler(_READ_RESULT))
    provider = _RecordingProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={"path": "core/example.py", "line": 1, "context_lines": 0},
            ),
            FinalAnswerAction("final_answer", "done"),
        ]
    )
    ToolAgentRuntime(registry=registry, provider=provider).run("synthetic question")

    catalog = provider.states[1].to_dict(include_evidence_reference_control=True)[
        "available_evidence_refs"
    ]
    assert catalog == [
        {
            "evidence_id": "E1",
            "kind": "project_code",
            "path": "core/example.py",
            "start_line": 1,
            "end_line": 2,
        }
    ]
    serialized = repr(catalog)
    assert "snippet" not in serialized
    assert "content" not in serialized
    assert "synthetic implementation" not in serialized
    assert "observation_result" not in serialized


# ---------------------------------------------------------------------------
# Tests D-E: prompt profile identity and rendering
# ---------------------------------------------------------------------------


def test_d_historical_kind_aware_profile_stays_render_identical():
    profile = ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE
    assert profile.version == "engineering_agent_decision_prompt_unified_kind_aware_v1"
    assert profile.sha256 == HISTORICAL_KIND_AWARE_SHA256
    assert (
        hashlib.sha256(profile.template.encode("utf-8")).hexdigest()
        == HISTORICAL_KIND_AWARE_SHA256
    )
    assert profile.render_evidence_reference_control is False

    state = DecisionControlState(
        iteration=1,
        remaining_iterations=4,
        remaining_tool_calls=4,
        tool_call_allowed=True,
        must_terminate=False,
        available_evidence_refs=(
            DecisionEvidenceReference(
                evidence_id="E1",
                kind="project_code",
                path="core/example.py",
                start_line=1,
                end_line=2,
            ),
        ),
        citation_required_evidence_groups=(("project_code",),),
        citation_required_min_distinct_project_code_paths=1,
    )
    messages = profile.build_messages(
        [], "synthetic question", control_state=state
    )
    assert "available_evidence_refs" not in messages[0]["content"]
    assert "citation_required_evidence_groups" not in messages[0]["content"]


def test_e_grounded_profile_renders_trusted_catalog_only_in_system_message():
    profile = ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE
    assert profile.version == (
        "engineering_agent_decision_prompt_unified_kind_aware_grounded_v1"
    )
    assert (
        hashlib.sha256(profile.template.encode("utf-8")).hexdigest()
        == profile.sha256
    )
    assert profile.render_evidence_reference_control is True
    assert profile.version in ENGINEERING_REPAIR_ENABLED_PROFILE_VERSIONS
    assert profile.version in ENGINEERING_OUTPUT_CAP_PROFILE_VERSIONS
    assert max_output_tokens_for_profile(profile) == 1200
    assert max_parse_repairs_for_profile(profile) == 1

    state = DecisionControlState(
        iteration=1,
        remaining_iterations=4,
        remaining_tool_calls=4,
        tool_call_allowed=True,
        must_terminate=False,
        available_evidence_refs=(
            DecisionEvidenceReference(
                evidence_id="E1",
                kind="knowledge",
                source_name="knowledge/theory.md",
                chunk_id="k1",
                rank=1,
            ),
        ),
    )
    observation = {
        "tool_name": "knowledge_search",
        "arguments": {"query": "theory"},
        "call_id": "call-1",
        "observation_status": "ok",
        "observation_result": {
            "matches": [
                {
                    "rank": 1,
                    "source_name": "knowledge/theory.md",
                    "chunk_id": "k1",
                    "score": 0.5,
                    "snippet": "secret untrusted snippet",
                }
            ]
        },
        "observation_error_code": None,
    }
    messages = profile.build_messages(
        [],
        "synthetic question",
        context=(),
        control_state=state,
    )
    # The untrusted Observation message is appended by the runtime provider;
    # here we assert the system side only carries the metadata catalog.
    system = messages[0]["content"]
    assert "available_evidence_refs" in system
    assert '"E1"' in system
    assert "knowledge/theory.md" in system
    assert "secret untrusted snippet" not in system

    from core.tool_agent.decision_prompt import _build_messages_from_template

    with_observation = _build_messages_from_template(
        profile.template,
        [],
        "synthetic question",
        context=(),
        control_state=state,
        include_evidence_reference_control=True,
    )
    assert "secret untrusted snippet" not in with_observation[0]["content"]
    assert "不要要求或编造" not in with_observation[0]["content"]


def test_control_state_reference_fields_are_gated_and_validated():
    state = DecisionControlState(1, 4, 4, True, False)
    assert "available_evidence_refs" not in state.to_dict()

    ref = DecisionEvidenceReference(
        evidence_id="E1",
        kind="project_code",
        path="core/example.py",
        start_line=1,
        end_line=2,
    )
    state = DecisionControlState(
        1, 4, 4, True, False, available_evidence_refs=(ref,)
    )
    payload = state.to_dict(include_evidence_reference_control=True)
    assert payload["available_evidence_refs"] == [ref.to_dict()]
    assert payload["citation_required_evidence_groups"] == []
    assert payload["citation_required_min_distinct_project_code_paths"] == 0

    with pytest.raises(ValueError):
        DecisionControlState(
            1,
            4,
            4,
            True,
            False,
            available_evidence_refs=(ref, ref),
        )
    with pytest.raises(ValueError):
        DecisionEvidenceReference(
            evidence_id="E1",
            kind="knowledge",
            source_name="knowledge/theory.md",
            rank=1,
            path="core/example.py",
        )
    with pytest.raises(ValueError):
        DecisionEvidenceReference(
            evidence_id="knowledge",
            kind="knowledge",
            source_name="knowledge/theory.md",
            rank=1,
        )


# ---------------------------------------------------------------------------
# Tests F-M: structural binding validator
# ---------------------------------------------------------------------------


def test_f_valid_binding_finalizes():
    result = _bound(_requirement(PROJECT_CODE_V1)).verify(
        (_code("E1"),),
        "The behavior is implemented here. [E1]",
    )
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_VALID
    assert result.cited_evidence_ids == ("E1",)
    assert result.invalid_evidence_ids == ()
    assert result.can_finalize is True
    assert result.recovery_allowed is False


def test_g_missing_binding_blocks_finalization():
    result = _bound(_requirement(PROJECT_CODE_V1)).verify(
        (_code("E1"),),
        "The behavior is implemented here.",
    )
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_MISSING
    assert result.cited_evidence_ids == ()
    assert ANSWER_EVIDENCE_REFERENCE_MISSING in result.insufficiency_reasons
    assert result.can_finalize is False
    assert result.recovery_allowed is False


def test_h_fake_evidence_id_is_invalid_with_precedence():
    result = _bound(_requirement(PROJECT_CODE_V1)).verify(
        (_code("E1"),),
        "The behavior is implemented here. [E1] [E99]",
    )
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INVALID
    assert result.invalid_evidence_ids == ("E99",)
    assert result.cited_evidence_ids == ("E1",)
    assert ANSWER_EVIDENCE_REFERENCE_INVALID in result.insufficiency_reasons
    assert result.can_finalize is False
    assert result.recovery_allowed is False

    only_fake = _bound(_requirement(PROJECT_CODE_V1)).verify(
        (_code("E1"),),
        "The behavior is implemented here. [E99]",
    )
    assert only_fake.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INVALID
    assert only_fake.cited_evidence_ids == ()


def test_i_theory_code_cited_subset_missing_project_side_is_incomplete():
    requirement = _requirement(THEORY_CODE_V1)
    verifier = _bound(
        requirement,
        planner=_SingleRetrievalPlanner(),
        docs=(
            Document(
                chunk_id="k1",
                document_id="knowledge-1",
                source_name="knowledge/theory.md",
                content="deterministic planned knowledge evidence",
                score=0.5,
                rank=1,
            ),
        ),
    )
    result = verifier.verify(
        (_knowledge("E1"), _code("E2")),
        "The theory works like this. [E1]",
    )
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INCOMPLETE
    assert result.cited_evidence_ids == ("E1",)
    assert ANSWER_EVIDENCE_REFERENCE_INCOMPLETE in result.insufficiency_reasons
    assert result.can_finalize is False


def test_j_theory_code_citing_both_groups_is_valid():
    requirement = _requirement(THEORY_CODE_V1)
    verifier = _bound(
        requirement,
        planner=_SingleRetrievalPlanner(),
        docs=(
            Document(
                chunk_id="k1",
                document_id="knowledge-1",
                source_name="knowledge/theory.md",
                content="deterministic planned knowledge evidence",
                score=0.5,
                rank=1,
            ),
        ),
    )
    result = verifier.verify(
        (_knowledge("E1"), _code("E2")),
        "The mechanism follows X. [E1]\nThe repository implements it here. [E2]",
    )
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_VALID
    assert result.cited_evidence_ids == ("E1", "E2")
    assert result.can_finalize is True


def test_k_change_test_cited_coverage():
    requirement = _requirement(CHANGE_TEST_V1)
    evidence = (_change("E1"), _test_evidence("E2"))

    incomplete = _bound(requirement).verify(
        evidence, "The change is documented here. [E1]"
    )
    assert incomplete.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INCOMPLETE
    assert incomplete.can_finalize is False

    valid = _bound(requirement).verify(
        evidence,
        "The change is documented here. [E1]\nThe test covers it. [E2]",
    )
    assert valid.answer_evidence_binding_status == ANSWER_BINDING_STATUS_VALID
    assert valid.can_finalize is True


def test_l_cross_file_cited_path_coverage():
    requirement = _requirement(DIAGNOSIS_CROSS_FILE_V1)
    evidence = (_code("E1", "core/one.py"), _code("E2", "core/two.py"))

    incomplete = _bound(requirement).verify(
        evidence, "The failure starts here. [E1]"
    )
    assert incomplete.answer_evidence_binding_status == ANSWER_BINDING_STATUS_INCOMPLETE
    assert incomplete.can_finalize is False

    valid = _bound(requirement).verify(
        evidence, "The failure starts here. [E1] and propagates there. [E2]"
    )
    assert valid.answer_evidence_binding_status == ANSWER_BINDING_STATUS_VALID
    assert valid.can_finalize is True


def test_m_no_evidence_direct_answer_is_not_required():
    result = _bound(_requirement(NO_ADDITIONAL_REQUIREMENT)).verify(
        (),
        "deterministic direct result",
    )
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_NOT_REQUIRED
    assert result.answer_evidence_binding_required is False
    assert result.cited_evidence_ids == ()
    assert result.can_finalize is True


def test_binding_not_checked_only_before_an_answer_exists():
    result = _bound(_requirement(PROJECT_CODE_V1)).verify((_code("E1"),), None)
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_NOT_CHECKED
    assert result.answer_evidence_binding_required is True
    assert result.can_finalize is True


def test_reference_parser_is_exact_and_case_sensitive():
    assert parse_answer_evidence_references("uses [E1] and [E2]") == ("E1", "E2")
    assert parse_answer_evidence_references("[E1] ... [E1]") == ("E1",)
    assert parse_answer_evidence_references("[e1] [E0] [E-1] [Efoo] [E01]") == ()
    assert parse_answer_evidence_references("[E12]") == ("E12",)
    assert parse_answer_evidence_references("no references at all") == ()
    with pytest.raises(TypeError):
        parse_answer_evidence_references(None)


def test_duplicate_references_keep_first_occurrence_order():
    result = _bound(_requirement(PROJECT_CODE_V1)).verify(
        (_code("E1"), _code("E2", "core/other.py")),
        "start [E2] middle [E1] again [E2]",
    )
    assert result.cited_evidence_ids == ("E2", "E1")
    assert result.answer_evidence_binding_status == ANSWER_BINDING_STATUS_VALID


# ---------------------------------------------------------------------------
# Runtime-level finalization behavior
# ---------------------------------------------------------------------------


def _product_facade(provider, requirement, monkeypatch):
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, _StaticHandler(_READ_RESULT))
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    monkeypatch.setattr(
        unified_runtime_module,
        "route_engineering_evidence_requirement",
        lambda _question: requirement,
    )
    return EngineeringAgentFacade(build_full_unified_runtime(runtime))


def test_runtime_completes_with_valid_binding_and_no_extra_model_call(monkeypatch):
    provider = _RecordingProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={"path": "core/example.py", "line": 1, "context_lines": 0},
            ),
            FinalAnswerAction("final_answer", "Implemented in core/example.py. [E1]"),
        ]
    )
    facade = _product_facade(provider, _requirement(PROJECT_CODE_V1), monkeypatch)

    result = facade.run("Where is this implemented?")

    assert result.status == "completed"
    assert result.answer == "Implemented in core/example.py. [E1]"
    assert provider.calls == 2
    assert result.tool_calls_used == 1


def test_runtime_missing_citation_hard_stops_without_extra_calls(monkeypatch):
    provider = _RecordingProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={"path": "core/example.py", "line": 1, "context_lines": 0},
            ),
            FinalAnswerAction("final_answer", "Implemented without a reference."),
        ]
    )
    facade = _product_facade(provider, _requirement(PROJECT_CODE_V1), monkeypatch)

    result = facade.run("Where is this implemented?")

    assert result.status == "refused"
    assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
    assert provider.calls == 2
    assert result.tool_calls_used == 1
    assert not any(
        event.event_type == "finalization_guard_blocked" for event in result.trace
    )


def test_runtime_fake_citation_hard_stops(monkeypatch):
    provider = _RecordingProvider(
        [
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={"path": "core/example.py", "line": 1, "context_lines": 0},
            ),
            FinalAnswerAction("final_answer", "Implemented here. [E99]"),
        ]
    )
    facade = _product_facade(provider, _requirement(PROJECT_CODE_V1), monkeypatch)

    result = facade.run("Where is this implemented?")

    assert result.status != "completed"
    assert result.reason_code == INSUFFICIENT_EVIDENCE_TO_FINALIZE
    assert provider.calls == 2


# ---------------------------------------------------------------------------
# Frozen identity guards
# ---------------------------------------------------------------------------


def test_budget_and_requirement_profiles_stay_frozen():
    budget = ToolAgentBudget()
    assert (budget.max_agent_iterations, budget.max_tool_calls, budget.max_tool_errors) == (
        5,
        4,
        2,
    )
    assert set(FROZEN_PROFILE_SPECS) == {
        THEORY_CODE_V1,
        CHANGE_TEST_V1,
        DIAGNOSIS_SINGLE_V1,
        DIAGNOSIS_CROSS_FILE_V1,
        DOCS_CODE_V1,
        PROJECT_CODE_V1,
        NO_ADDITIONAL_REQUIREMENT,
    }
