"""Product-owned local project registration and bounded facade reuse.

Roots stay on the server. Public IDs select registered projects; conversations
still use the existing root-based store key and the unchanged Core runtime.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections import OrderedDict
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from api.conversation_store import default_conversation_db_path, project_key_for_root
from api.project_workspace import EngineeringProject, resolve_engineering_project


PROJECT_DB_ENV = "ENGINEERING_PROJECT_DB"


def default_project_db_path() -> Path:
    configured = os.getenv(PROJECT_DB_ENV)
    return Path(configured) if configured else default_conversation_db_path().parent / "engineering_projects.sqlite3"


def _path_key(root: Path) -> str:
    return os.path.normcase(str(root.resolve()))


@dataclass(frozen=True)
class RegisteredProject:
    id: str
    project: EngineeringProject
    project_key: str

    def public(self, *, default_root: Path) -> dict:
        return {"id": self.id, "project_name": self.project.project_name,
                "source": self.project.source,
                "is_default": _path_key(self.project.root) == _path_key(default_root),
                "available": self.project.root.is_dir()}


class ProjectRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported project registry schema version")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, root TEXT NOT NULL, path_key TEXT UNIQUE NOT NULL,
                    project_key TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def _connection(self):
        # SQLite's transaction context alone does not close the connection.
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    @staticmethod
    def _record(row) -> RegisteredProject:
        return RegisteredProject(row["id"], EngineeringProject(Path(row["root"]), row["name"], row["source"]), row["project_key"])

    def register(self, project: EngineeringProject) -> RegisteredProject:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(path_key) DO NOTHING",
                (uuid4().hex, str(project.root), _path_key(project.root), project_key_for_root(project.root),
                 project.project_name, project.source, datetime.now(timezone.utc).isoformat()),
            )
            row = connection.execute("SELECT * FROM projects WHERE path_key=?", (_path_key(project.root),)).fetchone()
        return self._record(row)

    def add_local(self, path: str) -> RegisteredProject:
        path = path.strip()
        root = Path(path).expanduser()
        if not path or not root.is_absolute():
            raise ValueError("请输入本机项目的完整目录路径。")
        project = resolve_engineering_project(root, configured_root=path)
        return self.register(project)

    def get(self, project_id: str) -> RegisteredProject:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise LookupError("Project not found")
        return self._record(row)

    def find(self, root: Path) -> RegisteredProject | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE path_key=?", (_path_key(root),)).fetchone()
        return self._record(row) if row else None

    def list_projects(self) -> list[RegisteredProject]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC, id").fetchall()
        return [self._record(row) for row in rows]


class ProjectRuntimeCache:
    """Eviction drops the cache reference, never a running request's facade."""

    def __init__(self, factory: Callable, *, max_entries: int = 4):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._factory = factory
        self._max_entries = max_entries
        self._facades = OrderedDict()
        self._lock = threading.RLock()

    def seed(self, project_id: str, facade) -> None:
        with self._lock:
            self._facades[project_id] = facade
            self._facades.move_to_end(project_id)
            while len(self._facades) > self._max_entries:
                self._facades.popitem(last=False)

    def get(self, project: RegisteredProject):
        with self._lock:
            if project.id not in self._facades:
                self.seed(project.id, self._factory(project.project))
            self._facades.move_to_end(project.id)
            return self._facades[project.id]
