import hashlib
from typing import List, Optional

import chromadb
from chromadb.config import Settings

from core.loader.base import Document
from core.vector_store.base import BaseVectorStore


class ChromaStore(BaseVectorStore):

    def __init__(self, path: str = "./data/vector_store",
                 collection_name: str = "documents",
                 model_name: str | None = None):
        if path is None:
            self.client = chromadb.Client(Settings(anonymized_telemetry=False))
        else:
            self.client = chromadb.PersistentClient(
                path=path,
                settings=Settings(anonymized_telemetry=False),
            )
        safe = collection_name
        if model_name:
            safe = f"{collection_name}_{model_name.replace('/', '_')}"
        self.collection = self.client.get_or_create_collection(
            name=safe,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedding_dim: int | None = None

    @staticmethod
    def _make_chunk_id(document_id: str, content: str) -> str:
        raw = f"{document_id}:{content}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ── 校验 ────────────────────────────────────────────────

    def _validate_batch(self, docs: List[Document], embs: List[List[float]]):
        if len(docs) != len(embs):
            raise ValueError(f"documents {len(docs)} 与 embeddings {len(embs)} 数量不一致")
        if not embs:
            return
        dim = len(embs[0])
        if self._embedding_dim is None:
            self._embedding_dim = dim
        elif dim != self._embedding_dim:
            raise ValueError(f"向量维度不匹配：期望 {self._embedding_dim}，实际 {dim}")

    # ── 写入 ────────────────────────────────────────────────

    def _batch(self, docs: List[Document]):
        ids, metas, texts = [], [], []
        for d in docs:
            doc_id = d.metadata.get("document_id", "unknown")
            cid = self._make_chunk_id(doc_id, d.content)
            ids.append(cid)
            meta = dict(d.metadata) if d.metadata else {}
            meta["document_id"] = doc_id
            meta["id"] = cid
            metas.append(meta)
            d.metadata = meta
            texts.append(d.content)
        return ids, metas, texts

    def add(self, docs: List[Document], embs: List[List[float]]) -> List[str]:
        self._validate_batch(docs, embs)
        ids, metas, texts = self._batch(docs)
        if ids:
            self.collection.add(ids=ids, embeddings=embs, documents=texts, metadatas=metas)
        return ids

    def upsert(self, docs: List[Document], embs: List[List[float]]) -> List[str]:
        self._validate_batch(docs, embs)
        ids, metas, texts = self._batch(docs)
        if ids:
            self.collection.upsert(ids=ids, embeddings=embs, documents=texts, metadatas=metas)
        return ids

    # ── 查询 ────────────────────────────────────────────────

    def search(self, query_emb: List[float], top_k: int = 5,
               where: Optional[dict] = None) -> List[Document]:
        kwargs: dict = {
            "query_embeddings": [query_emb],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self.collection.query(**kwargs)
        docs = []
        if results["documents"] and results["documents"][0]:
            for i, text in enumerate(results["documents"][0]):
                meta = dict(results["metadatas"][0][i]) if results["metadatas"] and results["metadatas"][0] else {}
                dist = results["distances"][0][i] if results["distances"] else 0.0
                meta["id"] = results["ids"][0][i] if results["ids"] else ""
                meta["distance"] = round(dist, 6)
                meta["score"] = round(1.0 - dist, 6)
                meta["rank"] = i + 1
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

    def list_ids(self, limit: int = 100) -> List[str]:
        data = self.collection.get(limit=limit)
        return list(data["ids"]) if data else []
