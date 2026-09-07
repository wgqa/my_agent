"""PRODUCT-CONVERSATION-20 provider-free vertical slice tests.

Covers the server-owned Engineering conversation path end to end without any
provider: SQLite conversation store (schema, project isolation, atomic turns,
restart recovery), the new conversation API (create/list/get/delete/message
stream), the frozen question-only contract, bounded context through the real
EngineeringContextResolver / RecentContextWindow, conversation and project
isolation, and the persistence-failure stream boundary.

The Core Agent is exercised through the real UnifiedEngineeringRuntime
assembly with scripted decisions; no DeepSeek call is possible.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import api.app
from api.conversation_store import ConversationStore, project_key_for_root
from api.project_workspace import EngineeringProject
from core.engineering_context import EngineeringContextResolver
from core.conversation_context import ConversationQueryResolution
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    build_tool_agent_runtime,
)
from core.agent_runtime.runtime import RetrievalPort
from tests._engineering_runtime_support import (
    NoRetrievalPlanner,
    build_full_unified_runtime,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
client = TestClient(api.app.app)


# ---------------------------------------------------------------------------
# deterministic fakes (no provider)
# ---------------------------------------------------------------------------


class ScriptedProvider:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def decide(self, registry, user_query, *, context=()):
        item = self.decisions[min(self.calls, len(self.decisions) - 1)]
        self.calls += 1
        if callable(item):
            return item(registry, user_query, context)
        return item


class FakeRetrievalPort(RetrievalPort):
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


class RecordingQueryResolver:
    """Deterministic fake ConversationQueryResolver; never calls a provider."""

    def __init__(self):
        self.calls = []

    def resolve(self, selected_messages, user_input):
        self.calls.append(
            (tuple((m.role, m.content) for m in selected_messages), user_input)
        )
        return ConversationQueryResolution(f"standalone: {user_input}", True, False)


class RecordingContextResolver(EngineeringContextResolver):
    """Record trusted context snapshots for bounded-context assertions."""

    def __init__(self, query_resolver=None):
        super().__init__(query_resolver)
        self.snapshots = []

    def resolve(self, user_input, conversation_context):
        snapshot = super().resolve(user_input, conversation_context)
        self.snapshots.append(snapshot)
        return snapshot


def _final(answer: str):
    return AgentDecisionOutcome(
        action=FinalAnswerAction(action="final_answer", answer=answer),
        failure_code=None,
        call_metadata=None,
    )


def _refuse():
    return AgentDecisionOutcome(
        action=RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION"),
        failure_code=None,
        call_metadata=None,
    )


def _build_facade(decisions, *, query_resolver=None):
    context_resolver = RecordingContextResolver(query_resolver)
    tool_runtime = build_tool_agent_runtime(
        repo_root=REPO_ROOT,
        retrieval_port=FakeRetrievalPort(),
        provider=ScriptedProvider(decisions),
    )
    runtime = build_full_unified_runtime(
        tool_runtime,
        context_resolver=context_resolver,
        planner=NoRetrievalPlanner(),
        retrieval_port=FakeRetrievalPort(),
    )
    return EngineeringAgentFacade(runtime), context_resolver


def _install(monkeypatch, tmp_path: Path, facade, *, project_root="project-a"):
    monkeypatch.setattr(api.app, "engineering_agent_facade", facade)
    monkeypatch.setattr(
        api.app,
        "engineering_project",
        EngineeringProject(
            root=tmp_path / project_root,
            project_name=project_root,
            source="default_repo",
        ),
    )
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    monkeypatch.setattr(api.app, "conversation_store", store)
    return store


def _events(response) -> list[dict]:
    parsed = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            parsed.append(json.loads(line[6:]))
    return parsed


def _event_types(response) -> list[str]:
    return [event.get("type") for event in _events(response)]


# ---------------------------------------------------------------------------
# store level
# ---------------------------------------------------------------------------


def test_store_roundtrip_and_restart_recovery(tmp_path: Path):
    db_path = tmp_path / "conversations.sqlite3"
    store_a = ConversationStore(db_path)
    created = store_a.create_conversation(
        project_key=project_key_for_root(tmp_path / "a"),
        project_name="proj-a",
        project_source="default_repo",
    )
    long_question = "Where is the verifier implemented " + "and " * 30 + "used?"
    store_a.append_turn(
        project_key_for_root(tmp_path / "a"),
        created["id"],
        user_content=long_question,
        assistant_content="Refused: INSUFFICIENT_EVIDENCE_TO_FINALIZE",
        result={"status": "refused", "answer": None},
    )

    # A brand-new store instance on the same DB recovers everything.
    store_b = ConversationStore(db_path)
    detail = store_b.get_conversation(project_key_for_root(tmp_path / "a"), created["id"])
    assert detail is not None
    assert detail["title"].startswith("Where is the verifier implemented")
    assert detail["title"].endswith("…")
    assert len(detail["title"]) <= 36
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == long_question
    assert detail["messages"][1]["result"] == {"status": "refused", "answer": None}
    assert store_b.list_conversations(project_key_for_root(tmp_path / "a")) != []


def test_store_title_uses_first_user_message_only(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    key = project_key_for_root(tmp_path / "a")
    created = store.create_conversation(
        project_key=key, project_name="proj-a", project_source="default_repo"
    )
    store.append_turn(
        key,
        created["id"],
        user_content="First question about planning",
        assistant_content="answer",
        result={"status": "completed", "answer": "answer"},
    )
    store.append_turn(
        key,
        created["id"],
        user_content="Second follow-up question",
        assistant_content="answer two",
        result={"status": "completed", "answer": "answer two"},
    )
    detail = store.get_conversation(key, created["id"])
    assert detail["title"] == "First question about planning"
    assert len(detail["messages"]) == 4


def test_store_project_isolation(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    key_a = project_key_for_root(tmp_path / "a")
    key_b = project_key_for_root(tmp_path / "b")
    created = store.create_conversation(
        project_key=key_a, project_name="proj-a", project_source="default_repo"
    )
    assert store.list_conversations(key_b) == []
    assert store.get_conversation(key_b, created["id"]) is None
    assert store.delete_conversation(key_b, created["id"]) is False
    assert store.load_history(key_b, created["id"]) is None
    assert store.delete_conversation(key_a, created["id"]) is True


def test_store_history_is_role_content_only(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    key = project_key_for_root(tmp_path / "a")
    created = store.create_conversation(
        project_key=key, project_name="proj-a", project_source="default_repo"
    )
    store.append_turn(
        key,
        created["id"],
        user_content="question",
        assistant_content="answer",
        result={"status": "completed", "answer": "answer", "trace": [{"safe": True}]},
    )
    history = store.load_history(key, created["id"])
    assert history == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


# ---------------------------------------------------------------------------
# API level
# ---------------------------------------------------------------------------


def test_conversation_api_crud_and_public_shape(monkeypatch, tmp_path: Path):
    store = _install(monkeypatch, tmp_path, _build_facade([_final("ok")])[0])

    created = client.post("/engineering/conversations")
    assert created.status_code == 201
    body = created.json()
    assert body["schema_version"] == "engineering_conversation_v1"
    assert body["title"] == "New conversation"
    assert body["project_name"] == "project-a"
    assert body["project_source"] == "default_repo"
    # Internal binding identity and local paths never leak.
    assert "project_key" not in body
    assert str(tmp_path) not in created.text

    listing = client.get("/engineering/conversations")
    assert listing.status_code == 200
    assert listing.json()["schema_version"] == "engineering_conversation_list_v1"
    assert [c["id"] for c in listing.json()["conversations"]] == [body["id"]]

    detail = client.get(f"/engineering/conversations/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    deleted = client.delete(f"/engineering/conversations/{body['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/engineering/conversations/{body['id']}").status_code == 404
    assert client.delete(f"/engineering/conversations/{body['id']}").status_code == 404
    assert store.list_conversations(project_key_for_root(tmp_path / "project-a")) == []


def test_conversation_api_isolated_by_project(monkeypatch, tmp_path: Path):
    store = _install(monkeypatch, tmp_path, _build_facade([_final("ok")])[0])
    created = client.post("/engineering/conversations").json()

    monkeypatch.setattr(
        api.app,
        "engineering_project",
        EngineeringProject(
            root=tmp_path / "project-b",
            project_name="project-b",
            source="configured",
        ),
    )
    assert client.get("/engineering/conversations").json()["conversations"] == []
    assert (
        client.get(f"/engineering/conversations/{created['id']}").status_code == 404
    )
    assert (
        client.delete(f"/engineering/conversations/{created['id']}").status_code == 404
    )
    message = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "follow-up"},
    )
    assert message.status_code == 404
    assert created["id"] not in message.text
    # The original project's data is untouched.
    monkeypatch.setattr(
        api.app,
        "engineering_project",
        EngineeringProject(
            root=tmp_path / "project-a",
            project_name="project-a",
            source="default_repo",
        ),
    )
    assert client.get(f"/engineering/conversations/{created['id']}").status_code == 200
    assert store is not None


def test_old_engineering_query_contract_unchanged(monkeypatch, tmp_path: Path):
    _install(monkeypatch, tmp_path, _build_facade([_final("ok")])[0])
    rejected = client.post(
        "/engineering/query",
        json={"question": "Where is the planner?", "history": [{"role": "user", "content": "hi"}]},
    )
    assert rejected.status_code == 422


def test_message_stream_persists_completed_turn(monkeypatch, tmp_path: Path):
    facade, context_resolver = _build_facade(
        [_final("planner answer"), _final("consumer answer")],
        query_resolver=RecordingQueryResolver(),
    )
    store = _install(monkeypatch, tmp_path, facade)
    created = client.post("/engineering/conversations").json()

    streamed = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "Where is the planner implemented?"},
    )
    assert streamed.status_code == 200
    types = _event_types(streamed)
    assert "final" in types and types[-1] == "done"
    final = next(e for e in _events(streamed) if e["type"] == "final")["result"]
    assert final["status"] == "completed"
    assert final["answer"] == "planner answer"

    detail = client.get(f"/engineering/conversations/{created['id']}").json()
    assert detail["title"] == "Where is the planner implemented?"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["result"] is None
    assert detail["messages"][1]["result"] == final
    assert detail["messages"][1]["content"] == "planner answer"

    # A second turn appends; the store history feeds the next request.
    streamed_two = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "Who consumes its plan?"},
    )
    assert "final" in _event_types(streamed_two)
    detail = client.get(f"/engineering/conversations/{created['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]


def test_message_stream_refused_turn_persists_display_text(monkeypatch, tmp_path: Path):
    _install(
        monkeypatch,
        tmp_path,
        _build_facade([_refuse()], query_resolver=RecordingQueryResolver())[0],
    )
    created = client.post("/engineering/conversations").json()
    streamed = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "What does this repo not implement?"},
    )
    final = next(e for e in _events(streamed) if e["type"] == "final")["result"]
    assert final["status"] == "refused"
    assert final["answer"] is None
    detail = client.get(f"/engineering/conversations/{created['id']}").json()
    assistant = detail["messages"][1]
    assert assistant["content"] == "Refused: INSUFFICIENT_INFORMATION"
    assert assistant["result"]["status"] == "refused"


def test_message_stream_rejects_client_control_fields(monkeypatch, tmp_path: Path):
    _install(monkeypatch, tmp_path, _build_facade([_final("ok")])[0])
    created = client.post("/engineering/conversations").json()
    rejected = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "hi", "history": [{"role": "user", "content": "seed"}]},
    )
    assert rejected.status_code == 422


def test_persistence_failure_fails_stream_before_final(monkeypatch, tmp_path: Path):
    real_store = _install(monkeypatch, tmp_path, _build_facade([_final("ok")])[0])
    created = client.post("/engineering/conversations").json()

    class FailingStore:
        def __getattr__(self, name):
            return getattr(real_store, name)

        def append_turn(self, *args, **kwargs):
            raise RuntimeError("sqlite unavailable")

    monkeypatch.setattr(api.app, "conversation_store", FailingStore())
    streamed = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "Where is the planner implemented?"},
    )
    types = _event_types(streamed)
    assert types[-1] == "done"
    assert "error" in types
    for forbidden in ("evidence", "answer_start", "answer_delta", "final"):
        assert forbidden not in types
    # No half-turn was persisted.
    assert client.get(f"/engineering/conversations/{created['id']}").json()["messages"] == []


def test_restart_persistence_across_store_instances(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "conversations.sqlite3"
    store_a = ConversationStore(db_path)
    key = project_key_for_root(tmp_path / "project-a")
    created = store_a.create_conversation(
        project_key=key, project_name="project-a", project_source="default_repo"
    )
    store_a.append_turn(
        key,
        created["id"],
        user_content="Where is the planner implemented?",
        assistant_content="planner answer",
        result={"status": "completed", "answer": "planner answer"},
    )

    # Fresh store instance + fresh API retrieval after "restart".
    _install(monkeypatch, tmp_path, _build_facade([_final("unused")])[0])
    detail = client.get(f"/engineering/conversations/{created['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["result"]["answer"] == "planner answer"


# ---------------------------------------------------------------------------
# bounded context through the real resolver
# ---------------------------------------------------------------------------


def test_context_follow_up_reaches_existing_resolver(monkeypatch, tmp_path: Path):
    query_resolver = RecordingQueryResolver()
    facade, context_resolver = _build_facade(
        [_final("planner location"), _final("consumer answer")],
        query_resolver=query_resolver,
    )
    _install(monkeypatch, tmp_path, facade)
    created = client.post("/engineering/conversations").json()

    first = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "Where is EngineeringEvidenceVerifier implemented?"},
    )
    assert "final" in _event_types(first)
    second = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "Where is it used before finalization?"},
    )
    assert "final" in _event_types(second)

    snapshot = context_resolver.snapshots[-1]
    # Stored history reached the existing bounded context component.
    assert snapshot.received_count == 2
    assert snapshot.used_count >= 1
    assert len(snapshot.selected_messages) == snapshot.used_count
    selected = tuple((m.role, m.content) for m in snapshot.selected_messages)
    assert ("user", "Where is EngineeringEvidenceVerifier implemented?") in selected
    # The deterministic fake resolver received the previous turn.
    previous_call_messages, previous_call_input = query_resolver.calls[-1]
    assert previous_call_input == "Where is it used before finalization?"
    assert ("user", "Where is EngineeringEvidenceVerifier implemented?") in previous_call_messages
    assert snapshot.resolved_input == "standalone: Where is it used before finalization?"


def test_bounded_history_respects_existing_window(monkeypatch, tmp_path: Path):
    query_resolver = RecordingQueryResolver()
    facade, context_resolver = _build_facade(
        [_final("ok")] * 9, query_resolver=query_resolver
    )
    store = _install(monkeypatch, tmp_path, facade)
    created = client.post("/engineering/conversations").json()
    key = project_key_for_root(tmp_path / "project-a")
    for index in range(7):
        store.append_turn(
            key,
            created["id"],
            user_content=f"history question {index}",
            assistant_content=f"history answer {index}",
            result={"status": "completed", "answer": f"history answer {index}"},
        )

    streamed = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "fresh question"},
    )
    assert "final" in _event_types(streamed)

    snapshot = context_resolver.snapshots[-1]
    assert snapshot.received_count == 14
    assert snapshot.used_count <= 6
    assert snapshot.used_tokens <= 1200


def test_conversation_isolation(monkeypatch, tmp_path: Path):
    facade, context_resolver = _build_facade(
        [_final("a"), _final("b"), _final("c")],
        query_resolver=RecordingQueryResolver(),
    )
    _install(monkeypatch, tmp_path, facade)
    conversation_a = client.post("/engineering/conversations").json()
    conversation_b = client.post("/engineering/conversations").json()

    client.post(
        f"/engineering/conversations/{conversation_a['id']}/messages/stream/v1",
        json={"message": "Where is the Planner implemented?"},
    )
    client.post(
        f"/engineering/conversations/{conversation_b['id']}/messages/stream/v1",
        json={"message": "Where is the Verifier implemented?"},
    )
    client.post(
        f"/engineering/conversations/{conversation_b['id']}/messages/stream/v1",
        json={"message": "follow-up for B only"},
    )

    last_snapshot = context_resolver.snapshots[-1]
    selected = tuple((m.role, m.content) for m in last_snapshot.selected_messages)
    assert ("user", "Where is the Verifier implemented?") in selected
    assert all("Where is the Planner implemented?" not in content for _, content in selected)


def test_message_stream_does_not_run_runtime_for_wrong_project(
    monkeypatch, tmp_path: Path
):
    class ExplodingFacade:
        def run(self, *args, **kwargs):
            raise AssertionError("runtime must not run for a foreign conversation")

    store = _install(monkeypatch, tmp_path, ExplodingFacade())
    created = client.post("/engineering/conversations").json()
    monkeypatch.setattr(
        api.app,
        "engineering_project",
        EngineeringProject(
            root=tmp_path / "project-b",
            project_name="project-b",
            source="configured",
        ),
    )
    response = client.post(
        f"/engineering/conversations/{created['id']}/messages/stream/v1",
        json={"message": "follow-up"},
    )
    assert response.status_code == 404
