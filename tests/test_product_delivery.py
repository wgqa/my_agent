"""Current product identity, demo protocol and isolated delivery regressions."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.app as backend
from api.conversation_store import ConversationStore
from api.project_workspace import EngineeringProject
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_knowledge import EngineeringKnowledgeIdentity
from core.product_version import PRODUCT_VERSION, product_identity
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.integration import build_tool_agent_runtime
from scripts import demo_engineering as demo
from scripts.smoke_local_api import _build_env
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime
from ui import app as frontend
from ui.api_client import ApiError


def test_version_and_openapi_agree_even_when_runtimes_are_unavailable(monkeypatch):
    for name in ("pipeline", "engineering_agent_facade", "tool_agent_runtime", "agent_runtime"):
        monkeypatch.setattr(backend, name, None)
    client = TestClient(backend.app)
    assert client.get("/health").status_code == 503
    assert client.get("/version").json() == product_identity()
    assert client.get("/openapi.json").json()["info"]["version"] == PRODUCT_VERSION
    assert "dev" in PRODUCT_VERSION


def test_ui_exposes_version_difference_without_disabling_ready_runtime(monkeypatch):
    captions, warnings = [], []
    state = SimpleNamespace(backend_version={"version": "1.0.0"}, api_available=True)
    monkeypatch.setattr(frontend.st, "session_state", state)
    monkeypatch.setattr(frontend.st, "caption", captions.append)
    monkeypatch.setattr(frontend.st, "warning", warnings.append)
    frontend._render_version_status()
    assert PRODUCT_VERSION in captions[0] and "1.0.0" in captions[0]
    assert len(warnings) == 1 and state.api_available


def test_smoke_does_not_inherit_developer_project_corpus_database_or_keys(monkeypatch, tmp_path):
    for name in ("ENGINEERING_PROJECT_ROOT", "ENGINEERING_KNOWLEDGE_CORPUS_ROOT", "ENGINEERING_CONVERSATION_DB", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "developer-value")
    env = _build_env(tmp_path)
    for name in ("ENGINEERING_PROJECT_ROOT", "ENGINEERING_KNOWLEDGE_CORPUS_ROOT", "ENGINEERING_CONVERSATION_DB"):
        Path(env[name]).relative_to(tmp_path)
    assert env["DEEPSEEK_API_KEY"] == env["OPENAI_API_KEY"] == "dummy-placeholder-not-a-real-key"
    assert env["HF_HUB_OFFLINE"] == "1"


@pytest.fixture
def project(tmp_path):
    return demo.prepare_project(tmp_path / "engineering-demo")


def test_preparation_creates_only_fixture_change_and_rejects_existing_workspace(project):
    before = (project / "support_search/settings.py").read_bytes()
    changed = subprocess.run(["git", "diff", "--name-only"], cwd=project, check=True, capture_output=True, text=True).stdout.strip()
    baseline = subprocess.run(["git", "show", "HEAD:support_search/settings.py"], cwd=project, check=True, capture_output=True, text=True).stdout
    assert changed == "support_search/settings.py"
    assert "DEFAULT_RESULT_LIMIT = 4" in baseline
    assert "DEFAULT_RESULT_LIMIT = 6" in before.decode()
    assert '["limit"] == 4' in (project / "tests/test_service.py").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        demo.prepare_project(project)
    assert (project / "support_search/settings.py").read_bytes() == before


class RecordingClient:
    def __init__(self):
        self.identity = product_identity()
        self.feature = True
        self.project_name = "engineering-demo"
        self.requests = []
        self.message = ""
        self.result = {"status": "refused", "reason_code": "INSUFFICIENT_INFORMATION", "answer": None,
                       "iterations_used": 1, "tool_calls_used": 0, "tool_errors_used": 0}

    def version(self):
        return self.identity
    def capabilities(self):
        return {"features": {"engineering_agent": self.feature}}
    def engineering_knowledge(self):
        return {"ready": True, "verified": True}
    def project(self):
        return {"project_name": self.project_name}
    def engineering_conversations_create(self):
        return {"id": "test-conversation"}
    def engineering_conversation_message_stream(self, conversation_id, message):
        self.requests.append((conversation_id, message))
        self.message = message
        yield {"type": "final", "result": self.result}
        yield {"type": "done"}
    def engineering_conversation_detail(self, conversation_id):
        return {"messages": [{"role": "user", "content": self.message}, {"role": "assistant", "result": self.result}]}


@pytest.mark.parametrize("bad", ["version", "feature", "project"])
def test_failed_preflight_never_sends_model_request(tmp_path, bad):
    client = RecordingClient()
    if bad == "version":
        client.identity = {"schema_version": "product_version_v1", "version": "1.0.0"}
    elif bad == "feature":
        client.feature = False
    else:
        client.project_name = "user-project"
    with pytest.raises(ValueError):
        demo.run_demo(client, "engineering-demo", tmp_path / "result.json")
    assert client.requests == [] and not (tmp_path / "result.json").exists()


def test_refusals_are_recorded_once_without_becoming_correctness_scores(tmp_path):
    client = RecordingClient()
    path = tmp_path / "result.json"
    result = demo.run_demo(client, "engineering-demo", path)
    assert len(client.requests) == 3 and result["runtime_statuses"] == {"refused": 3}
    assert result["benchmark"] is False and result["message_retries"] == 0
    assert all(item["content_review"] == "not_evaluated" for item in result["cases"])
    assert json.loads(path.read_text(encoding="utf-8")) == result
    with pytest.raises(FileExistsError):
        demo.run_demo(client, "engineering-demo", path)
    assert len(client.requests) == 3


def test_stream_failure_stops_without_retry_and_preserves_partial_record(tmp_path):
    class Broken(RecordingClient):
        def engineering_conversation_message_stream(self, conversation_id, message):
            self.requests.append((conversation_id, message))
            raise ApiError("connection_error", "offline")
    client = Broken()
    result = demo.run_demo(client, "engineering-demo", tmp_path / "result.json")
    assert len(client.requests) == 1
    assert result["transport_error"] == {"case_id": "configuration", "type": "ApiError"}
    assert result["cases"] == []


def test_all_three_demo_cases_use_actual_conversation_sse_and_real_tools(project, tmp_path, monkeypatch):
    def read(path):
        return ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": path, "target": {"kind": "file", "start_line": 1}})
    actions = iter([
        read("support_search/settings.py"), read("support_search/service.py"),
        FinalAnswerAction(action="final_answer", answer="默认6，可由环境变量覆盖，范围1..20 [E1]；向retriever传递limit [E2]。"),
        ToolCallAction(action="tool_call", tool_name="git_diff", arguments={"mode": "working_tree", "path": "support_search/settings.py"}),
        ToolCallAction(action="tool_call", tool_name="find_tests", arguments={"path": "support_search/settings.py"}),
        read("tests/test_service.py"),
        FinalAnswerAction(action="final_answer", answer="默认4改为6 [E1]；默认测试断言4，覆盖测试断言9 [E2]。建议 python -m pytest tests/test_service.py，未执行。"),
        read("README.md"), read("support_search/settings.py"),
        FinalAnswerAction(action="final_answer", answer="文档默认4 [E1]，源码默认6 [E2]，存在冲突；范围和环境覆盖一致。"),
    ])
    class Decisions:
        def decide(self, *_args, **_kwargs):
            return AgentDecisionOutcome(action=next(actions), failure_code=None, call_metadata=None)
    runtime = build_tool_agent_runtime(repo_root=project, retrieval_port=EmptyRetrievalPort(), provider=Decisions(),
        prompt_profile=backend.ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE,
        code_search_version=backend.CODE_SEARCH_TEST_VERSION, read_project_context_version=backend.READ_PROJECT_TARGETS_VERSION)
    facade = EngineeringAgentFacade(build_full_unified_runtime(runtime))
    monkeypatch.setattr(backend, "engineering_agent_facade", facade)
    monkeypatch.setattr(backend, "engineering_project", EngineeringProject(project, "engineering-demo", "configured"))
    monkeypatch.setattr(backend, "conversation_store", ConversationStore(tmp_path / "conversations.sqlite3"))
    monkeypatch.setattr(backend, "engineering_knowledge_backend", SimpleNamespace(identity=EngineeringKnowledgeIdentity("870e5864df67", 37, 215, "bm25", "dbc497c796d5", True)))
    http = TestClient(backend.app)
    class HttpClient(RecordingClient):
        def version(self):
            return http.get("/version").json()
        def capabilities(self):
            return http.get("/capabilities").json()
        def engineering_knowledge(self):
            return http.get("/engineering/knowledge").json()
        def project(self):
            return http.get("/project").json()
        def engineering_conversations_create(self):
            response = http.post("/engineering/conversations")
            assert response.status_code == 201
            return response.json()
        def engineering_conversation_message_stream(self, conversation_id, message):
            self.requests.append((conversation_id, message))
            response = http.post(f"/engineering/conversations/{conversation_id}/messages/stream/v1", json={"message": message})
            assert response.status_code == 200
            for line in response.text.splitlines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])
        def engineering_conversation_detail(self, conversation_id):
            return http.get(f"/engineering/conversations/{conversation_id}").json()
    client = HttpClient()
    report = demo.run_demo(client, "engineering-demo", tmp_path / "demo.json")
    assert report["transport_error"] is None and len(client.requests) == 3
    assert report["runtime_statuses"] == {"completed": 3}
    assert {e["kind"] for e in report["cases"][1]["public_result"]["evidence"]} == {"project_change", "project_test"}
    assert all(item["persistence_checked"] for item in report["cases"])
