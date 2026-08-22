"""Verified, read-only Knowledge backend for the Engineering Agent.

The Engineering Agent deliberately does not reuse the legacy Pipeline's
default vector store. This backend verifies the frozen corpus manifest,
recreates the frozen Recursive + BM25 chunks, and exposes the existing
PipelineRetrievalAdapter contract.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from core.agent_runtime.adapters import PipelineRetrievalAdapter
from core.domain.models import make_chunk_id, make_document_id
from core.loader.base import Document
from core.retriever.bm25_only import BM25OnlyRetriever
from core.chunker.recursive import RecursiveChunker


CORPUS_ENV_VAR = "ENGINEERING_KNOWLEDGE_CORPUS_ROOT"
AUTHORITY_MANIFEST_RELATIVE_PATH = Path(
    "experiments",
    "dbc497c796d5",
    "agent-ai-v1-recursive-bm25-baseline-001",
    "index_manifest.json",
)
EXPECTED_CORPUS_ID = "870e5864df67"
EXPECTED_EXPERIMENT_ID = "dbc497c796d5"
EXPECTED_FILE_COUNT = 37
EXPECTED_CHUNK_COUNT = 215
EXPECTED_STRATEGY = "bm25"
EXPECTED_CHUNK_STRATEGY = "recursive"
EXPECTED_CHUNK_POLICY = "cl100k_content_v1"
EXPECTED_CHUNK_SIZE = 512
EXPECTED_CHUNK_OVERLAP = 64
EXPECTED_TOP_K = 5


class EngineeringKnowledgeError(ValueError):
    """The configured Engineering Knowledge corpus is not verified."""


@dataclass(frozen=True)
class EngineeringKnowledgeIdentity:
    corpus_id: str
    file_count: int
    chunk_count: int
    retrieval_strategy: str
    manifest_experiment_id: str
    verified: bool

    def to_dict(self) -> dict:
        return {
            "corpus_id": self.corpus_id,
            "file_count": self.file_count,
            "chunk_count": self.chunk_count,
            "retrieval_strategy": self.retrieval_strategy,
            "manifest_experiment_id": self.manifest_experiment_id,
            "verified": self.verified,
        }


def _safe_relative_path(value: object) -> str:
    if type(value) is not str or not value or any(ord(c) < 32 for c in value):
        raise EngineeringKnowledgeError("manifest relative_path is invalid")
    if "\\" in value:
        raise EngineeringKnowledgeError("manifest relative_path must use / separators")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or value.startswith("/")
        or any(part in ("", ".", "..") for part in posix.parts)
    ):
        raise EngineeringKnowledgeError("manifest relative_path is unsafe")
    return posix.as_posix()


def _contained_file(root: Path, relative_path: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise EngineeringKnowledgeError("corpus file is missing or outside corpus root") from exc
    if not resolved.is_file():
        raise EngineeringKnowledgeError("corpus entry is not a regular file")
    return resolved


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _manifest_entries(manifest: dict) -> tuple[list[dict], dict[str, dict]]:
    corpus_entries = manifest.get("corpus_entries")
    files = manifest.get("files")
    if not isinstance(corpus_entries, list) or not isinstance(files, list):
        raise EngineeringKnowledgeError("authority manifest entries are invalid")
    if len(corpus_entries) != EXPECTED_FILE_COUNT or len(files) != EXPECTED_FILE_COUNT:
        raise EngineeringKnowledgeError("authority manifest file count is invalid")
    normalized_entries = []
    for entry in corpus_entries:
        if not isinstance(entry, dict):
            raise EngineeringKnowledgeError("authority manifest corpus entry is invalid")
        relative_path = _safe_relative_path(entry.get("relative_path"))
        sha256 = entry.get("sha256")
        size_bytes = entry.get("size_bytes")
        if (
            type(sha256) is not str
            or len(sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in sha256)
            or type(size_bytes) is not int
            or size_bytes < 0
        ):
            raise EngineeringKnowledgeError("authority manifest file identity is invalid")
        normalized_entries.append(
            {"relative_path": relative_path, "sha256": sha256.lower(), "size_bytes": size_bytes}
        )
    expected_by_path = {}
    for entry in normalized_entries:
        if entry["relative_path"] in expected_by_path:
            raise EngineeringKnowledgeError("authority manifest has duplicate paths")
        expected_by_path[entry["relative_path"]] = entry
    chunks_by_path = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise EngineeringKnowledgeError("authority manifest chunk entry is invalid")
        relative_path = _safe_relative_path(entry.get("relative_path"))
        chunks = entry.get("chunks")
        if type(chunks) is not int or chunks < 1 or relative_path in chunks_by_path:
            raise EngineeringKnowledgeError("authority manifest chunk identity is invalid")
        chunks_by_path[relative_path] = {"chunks": chunks}
    if set(expected_by_path) != set(chunks_by_path):
        raise EngineeringKnowledgeError("authority manifest file identities disagree")
    return normalized_entries, chunks_by_path


class VerifiedEngineeringKnowledge:
    """Frozen corpus validator and read-only BM25 RetrievalPort owner."""

    def __init__(self, corpus_root: str | os.PathLike, *, authority_manifest: str | os.PathLike):
        root = Path(corpus_root)
        if not root.exists() or not root.is_dir():
            raise EngineeringKnowledgeError("Engineering Knowledge corpus root is unavailable")
        self._root = root.resolve()
        manifest_path = Path(authority_manifest)
        if not manifest_path.exists() or not manifest_path.is_file():
            raise EngineeringKnowledgeError("Engineering Knowledge authority manifest is unavailable")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EngineeringKnowledgeError("Engineering Knowledge authority manifest is unreadable") from exc
        if not isinstance(manifest, dict):
            raise EngineeringKnowledgeError("Engineering Knowledge authority manifest is invalid")
        self._validate_manifest_identity(manifest)
        entries, chunks_by_path = _manifest_entries(manifest)
        self._validate_files(entries, chunks_by_path)
        documents = self._chunk_documents(entries, chunks_by_path)
        if len(documents) != EXPECTED_CHUNK_COUNT:
            raise EngineeringKnowledgeError("Engineering Knowledge chunk count is invalid")
        retriever = BM25OnlyRetriever()
        retriever.build_sparse_index(
            [
                (chunk.metadata["id"], chunk.content, chunk.metadata)
                for chunk in documents
            ]
        )
        if retriever._bm25.doc_count != EXPECTED_CHUNK_COUNT:
            raise EngineeringKnowledgeError("Engineering Knowledge BM25 index is invalid")
        self._retriever = retriever
        self._port = PipelineRetrievalAdapter(retriever)
        self._identity = EngineeringKnowledgeIdentity(
            corpus_id=EXPECTED_CORPUS_ID,
            file_count=EXPECTED_FILE_COUNT,
            chunk_count=EXPECTED_CHUNK_COUNT,
            retrieval_strategy=EXPECTED_STRATEGY,
            manifest_experiment_id=EXPECTED_EXPERIMENT_ID,
            verified=True,
        )
        self._source_names = tuple(entry["relative_path"] for entry in entries)

    @classmethod
    def from_repo(
        cls,
        corpus_root: str | os.PathLike | None,
        *,
        repo_root: str | os.PathLike,
    ) -> "VerifiedEngineeringKnowledge":
        if corpus_root is None:
            raise EngineeringKnowledgeError(f"{CORPUS_ENV_VAR} is required")
        if isinstance(corpus_root, os.PathLike):
            corpus_root = os.fspath(corpus_root)
        if type(corpus_root) is not str or not corpus_root.strip():
            raise EngineeringKnowledgeError(f"{CORPUS_ENV_VAR} is required")
        return cls(
            corpus_root,
            authority_manifest=Path(repo_root) / AUTHORITY_MANIFEST_RELATIVE_PATH,
        )

    @staticmethod
    def _validate_manifest_identity(manifest: dict) -> None:
        config = manifest.get("config")
        if (
            manifest.get("corpus_id") != EXPECTED_CORPUS_ID
            or manifest.get("experiment_id") != EXPECTED_EXPERIMENT_ID
            or manifest.get("file_count") != EXPECTED_FILE_COUNT
            or manifest.get("total_chunks") != EXPECTED_CHUNK_COUNT
            or not isinstance(config, dict)
            or config.get("retriever_strategy") != EXPECTED_STRATEGY
            or config.get("chunk_strategy") != EXPECTED_CHUNK_STRATEGY
            or config.get("chunk_budget_policy", EXPECTED_CHUNK_POLICY)
            != EXPECTED_CHUNK_POLICY
            or config.get("chunk_size") != EXPECTED_CHUNK_SIZE
            or config.get("chunk_overlap") != EXPECTED_CHUNK_OVERLAP
            or config.get("top_k") != EXPECTED_TOP_K
        ):
            raise EngineeringKnowledgeError("authority manifest identity does not match frozen Engineering Knowledge")

    def _validate_files(self, entries: list[dict], chunks_by_path: dict[str, dict]) -> None:
        expected_paths = {entry["relative_path"] for entry in entries}
        actual_paths = {
            path.relative_to(self._root).as_posix()
            for path in self._root.rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            raise EngineeringKnowledgeError("corpus files do not match authority manifest")
        for entry in entries:
            path = _contained_file(self._root, entry["relative_path"])
            actual_sha, actual_size = _sha256_and_size(path)
            if actual_sha != entry["sha256"] or actual_size != entry["size_bytes"]:
                raise EngineeringKnowledgeError("corpus file hash or size does not match authority manifest")

    def _chunk_documents(self, entries: list[dict], chunks_by_path: dict[str, dict]) -> list[Document]:
        chunker = RecursiveChunker(
            chunk_size=EXPECTED_CHUNK_SIZE,
            chunk_overlap=EXPECTED_CHUNK_OVERLAP,
        )
        chunks = []
        for entry in entries:
            relative_path = entry["relative_path"]
            path = _contained_file(self._root, relative_path)
            content = path.read_text(encoding="utf-8")
            document_id = make_document_id(relative_path)
            chunked = chunker.chunk(
                [
                    Document(
                        content=content,
                        metadata={
                            "document_id": document_id,
                            "source_name": relative_path,
                        },
                    )
                ]
            )
            if len(chunked) != chunks_by_path[relative_path]["chunks"]:
                raise EngineeringKnowledgeError("corpus chunking does not match authority manifest")
            for chunk_index, chunk in enumerate(chunked):
                metadata = dict(chunk.metadata)
                metadata.update(
                    {
                        "id": make_chunk_id(document_id, chunk_index, chunk.content),
                        "document_id": document_id,
                        "source_name": relative_path,
                        "chunk_index": chunk_index,
                    }
                )
                chunks.append(Document(content=chunk.content, metadata=metadata))
        return chunks

    @property
    def identity(self) -> EngineeringKnowledgeIdentity:
        return self._identity

    @property
    def retrieval_port(self) -> PipelineRetrievalAdapter:
        return self._port

    @property
    def source_names(self) -> tuple[str, ...]:
        return self._source_names

    @property
    def retriever_type(self) -> str:
        return type(self._retriever).__name__

    @property
    def bm25_doc_count(self) -> int:
        return self._retriever._bm25.doc_count

    @property
    def absolute_provenance_count(self) -> int:
        return sum(
            1
            for source_name in self._source_names
            if PureWindowsPath(source_name).is_absolute()
            or PureWindowsPath(source_name).drive
            or PurePosixPath(source_name).is_absolute()
        )


def build_verified_engineering_knowledge(
    corpus_root: str | os.PathLike | None,
    *,
    repo_root: str | os.PathLike,
) -> VerifiedEngineeringKnowledge:
    return VerifiedEngineeringKnowledge.from_repo(corpus_root, repo_root=repo_root)


__all__ = [
    "AUTHORITY_MANIFEST_RELATIVE_PATH",
    "CORPUS_ENV_VAR",
    "EngineeringKnowledgeError",
    "EngineeringKnowledgeIdentity",
    "EXPECTED_CHUNK_COUNT",
    "EXPECTED_CORPUS_ID",
    "EXPECTED_EXPERIMENT_ID",
    "EXPECTED_FILE_COUNT",
    "EXPECTED_STRATEGY",
    "VerifiedEngineeringKnowledge",
    "build_verified_engineering_knowledge",
]
