from core.loader.base import Document
from core.vector_store.chroma_store import ChromaStore


def test_chroma_store_add_and_count():
    store = ChromaStore(path=None, collection_name="test_add")
    docs = [Document(content="hello world"), Document(content="foo bar")]
    embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    ids = store.add(docs, embeddings)

    assert len(ids) == 2
    assert store.count() == 2


def test_chroma_store_search():
    store = ChromaStore(path=None, collection_name="test_search")
    docs = [Document(content="hello world", metadata={"source": "test.txt"})]
    embeddings = [[0.1, 0.2, 0.3]]
    store.add(docs, embeddings)

    results = store.search([0.1, 0.2, 0.3], top_k=1)
    assert len(results) == 1
    assert "hello" in results[0].content
    assert results[0].metadata["source"] == "test.txt"


def test_chroma_store_empty_search():
    store = ChromaStore(path=None, collection_name="test_empty")
    results = store.search([0.1, 0.2, 0.3])
    assert len(results) == 0


def test_chroma_store_delete():
    store = ChromaStore(path=None, collection_name="test_delete")
    docs = [Document(content="test")]
    ids = store.add(docs, [[0.1, 0.2, 0.3]])
    assert store.count() == 1
    store.delete(ids)
    assert store.count() == 0


# ── M1-T2 回归测试 ─────────────────────────────────────

def test_upsert_same_chunk_is_idempotent():
    store = ChromaStore(path=None, collection_name="test_idempotent")
    doc = Document(content="unique", metadata={"document_id": "d1"})
    ids1 = store.upsert([doc], [[0.1, 0.2, 0.3]])
    ids2 = store.upsert([doc], [[0.1, 0.2, 0.3]])
    assert ids1 == ids2
    assert store.count() == 1


def test_delete_then_add_does_not_reuse_existing_id():
    store = ChromaStore(path=None, collection_name="test_reuse")
    doc = Document(content="hello", metadata={"document_id": "d1"})
    ids = store.add([doc], [[0.1, 0.2, 0.3]])
    assert store.count() == 1
    store.delete(ids)
    assert store.count() == 0
    ids2 = store.add([doc], [[0.1, 0.2, 0.3]])
    assert store.count() == 1
    assert ids2[0] == ids[0]


def test_search_returns_distance_and_rank():
    store = ChromaStore(path=None, collection_name="test_dist_rank")
    docs = [Document(content="a"), Document(content="b")]
    store.add(docs, [[0.1, 0.2, 0.3], [0.5, 0.6, 0.7]])
    results = store.search([0.1, 0.2, 0.3], top_k=2)
    for r in results:
        assert "distance" in r.metadata
        assert "score" in r.metadata
        assert "rank" in r.metadata
    assert results[0].metadata["score"] >= results[1].metadata["score"]


def test_delete_by_document_removes_only_target():
    store = ChromaStore(path=None, collection_name="test_delete_doc")
    store.add([Document(content="redis", metadata={"document_id": "a"})], [[0.1, 0.2]])
    store.add([Document(content="jvm", metadata={"document_id": "b"})], [[0.3, 0.4]])
    assert store.count() == 2
    store.delete_by_document_id("a")
    assert store.count() == 1
    remaining = store.search([0.1, 0.2], top_k=5)
    assert "a" not in [r.metadata["document_id"] for r in remaining]


def test_filter_by_document_id():
    store = ChromaStore(path=None, collection_name="test_filter")
    store.add([Document(content="x", metadata={"document_id": "d1"}),
               Document(content="y", metadata={"document_id": "d2"})],
              [[0.1, 0.2], [0.3, 0.4]])
    results = store.search([0.1, 0.2], top_k=5, where={"document_id": "d1"})
    for r in results:
        assert r.metadata["document_id"] == "d1"


def test_embedding_dimension_mismatch_fails():
    store = ChromaStore(path=None, collection_name="test_dim")
    store.add([Document(content="a")], [[0.1, 0.2, 0.3]])
    try:
        store.add([Document(content="b")], [[0.5, 0.6]])
        assert False
    except ValueError:
        pass


def test_empty_batch_is_handled_explicitly():
    store = ChromaStore(path=None, collection_name="test_empty_batch")
    ids = store.add([], [])
    assert ids == []
    assert store.count() == 0


def test_upsert_sets_id_on_all_input_docs_including_deduped():
    """upsert 去重后，输入中每个 doc（含被去重的）都必须拿到正确的 id"""
    store = ChromaStore(path=None, collection_name="align_test")
    docs = [
        Document(content="内容A", metadata={"document_id": "doc1"}),
        Document(content="内容B", metadata={"document_id": "doc1"}),
        Document(content="内容A", metadata={"document_id": "doc1"}),  # 中间重复
        Document(content="内容C", metadata={"document_id": "doc1"}),
    ]
    store.upsert(docs, [[0.1] * 512] * 4)

    ids = [d.metadata.get("id") for d in docs]
    assert all(ids), f"去重后被跳过的 doc 缺少 id: {ids}"
    assert ids[0] == ids[2]  # 重复内容同 id
    assert ids[1] != ids[0]
    assert ids[3] != ids[0]
    assert store.count() == 3
