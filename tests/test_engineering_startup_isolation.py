"""Failure injection through lifespan and HTTP, without model/network calls."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.app as backend
from core.engineering_knowledge import EngineeringKnowledgeIdentity
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.integration import build_tool_agent_runtime
from tests._engineering_runtime_support import EmptyRetrievalPort, NoRetrievalPlanner
from ui import app as frontend
from ui.api_client import ApiError


class CalculatorDecisions:
    def __init__(self):
        self.actions = iter([
            ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression": "2 * 3"}),
            FinalAnswerAction(action="final_answer", answer="6"),
        ])

    def decide(self, *_args, **_kwargs):
        return AgentDecisionOutcome(action=next(self.actions), failure_code=None, call_metadata=None)


@pytest.fixture
def startup(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGINEERING_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ENGINEERING_CONVERSATION_DB", str(tmp_path / "conversations.sqlite3"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-startup-key")
    port = EmptyRetrievalPort()
    knowledge = SimpleNamespace(
        retrieval_port=port,
        identity=EngineeringKnowledgeIdentity("870e5864df67", 37, 215, "bm25", "dbc497c796d5", True),
    )
    pipeline = SimpleNamespace(
        retriever=object(),
        vector_store=SimpleNamespace(count=lambda: 0),
        config=SimpleNamespace(generator_provider="deepseek", embedding_provider="bge", retriever_strategy="hybrid"),
    )
    calls = []
    monkeypatch.setattr(backend, "Pipeline", lambda **_kwargs: pipeline)
    monkeypatch.setattr(backend, "PipelineRetrievalAdapter", lambda _retriever: port)
    monkeypatch.setattr(backend, "build_pipeline_agent_runtime", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(backend, "build_verified_engineering_knowledge", lambda *_args, **_kwargs: knowledge)
    monkeypatch.setattr(backend, "OpenAICompatibleQueryPlanner", lambda **_kwargs: NoRetrievalPlanner())
    # First-turn queries never call this resolver. Throw if a regression does.
    monkeypatch.setattr(backend, "OpenAICompatibleConversationQueryResolver", lambda **_kwargs: None)

    def build_runtime(**kwargs):
        calls.append(kwargs)
        return build_tool_agent_runtime(provider=CalculatorDecisions(), **kwargs)

    monkeypatch.setattr(backend, "build_tool_agent_runtime", build_runtime)
    return calls, build_runtime


def fail(*_args, **_kwargs):
    raise RuntimeError("injected component failure")


@pytest.mark.parametrize("failed_component", ["none", "pipeline", "agent", "tool"])
def test_legacy_failure_keeps_engineering_query_and_ui_available(startup, monkeypatch, failed_component):
    calls, build_runtime = startup
    if failed_component == "pipeline":
        monkeypatch.setattr(backend, "Pipeline", fail)
    elif failed_component == "agent":
        monkeypatch.setattr(backend, "build_pipeline_agent_runtime", fail)
    elif failed_component == "tool":
        def fail_legacy_tool(**kwargs):
            if "prompt_profile" not in kwargs:
                return fail()
            return build_runtime(**kwargs)
        monkeypatch.setattr(backend, "build_tool_agent_runtime", fail_legacy_tool)

    with TestClient(backend.app) as client:
        capabilities = client.get("/capabilities").json()
        assert capabilities["features"]["engineering_agent"] is True
        assert capabilities["pipeline_ready"] is (failed_component != "pipeline")
        assert capabilities["agent_runtime_ready"] is (failed_component not in {"pipeline", "agent"})
        assert capabilities["tool_agent_runtime_ready"] is (failed_component not in {"pipeline", "tool"})
        assert client.get("/engineering/knowledge").json()["verified"] is True
        response = client.post("/engineering/query", json={"question": "请计算 2 * 3"})
        assert response.status_code == 200
        answer = response.json()
        assert answer["status"] == "completed" and answer["answer"] == "6"
        assert (answer["iterations_used"], answer["tool_calls_used"], answer["tool_errors_used"]) == (2, 1, 0)
        main_call = next(call for call in calls if "prompt_profile" in call)
        assert main_call["read_project_context_version"] == "read_project_context_v4"
        assert main_call["code_search_version"] == "code_search_v7"
        assert main_call["retrieval_port"] is backend.engineering_knowledge_backend.retrieval_port
        assert backend.engineering_tool_execution_runtime._budget.max_agent_iterations == 5
        if failed_component == "pipeline":
            assert client.get("/health").status_code == 503
            assert client.post("/query", json={"question": "q"}).status_code == 503
            monkeypatch.setattr(frontend.st, "session_state", SimpleNamespace())

            class Client:
                def health(self):
                    raise ApiError("http_error", "Pipeline unavailable", status=503)
                def capabilities(self):
                    return capabilities
                def project(self):
                    return client.get("/project").json()
                def engineering_knowledge(self):
                    return client.get("/engineering/knowledge").json()

            frontend._refresh_runtime(Client())
            assert frontend.st.session_state.api_available is True
            assert frontend._feature_enabled("engineering_agent") is True
            assert frontend._feature_enabled("basic_rag") is False
        conversation = client.post("/engineering/conversations")
        assert conversation.status_code == 201
    assert backend.engineering_agent_facade is None and backend.pipeline is None
    assert backend.conversation_store is None


@pytest.mark.parametrize("failed_component", ["knowledge", "main_tool", "store"])
def test_product_failure_does_not_disable_legacy_or_claim_readiness(startup, monkeypatch, failed_component):
    _, build_runtime = startup
    if failed_component == "knowledge":
        monkeypatch.setattr(backend, "build_verified_engineering_knowledge", fail)
    elif failed_component == "main_tool":
        def fail_main(**kwargs):
            return fail() if "prompt_profile" in kwargs else build_runtime(**kwargs)
        monkeypatch.setattr(backend, "build_tool_agent_runtime", fail_main)
    else:
        monkeypatch.setattr(backend, "ConversationStore", fail)
    with TestClient(backend.app) as client:
        capabilities = client.get("/capabilities").json()
        assert capabilities["pipeline_ready"] and capabilities["tool_agent_runtime_ready"]
        assert client.get("/health").status_code == 200
        knowledge = client.get("/engineering/knowledge").json()
        if failed_component == "store":
            assert capabilities["features"]["engineering_agent"] is True
            assert client.post("/engineering/conversations").status_code == 503
        else:
            assert capabilities["features"]["engineering_agent"] is False
            assert knowledge["ready"] is False
            assert knowledge["verified"] is (failed_component == "main_tool")
            assert client.post("/engineering/query", json={"question": "q"}).status_code == 503


def test_ui_connection_failure_clears_previous_availability(monkeypatch):
    monkeypatch.setattr(frontend.st, "session_state", SimpleNamespace(api_available=True))

    class Disconnected:
        health = capabilities = project = engineering_knowledge = staticmethod(
            lambda: (_ for _ in ()).throw(ApiError("connection_error", "offline"))
        )

    frontend._refresh_runtime(Disconnected())
    assert frontend.st.session_state.api_available is False
    assert frontend.st.session_state.runtime_capabilities is None
