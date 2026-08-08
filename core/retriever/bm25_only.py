"""BM25-only Retriever（G2-ABL-16 正式策略确认用）。

只使用 BM25 词法检索，不参与 Dense Embedding Search / RRF。
与 HybridRetriever 共享同一个 BM25Index 实现，保证打分一致。
"""

from typing import List

from core.loader.base import Document
from core.retriever.base import BaseRetriever
from core.retriever.hybrid import BM25Index


class BM25OnlyRetriever(BaseRetriever):
    """Dense 不参与排序的纯 BM25 检索器"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self._bm25 = BM25Index(k1=k1, b=b)

    def build_sparse_index(self, chunk_texts: List[tuple]):
        """批量建立 BM25 索引，语义与 HybridRetriever 完全一致"""
        for item in chunk_texts:
            chunk_id, text = item[0], item[1]
            meta = item[2] if len(item) >= 3 else None
            self._bm25.add_document(chunk_id, text, meta)

    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        """Query → BM25 → Top-K chunks；不调用 Embedding / VectorStore / RRF。"""
        hits = self._bm25.search(query, top_k=top_k)
        docs = []
        for chunk_id, score in hits:
            text = self._bm25.get_text(chunk_id)
            meta = self._bm25.get_meta(chunk_id)
            meta["id"] = chunk_id
            meta["sparse_score"] = round(score, 4)
            docs.append(Document(content=text, metadata=meta))
        return docs
