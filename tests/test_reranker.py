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
