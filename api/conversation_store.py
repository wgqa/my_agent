"""Server-owned SQLite conversation store for the Engineering product path.

Persistence lives at the API/product layer so the Core Agent stays frozen:
the store only saves what happened, while the existing
``EngineeringContextResolver`` / ``RecentContextWindow`` (6 messages / 1200
tokens) remains the sole owner of which history enters the Runtime.

Stored messages and assistant results are conversation context, never
grounding evidence: the next turn still acquires fresh evidence from the
Knowledge / Code / Docs / Git / Test backends.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

CONVERSATION_DB_ENV = "ENGINEERING_CONVERSATION_DB"
SCHEMA_VERSION = 1
DEFAULT_CONVERSATION_TITLE = "New conversation"
MAX_TITLE_CHARS = 36
_ROLES = frozenset({"user", "assistant"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    project_key TEXT NOT NULL,
    project_name TEXT NOT NULL,
    project_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL
        REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id);
"""


class ConversationStoreError(RuntimeError):
    """Raised when the conversation store cannot be opened or is stale."""


def default_conversation_db_path() -> Path:
    """Resolve the runtime DB path without leaking it through the public API."""

    configured = os.getenv(CONVERSATION_DB_ENV)
    if configured:
        return Path(configured)
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data" / "runtime" / "engineering_conversations.sqlite3"


def project_key_for_root(root: Path | str) -> str:
    """Internal server binding identity for one Engineering Project root.

    This key is never returned to clients; the public contract only exposes
    ``project_name`` / ``project_source``.
    """

    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


def conversation_title_from_message(message: str) -> str:
    """Deterministic short title from the first user message; no LLM call."""

    compact = " ".join(str(message).split())
    if not compact:
        return DEFAULT_CONVERSATION_TITLE
    if len(compact) <= MAX_TITLE_CHARS:
        return compact
    return compact[: MAX_TITLE_CHARS - 1].rstrip() + "…"


class ConversationStore:
    """Connection-per-operation SQLite store; no shared cross-thread connection."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else default_conversation_db_path()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        parent = self._path.parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version and version != SCHEMA_VERSION:
            connection.close()
            raise ConversationStoreError(
                f"conversation DB schema version {version} is not supported"
            )
        if version == 0:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return connection

    # ── conversations ────────────────────────────────────
    def create_conversation(
        self, *, project_key: str, project_name: str, project_source: str
    ) -> dict[str, Any]:
        now = _utc_now()
        conversation_id = _new_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations "
                "(id, title, project_key, project_name, project_source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    DEFAULT_CONVERSATION_TITLE,
                    project_key,
                    project_name,
                    project_source,
                    now,
                    now,
                ),
            )
        return self.get_conversation(project_key, conversation_id) or {}

    def list_conversations(self, project_key: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, project_name, project_source, created_at, updated_at "
                "FROM conversations WHERE project_key = ? ORDER BY updated_at DESC, rowid DESC",
                (project_key,),
            ).fetchall()
        return [self._summary_row(row) for row in rows]

    def get_conversation(
        self, project_key: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, project_name, project_source, created_at, updated_at "
                "FROM conversations WHERE project_key = ? AND id = ?",
                (project_key, conversation_id),
            ).fetchone()
            if row is None:
                return None
            message_rows = conn.execute(
                "SELECT id, role, content, result_json, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
        detail = self._summary_row(row)
        detail["messages"] = [
            {
                "id": message_id,
                "role": role,
                "content": content,
                "created_at": created_at,
                "result": json.loads(result_json) if result_json else None,
            }
            for message_id, role, content, result_json, created_at in message_rows
        ]
        return detail

    def delete_conversation(self, project_key: str, conversation_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversations WHERE project_key = ? AND id = ?",
                (project_key, conversation_id),
            )
        return cursor.rowcount > 0

    # ── messages ─────────────────────────────────────────
    def load_history(
        self, project_key: str, conversation_id: str
    ) -> list[dict[str, str]] | None:
        """Return role/content history only; ``None`` when not found for this project.

        ``result_json`` / evidence / trace intentionally never become context.
        """

        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE project_key = ? AND id = ?",
                (project_key, conversation_id),
            ).fetchone()
            if row is None:
                return None
            rows = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def append_turn(
        self,
        project_key: str,
        conversation_id: str,
        *,
        user_content: str,
        assistant_content: str,
        result: Mapping[str, Any],
    ) -> None:
        """Persist one completed turn atomically (user + assistant + metadata).

        The caller only invokes this after the Runtime produced a legal public
        terminal result, so no half-turn can ever be committed.
        """

        result_json = json.dumps(dict(result), ensure_ascii=False)
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title FROM conversations WHERE project_key = ? AND id = ?",
                (project_key, conversation_id),
            ).fetchone()
            if row is None:
                raise ConversationStoreError(
                    "conversation does not exist for this project"
                )
            has_messages = conn.execute(
                "SELECT 1 FROM messages WHERE conversation_id = ? LIMIT 1",
                (conversation_id,),
            ).fetchone() is not None
            title = row[0]
            if not has_messages:
                title = conversation_title_from_message(user_content)
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, result_json, created_at) "
                "VALUES (?, ?, 'user', ?, NULL, ?)",
                (_new_id(), conversation_id, user_content, now),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, result_json, created_at) "
                "VALUES (?, ?, 'assistant', ?, ?, ?)",
                (_new_id(), conversation_id, assistant_content, result_json, now),
            )
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? "
                "WHERE project_key = ? AND id = ?",
                (title, now, project_key, conversation_id),
            )

    # ── helpers ──────────────────────────────────────────
    @staticmethod
    def _summary_row(row: tuple) -> dict[str, Any]:
        (
            conversation_id,
            title,
            project_name,
            project_source,
            created_at,
            updated_at,
        ) = row
        return {
            "schema_version": "engineering_conversation_v1",
            "id": conversation_id,
            "title": title,
            "project_name": project_name,
            "project_source": project_source,
            "created_at": created_at,
            "updated_at": updated_at,
        }


__all__ = [
    "CONVERSATION_DB_ENV",
    "ConversationStore",
    "ConversationStoreError",
    "SCHEMA_VERSION",
    "conversation_title_from_message",
    "default_conversation_db_path",
    "project_key_for_root",
]
