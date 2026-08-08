import math
from collections import Counter
from typing import List, Dict

from core.loader.base import Document
from core.retriever.base import BaseRetriever
from core.embeddings.base import BaseEmbedding
from core.vector_store.base import BaseVectorStore


try:
    import jieba
except ImportError:
    jieba = None

VALID_RRF_TIE_BREAKERS = ("chunk_id_asc",)


def _tokenize(text: str) -> List[str]:
    """中文友好的分词：优先 jieba，降级到 split"""
    if jieba:
        return list(jieba.cut(text))
    return text.split()


class BM25Index:
    """从零实现的 BM25 索引，支持增量 IDF + 持久化"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._doc_freqs: Dict[str, Counter] = {}
        self._idf: Dict[str, float] = {}
        self._df: Dict[str, int] = {}
        self._doc_lens: Dict[str, int] = {}
        self._texts: Dict[str, str] = {}
        self._meta: Dict[str, dict] = {}
        self._avgdl: float = 0.0
        self._total_docs: int = 0

    def add_document(self, doc_id: str, text: str, meta: dict = None):
        """添加一篇文档到索引（增量 IDF）；同一 ID 重复添加视为更新，
        正文与元数据都被新版本替换"""
        if doc_id in self._doc_freqs:
            self.remove_document(doc_id)
        tokens = _tokenize(text)
        self._doc_freqs[doc_id] = Counter(tokens)
        self._doc_lens[doc_id] = sum(self._doc_freqs[doc_id].values())
        self._texts[doc_id] = text
        if meta is not None:
            self._meta[doc_id] = dict(meta)  # 副本，防止外部修改污染索引

        # 增量更新 DF
        for term in self._doc_freqs[doc_id]:
            self._df[term] = self._df.get(term, 0) + 1
        self._total_docs += 1
        self._update_avgdl()
        # 总文档数变化影响所有词项的 idf，必须全量重算（增量只重算新增词会留下陈旧值）
        self._recompute_idf()

    def remove_document(self, doc_id: str):
        """从索引中移除一篇文档（增量 IDF）"""
        if doc_id not in self._doc_freqs:
            return
        affected = set(self._doc_freqs[doc_id].keys())
        for term in affected:
            self._df[term] = self._df.get(term, 0) - 1
            if self._df[term] <= 0:
                self._df.pop(term, None)
        self._doc_freqs.pop(doc_id)
        self._doc_lens.pop(doc_id)
        self._texts.pop(doc_id, None)
        self._meta.pop(doc_id, None)
        self._total_docs -= 1
        self._update_avgdl()
        self._recompute_idf()

    def get_text(self, doc_id: str) -> str:
        return self._texts.get(doc_id, "")

    def get_meta(self, doc_id: str) -> dict:
        """返回存储的元数据副本；无记录返回空 dict"""
        return dict(self._meta.get(doc_id) or {})

    def _update_avgdl(self):
        self._avgdl = sum(self._doc_lens.values()) / max(self._total_docs, 1)

    # ── 持久化 ───────────────────────────────────────

    def save(self, path: str):
        """保存 BM25 索引到磁盘"""
        import json
        data = {
            "k1": self.k1, "b": self.b,
            "doc_freqs": {k: dict(v) for k, v in self._doc_freqs.items()},
            "df": self._df, "doc_lens": self._doc_lens,
            "texts": self._texts, "meta": self._meta,
            "total_docs": self._total_docs,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        self._recompute_idf()  # 重建 IDF

    @classmethod
    def load(cls, path: str) -> "BM25Index":
        """从磁盘加载 BM25 索引"""
        import json, os
        idx = cls()
        if not os.path.exists(path):
            return idx
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        idx.k1 = data["k1"]
        idx.b = data["b"]
        idx._doc_freqs = {k: Counter(v) for k, v in data["doc_freqs"].items()}
        idx._df = data["df"]
        idx._doc_lens = data["doc_lens"]
        idx._texts = data["texts"]
        idx._meta = data.get("meta") or {}  # 旧索引文件无 meta 字段时兼容
        idx._total_docs = data["total_docs"]
        idx._recompute_idf()
        return idx

    # ── 兼容旧接口 ───────────────────────────────────

    def _recompute_idf(self):
        """全量重算 IDF（仅在 save/load 时使用）"""
        self._avgdl = sum(self._doc_lens.values()) / max(self._total_docs, 1)
        self._df.clear()
        self._idf.clear()
        for counter in self._doc_freqs.values():
            for term in counter:
                self._df[term] = self._df.get(term, 0) + 1
        for term, freq in self._df.items():
            self._idf[term] = math.log(
                (self._total_docs - freq + 0.5) / (freq + 0.5) + 1.0
            )

    def search(self, query: str, top_k: int = 10) -> List[tuple[str, float]]:
        """检索，返回 [(doc_id, score), ...]"""
        query_tokens = _tokenize(query)
        scores: List[tuple[str, float]] = []

        for doc_id, doc_len in self._doc_lens.items():
            doc_freq = self._doc_freqs[doc_id]
            total = 0.0
            for term in query_tokens:
                if term not in self._idf:
                    continue
                tf = doc_freq.get(term, 0)
                if tf == 0:
                    continue
                total += self._idf[term] * (
                    (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / max(self._avgdl, 1)))
                )
            if total > 0:
                scores.append((doc_id, total))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    @property
    def doc_count(self) -> int:
        return self._total_docs


class HybridRetriever(BaseRetriever):
    """Dense + Sparse 独立召回 + RRF 融合"""

    def __init__(
        self,
        embedding: BaseEmbedding,
        vector_store: BaseVectorStore,
        dense_candidate_k: int = 30,
        sparse_candidate_k: int = 30,
        final_k: int = 20,
        rrf_k: float = 60.0,
        rrf_tie_breaker: str = "chunk_id_asc",
    ):
        self.embedding = embedding
        self.vector_store = vector_store
        self.dense_candidate_k = dense_candidate_k
        self.sparse_candidate_k = sparse_candidate_k
        self.final_k = final_k
        self.rrf_k = rrf_k
        if type(rrf_tie_breaker) is not str or rrf_tie_breaker == "":
            raise TypeError(
                "rrf_tie_breaker 必须是非空字符串，"
                f"实际 {type(rrf_tie_breaker).__name__}（{rrf_tie_breaker!r}）"
            )
        if rrf_tie_breaker not in VALID_RRF_TIE_BREAKERS:
            raise ValueError(
                f"未知 rrf_tie_breaker: {rrf_tie_breaker}，"
                f"支持 {VALID_RRF_TIE_BREAKERS}"
            )
        self.rrf_tie_breaker = rrf_tie_breaker
        self._bm25 = BM25Index()

    def build_sparse_index(self, chunk_texts: List[tuple]):
        """批量建立 BM25 索引。chunk_texts: [(chunk_id, text), ...] 或
        [(chunk_id, text, metadata), ...]（带元数据供 Sparse-only 恢复）"""
        for item in chunk_texts:
            chunk_id, text = item[0], item[1]
            meta = item[2] if len(item) >= 3 else None
            self._bm25.add_document(chunk_id, text, meta)

    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        """检索：Dense Top-N → Sparse Top-N → RRF → 返回 final_k 候选"""
        _, _, final = self._internal_retrieve(query, top_k)
        return final

    def retrieve_with_trace(self, query: str, top_k: int = 5) -> dict:
        """诊断接口：一次检索同时暴露 Dense/Sparse 完整候选与最终结果。

        与 retrieve() 共享同一次 _internal_retrieve()：不重复 embed、
        不重复 Dense Search、不重复 BM25 Search；普通 retrieve() 语义
        完全不变。返回：
        {
          "dense_candidates": [{"rank", "chunk_id", "document_id",
                                 "score"/"distance"(实际存在才保存)}, ...],
          "sparse_candidates": [{"rank", "chunk_id", "document_id",
                                 "sparse_score"}, ...],
          "final_results": [Document, ...],
        }
        """
        dense_results, sparse_hits, final = self._internal_retrieve(query, top_k)

        dense_candidates = []
        for rank, doc in enumerate(dense_results, 1):
            meta = doc.metadata or {}
            item = {
                "rank": rank,
                "chunk_id": meta.get("id", ""),
                "document_id": meta.get("document_id", ""),
            }
            for key in ("score", "distance"):
                if key in meta:
                    item[key] = meta[key]
            dense_candidates.append(item)

        sparse_candidates = []
        for rank, (chunk_id, sparse_score) in enumerate(sparse_hits, 1):
            meta = self._bm25.get_meta(chunk_id)
            sparse_candidates.append({
                "rank": rank,
                "chunk_id": chunk_id,
                "document_id": meta.get("document_id", ""),
                "sparse_score": round(sparse_score, 4),
            })

        return {
            "dense_candidates": dense_candidates,
            "sparse_candidates": sparse_candidates,
            "final_results": final,
        }

    def _internal_retrieve(self, query: str, top_k: int = 5):
        """共享私有实现：一次 embed + 一次 Dense Search + 一次 BM25 Search。

        返回 (dense_results, sparse_hits, final)；普通 retrieve() 与
        retrieve_with_trace() 都从这里取数，保证诊断不会引入第二次检索。
        """
        query_vec = self.embedding.embed_query(query)

        # 1. Dense 检索
        dense_results = self.vector_store.search(query_vec, top_k=self.dense_candidate_k)

        # 2. Sparse 检索
        sparse_hits = self._bm25.search(query, top_k=self.sparse_candidate_k)
        sparse_ids = {hit[0] for hit in sparse_hits}
        existing_ids = {d.metadata.get("id") for d in dense_results}

        # 3. RRF 融合
        dense_rank_map: Dict[str, int] = {}
        for rank, d in enumerate(dense_results):
            doc_id = d.metadata.get("id", "")
            if doc_id:
                dense_rank_map[doc_id] = rank + 1

        sparse_rank_map: Dict[str, int] = {}
        for rank, (doc_id, _) in enumerate(sparse_hits):
            sparse_rank_map[doc_id] = rank + 1

        all_ids = set(dense_rank_map.keys()) | set(sparse_rank_map.keys())
        rrf_scores = []
        for doc_id in all_ids:
            # RRF 缺席通道语义：文档只从实际命中的通道获得分数，
            # 未命中通道贡献严格为 0（不给虚拟排名，避免单通道文档
            # 获得另一通道的正分改变排序）
            rrf = 0.0
            if doc_id in dense_rank_map:
                rrf += 1.0 / (self.rrf_k + dense_rank_map[doc_id])
            if doc_id in sparse_rank_map:
                rrf += 1.0 / (self.rrf_k + sparse_rank_map[doc_id])
            rrf_scores.append((doc_id, rrf))

        rrf_scores = self._sort_rrf_scores(rrf_scores)

        # 4. 按 RRF 排序返回
        result_map = {d.metadata.get("id", ""): d for d in dense_results if d.metadata.get("id")}
        # 对 Dense 未召回但 Sparse 命中的文档，用 BM25 存储的原文与
        # 原始元数据补全（document_id/source/page 等），保证可追溯引用
        for chunk_id, s_score in sparse_hits:
            if chunk_id not in existing_ids:
                text = self._bm25.get_text(chunk_id)
                meta = self._bm25.get_meta(chunk_id)
                meta["id"] = chunk_id
                meta["sparse_score"] = round(s_score, 4)
                result_map[chunk_id] = Document(content=text, metadata=meta)

        final = []
        # 池大小取 final_k 与请求 top_k 的较大者，避免内部截断吞掉候选
        for doc_id, rrf in rrf_scores[:max(self.final_k, top_k)]:
            if doc_id in result_map:
                doc = result_map[doc_id]
                doc.metadata["rrf_score"] = round(rrf, 6)
                doc.metadata["dense_rank"] = dense_rank_map.get(doc_id)
                doc.metadata["sparse_rank"] = sparse_rank_map.get(doc_id)
                final.append(doc)

        return dense_results, sparse_hits, final[:top_k]

    @staticmethod
    def _sort_rrf_scores(rrf_scores):
        """正式 RRF 排序契约：rrf_score DESC，chunk_id ASC。

        排序基于完整 float（不先 round）；chunk_id 只用于完全同分时的
        canonical ordering，不代表更高相关性。
        """
        return sorted(rrf_scores, key=lambda item: (-item[1], item[0]))
