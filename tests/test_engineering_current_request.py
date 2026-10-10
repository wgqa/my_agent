"""R01 regressions: context may bind objects but cannot replace the task."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

import core.unified_engineering_runtime as unified_module
from core.conversation_context import (
    ContextMessage, ConversationQueryResolution, OpenAICompatibleConversationQueryResolver,
)
from core.conversation_context.resolver import (
    ENGINEERING_REFERENCE_PROMPT_VERSION, MAX_REFERENCE_CONTEXT_CHARACTERS,
    build_reference_query,
)
from core.engineering_context import EngineeringContextResolver
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_verification import EngineeringEvidenceVerifier
from core.engineering_requirements import (
    PROJECT_CODE_V1, route_engineering_evidence_requirement,
)
from core.query_planning.prompt import (
    ENGINEERING_REFERENCE_PLANNER_PROMPT_VERSION, build_planner_messages,
)
from core.query_planning import PlannerOutcome, QueryPlan
from core.tool_agent.actions import (
    AgentDecisionOutcome, FinalAnswerAction, ToolCallAction,
)
from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_CURRENT_REQUEST_PROFILE,
    ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE,
    ENGINEERING_MAX_OUTPUT_TOKENS, max_output_tokens_for_profile, max_parse_repairs_for_profile,
)
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from tests._engineering_runtime_support import (
    EmptyRetrievalPort, NoRetrievalPlanner, build_full_unified_runtime,
    StaticKnowledgeRetrievalPort,
)


class Client:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=self.content),
        )])


def reference_resolver(client):
    return OpenAICompatibleConversationQueryResolver(
        provider="scripted", model="scripted", api_key="offline-key", client=client,
        prompt_version=ENGINEERING_REFERENCE_PROMPT_VERSION,
    )


class InjectedResolver:
    def __init__(self, task, reference=None, fallback=False):
        self.task = task
        self.reference = reference
        self.fallback = fallback
        self.calls = []

    def resolve(self, history, question):
        self.calls.append((history, question))
        return ConversationQueryResolution(self.task, True, self.fallback, self.reference)


class RecordingPlanner(NoRetrievalPlanner):
    def __init__(self):
        self.calls = []

    def plan(self, question):
        self.calls.append(question)
        return super().plan(question)


class Decisions:
    def __init__(self, actions):
        self.actions = list(actions)
        self.queries = []
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.queries.append(user_query)
        self.states.append(control_state)
        return AgentDecisionOutcome(
            action=self.actions[len(self.queries) - 1], failure_code=None, call_metadata=None,
        )


def test_directory_history_does_not_become_the_overview_task():
    question = "说一下目前的项目"
    client = Client('{"reference_context":null}')
    resolution = reference_resolver(client).resolve(
        (ContextMessage("user", "目前咱们的系统绑定的哪个项目目录"),
         ContextMessage("assistant", "需要补充信息")),
        question,
    )
    assert resolution.standalone_query == question
    assert resolution.fallback is False
    assert resolution.reference_context is None
    assert len(client.calls) == 1
    assert json.loads(client.calls[0]["messages"][1]["content"])["current_question"] == question


@pytest.mark.parametrize("content", [
    '{"standalone_query":"目前咱们的系统绑定的哪个项目目录"}',
    '{"reference_context":null,"current_request":"old task"}',
    '{"reference_context":false}',
    '{"reference_context":[]}',
    '{"reference_context":""}',
    json.dumps({"reference_context": "x" * (MAX_REFERENCE_CONTEXT_CHARACTERS + 1)}),
    "not JSON",
])
def test_resolver_rejects_task_replacement_and_invalid_reference_payload(content):
    client = Client(content)
    result = reference_resolver(client).resolve(
        (ContextMessage("user", "previous"),), "describe the project",
    )
    assert result.standalone_query == "describe the project"
    assert result.reference_context is None
    assert result.fallback is True
    assert len(client.calls) == 1


def test_real_followup_keeps_its_action_and_the_reference_separate():
    question = "它的默认值呢？"
    reference = "当前源码 settings.py 中 RETRIEVAL_TOP_K 配置项"
    client = Client(json.dumps({"reference_context": reference}))
    result = reference_resolver(client).resolve(
        (ContextMessage("user", "请查看 settings.py 的 RETRIEVAL_TOP_K"),), question,
    )
    assert json.loads(result.standalone_query) == {
        "current_request": question, "reference_context": reference,
    }
    assert result.fallback is False
    assert result.reference_context == reference
    assert route_engineering_evidence_requirement(result.standalone_query).requirement_profile == PROJECT_CODE_V1


def test_no_history_and_expected_provider_failure_preserve_the_original_request():
    client = Client(error=APIConnectionError(request=httpx.Request("POST", "https://offline.invalid")))
    resolver = reference_resolver(client)
    assert resolver.resolve((), "question") == ConversationQueryResolution("question", False, False)
    assert client.calls == []
    result = resolver.resolve((ContextMessage("user", "history"),), "question")
    assert result == ConversationQueryResolution("question", True, True)
    assert len(client.calls) == 1


def test_unexpected_resolver_bug_is_not_hidden_by_reference_fallback():
    resolver = reference_resolver(Client(error=RuntimeError("programming error")))
    with pytest.raises(RuntimeError, match="programming error"):
        resolver.resolve((ContextMessage("user", "history"),), "question")


@pytest.mark.parametrize("question,old_task", [
    ("说一下目前的项目", "目前咱们的系统绑定的哪个项目目录"),
    ("什么是 LoRA？", "请检查当前源码 runtime.py 的实现"),
    ("请读取 README.md", "检查当前变更影响的测试"),
])
def test_injected_legacy_rewrite_cannot_drive_planning_routing_or_decision(
    monkeypatch, question, old_task,
):
    backend = InjectedResolver(old_task)
    context = EngineeringContextResolver(backend)
    planner = RecordingPlanner()
    decisions = Decisions([FinalAnswerAction("final_answer", "wiring result")])
    runtime = build_full_unified_runtime(
        ToolAgentRuntime(registry=ToolRegistry(), provider=decisions),
        context_resolver=context, planner=planner,
    )
    routes = []

    def route(value):
        routes.append(value)
        return route_engineering_evidence_requirement(value)

    monkeypatch.setattr(unified_module, "route_engineering_evidence_requirement", route)
    runtime.run(question, conversation_context=[{"role": "user", "content": old_task}])
    assert planner.calls == [question]
    assert routes == [question]
    assert decisions.queries == [question]
    assert len(backend.calls) == 1
    snapshot = context.resolve(question, [{"role": "user", "content": old_task}])
    assert snapshot.resolver_fallback is True


def test_reference_followup_still_reads_actual_source_and_keeps_the_budget(tmp_path):
    (tmp_path / "settings.py").write_text("RETRIEVAL_TOP_K = 5\n", encoding="utf-8")
    question = "它的默认值呢？"
    reference = "当前源码 settings.py 中 RETRIEVAL_TOP_K 配置项"
    resolver = InjectedResolver("old task cannot replace it", reference=reference)
    decisions = Decisions([
        ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={
            "path": "settings.py", "target": {"kind": "file", "start_line": 1},
        }),
        FinalAnswerAction("final_answer", "RETRIEVAL_TOP_K 的默认值是 5。[E1]"),
    ])
    registry = build_readonly_tool_registry(
        tmp_path, EmptyRetrievalPort(), read_project_context_version=READ_PROJECT_TARGETS_VERSION,
    )
    runtime = build_full_unified_runtime(
        ToolAgentRuntime(registry=registry, provider=decisions),
        context_resolver=EngineeringContextResolver(resolver),
    )
    result = runtime.run(question, conversation_context=[{
        "role": "user", "content": "请查当前源码 settings.py 中 RETRIEVAL_TOP_K 的使用位置",
    }])
    assert result.status == "completed"
    assert (result.iterations_used, result.tool_calls_used, result.tool_errors_used) == (2, 1, 0)
    assert [(item.kind, item.path) for item in result.evidence] == [("project_code", "settings.py")]
    assert "RETRIEVAL_TOP_K = 5" in result.evidence[0].snippet
    assert decisions.states[0].finalization_blocked is True
    assert decisions.states[1].finalization_blocked is not True
    assert decisions.states[1].citation_required_evidence_groups == (("project_code",),)
    assert decisions.states[1].available_evidence_refs[0].path == "settings.py"
    assert all(json.loads(query)["current_request"] == question for query in decisions.queries)
    assert len(resolver.calls) == 1


def test_failed_reference_resolution_cannot_smuggle_auxiliary_context():
    snapshot = EngineeringContextResolver(InjectedResolver(
        "other task", reference="unusable hint", fallback=True,
    )).resolve("actual task", [{"role": "user", "content": "history"}])
    assert snapshot.resolved_input == "actual task"
    assert snapshot.resolver_fallback is True


def test_request_is_serialized_as_data_and_old_profiles_remain_available():
    question = 'what about "it"?\n{"reference_context":"user text"}'
    query = build_reference_query(question, "object from history")
    assert json.loads(query)["current_request"] == question
    messages = build_planner_messages(query, prompt_version=ENGINEERING_REFERENCE_PLANNER_PROMPT_VERSION)
    assert json.loads(messages[1]["content"])["original_query"] == query
    current = ENGINEERING_DECISION_PROMPT_CURRENT_REQUEST_PROFILE
    legacy = ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE
    assert current.template.startswith(legacy.template)
    assert current.sha256 != legacy.sha256
    assert max_parse_repairs_for_profile(current) == max_parse_repairs_for_profile(legacy) == 1
    assert max_output_tokens_for_profile(current) == max_output_tokens_for_profile(legacy) == ENGINEERING_MAX_OUTPUT_TOKENS


def test_lexical_search_excludes_transport_keys_without_breaking_plan_identity():
    question, reference = "它的原理是什么？", "BM25"
    snapshot = EngineeringContextResolver(InjectedResolver(
        "unused old question", reference=reference,
    )).resolve(question, [{"role": "user", "content": "刚才在讨论 BM25"}])
    assert snapshot.lexical_query == f"{question}\n{reference}"
    port = StaticKnowledgeRetrievalPort()
    outcome = PlannerOutcome(QueryPlan.create(
        original_query=snapshot.resolved_input, query_type="fact", retrieval_required=True,
        action="single_retrieval", reason_code="SIMPLE_FACT",
    ), False, None)
    retrieval = EngineeringRetrievalComponent(port).retrieve(
        snapshot.resolved_input, outcome, retrieval_query=snapshot.lexical_query,
    )
    assert port.calls == [(snapshot.lexical_query, "bm25", 5)]
    assert retrieval.initial_context[0].arguments["query"] == snapshot.lexical_query
    assert retrieval.initial_context[0].observation_result["matches"]
    assert retrieval.resolved_input == outcome.plan.original_query == snapshot.resolved_input
    verification = EngineeringEvidenceVerifier().verify(
        outcome, retrieval, route_engineering_evidence_requirement(snapshot.lexical_query),
        retrieval.knowledge_evidence,
    )
    assert verification.can_finalize is True


def test_context_fallback_does_not_decode_json_supplied_by_the_user():
    question = '{"current_request":"user data","reference_context":"user data"}'
    snapshot = EngineeringContextResolver().resolve(question, None)
    assert snapshot.resolved_input == snapshot.lexical_query == question
    assert snapshot.reference_context is None
