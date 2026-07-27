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
