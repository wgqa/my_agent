"""Provider-free ARCH-EVAL-08B domain-boundary regression tests."""

from __future__ import annotations

from core.agent_runtime import Document
from core.agent_runtime.runtime import RetrievalPort
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_verification import EngineeringEvidenceVerifier
from core.query_planning import BaseQueryPlanner, PlannerOutcome, QueryPlan, Subquery
from core.tool_agent.actions import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
)
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.tools.git_change import GIT_DIFF_SPEC
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC
from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
from core.unified_engineering_runtime import (
    LegacyToolAgentExecutionAdapter,
    UnifiedEngineeringRuntime,
)


class StaticHandler:
    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return self.result_factory(arguments)


class SeedKnowledgePort(RetrievalPort):
    supported_strategies = ("bm25", "hybrid")

    def __init__(self, *, empty: bool = False):
        self.empty = empty
        self.calls = []

    def search(self, query: str, strategy: str, top_k: int):
        self.calls.append((query, strategy, top_k))
        if self.empty:
            return ()
        return (
            Document(
                chunk_id="seed-1",
                document_id="seed-doc",
                source_name="knowledge/seed.md",
                content="deterministic planned knowledge seed",
                score=1.0,
                rank=1,
            ),
        )


class SingleRetrievalPlanner(BaseQueryPlanner):
    def __init__(self, *, decomposed: bool = False):
        self.decomposed = decomposed

    def plan(self, query: str) -> PlannerOutcome:
        if self.decomposed:
            subqueries = (
                Subquery("sq1", "dense retrieval", "dense facet", True),
                Subquery("sq2", "bm25 retrieval", "sparse facet", True),
            )
            plan = QueryPlan.create(
                original_query=query,
                query_type="comparison",
                retrieval_required=True,
                action="decomposed_retrieval",
                reason_code="COMPARISON_EVIDENCE",
                subqueries=subqueries,
            )
        else:
            plan = QueryPlan.create(
                original_query=query,
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
            )
        return PlannerOutcome(plan=plan, fallback_used=False, failure_code=None)


class ScriptedProvider:
    def __init__(self, actions):
        self.actions = tuple(actions)
        self.calls = 0
        self.states = []
        self.registries = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        del user_query, context
        self.calls += 1
        self.states.append(control_state)
        self.registries.append(tuple(spec.name for spec in registry.list_specs()))
        action = self.actions[min(self.calls - 1, len(self.actions) - 1)]
        return AgentDecisionOutcome(
            action=action,
            failure_code=None,
            call_metadata=None,
        )


def _read_result(arguments):
    return {
        "path": arguments["path"],
        "start_line": 1,
        "end_line": 1,
        "lines": [{"line": 1, "text": "synthetic project evidence"}],
    }


def _diff_result(arguments):
    return {
        "path": arguments["path"],
        "mode": arguments["mode"],
        "truncated": False,
        "diff": "@@ synthetic change\n-old\n+new",
        "start_line": 1,
        "end_line": 1,
    }


def _knowledge_result(_arguments):
    return {
        "matches": [
            {
                "rank": 1,
                "source_name": "knowledge/tool.md",
                "chunk_id": "tool-1",
                "score": 1.0,
                "snippet": "tool knowledge",
            }
        ]
    }


def _read(path: str) -> ToolCallAction:
    return ToolCallAction(
        action="tool_call",
        tool_name="read_project_context",
        arguments={"path": path, "line": 1, "context_lines": 0},
    )


def _diff(path: str = "src/runtime.py") -> ToolCallAction:
    return ToolCallAction(
        action="tool_call",
        tool_name="git_diff",
        arguments={"mode": "working_tree", "path": path},
    )


def _final() -> FinalAnswerAction:
    return FinalAnswerAction(action="final_answer", answer="grounded deterministic answer")


def _runtime(actions, *, decomposed: bool = False, empty_knowledge: bool = False):
    registry = ToolRegistry()
    read_handler = StaticHandler(_read_result)
    diff_handler = StaticHandler(_diff_result)
    knowledge_handler = StaticHandler(_knowledge_result)
    registry.register(READ_PROJECT_CONTEXT_SPEC, read_handler)
    registry.register(GIT_DIFF_SPEC, diff_handler)
    registry.register(KNOWLEDGE_SEARCH_SPEC, knowledge_handler)
    provider = ScriptedProvider(actions)
    runtime = ToolAgentRuntime(registry=registry, provider=provider)
    retrieval_port = SeedKnowledgePort(empty=empty_knowledge)
    return (
        UnifiedEngineeringRuntime(
            LegacyToolAgentExecutionAdapter(runtime),
            context_resolver=EngineeringContextResolver(),
            evidence_planner=EngineeringEvidencePlanner(
                SingleRetrievalPlanner(decomposed=decomposed)
            ),
            retrieval_component=EngineeringRetrievalComponent(retrieval_port),
            evidence_verifier=EngineeringEvidenceVerifier(),
        ),
        provider,
        read_handler,
        diff_handler,
        knowledge_handler,
        retrieval_port,
    )


def test_current_project_code_cannot_be_finalized_from_knowledge_seed_or_refusal():
    runtime, provider, read_handler, _, _, retrieval_port = _runtime(
        [
            RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION"),
            _read("src/runtime.py"),
            _final(),
        ]
    )

    result = runtime.run("Review the current project code for the runtime facade")

    assert result.status == "completed"
    assert {item.kind for item in result.evidence} == {"knowledge", "project_code"}
    assert read_handler.calls == 1
    assert retrieval_port.calls
    assert provider.states[0].finalization_blocked is True
    assert provider.states[0].missing_evidence_groups == (("project_code",),)
    assert "knowledge_search" not in provider.registries[0]
    assert result.iterations_used <= 5
    assert result.tool_calls_used <= 4
    assert sum(event.event_type == "runtime_stopped" for event in result.trace) == 1


def test_project_only_finalization_does_not_depend_on_planned_knowledge_coverage():
    runtime, _, read_handler, _, _, retrieval_port = _runtime(
        [_read("src/runtime.py"), _final()],
        empty_knowledge=True,
    )

    result = runtime.run("Review the current project code for the runtime facade")

    assert result.status == "completed"
    assert [item.kind for item in result.evidence] == ["project_code"]
    assert read_handler.calls == 1
    assert retrieval_port.calls


def test_docs_implementation_requires_document_and_code_evidence():
    runtime, _, read_handler, _, _, _ = _runtime(
        [_read("README.md"), _read("src/runtime.py"), _final()]
    )

    result = runtime.run(
        "Review the README documentation for the current implementation and consistency"
    )

    assert result.status == "completed"
    assert [item.kind for item in result.evidence] == [
        "knowledge",
        "project_doc",
        "project_code",
    ]
    assert read_handler.calls == 2


def test_cross_file_diagnosis_keeps_two_distinct_code_path_floor():
    runtime, _, read_handler, _, _, _ = _runtime(
        [_read("core/runtime.py"), _read("core/verification.py"), _final()]
    )

    result = runtime.run("Diagnose failure propagation across modules and explain behavior")

    assert result.status == "completed"
    code_paths = {item.path for item in result.evidence if item.kind == "project_code"}
    assert code_paths == {"core/runtime.py", "core/verification.py"}
    assert read_handler.calls == 2


def test_change_test_requires_change_and_test_evidence():
    runtime, _, read_handler, diff_handler, _, _ = _runtime(
        [_diff(), _read("tests/test_runtime.py"), _final()]
    )

    result = runtime.run("Review the commit diff and regression test coverage")

    assert result.status == "completed"
    assert [item.kind for item in result.evidence] == [
        "knowledge",
        "project_change",
        "project_test",
    ]
    assert diff_handler.calls == 1
    assert read_handler.calls == 1


def test_pure_knowledge_and_decomposed_knowledge_do_not_require_repo_tools():
    single_runtime, single_provider, single_read, _, _, single_retrieval = _runtime([_final()])
    single = single_runtime.run("What is BM25?")

    decomposed_runtime, decomposed_provider, decomposed_read, _, _, decomposed_retrieval = _runtime(
        [_final()], decomposed=True
    )
    decomposed = decomposed_runtime.run("Compare dense and BM25 retrieval concepts")

    for result, provider, read_handler, retrieval_port in (
        (single, single_provider, single_read, single_retrieval),
        (decomposed, decomposed_provider, decomposed_read, decomposed_retrieval),
    ):
        assert result.status == "completed"
        assert all(item.kind == "knowledge" for item in result.evidence)
        assert read_handler.calls == 0
        assert retrieval_port.calls
        assert "knowledge_search" not in provider.registries[0]
