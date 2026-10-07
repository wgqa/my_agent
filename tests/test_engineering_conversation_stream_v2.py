"""V2 activity, atomic chat persistence and failure boundaries, with no providers."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

import api.app as backend
from api.conversation_store import ConversationStore
from api.engineering_stream_v2 import stream_engineering_query_v2
from api.project_workspace import EngineeringProject
from core.tool_agent.activity import RunStartedActivity, ToolActivityEvent, EvidenceAddedActivity, VerificationBlockedActivity
from core.tool_agent.runtime_models import EngineeringEvidence, ToolAgentRunResult


def result(status="completed"):
    return ToolAgentRunResult(
        status=status, answer="已读取项目源码 [E1]" if status == "completed" else None,
        reason_code="INSUFFICIENT_EVIDENCE_TO_FINALIZE" if status == "refused" else None,
        failure_code="ACTION_TIMEOUT" if status == "failed" else None,
        iterations_used=2, tool_calls_used=1, tool_errors_used=0, trace=(),
        evidence=(EngineeringEvidence(evidence_id="E1", kind="project_code", path="src/service.py",
                    start_line=1, end_line=2, snippet="def run():\n    return 1"),),
    )


EVENTS = (
    RunStartedActivity(7),
    ToolActivityEvent("A1", 1, "read_project_context", "started", "Read source",
                      target={"path": "src/service.py", "line": 1}),
    EvidenceAddedActivity("E1", "project_code", path="src/service.py", start_line=1, end_line=2),
    ToolActivityEvent("A1", 1, "read_project_context", "completed", "Read source",
                      target={"path": "src/service.py", "line": 1},
                      result_summary={"path": "src/service.py", "start_line": 1, "end_line": 2},
                      evidence_ids_added=("E1",)),
    VerificationBlockedActivity(2, ("project_test",)),
)


class Facade:
    def __init__(self):
        self.calls = []
        self.result = result()
        self.error = None

    def run(self, question, *, conversation_context=None, activity_sink=None, trace_sink=None, cancel_requested=None):
        self.calls.append((question, tuple((m["role"], m["content"]) for m in conversation_context or ())))
        for event in EVENTS:
            if activity_sink:
                activity_sink(event)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def chat(tmp_path, monkeypatch):
    root = tmp_path / "项目"
    root.mkdir()
    facade = Facade()
    store = ConversationStore(tmp_path / "chat.sqlite3")
    monkeypatch.setattr(backend, "engineering_project", EngineeringProject(root=root, project_name="项目", source="configured"))
    monkeypatch.setattr(backend, "engineering_agent_facade", facade)
    monkeypatch.setattr(backend, "conversation_store", store)
    monkeypatch.setattr(backend, "_engineering_run_slots", threading.BoundedSemaphore(2))
    client = TestClient(backend.app)
    created = client.post("/engineering/conversations").json()
    return client, created["id"], facade, store


def send(chat, message="分析 src/service.py", version="v2", **extra):
    client, conversation_id, _, _ = chat
    return client.post(f"/engineering/conversations/{conversation_id}/messages/stream/{version}",
                       json={"message": message, **extra})


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_v2_activity_matches_live_final_saved_and_restarted_chat(chat, monkeypatch):
    client, conversation_id, facade, store = chat
    response = send(chat)
    observed = events(response)
    assert response.headers["x-engineering-stream-schema"] == "engineering_query_stream_v2"
    assert observed[:len(EVENTS)] == [event.to_dict() for event in EVENTS]
    public = next(event["result"] for event in observed if event["type"] == "final")
    assert public["activity"] == observed[:len(EVENTS)]
    assert "".join(e["delta"] for e in observed if e["type"] == "answer_delta") == public["answer"]
    assert observed[-1] == {"type": "done"}
    monkeypatch.setattr(backend, "conversation_store", ConversationStore(store.path))
    detail = client.get(f"/engineering/conversations/{conversation_id}").json()
    assert detail["messages"][1]["result"] == public
    assert send(chat, "接着分析这个函数").status_code == 200
    assert facade.calls[1][1] == (("user", "分析 src/service.py"), ("assistant", public["answer"]))
    assert len(client.get(f"/engineering/conversations/{conversation_id}").json()["messages"]) == 4


@pytest.mark.parametrize("status", ["refused", "failed"])
def test_v2_noncompleted_turn_saves_feedback_and_activity_without_answer(chat, status):
    client, conversation_id, facade, _ = chat
    facade.result = result(status)
    observed = events(send(chat))
    assert not any(e["type"] in {"answer_start", "answer_delta"} for e in observed)
    public = next(e["result"] for e in observed if e["type"] == "final")
    assert public["status"] == status and public["answer"] is None
    saved = client.get(f"/engineering/conversations/{conversation_id}").json()["messages"][1]
    assert saved["result"]["activity"] == public["activity"]
    assert saved["result"]["feedback"]["message"] in saved["content"]
    assert len(facade.calls) == 1


def test_v2_persistence_failure_never_presents_answer_or_partial_turn(chat, monkeypatch):
    client, conversation_id, facade, store = chat
    def fail(*args, **kwargs):
        raise RuntimeError("private persistence details")
    monkeypatch.setattr(store, "append_turn", fail)
    response = send(chat)
    observed = events(response)
    assert observed[-2:] == [{"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"}, {"type": "done"}]
    assert not any(e["type"] in {"answer_start", "answer_delta", "final"} for e in observed)
    assert "private" not in response.text
    assert client.get(f"/engineering/conversations/{conversation_id}").json()["messages"] == []
    assert len(facade.calls) == 1


def test_v2_worker_failure_preserves_generic_error_and_no_saved_turn(chat):
    client, conversation_id, facade, _ = chat
    facade.error = RuntimeError("private provider details")
    response = send(chat)
    assert events(response)[-2:] == [{"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"}, {"type": "done"}]
    assert "private" not in response.text
    assert client.get(f"/engineering/conversations/{conversation_id}").json()["messages"] == []


def test_v2_capacity_and_invalid_requests_do_not_run_or_save(chat, monkeypatch):
    client, conversation_id, facade, _ = chat
    assert send(chat, history=[]).status_code == 422
    assert client.post("/engineering/conversations/missing/messages/stream/v2", json={"message": "question"}).status_code == 404
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(backend, "_engineering_run_slots", slots)
    assert send(chat).status_code == 503
    assert facade.calls == []
    assert client.get(f"/engineering/conversations/{conversation_id}").json()["messages"] == []


def test_v1_compatibility_retains_its_original_event_contract(chat):
    response = send(chat, version="v1")
    observed = events(response)
    assert response.headers["x-engineering-stream-schema"] == "engineering_query_stream_v1"
    assert observed[0] == {"type": "status", "stage": "analysis", "state": "started"}
    assert all(e["type"] not in {"run_started", "activity", "evidence_added", "verification"} for e in observed)
    assert "activity" not in next(e["result"] for e in observed if e["type"] == "final")


def test_v2_disconnect_signals_cancellation_but_worker_owns_cleanup():
    release, finished, cancelled = threading.Event(), threading.Event(), threading.Event()
    cleanup = []
    class BlockingFacade:
        def run(self, _question, *, conversation_context=None, activity_sink=None, cancel_requested=None):
            activity_sink(RunStartedActivity(7))
            assert release.wait(3)
            if cancel_requested():
                cancelled.set()
            return result()
    def done():
        cleanup.append(True)
        finished.set()
    stream = stream_engineering_query_v2(BlockingFacade(), "question", build_response=lambda value: {}, on_worker_done=done)
    try:
        assert "run_started" in next(stream)
        stream.close()
        assert not cleanup
    finally:
        release.set()
    assert finished.wait(3) and cancelled.is_set()
    assert cleanup == [True]
