import pytest

from evaluation.report import generate_report
from evaluation.evaluator import Evaluator, QAPair
from core.pipeline import Pipeline


def test_generate_report_empty():
    assert generate_report([]) == "No results."


def test_generate_report_basic():
    results = [
        {"chunk": "fixed", "hit_at_k": 0.8, "mrr": 0.6, "recall_at_k": 0.7},
        {"chunk": "recursive", "hit_at_k": 0.9, "mrr": 0.7, "recall_at_k": 0.8},
    ]
    report = generate_report(results)
    assert "评估对比报告" in report
    assert "0.900" in report
    assert "recursive" in report


def test_report_sorts_by_hit_at_k_and_shows_best():
    """报告按 hit_at_k 排序（B 在前），最佳配置显示 0.8 而非默认 0"""
    results = [
        {"chunk": "A", "hit_at_k": 0.5, "mrr": 0.3, "ndcg": 0.2},
        {"chunk": "B", "hit_at_k": 0.8, "mrr": 0.6, "ndcg": 0.5},
    ]
    report = generate_report(results)
    assert report.index("B") < report.index("A"), "B 必须排在 A 前面"
    assert "Hit@K: 0.800" in report, "最佳配置必须显示 0.8"
    assert "Hit Rate: 0.000" not in report and "Hit@K: 0.000" not in report


class _FakeHit:
    metadata = {"id": "hit1"}


class _FakeRetriever:
    def __init__(self, events=None):
        self.called = False
        self.events = events if events is not None else []

    def retrieve(self, query, top_k=5):
        self.called = True
        self.events.append("retrieve")
        return [_FakeHit()]


class _FakeCollection:
    def __init__(self, data):
        self._data = data

    def get(self, include=None):
        if self._data is None:
            raise RuntimeError("collection read failed")
        return self._data


class _FakeVectorStore:
    def __init__(self, data=None):
        self.collection = _FakeCollection(data)


class _FakeBM25:
    def __init__(self):
        self._count = 0

    @property
    def doc_count(self):
        return self._count


class _FakeHybridRetriever:
    """带 build_sparse_index + _bm25.doc_count 的 Hybrid 替身"""

    def __init__(self, fail_build=False, count_after=None):
        self.fail_build = fail_build
        self._count_after = count_after
        self._bm25 = _FakeBM25()
        self.called = False

    def build_sparse_index(self, pairs):
        if self.fail_build:
            raise RuntimeError("build_sparse_index failed")
        self._bm25._count = (
            self._count_after if self._count_after is not None else len(pairs)
        )

    def retrieve(self, query, top_k=5):
        self.called = True
        return [_FakeHit()]


class _FakePipeline:
    def __init__(self, retriever=None, vector_data=None):
        self.events = []
        self.retriever = retriever if retriever is not None else _FakeRetriever(self.events)
        self.vector_store = _FakeVectorStore(vector_data)

    def _init_retriever(self):
        self.events.append("init_retriever")
        return self.retriever

    def _rebuild_sparse_index(self, strict=False):
        self.events.append("rebuild_sparse_index")
        return Pipeline._rebuild_sparse_index(self, strict=strict)


def test_evaluator_rejects_multi_chunk_strategy_before_retrieval():
    """跨 chunk_strategy 对比在检索前抛异常，信息说明索引未重建"""
    evaluator = Evaluator(_FakePipeline(), [QAPair("q", ["hit1"])])
    with pytest.raises(ValueError, match="重建"):
        evaluator.run({"chunk_strategy": ["fixed", "recursive"]})
    assert evaluator.pipeline.retriever.called is False


def test_evaluator_single_chunk_strategy_not_blocked():
    """单一 chunk_strategy 值不触发保护，实验正常执行"""
    evaluator = Evaluator(_FakePipeline(), [QAPair("q", ["hit1"])])
    results = evaluator.run({"chunk_strategy": ["fixed"]})
    assert len(results) == 1
    assert results[0]["hit_at_k"] == 1.0


def test_evaluator_rebuilds_sparse_index_before_retrieve():
    """每组实验顺序：init_retriever → rebuild_sparse_index → retrieve（top_k 场景）"""
    pipeline = _FakePipeline()
    evaluator = Evaluator(pipeline, [QAPair("q", ["hit1"])])
    evaluator.run({"top_k": [3]})
    events = pipeline.events
    assert "init_retriever" in events
    assert "rebuild_sparse_index" in events
    assert events.index("init_retriever") < events.index("rebuild_sparse_index"), \
        "重建稀疏索引必须在重建 Retriever 之后"
    assert events.index("rebuild_sparse_index") < events.index("retrieve"), \
        "稀疏索引重建必须在本组实验第一次检索之前"


VECTOR_DATA = {
    "ids": ["c1", "c2"],
    "documents": ["text one", "text two"],
    "metadatas": [{"id": "c1"}, {"id": "c2"}],
}


def test_rebuild_strict_success_returns_built_count():
    """Hybrid 重建成功：返回实际重建文档数，BM25 计数正确"""
    pipeline = _FakePipeline(retriever=_FakeHybridRetriever(), vector_data=VECTOR_DATA)
    count = pipeline._rebuild_sparse_index(strict=True)
    assert count == 2
    assert pipeline.retriever._bm25.doc_count == 2


def test_rebuild_strict_raises_on_build_failure():
    """VectorStore 有数据但构建失败：严格模式抛异常，信息说明评测终止"""
    pipeline = _FakePipeline(retriever=_FakeHybridRetriever(fail_build=True),
                             vector_data=VECTOR_DATA)
    with pytest.raises(RuntimeError, match="Sparse retrieval 评测已终止"):
        pipeline._rebuild_sparse_index(strict=True)


def test_rebuild_non_strict_keeps_tolerant_on_failure():
    """普通模式（默认）构建失败不抛异常，返回 0 保留原容错"""
    pipeline = _FakePipeline(retriever=_FakeHybridRetriever(fail_build=True),
                             vector_data=VECTOR_DATA)
    assert pipeline._rebuild_sparse_index() == 0


def test_rebuild_strict_raises_when_bm25_empty_despite_data():
    """VectorStore 有数据但 BM25 文档数为 0：严格模式抛异常"""
    pipeline = _FakePipeline(retriever=_FakeHybridRetriever(count_after=0),
                             vector_data=VECTOR_DATA)
    with pytest.raises(RuntimeError, match="BM25 文档数为 0"):
        pipeline._rebuild_sparse_index(strict=True)


def test_rebuild_strict_raises_on_count_mismatch():
    """BM25 文档数与可索引 chunk 数不一致：严格模式抛异常"""
    pipeline = _FakePipeline(retriever=_FakeHybridRetriever(count_after=1),
                             vector_data=VECTOR_DATA)
    with pytest.raises(RuntimeError, match="不一致"):
        pipeline._rebuild_sparse_index(strict=True)


def test_rebuild_strict_skips_non_hybrid_retriever():
    """Simple/MMR（无 build_sparse_index）：严格模式也安全跳过"""
    pipeline = _FakePipeline(retriever=_FakeRetriever(), vector_data=VECTOR_DATA)
    assert pipeline._rebuild_sparse_index(strict=True) == 0


def test_evaluator_strict_mode_aborts_before_retrieve():
    """Evaluator 严格模式：重建失败时在第一次 retrieve 前终止"""
    pipeline = _FakePipeline(retriever=_FakeHybridRetriever(fail_build=True),
                             vector_data=VECTOR_DATA)
    evaluator = Evaluator(pipeline, [QAPair("q", ["hit1"])])
    with pytest.raises(RuntimeError, match="Sparse retrieval 评测已终止"):
        evaluator.run({"top_k": [3]})
    assert pipeline.retriever.called is False
