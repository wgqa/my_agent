"""G2-ABL-16：BM25-only Retriever 正式策略最小测试"""

import pytest

from core.retriever.bm25_only import BM25OnlyRetriever
from evaluation.experiment_config import ExperimentConfig


def _build_retriever():
    r = BM25OnlyRetriever()
    r.build_sparse_index([
        ("c1", "the cat sat on the mat", {
            "id": "c1", "document_id": "d1",
        }),
        ("c2", "the dog chased the cat", {
            "id": "c2", "document_id": "d2",
        }),
        ("c3", "cat mat dog park", {
            "id": "c3", "document_id": "d3",
        }),
    ])
    return r


def test_bm25_only_retrieve_returns_sorted_docs_with_metadata():
    r = _build_retriever()
    docs = r.retrieve("cat mat", top_k=2)
    assert len(docs) == 2
    assert docs[0].metadata["sparse_score"] is not None
    assert docs[0].metadata["document_id"]
    assert docs[0].metadata["sparse_score"] >= docs[1].metadata["sparse_score"]
    assert r._bm25.doc_count == 3


def test_bm25_only_retrieve_top_k():
    r = _build_retriever()
    docs = r.retrieve("cat", top_k=5)
    assert len(docs) == 3


def test_bm25_only_same_id_update_replaces_stats():
    r = BM25OnlyRetriever()
    r.build_sparse_index([("c1", "cat mat", {"id": "c1", "document_id": "d1"})])
    r.build_sparse_index([("c1", "dog", {"id": "c1", "document_id": "d1"})])
    assert r._bm25.doc_count == 1
    docs = r.retrieve("dog", top_k=5)
    assert len(docs) == 1
    assert r.retrieve("cat", top_k=5) == []


def test_experiment_config_accepts_bm25_strategy():
    config = ExperimentConfig(retriever_strategy="bm25")
    assert config.retriever_strategy == "bm25"
    assert config.to_dict()["retriever_strategy"] == "bm25"


def test_bm25_only_retriever_has_bm25_attr():
    r = BM25OnlyRetriever()
    assert hasattr(r, "_bm25")
