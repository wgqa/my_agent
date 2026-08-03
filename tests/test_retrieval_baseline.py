"""M2-T1: Dense Baseline 人工评测 fixture

三份答案显而易见的小语料，验证检索排序符合语义直觉。
"""

from core.loader.base import Document
from core.vector_store.chroma_store import ChromaStore
from core.retriever.simple import SimpleRetriever


class _FakeEmbedding:
    """伪 embedding：向量空间人为构造，语义相近 = 向量夹角小"""

    def __init__(self):
        self._doc_vectors = {
            "缓存穿透定义": [1.0, 0.0, 0.0, 0.1],
            "缓存击穿定义": [0.9, 0.1, 0.0, 0.2],
            "JVM类加载":    [0.0, 1.0, 1.0, 0.0],
        }
        self._query_vectors = {
            "什么是缓存穿透": [1.0, 0.0, 0.0, 0.1],
        }

    def embed(self, texts):
        return [self._doc_vectors.get(t, [0.0] * 4) for t in texts]

    def embed_query(self, text):
        return self._query_vectors.get(text, [0.0] * 4)


def _build_store():
    store = ChromaStore(path=None, collection_name="baseline_manual")
    emb = _FakeEmbedding()
    docs = [
        Document(content="缓存穿透定义", metadata={"document_id": "doc_a"}),
        Document(content="缓存击穿定义", metadata={"document_id": "doc_b"}),
        Document(content="JVM类加载",    metadata={"document_id": "doc_c"}),
    ]
    store.add(docs, emb.embed([d.content for d in docs]))
    return store, emb


def test_dense_baseline_ordering():
    """缓存穿透应排在击穿/JVM 之前"""
    store, emb = _build_store()
    retriever = SimpleRetriever(emb, store)
    results = retriever.retrieve("什么是缓存穿透", top_k=3)

    assert len(results) == 3
    assert results[0].content == "缓存穿透定义"
    assert results[1].content == "缓存击穿定义"
    assert results[2].content == "JVM类加载"


def test_dense_baseline_score_order_matches_ranking():
    """score 语义与排序一致：分数递减"""
    store, emb = _build_store()
    retriever = SimpleRetriever(emb, store)
    results = retriever.retrieve("什么是缓存穿透", top_k=3)

    scores = [r.metadata["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > scores[1] > scores[2]


def test_dense_baseline_has_stable_id():
    """结果包含稳定 chunk_id"""
    store, emb = _build_store()
    retriever = SimpleRetriever(emb, store)
    results = retriever.retrieve("什么是缓存穿透", top_k=3)

    for r in results:
        assert r.metadata["id"]


def test_dense_baseline_ranking_after_restart(tmp_path):
    """重启 Store 后（持久化）排序结果一致"""
    store_dir = tmp_path / "baseline_vs"
    store = ChromaStore(path=str(store_dir), collection_name="baseline_persist")
    emb = _FakeEmbedding()
    docs = [
        Document(content="缓存穿透定义", metadata={"document_id": "doc_a"}),
        Document(content="缓存击穿定义", metadata={"document_id": "doc_b"}),
        Document(content="JVM类加载",    metadata={"document_id": "doc_c"}),
    ]
    store.add(docs, emb.embed([d.content for d in docs]))

    r1 = SimpleRetriever(emb, store).retrieve("什么是缓存穿透", top_k=3)
    order1 = [r.content for r in r1]

    store2 = ChromaStore(path=str(store_dir), collection_name="baseline_persist")
    r2 = SimpleRetriever(emb, store2).retrieve("什么是缓存穿透", top_k=3)
    order2 = [r.content for r in r2]

    assert order1 == order2 == ["缓存穿透定义", "缓存击穿定义", "JVM类加载"]


def test_dense_baseline_top_k_larger_than_count():
    """top_k 大于库内数量时返回全部，不报错"""
    store, emb = _build_store()
    retriever = SimpleRetriever(emb, store)
    results = retriever.retrieve("什么是缓存穿透", top_k=100)
    assert len(results) == 3


def test_dense_baseline_empty_store():
    """空库检索返回空列表，不报错"""
    store = ChromaStore(path=None, collection_name="baseline_empty")
    emb = _FakeEmbedding()
    retriever = SimpleRetriever(emb, store)
    results = retriever.retrieve("什么是缓存穿透", top_k=3)
    assert results == []


# ── M2-T2: Sparse 补召回 ──────────────────────────────

class _MissEmbedding:
    """Dense 对目标文档完全无感（向量远离），Sparse 才能救回来"""

    def __init__(self):
        self._doc_vectors = {
            "ERROR_CODE_502 表示网关错误": [1.0, 0.0, 0.0, 0.0],
            "JVM类加载机制详解":           [0.0, 1.0, 0.0, 0.0],
        }
        self._query_vectors = {
            "ERROR_CODE_502": [0.99, 0.0, 0.0, 0.0],
        }

    def embed(self, texts):
        return [self._doc_vectors.get(t, [0.0] * 4) for t in texts]

    def embed_query(self, text):
        return self._query_vectors.get(text, [0.0] * 4)


def test_sparse_can_recall_doc_missed_by_dense():
    """Sparse 召回 Dense 漏掉的文档（专有名词/错误码场景）"""
    from core.retriever.hybrid import HybridRetriever

    emb = _MissEmbedding()
    store = ChromaStore(path=None, collection_name="sparse_miss")

    docs = [
        Document(content="ERROR_CODE_502 表示网关错误", metadata={"document_id": "d1"}),
        Document(content="JVM类加载机制详解",           metadata={"document_id": "d2"}),
    ]
    ids = store.add(docs, emb.embed([d.content for d in docs]))
    for d, cid in zip(docs, ids):
        d.metadata["id"] = cid

    # 构建 BM25 索引
    retriever = HybridRetriever(emb, store)
    retriever.build_sparse_index([(d.metadata["id"], d.content) for d in docs])

    results = retriever.retrieve("ERROR_CODE_502", top_k=2)
    contents = [r.content for r in results]
    # ERROR_CODE_502 文档必须出现在结果中（BM25 精确匹配）
    assert "ERROR_CODE_502" in contents[0]


def test_second_query_uses_correct_corpus():
    """连续不同查询不会串语料（旧版 bug 回归测试）"""
    from core.retriever.hybrid import HybridRetriever

    emb = _MissEmbedding()
    store = ChromaStore(path=None, collection_name="sparse_second")

    docs = [
        Document(content="ERROR_CODE_502 表示网关错误", metadata={"document_id": "d1"}),
        Document(content="JVM类加载机制详解",           metadata={"document_id": "d2"}),
    ]
    ids = store.add(docs, emb.embed([d.content for d in docs]))
    for d, cid in zip(docs, ids):
        d.metadata["id"] = cid

    retriever = HybridRetriever(emb, store)
    retriever.build_sparse_index([(d.metadata["id"], d.content) for d in docs])

    # 第一次查询
    r1 = retriever.retrieve("ERROR_CODE_502", top_k=2)
    assert "ERROR_CODE_502" in r1[0].content

    # 第二次查询 JVM（语料不能停留在第一次）
    r2 = retriever.retrieve("JVM类加载机制详解", top_k=2)
    assert "JVM类加载" in r2[0].content
