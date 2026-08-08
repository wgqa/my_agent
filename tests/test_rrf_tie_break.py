"""G2-DIAG-13-R1：RRF 确定性 Tie-Break 回归测试"""

import os
import subprocess
import sys

import pytest

from core.loader.base import Document
from core.retriever.hybrid import HybridRetriever


class _Embedding:
    def embed(self, texts):
        return [[0.1, 0.2]] * len(texts)

    def embed_query(self, text):
        return [0.1, 0.2]


class _DenseStore:
    def __init__(self, docs):
        self._docs = list(docs)

    def search(self, query_emb, top_k=5, where=None):
        return self._docs[:top_k]


class _BM25Stub:
    def __init__(self, hits):
        self._hits = list(hits)

    def search(self, query, top_k=10):
        return self._hits[:top_k]

    def get_text(self, doc_id):
        return f"text {doc_id}"

    def get_meta(self, doc_id):
        return {}


def _doc(chunk_id):
    return Document(content=f"content {chunk_id}", metadata={"id": chunk_id})


def _symmetric_tie_retriever(dense_order, sparse_order):
    """构造 A: (dense2, sparse8) 与 B: (dense8, sparse2) 的完全平局。

    dense_order/sparse_order 是带 8 个条目的候选顺序；
    A 在 dense 第 2、sparse 第 8；B 在 dense 第 8、sparse 第 2。
    """
    dense_docs = [_doc(cid) for cid in dense_order]
    sparse_hits = [(cid, float(score)) for score, cid in enumerate(sparse_order, 1)]
    r = HybridRetriever(
        _Embedding(), _DenseStore(dense_docs),
        dense_candidate_k=30, sparse_candidate_k=30, final_k=20, rrf_k=60.0,
    )
    r._bm25 = _BM25Stub(sparse_hits)
    return r


def test_symmetric_rank_tie_uses_chunk_id_asc():
    # A: dense2/sparse8；B: dense8/sparse2；其余 6 个填充位
    dense_order = ["d0", "A", "d1", "d2", "d3", "d4", "d5", "B"]
    sparse_order = ["dX", "B", "d1", "d2", "d3", "d4", "d5", "A"]
    r = _symmetric_tie_retriever(dense_order, sparse_order)
    docs = r.retrieve("q", top_k=20)
    a = next(d for d in docs if d.metadata["id"] == "A")
    b = next(d for d in docs if d.metadata["id"] == "B")
    assert a.metadata["rrf_score"] == b.metadata["rrf_score"]
    assert docs.index(a) < docs.index(b), (
        "chunk_id_asc tie-break：A 应排在 B 前"
    )


def test_input_order_reversal_produces_same_ranking():
    """相同 rank/score 的候选以 A,B 与 B,A 输入，排序必须完全一致。"""
    items = [
        ("A", 0.0308349),
        ("B", 0.0308349),
        ("C", 0.0308349),
    ]
    forward = HybridRetriever._sort_rrf_scores(list(items))
    backward = HybridRetriever._sort_rrf_scores(list(reversed(items)))
    assert forward == backward


def test_sort_rrf_scores_stable_across_hash_seeds():
    """subprocess 回归：不同 PYTHONHASHSEED 下平局候选顺序一致"""
    script = (
        "from core.retriever.hybrid import HybridRetriever; "
        "items = [('B', 0.0308349), ('A', 0.0308349), ('C', 0.0308349)]; "
        "print([i for i, _ in HybridRetriever._sort_rrf_scores(items)])"
    )
    outputs = []
    for seed in ("1", "2"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        outputs.append(result.stdout.strip())
    assert outputs[0] == outputs[1] == "['A', 'B', 'C']"


def test_non_tie_unaffected_by_chunk_id_order():
    items = [
        ("Z", 0.5),
        ("A", 0.4),
    ]
    sorted_items = HybridRetriever._sort_rrf_scores(items)
    assert sorted_items[0][0] == "Z", (
        "RRF 更高者必须在前，即使 chunk_id 更大"
    )
    assert sorted_items[1][0] == "A"


def test_retriever_rejects_unknown_tie_breaker():
    with pytest.raises(ValueError, match="rrf_tie_breaker"):
        HybridRetriever(
            _Embedding(), _DenseStore([]),
            rrf_tie_breaker="dense_rank_asc",
        )
