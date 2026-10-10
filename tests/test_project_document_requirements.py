"""Document evidence must use the existing acquisition/binding path."""

import copy
from dataclasses import replace

import pytest

from core.engineering_requirements import (
    DOCS_CODE_V1,
    NO_ADDITIONAL_REQUIREMENT,
    PROJECT_CODE_V1,
    PROJECT_DOC_V1,
    evaluate_evidence_requirement,
    route_engineering_evidence_requirement,
)
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan
from tests._engineering_runtime_support import (
    EmptyRetrievalPort, StaticKnowledgeRetrievalPort, build_full_unified_runtime,
)


@pytest.mark.parametrize("question", [
    "请依据项目 README.md，列出支持的功能并引用该文档。",
    "根据仓库里的 README.md，说明最低 Python 版本和安装命令。",
    "请阅读 README.md 的 Quick demo 并引用文档。",
    "Read docs/guide.rst and cite its setup instructions.",
    "Summarize docs/usage.txt.",
    "请根据 docs\\指南.md 概括安装流程。",
    "请根据 docs/configuration.md 说明配置字段的含义。",
    "Summarize the current project documentation.",
    "请根据README.md列出功能并引用该文档。",
    "Read docs/source.md and cite it.",
    "Read docs/code-guide.md and cite it.",
    "根据 文档/安装指南.md 总结安装流程。",
])
def test_explicit_document_source_routes_to_document_not_source_code(question):
    requirement = route_engineering_evidence_requirement(question)
    assert requirement.requirement_profile is PROJECT_DOC_V1
    assert requirement.required_evidence_groups == (("project_doc",),)
    assert requirement.min_distinct_project_code_paths == 0


@pytest.mark.parametrize("question", [
    "How should I write README.md?",
    "如何编写一个清晰的 README.md？",
    "Discuss documentation design for an agent.",
    "README 与 API 文档的用途有什么区别？无需查看当前项目。",
    "Read about Markdown syntax.",
    "Summarize https://example.org/guide.md.",
    "Read D:/external/guide.md.",
    "Read ../README.md.",
    "Read tests/test_docs.md.",
    "How should I write docs/read.md?",
    "How should I create docs/cite.txt?",
])
def test_document_topics_and_nonlocal_references_do_not_add_document_obligation(question):
    requirement = route_engineering_evidence_requirement(question)
    assert requirement.requirement_profile is NO_ADDITIONAL_REQUIREMENT


def test_existing_mixed_and_source_requirements_keep_their_precedence():
    assert route_engineering_evidence_requirement(
        "Compare the README documentation with the current implementation for consistency"
    ).requirement_profile is DOCS_CODE_V1
    assert route_engineering_evidence_requirement(
        "Read README.md and explain the project source code"
    ).requirement_profile is PROJECT_CODE_V1


def test_only_document_evidence_satisfies_the_new_domain():
    requirement = route_engineering_evidence_requirement("Read README.md and cite it")
    document = EngineeringEvidence(
        evidence_id="E1", kind="project_doc", path="README.md",
        start_line=1, end_line=1, snippet="Installation: pip install demo",
    )
    code = replace(document, kind="project_code", path="src/demo.py")
    knowledge = KnowledgeEvidence(
        evidence_id="E1", kind="knowledge", source_name="knowledge/guide.md",
        chunk_id="k1", score=1.0, rank=1, snippet="unrelated knowledge",
    )
    assert not evaluate_evidence_requirement(requirement, [knowledge, code]).satisfied
    assert evaluate_evidence_requirement(requirement, [document]).satisfied


def test_historical_router_identity_does_not_follow_live_document_router():
    from core.engineering_requirements import ROUTER_VERSION
    from evaluation.integration_v7 import ProtocolViolation, load_protocol_manifest
    from evaluation.integration_v7.case_contract import _validate_current_system_b_identity

    manifest = load_protocol_manifest()
    historical = copy.deepcopy(manifest["systems"]["B"])
    assert historical["requirement_router"]["version"] == "engineering_requirement_router_v1"
    assert ROUTER_VERSION == "engineering_requirement_router_v5"
    _validate_current_system_b_identity(historical)
    historical["requirement_router"]["version"] = ROUTER_VERSION
    with pytest.raises(ProtocolViolation, match="requirement_router identity drift"):
        _validate_current_system_b_identity(historical)


class _ReadThenAnswer:
    def __init__(self, answer):
        self.answer = answer
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.states.append(control_state)
        action = (
            ToolCallAction(action="tool_call", tool_name="read_project_context",
                           arguments={"path": "README.md", "line": 1, "context_lines": 5})
            if len(self.states) == 1
            else FinalAnswerAction(action="final_answer", answer=self.answer)
        )
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


@pytest.mark.parametrize("answer, expected_status", [
    ("Install with pip install demo [E1].", "completed"),
    ("Install with pip install demo [E999].", "refused"),
    ("Install with pip install demo.", "refused"),
])
def test_full_assembly_reuses_acquisition_guard_and_reference_binding(tmp_path, answer, expected_status):
    (tmp_path / "README.md").write_text("Installation: pip install demo\n", encoding="utf-8")
    provider = _ReadThenAnswer(answer)
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort())
    runtime = build_full_unified_runtime(ToolAgentRuntime(registry=registry, provider=provider))
    result = runtime.run("Read README.md and cite its installation command")
    assert result.status == expected_status
    assert result.iterations_used == 2
    assert result.tool_calls_used == 1
    assert result.tool_errors_used == 0
    assert provider.states[0].missing_evidence_groups == (("project_doc",),)
    assert provider.states[0].finalization_blocked is True
    assert provider.states[0].remaining_tool_calls == 4
    assert provider.states[1].must_terminate is False
    assert result.evidence[0].kind == "project_doc"


class _SingleKnowledgePlan(BaseQueryPlanner):
    def plan(self, original_query):
        return PlannerOutcome(
            plan=QueryPlan.create(
                original_query=original_query, query_type="fact",
                retrieval_required=True, action="single_retrieval",
                reason_code="SIMPLE_FACT",
            ),
            fallback_used=False, failure_code=None,
        )


@pytest.mark.parametrize("with_knowledge", [False, True])
def test_planned_knowledge_does_not_become_a_document_prerequisite(tmp_path, with_knowledge):
    (tmp_path / "README.md").write_text("Installation: pip install demo\n", encoding="utf-8")
    port = StaticKnowledgeRetrievalPort() if with_knowledge else EmptyRetrievalPort()
    doc_id = "E2" if with_knowledge else "E1"
    provider = _ReadThenAnswer(f"Install with pip install demo [{doc_id}].")
    registry = build_readonly_tool_registry(tmp_path, port)
    runtime = build_full_unified_runtime(
        ToolAgentRuntime(registry=registry, provider=provider),
        planner=_SingleKnowledgePlan(), retrieval_port=port,
    )
    result = runtime.run("Read README.md and cite its installation command")
    assert result.status == "completed"
    assert result.tool_calls_used == 1
    assert result.tool_errors_used == 0
    assert result.evidence[-1].kind == "project_doc"
    assert provider.states[0].missing_evidence_groups == (("project_doc",),)
