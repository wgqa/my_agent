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
