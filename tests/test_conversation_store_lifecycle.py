"""Real SQLite resource cleanup and atomic-turn failure regressions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.conversation_store import ConversationStore, ConversationStoreError


class TrackingConnection(sqlite3.Connection):
    close_calls = 0
    fail_initialization = False
    fail_assistant_insert = False

    def close(self):
        self.close_calls += 1
        super().close()

    def executescript(self, sql_script):
        if self.fail_initialization:
            raise sqlite3.OperationalError("injected schema initialization failure")
        return super().executescript(sql_script)

    def execute(self, sql, parameters=()):
        if self.fail_assistant_insert and sql.startswith("INSERT INTO messages"):
            if "'assistant'" in sql:
                raise sqlite3.OperationalError("injected assistant insert failure")
        return super().execute(sql, parameters)


@pytest.fixture
def connection_tracker(monkeypatch):
    real_connect = sqlite3.connect
    tracker = SimpleNamespace(
        connections=[], fail_initialization=False, fail_assistant_insert=False
    )

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs, factory=TrackingConnection)
        conn.fail_initialization = tracker.fail_initialization
        conn.fail_assistant_insert = tracker.fail_assistant_insert
        tracker.connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    yield tracker
    # Also release handles if an assertion exposes a regression.
    for conn in tracker.connections:
        if not conn.close_calls:
            conn.close()


def _create(store):
    return store.create_conversation(
        project_key="project-a", project_name="a", project_source="default_repo"
    )


def _append(store, conversation_id, *, project_key="project-a"):
    store.append_turn(
        project_key,
        conversation_id,
        user_content="First question",
        assistant_content="Answer",
        result={"status": "completed", "answer": "Answer"},
    )


def _assert_closed(tracker):
    assert tracker.connections
    for conn in tracker.connections:
        assert conn.close_calls == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            conn.execute("SELECT 1")


@pytest.mark.parametrize("operation", ["create", "list", "get", "delete", "history", "append"])
def test_successful_store_operations_close_connections(
    tmp_path: Path, connection_tracker, operation
):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    created = _create(store)
    operations = {
        "create": lambda: _create(store),
        "list": lambda: store.list_conversations("project-a"),
        "get": lambda: store.get_conversation("project-a", created["id"]),
        "delete": lambda: store.delete_conversation("project-a", created["id"]),
        "history": lambda: store.load_history("project-a", created["id"]),
        "append": lambda: _append(store, created["id"]),
    }
    operations[operation]()
    _assert_closed(connection_tracker)


@pytest.mark.parametrize("operation", ["get", "delete", "history"])
def test_missing_conversation_closes_connection(tmp_path: Path, connection_tracker, operation):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    operations = {
        "get": store.get_conversation,
        "delete": store.delete_conversation,
        "history": store.load_history,
    }
    assert not operations[operation]("project-a", "missing")
    _assert_closed(connection_tracker)


def test_business_failure_closes_connection(tmp_path: Path, connection_tracker):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    created = _create(store)
    with pytest.raises(ConversationStoreError, match="does not exist for this project"):
        _append(store, created["id"], project_key="project-b")
    _assert_closed(connection_tracker)


def test_second_message_failure_rolls_back_whole_turn_and_closes(
    tmp_path: Path, connection_tracker
):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    created = _create(store)
    connection_tracker.fail_assistant_insert = True
    with pytest.raises(sqlite3.OperationalError, match="assistant insert failure"):
        _append(store, created["id"])
    _assert_closed(connection_tracker)

    connection_tracker.fail_assistant_insert = False
    restarted = ConversationStore(store.path)
    assert restarted.get_conversation("project-a", created["id"]) == created
    _assert_closed(connection_tracker)


def test_initialization_failure_closes_connection(tmp_path: Path, connection_tracker):
    connection_tracker.fail_initialization = True
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    with pytest.raises(sqlite3.OperationalError, match="schema initialization failure"):
        store.list_conversations("project-a")
    _assert_closed(connection_tracker)


def test_unsupported_schema_closes_connection(tmp_path: Path, connection_tracker):
    db_path = tmp_path / "conversations.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(ConversationStoreError, match="version 99 is not supported"):
        ConversationStore(db_path).list_conversations("project-a")
    _assert_closed(connection_tracker)
