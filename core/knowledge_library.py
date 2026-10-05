"""Persistent, mutable product knowledge with one searchable BM25 index.

The frozen evaluation corpus remains a separate initialization source. Once
initialized, this library owns its documents; deleted seeds are never restored
by a restart. Mutations commit documents, chunks and a new index together.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from core.agent_runtime.adapters import PipelineRetrievalAdapter
from core.chunker.recursive import RecursiveChunker
from core.domain.models import make_chunk_id
from core.loader.base import Document
from core.retriever.bm25_only import BM25OnlyRetriever


LIBRARY_DB_ENV = "ENGINEERING_KNOWLEDGE_DB"
KNOWLEDGE_MODE_ENV = "ENGINEERING_KNOWLEDGE_MODE"
MAX_CONTENT_CHARACTERS = 2_000_000


class KnowledgeDocumentNotFound(LookupError):
    pass


class KnowledgeDocumentConflict(ValueError):
    pass


@dataclass(frozen=True)
class LibraryIdentity:
    corpus_id: str
    file_count: int
    chunk_count: int
    retrieval_strategy: str = "bm25"
    manifest_experiment_id: None = None
    verified: bool = False


class LibraryRetrievalPort:
    """Stable runtime binding; every search uses the latest complete index."""

    supported_strategies = ("bm25",)

    def __init__(self, library: KnowledgeLibrary):
        self._library = library

    def search(self, query: str, strategy: str, top_k: int):
        snapshot = self._library._current_snapshot()
        return snapshot.search(query, strategy, top_k)


class KnowledgeLibrary:
    def __init__(self, path: str | Path, *, seeds: Sequence[Document] = ()):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._chunker = RecursiveChunker(chunk_size=512, chunk_overlap=64)
        self._revision = -1
        self._snapshot = PipelineRetrievalAdapter(BM25OnlyRetriever())
        self._port = LibraryRetrievalPort(self)
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported knowledge library schema version")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS library_state (
                    id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL, content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
                    origin TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id)
                        ON DELETE CASCADE,
                    position INTEGER NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
                PRAGMA user_version = 1;
            """)
        # Only the first initialization may seed the editable library.
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT revision FROM library_state WHERE id = 1").fetchone() is None:
                for document in seeds:
                    name = document.metadata["source_name"]
                    self._write_document(connection, name, [document],
                                         len(document.content.encode("utf-8")), "seed")
                connection.execute("INSERT INTO library_state VALUES (1, 1)")
            self._snapshot = self._build_snapshot(connection)
            self._revision = self._read_revision(connection)

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self._path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection

    @staticmethod
    def _read_revision(connection) -> int:
        return connection.execute("SELECT revision FROM library_state WHERE id = 1").fetchone()[0]

    @staticmethod
    def _build_snapshot(connection) -> PipelineRetrievalAdapter:
        retriever = BM25OnlyRetriever()
        rows = connection.execute("SELECT id, content, metadata FROM chunks ORDER BY document_id, position")
        retriever.build_sparse_index([(row["id"], row["content"], json.loads(row["metadata"])) for row in rows])
        return PipelineRetrievalAdapter(retriever)

    def _current_snapshot(self) -> PipelineRetrievalAdapter:
        with self._lock, self._connection() as connection:
            revision = self._read_revision(connection)
            if revision != self._revision:
                self._snapshot = self._build_snapshot(connection)
                self._revision = revision
            return self._snapshot

    @property
    def retrieval_port(self) -> LibraryRetrievalPort:
        return self._port

    @property
    def revision(self) -> int:
        with self._connection() as connection:
            return self._read_revision(connection)

    @property
    def identity(self) -> LibraryIdentity:
        with self._connection() as connection:
            counts = connection.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM documents").fetchone()
            revision = self._read_revision(connection)
        return LibraryIdentity(f"managed-v1-{revision}", counts[0], counts[1])

    @staticmethod
    def _summary(row) -> dict:
        return {
            "id": row["id"], "name": row["name"],
            "file_type": Path(row["name"]).suffix.lstrip(".").lower(),
            "size_bytes": row["size_bytes"], "chunk_count": row["chunk_count"],
            "origin": row["origin"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "status": "ready",
        }

    def list_documents(self, *, query: str = "", limit: int = 50, offset: int = 0) -> dict:
        pattern = "%" + query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._connection() as connection:
            counts = connection.execute("SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM documents").fetchone()
            total = connection.execute("SELECT COUNT(*) FROM documents WHERE name_key LIKE ? ESCAPE '\\'", (pattern,)).fetchone()[0]
            rows = connection.execute(
                "SELECT id, name, size_bytes, chunk_count, origin, created_at, updated_at FROM documents "
                "WHERE name_key LIKE ? ESCAPE '\\' ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (pattern, limit, offset),
            ).fetchall()
            revision = self._read_revision(connection)
        return {"items": [self._summary(row) for row in rows], "total": total,
                "file_count": counts[0], "chunk_count": counts[1], "revision": revision,
                "limit": limit, "offset": offset, "search_scope": "all_documents"}

    def get_document(self, document_id: str, *, offset: int = 0, limit: int = 20000) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise KnowledgeDocumentNotFound(document_id)
        content = row["content"]
        end = min(offset + limit, len(content))
        return {**self._summary(row), "content": content[offset:end],
                "content_length": len(content), "offset": offset,
                "next_offset": end if end < len(content) else None}

    def _write_document(self, connection, name, documents, size_bytes, origin, document_id=None):
        content = "\n\n".join(document.content for document in documents if document.content.strip())
        if not content.strip():
            raise ValueError("Document has no readable text; encrypted or scanned PDFs are not supported")
        if len(content) > MAX_CONTENT_CHARACTERS:
            raise ValueError("Document text exceeds the 2,000,000 character limit")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if document_id:
            old = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if old is None:
                raise KnowledgeDocumentNotFound(document_id)
        else:
            old = connection.execute("SELECT * FROM documents WHERE name_key = ?", (name.casefold(),)).fetchone()
        if old and old["content_hash"] == content_hash and old["name"] == name:
            return old["id"], "no_change"
        document_id = old["id"] if old else uuid.uuid4().hex
        chunks = self._chunker.chunk([
            Document(document.content, {"source_name": name, "document_id": document_id,
                                       **({"page_num": document.metadata["page_num"]} if "page_num" in document.metadata else {})})
            for document in documents if document.content.strip()
        ])
        if not chunks:
            raise ValueError("Document produced no searchable chunks")
        now = datetime.now(timezone.utc).isoformat()
        try:
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, name_key=excluded.name_key, "
                "content=excluded.content, content_hash=excluded.content_hash, size_bytes=excluded.size_bytes, "
                "chunk_count=excluded.chunk_count, origin=excluded.origin, updated_at=excluded.updated_at",
                (document_id, name, name.casefold(), content, content_hash, size_bytes, len(chunks), origin,
                 old["created_at"] if old else now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise KnowledgeDocumentConflict("Another document already uses this filename") from exc
        connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        for index, chunk in enumerate(chunks):
            chunk_id = make_chunk_id(document_id, index, chunk.content)
            metadata = {**chunk.metadata, "id": chunk_id, "chunk_id": chunk_id, "chunk_index": index,
                        "document_id": document_id, "source_name": name, "content_hash": content_hash}
            connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)",
                               (chunk_id, document_id, index, chunk.content, json.dumps(metadata, ensure_ascii=False)))
        return document_id, "update" if old else "create"

    def upload(self, name: str, documents: Sequence[Document], *, size_bytes: int, document_id=None) -> dict:
        with self._lock:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                document_id, status = self._write_document(connection, name, documents, size_bytes, "upload", document_id)
                if status != "no_change":
                    connection.execute("UPDATE library_state SET revision = revision + 1 WHERE id = 1")
                snapshot = self._build_snapshot(connection)
                revision = self._read_revision(connection)
            # Publish only after the SQLite commit succeeds. Existing readers
            # retain their immutable snapshot; subsequent searches see this one.
            self._snapshot, self._revision = snapshot, revision
            document = self.get_document(document_id)
        document.pop("content")
        document.pop("content_length")
        document.pop("offset")
        document.pop("next_offset")
        return {"document": document, "status": status, "revision": revision}

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
                if not result.rowcount:
                    raise KnowledgeDocumentNotFound(document_id)
                connection.execute("UPDATE library_state SET revision = revision + 1 WHERE id = 1")
                snapshot = self._build_snapshot(connection)
                revision = self._read_revision(connection)
            self._snapshot, self._revision = snapshot, revision


def library_is_initialized(path: str | Path) -> bool:
    if not Path(path).is_file():
        return False
    with closing(sqlite3.connect(path)) as connection:
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_state'").fetchone()
        return bool(table and connection.execute("SELECT 1 FROM library_state WHERE id=1").fetchone())
