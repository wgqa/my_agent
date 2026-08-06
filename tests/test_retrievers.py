import pytest

from core.loader.base import Document
from core.retriever.base import BaseRetriever


def test_base_retriever_abstract():
    try:
        BaseRetriever()
        assert False
    except TypeError:
        pass


def test_bm25_index():
    from core.retriever.hybrid import BM25Index
    bm25 = BM25Index()
    bm25.add_document("doc_0", "the cat sat on the mat")
    bm25.add_document("doc_1", "the dog chased the cat")

    results = bm25.search("cat mat", top_k=5)
    assert len(results) == 2
    assert results[0][0] == "doc_0"
    assert results[0][1] > results[1][1]


# ── REWORK-P0-02: BM25 重复入库统计膨胀 ───────────────

def test_bm25_add_same_id_twice_no_inflation():
    """同一 ID、同一文本添加两次，doc 计数仍为 1，DF 不重复累计"""
    from core.retriever.hybrid import BM25Index
    bm25 = BM25Index()
    bm25.add_document("d1", "cat cat mat")
    bm25.add_document("d1", "cat cat mat")

    assert bm25._total_docs == 1
    assert len(bm25._doc_freqs) == 1
    assert bm25._doc_freqs["d1"]["cat"] == 2
    assert bm25._df["cat"] == 1


def test_bm25_update_same_id_replaces_stats():
    """同一 ID 更新为新文本：旧词项 DF 消失，新词项生效"""
    from core.retriever.hybrid import BM25Index
    bm25 = BM25Index()
    bm25.add_document("d1", "cat mat")
    bm25.add_document("d1", "dog")

    assert bm25._total_docs == 1
    assert "cat" not in bm25._df
    assert bm25._df["dog"] == 1
    assert bm25.get_text("d1") == "dog"


def test_build_sparse_index_idempotent():
    """相同语料重复 build_sparse_index，搜索排名和分数不变"""
    from core.retriever.hybrid import HybridRetriever
    r = HybridRetriever(MockEmbedding(), MockVectorStore())
    data = [("d0", "the cat sat on the mat"), ("d1", "the dog chased the cat")]
    r.build_sparse_index(data)
    before = r._bm25.search("cat mat", top_k=5)
    r.build_sparse_index(data)
    after = r._bm25.search("cat mat", top_k=5)

    assert before == after
    assert r._bm25._total_docs == 2


class MockEmbedding:
    def embed(self, texts):
        return [[0.1, 0.2]] * len(texts)

    def embed_query(self, text):
        return [0.1, 0.2]


class MockVectorStore:
    def __init__(self):
        self.docs = [
            Document(content="cat on mat", metadata={"distance": 0.1}),
            Document(content="dog in park", metadata={"distance": 0.5}),
        ]

    def search(self, query_emb, top_k=5, where=None):
        return self.docs[:top_k]


class _DenseHitsVectorStore:
    """Dense 通道可控替身：search 返回预设 Document 列表并截断"""

    def __init__(self, hits):
        self._hits = list(hits)

    def search(self, query_emb, top_k=5, where=None):
        return self._hits[:top_k]


class _FakeBM25Hits:
    """Sparse 通道可控替身：search 返回预设 [(doc_id, score)]，get_text/get_meta 供补全"""

    def __init__(self, hits, metas=None):
        self._hits = list(hits)
        self._metas = metas or {}

    def search(self, query, top_k=10):
        return self._hits[:top_k]

    def get_text(self, doc_id):
        return f"text {doc_id}"

    def get_meta(self, doc_id):
        return dict(self._metas.get(doc_id) or {})


def _rrf_doc(doc_id, score=1.0):
    return Document(content=f"content {doc_id}",
                    metadata={"id": doc_id, "score": score})


def _rrf_retriever(dense_docs, sparse_hits, dense_candidate_k=3, sparse_candidate_k=9):
    from core.retriever.hybrid import HybridRetriever
    r = HybridRetriever(
        MockEmbedding(), _DenseHitsVectorStore(dense_docs),
        dense_candidate_k=dense_candidate_k, sparse_candidate_k=sparse_candidate_k,
        final_k=20, rrf_k=60.0,
    )
    r._bm25 = _FakeBM25Hits(sparse_hits)
    return r


def test_rrf_dense_only_score():
    """Dense-only 文档分数只含 Dense 项，Sparse 缺席贡献严格为 0"""
    r = _rrf_retriever([_rrf_doc("A")], [])
    docs = r.retrieve("q", top_k=5)
    a = next(d for d in docs if d.metadata["id"] == "A")
    assert a.metadata["rrf_score"] == pytest.approx(round(1 / 61.0, 6))
    assert a.metadata["sparse_rank"] is None


def test_rrf_sparse_only_score():
    """Sparse-only 文档分数只含 Sparse 项，Dense 缺席贡献严格为 0"""
    r = _rrf_retriever([], [("A", 1.0)])
    docs = r.retrieve("q", top_k=5)
    a = next(d for d in docs if d.metadata["id"] == "A")
    assert a.metadata["rrf_score"] == pytest.approx(round(1 / 61.0, 6))
    assert a.metadata["dense_rank"] is None


def test_rrf_both_channels_sum():
    """同时命中两个通道：分数 = Dense 项 + Sparse 项"""
    r = _rrf_retriever(
        [_rrf_doc("X"), _rrf_doc("A")],  # A dense rank2
        [("A", 1.0)],                    # A sparse rank1
        dense_candidate_k=2,
    )
    docs = r.retrieve("q", top_k=5)
    a = next(d for d in docs if d.metadata["id"] == "A")
    assert a.metadata["rrf_score"] == pytest.approx(round(1 / 62.0 + 1 / 61.0, 6))
    assert a.metadata["dense_rank"] == 2
    assert a.metadata["sparse_rank"] == 1


def test_rrf_absent_channel_zero_changes_ordering():
    """旧算法（缺席给虚拟排名）排序为 X>A>B，正确算法必须为 X>B>A"""
    r = _rrf_retriever(
        [_rrf_doc("B"), _rrf_doc("X")],  # B dense rank1，X dense rank2
        [("X", 2.0), ("A", 1.0)],        # X sparse rank1，A sparse rank2
        dense_candidate_k=2, sparse_candidate_k=9,
    )
    docs = r.retrieve("q", top_k=5)
    order = [d.metadata["id"] for d in docs]
    assert order.index("B") < order.index("A"), f"正确 RRF 下 B 应在 A 前: {order}"
    b = next(d for d in docs if d.metadata["id"] == "B")
    a = next(d for d in docs if d.metadata["id"] == "A")
    assert b.metadata["rrf_score"] > a.metadata["rrf_score"]
    assert b.metadata["sparse_rank"] is None
    assert a.metadata["dense_rank"] is None


def test_simple_retriever():
    from core.retriever.simple import SimpleRetriever
    r = SimpleRetriever(MockEmbedding(), MockVectorStore())
    results = r.retrieve("cat", top_k=2)
    assert len(results) == 2
    assert "cat" in results[0].content


def test_mmr_retriever():
    from core.retriever.mmr import MMRRetriever
    r = MMRRetriever(MockEmbedding(), MockVectorStore())
    results = r.retrieve("cat", top_k=2)
    assert len(results) == 2


# ── G1-META-02：Sparse-only 保留完整元数据 ─────────────

def _sparse_only_retriever_with_meta():
    """Dense 通道无 id（结果不进入融合），Sparse 通道命中 c1（真实 BM25）"""
    from core.retriever.hybrid import HybridRetriever
    r = HybridRetriever(MockEmbedding(), MockVectorStore())
    r.build_sparse_index([(
        "c1", "python",
        {
            "id": "c1", "document_id": "doc1", "source": "a.md",
            "source_name": "a.md", "file_path": "docs/a.md",
            "page": 3, "page_number": 3, "chunk_index": 0,
            "start_offset": 0, "end_offset": 10,
        },
    )])
    return r


def test_sparse_only_preserves_full_metadata():
    """Sparse-only 命中从 BM25 恢复完整原始元数据"""
    r = _sparse_only_retriever_with_meta()
    docs = r.retrieve("python", top_k=5)
    assert len(docs) == 1
    meta = docs[0].metadata
    assert meta["id"] == "c1"
    assert meta["document_id"] == "doc1"
    assert meta["source"] == "a.md"
    assert meta["source_name"] == "a.md"
    assert meta["file_path"] == "docs/a.md"
    assert meta["page"] == 3
    assert meta["page_number"] == 3
    assert meta["chunk_index"] == 0
    assert meta["start_offset"] == 0
    assert meta["end_offset"] == 10
    assert meta["sparse_score"] is not None
    assert meta["dense_rank"] is None


def test_sparse_only_metadata_flows_to_assembler():
    """Sparse-only 结果进入 ContextAssembler 后来源不是 unknown"""
    from core.context.assembler import ContextAssembler
    r = _sparse_only_retriever_with_meta()
    docs = r.retrieve("python", top_k=5)
    blocks = ContextAssembler().assemble(docs)
    assert len(blocks) == 1
    assert blocks[0].source_name == "a.md"


def test_dense_hit_not_overwritten_by_sparse_meta():
    """Dense+Sparse 同时命中：以 Dense 返回的完整 Document 为主体"""
    dense_doc = _rrf_doc("c1")
    dense_doc.metadata["source_name"] = "dense.md"
    dense_doc.metadata["document_id"] = "doc-dense"
    r = _rrf_retriever([dense_doc], [("c1", 1.0)], dense_candidate_k=2)
    r._bm25 = _FakeBM25Hits([("c1", 1.0)], metas={
        "c1": {"source_name": "sparse.md", "document_id": "doc-sparse"},
    })
    docs = r.retrieve("q", top_k=5)
    c1 = next(d for d in docs if d.metadata["id"] == "c1")
    assert c1.metadata["source_name"] == "dense.md"
    assert c1.metadata["document_id"] == "doc-dense"


def test_bm25_same_id_update_replaces_text_and_meta():
    """同 ID 重复添加：正文与元数据都被新版本替换"""
    from core.retriever.hybrid import BM25Index
    idx = BM25Index()
    idx.add_document("c1", "old text", {"source": "old.md", "page": 1})
    idx.add_document("c1", "new text", {"source": "new.md", "page": 2})
    assert idx.get_text("c1") == "new text"
    assert idx.get_meta("c1") == {"source": "new.md", "page": 2}
    assert idx.doc_count == 1


def test_bm25_save_load_keeps_metadata(tmp_path):
    """save/load 后元数据不丢失"""
    from core.retriever.hybrid import BM25Index
    idx = BM25Index()
    idx.add_document("c1", "python", {"source": "a.md", "page": 3})
    path = tmp_path / "bm25.json"
    idx.save(str(path))
    loaded = BM25Index.load(str(path))
    assert loaded.get_text("c1") == "python"
    assert loaded.get_meta("c1") == {"source": "a.md", "page": 3}


def test_bm25_load_old_index_without_meta_compatible(tmp_path):
    """旧索引文件缺少 metadata 字段时兼容（get_meta 返回空）"""
    import json
    from core.retriever.hybrid import BM25Index
    path = tmp_path / "old_bm25.json"
    path.write_text(json.dumps({
        "k1": 1.5, "b": 0.75,
        "doc_freqs": {"c1": {"python": 1}},
        "df": {"python": 1}, "doc_lens": {"c1": 1},
        "texts": {"c1": "python"}, "total_docs": 1,
    }), encoding="utf-8")
    loaded = BM25Index.load(str(path))
    assert loaded.get_text("c1") == "python"
    assert loaded.get_meta("c1") == {}
