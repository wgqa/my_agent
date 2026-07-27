import hashlib
from typing import List

import chromadb
from chromadb.config import Settings

from core.loader.base import Document
from core.vector_store.base import BaseVectorStore


class ChromaStore(BaseVectorStore):

    def __init__(self, path: str = "./data/vector_store", collection_name: str = "documents"):
        if path is None:
            self.client = chromadb.Client(Settings(anonymized_telemetry=False))
        else:
            self.client = chromadb.PersistentClient(
                path=path,
                settings=Settings(anonymized_telemetry=False),
            )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── ID 生成 ─────────────────────────────────────────────

    @staticmethod
    def _make_chunk_id(document_id: str, content: str) -> str:
        """基于 document_id + content 生成稳定的 chunk_id，不依赖 count"""
        raw = f"{document_id}:{content}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ── 写入 ────────────────────────────────────────────────

    def add(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        ids = []
        metadatas = []
        texts = []

        for doc in documents:
            doc_id = doc.metadata.get("document_id", "unknown")
            chunk_id = self._make_chunk_id(doc_id, doc.content)
            ids.append(chunk_id)
            meta = dict(doc.metadata) if doc.metadata else {}
            meta["document_id"] = doc_id
            meta["id"] = chunk_id
            metadatas.append(meta)
            doc.metadata = meta
            texts.append(doc.content)

        self.collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        return ids

    def upsert(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        """存在则更新，不存在则插入"""
        ids = []
        metadatas = []
        texts = []

        for doc in documents:
            doc_id = doc.metadata.get("document_id", "unknown")
            chunk_id = self._make_chunk_id(doc_id, doc.content)
            ids.append(chunk_id)
            meta = dict(doc.metadata) if doc.metadata else {}
            meta["document_id"] = doc_id
            meta["id"] = chunk_id
            metadatas.append(meta)
            doc.metadata = meta
            texts.append(doc.content)

        self.collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        return ids

    # ── 查询 ────────────────────────────────────────────────

    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Document]:
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        docs = []
        if results["documents"] and results["documents"][0]:
            for i, text in enumerate(results["documents"][0]):
                meta = dict(results["metadatas"][0][i]) if results["metadatas"] and results["metadatas"][0] else {}
                dist = results["distances"][0][i] if results["distances"] else 0.0
                meta["id"] = results["ids"][0][i] if results["ids"] else ""
                meta["distance"] = round(dist, 6)
                meta["score"] = round(1.0 - dist, 6)
                docs.append(Document(content=text, metadata=meta))
        return docs

    # ── 删除 ────────────────────────────────────────────────

    def delete(self, ids: List[str]):
        self.collection.delete(ids=ids)

    def delete_by_document_id(self, document_id: str):
        self.collection.delete(where={"document_id": document_id})

    # ── 工具 ────────────────────────────────────────────────

    def count(self) -> int:
        return self.collection.count()
