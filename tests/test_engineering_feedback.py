"""User recovery guidance through real persistence/SSE, with no providers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import api.app as backend
from api.conversation_store import ConversationStore, project_key_for_root
from api.engineering_feedback import engineering_feedback, feedback_content
from api.project_workspace import EngineeringProject
from core.tool_agent.actions import REFUSE_REASON_CODES, AGENT_DECISION_FAILURE_CODES
from core.tool_agent.runtime_models import AGENT_TERMINATION_CODES, ToolAgentRunResult


OUTCOMES = [("refused", code) for code in REFUSE_REASON_CODES + AGENT_TERMINATION_CODES]
OUTCOMES += [("failed", code) for code in AGENT_DECISION_FAILURE_CODES]


@pytest.fixture
def mounted(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    monkeypatch.setattr(backend, "engineering_project", EngineeringProject(root, "project", "configured"))
    monkeypatch.setattr(backend, "conversation_store", store)
    monkeypatch.setattr(backend, "project_registry", None)
    return TestClient(backend.app), store, root


@pytest.mark.parametrize("status,code", OUTCOMES)
def test_every_public_noncompleted_outcome_keeps_its_status_and_helpful_saved_feedback(mounted, monkeypatch, status, code):
    client, store, root = mounted
    result = ToolAgentRunResult(status=status, answer=None,
        reason_code=code if status == "refused" else None,
        failure_code=code if status == "failed" else None,
        iterations_used=1, tool_calls_used=0, tool_errors_used=0, trace=(), evidence=())
    calls = []
    class Facade:
        def run(self, question, **kwargs):
            calls.append(question)
            return result
    monkeypatch.setattr(backend, "engineering_agent_facade", Facade())
    conversation = client.post("/engineering/conversations").json()
    response = client.post(f"/engineering/conversations/{conversation['id']}/messages/stream/v1", json={"message": "请分析项目配置。"})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    assert not {"answer_start", "answer_delta"} & {event["type"] for event in events}
    final = next(event["result"] for event in events if event["type"] == "final")
    assert final["status"] == status and final["answer"] is None
    assert final["reason_code" if status == "refused" else "failure_code"] == code
    feedback = final["feedback"]
    assert feedback["next_steps"] and code not in json.dumps(feedback)
    assert feedback["title"] not in ("本次暂未形成可靠结论", "本次分析未完成")
    assert feedback["action"] is None if code == "UNSAFE_REQUEST" else feedback["action"] in {"revise", "retry"}
    saved = store.get_conversation(project_key_for_root(root), conversation["id"])["messages"][1]
    restored = client.get(f"/engineering/conversations/{conversation['id']}").json()["messages"][1]
    assert saved["content"] == restored["content"] == feedback_content(final)
    assert restored["result"] == final
    assert calls == ["请分析项目配置。"]  # No automatic request-level retry.


def test_old_refusal_history_is_presented_without_rewriting_storage_or_leaking_details(mounted):
    client, store, root = mounted
    conversation = client.post("/engineering/conversations").json()
    result = {"status": "refused", "answer": None, "reason_code": "INSUFFICIENT_INFORMATION",
              "trace": [], "evidence": [], "iterations_used": 1, "tool_calls_used": 0, "tool_errors_used": 0}
    old_content = "Refused: INSUFFICIENT_INFORMATION"
    store.append_turn(project_key_for_root(root), conversation["id"], user_content="配置有什么问题？",
                      assistant_content=old_content, result=result)
    presented = client.get(f"/engineering/conversations/{conversation['id']}").json()["messages"][1]
    assert "还需要一些具体信息" in presented["content"] and "Refused:" not in presented["content"]
    assert presented["result"]["feedback"]["next_steps"]
    stored = store.get_conversation(project_key_for_root(root), conversation["id"])["messages"][1]
    assert stored["content"] == old_content and "feedback" not in stored["result"]


@pytest.mark.parametrize("code", ["SECRET_PATH_AND_KEY", ["invalid"], None])
def test_unknown_codes_have_safe_guidance_without_inventing_a_specific_cause(code):
    feedback = engineering_feedback({"status": "refused", "reason_code": code, "answer": "unverified"})
    assert feedback["title"] == "本次暂未形成可靠结论"
    assert "SECRET" not in json.dumps(feedback)
    assert "unverified" not in feedback_content({"status": "refused", "reason_code": code, "answer": "unverified"})


def test_completed_answer_keeps_content_and_has_no_refusal_feedback():
    result = {"status": "completed", "answer": "A verified answer [E1]"}
    assert engineering_feedback(result) is None
    assert feedback_content(result) == result["answer"]


@pytest.mark.parametrize("status,code,title", [
    ("refused", "INSUFFICIENT_EVIDENCE_TO_FINALIZE", "暂时无法给出可靠结论"),
    ("failed", "ACTION_TIMEOUT", "模型响应超时"),
])
def test_streamlit_uses_the_same_reason_and_next_steps(status, code, title):
    result = {"status": status, "reason_code": code if status == "refused" else None,
              "failure_code": code if status == "failed" else None, "answer": None,
              "evidence": [], "trace": []}
    app = AppTest.from_string("from ui.renderers import render_engineering_result\nrender_engineering_result(" + repr(result) + ")").run()
    assert not app.exception
    banner = app.warning if status == "refused" else app.error
    assert banner[0].value == title
    assert any("建议：" in caption.value for caption in app.caption)


def test_frontend_feedback_and_stream_boundary_without_browser_or_network():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the offline frontend checks")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, "--test", "tests/frontend_feedback.test.mjs", "tests/frontend_stream_v2.test.mjs"], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
