"""Exercise direct-answer planning without bypassing evidence or fallback checks."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from core.engineering_context import EngineeringContextResolver
from core.query_planning import OpenAICompatibleQueryPlanner
from core.query_planning.openai_compatible import PlannerTimeoutError
from core.query_planning.prompt import (
    ENGINEERING_PLANNER_PROMPT_SHA256,
    ENGINEERING_PLANNER_PROMPT_VERSION,
    ENGINEERING_PLANNER_SYSTEM_PROMPT,
    PLANNER_PROMPT_SHA256,
    PLANNER_PROMPT_VERSION,
    build_planner_messages,
)
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import ToolAgentBudget
from tests._engineering_runtime_support import (
    NoRetrievalPlanner, StaticKnowledgeRetrievalPort, build_full_unified_runtime,
)


def _direct_payload(**overrides):
    return {
        "query_type": "unanswerable_or_no_retrieval", "retrieval_required": False,
        "action": "no_retrieval", "reason_code": "NO_RETRIEVAL_NEEDED",
        "subqueries": [], **overrides,
    }


class _PlannerClient:
    def __init__(self, payload=None, error=None):
        self.payload = _direct_payload() if payload is None else payload
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload)))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def _planner(client, version=ENGINEERING_PLANNER_PROMPT_VERSION):
    return OpenAICompatibleQueryPlanner(
        provider="scripted", model="scripted", api_key="local-test-key",
        client=client, prompt_version=version,
    )


class _Decisions:
    def __init__(self, answer, expression=None):
        self.answer = answer
        self.expression = expression
        self.states = []

    def decide(self, registry, user_query, *, context=(), control_state=None):
        self.states.append(control_state)
        action = (
            ToolCallAction(action="tool_call", tool_name="calculator",
                           arguments={"expression": self.expression})
            if self.expression is not None and len(self.states) == 1
            else FinalAnswerAction(action="final_answer", answer=self.answer)
        )
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def _run(tmp_path, question, answer, *, client=None, expression=None):
    port = StaticKnowledgeRetrievalPort()
    client = client or _PlannerClient()
    provider = _Decisions(answer, expression)
    runtime = build_full_unified_runtime(
        ToolAgentRuntime(registry=build_readonly_tool_registry(tmp_path, port), provider=provider),
        planner=_planner(client), retrieval_port=port,
    )
    return runtime.run(question), port, client, provider


def test_prompt_and_metadata_match_the_messages_actually_sent():
    client = _PlannerClient()
    result = _planner(client).plan("Compare two general concepts; no project facts")
    messages = client.calls[0]["messages"]
    assert messages[0]["content"] == ENGINEERING_PLANNER_SYSTEM_PROMPT
    assert result.call_metadata.prompt_version == ENGINEERING_PLANNER_PROMPT_VERSION
    assert result.call_metadata.prompt_sha256 == ENGINEERING_PLANNER_PROMPT_SHA256
    assert result.call_metadata.call_count == len(client.calls) == 1
    template = json.loads(messages[1]["content"])
    template["original_query"] = "<runtime-original-query>"
    identity = {
        "prompt_version": result.call_metadata.prompt_version,
        "system_prompt": messages[0]["content"], "user_payload_template": template,
        "user_payload_canonicalization": "python_json_sort_keys_compact_v1",
    }
    assert hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest() == result.call_metadata.prompt_sha256
    assert result.fallback_used is False


def test_legacy_default_prompt_identity_and_payload_are_preserved():
    client = _PlannerClient()
    planner = OpenAICompatibleQueryPlanner(
        provider="scripted", model="scripted", api_key="local-test-key", client=client,
    )
    outcome = planner.plan("hello")
    assert client.calls[0]["messages"] == build_planner_messages("hello")
    assert outcome.call_metadata.prompt_version == PLANNER_PROMPT_VERSION
    assert outcome.call_metadata.prompt_sha256 == PLANNER_PROMPT_SHA256 == (
        "5b209054f5274fa8f1f88975625c80b78d7e9e2a84569179288fed0c3a3b5c95"
    )


@pytest.mark.parametrize("version", [None, {}, "unknown", "gate3_planner_prompt_v2"])
def test_unsupported_profiles_fail_before_calling_the_provider(version):
    client = _PlannerClient()
    with pytest.raises(ValueError, match="Unsupported planner prompt_version"):
        _planner(client, version)
    assert client.calls == []


@pytest.mark.parametrize("question,answer,expression", [
    ("计算 37 * 29", "1073", "37 * 29"),
    ("Compute (125 + 7) * 16", "2112", "(125 + 7) * 16"),
    ("从通用软件工程的角度，README 与 API 文档的用途有什么区别？无需查看当前项目。",
     "README 介绍项目与使用入口；API 文档描述接口、参数与返回值。", None),
    ("将用户给定的 8, 2, 5 按升序排列", "2, 5, 8", None),
])
def test_valid_direct_plans_do_not_seed_knowledge_or_require_unrelated_citations(
    tmp_path, question, answer, expression,
):
    result, port, client, provider = _run(tmp_path, question, answer, expression=expression)
    assert result.status == "completed"
    assert result.answer == answer
    assert result.evidence == ()
    assert port.calls == []
    assert len(client.calls) == 1
    assert result.tool_calls_used == (1 if expression else 0)
    assert result.tool_errors_used == 0
    assert result.iterations_used == (2 if expression else 1)
    assert provider.states[0].available_evidence_refs == ()
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)


@pytest.mark.parametrize("payload", [
    _direct_payload(query_type="fact"),
    _direct_payload(query_type="comparison"),
    _direct_payload(retrieval_required=True),
    _direct_payload(reason_code="PLANNER_FALLBACK"),
    _direct_payload(extra_field="untrusted"),
])
def test_new_prompt_does_not_normalize_or_accept_invalid_plans(payload):
    client = _PlannerClient(payload)
    outcome = _planner(client).plan("synthetic direct request")
    assert outcome.fallback_used is True
    assert outcome.failure_code == "PLAN_INVALID_SCHEMA"
    assert outcome.plan.action == "single_retrieval"
    assert outcome.plan.reason_code == "PLANNER_FALLBACK"
    assert len(client.calls) == 1
    assert outcome.call_metadata.prompt_sha256 == ENGINEERING_PLANNER_PROMPT_SHA256


def test_provider_timeout_stays_a_single_call_conservative_fallback():
    client = _PlannerClient(error=PlannerTimeoutError("test timeout"))
    outcome = _planner(client).plan("synthetic request")
    assert outcome.fallback_used is True
    assert outcome.failure_code == "PLANNER_TIMEOUT"
    assert outcome.plan.action == "single_retrieval"
    assert outcome.call_metadata.prompt_sha256 == ENGINEERING_PLANNER_PROMPT_SHA256
    assert len(client.calls) == 1


@pytest.mark.parametrize("question", [
    "Read README.md and cite its installation command",
    "请依据项目源码解释 process 函数的实现",
    "请依据知识库理论与项目源码解释 RAG 的实现机制",
])
def test_direct_knowledge_plan_cannot_cancel_project_or_theory_evidence_requirements(
    tmp_path, question,
):
    result, port, client, provider = _run(tmp_path, question, "unsupported project claim")
    assert result.status == "refused"
    assert result.answer is None
    assert provider.states[0].missing_evidence_groups
    assert port.calls == []
    assert len(client.calls) == 1
    assert result.iterations_used <= 5
    assert result.tool_calls_used <= 4


def test_fabricated_reference_still_blocks_an_otherwise_direct_answer(tmp_path):
    result, _, _, _ = _run(tmp_path, "hello", "Hello [E99]")
    assert result.status == "refused"
    assert result.answer is None


def test_planner_fallback_does_not_turn_into_an_unguarded_direct_answer(tmp_path):
    result, port, _, _ = _run(
        tmp_path, "synthetic request", "unsupported answer",
        client=_PlannerClient(_direct_payload(query_type="comparison")),
    )
    assert port.calls
    assert result.evidence
    assert result.status == "refused"
    assert result.answer is None


def test_production_lifespan_selects_engineering_profile_without_changing_legacy_default(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_MODE", "verified")
    import api.app as application

    selected = []
    port = StaticKnowledgeRetrievalPort()
    monkeypatch.setattr(application, "ConversationStore", lambda: object())
    monkeypatch.setattr(application, "Pipeline", lambda **_: SimpleNamespace(retriever=object()))
    monkeypatch.setattr(application, "resolve_engineering_project", lambda _: SimpleNamespace(root=tmp_path))
    monkeypatch.setattr(application, "_resolve_agent_provider", lambda _: ("scripted", "local-test-key"))
    monkeypatch.setattr(application, "build_pipeline_agent_runtime", lambda *a, **k: object())
    monkeypatch.setattr(application, "PipelineRetrievalAdapter", lambda _: port)
    monkeypatch.setattr(application, "build_verified_engineering_knowledge",
                        lambda *a, **k: SimpleNamespace(retrieval_port=port))
    monkeypatch.setattr(application, "build_tool_agent_runtime", lambda **_: ToolAgentRuntime(
        registry=ToolRegistry(), provider=_Decisions("hello"),
    ))
    monkeypatch.setattr(application, "OpenAICompatibleConversationQueryResolver", lambda **_: None)
    monkeypatch.setattr(application, "EngineeringContextResolver", lambda _: EngineeringContextResolver())

    def planner_factory(**kwargs):
        selected.append(kwargs["prompt_version"])
        return NoRetrievalPlanner()

    monkeypatch.setattr(application, "OpenAICompatibleQueryPlanner", planner_factory)

    async def run():
        async with application.lifespan(application.app):
            assert application.engineering_agent_facade is not None
            assert selected == [ENGINEERING_PLANNER_PROMPT_VERSION]

    asyncio.run(run())
