from core.loader.base import Document
from core.reranker.base import BaseReranker


def test_base_reranker_abstract():
    try:
        BaseReranker()
        assert False
    except TypeError:
        pass


def test_bge_reranker_initialization():
    from core.reranker.bge_reranker import BGEReranker
    reranker = BGEReranker()
    assert reranker.model_name == "BAAI/bge-reranker-v2-m3"


def test_reranker_empty_docs():
    from core.reranker.bge_reranker import BGEReranker
    reranker = BGEReranker()
    result = reranker.rerank("test", [])
    assert result == []


class _FakeRerankModel:
    def __init__(self, scores):
        self._scores = scores

    def predict(self, pairs):
        return self._scores


def _reranker_with_scores(scores):
    from core.reranker.bge_reranker import BGEReranker
    reranker = BGEReranker()
    reranker._model = _FakeRerankModel(scores)
    return reranker


def test_rerank_writes_score_and_rank_to_metadata():
    docs = [
        Document(content="aaa", metadata={"id": "1", "score": 0.9}),
        Document(content="bbb", metadata={"id": "2", "score": 0.1}),
    ]
    reranker = _reranker_with_scores([0.2, 0.8])
    result = reranker.rerank("q", docs, top_k=2)
    # 按 rerank 分数重排（与稠密分数顺序相反）
    assert [d.metadata["id"] for d in result] == ["2", "1"]
    assert result[0].metadata["rerank_score"] == 0.8
    assert result[1].metadata["rerank_score"] == 0.2
    assert result[0].metadata["final_rank"] == 1
    assert result[1].metadata["final_rank"] == 2


def test_rerank_preserves_original_score():
    docs = [Document(content="aaa", metadata={"id": "1", "score": 0.9})]
    reranker = _reranker_with_scores([0.3])
    result = reranker.rerank("q", docs, top_k=1)
    assert result[0].metadata["score"] == 0.9
