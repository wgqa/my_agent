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
