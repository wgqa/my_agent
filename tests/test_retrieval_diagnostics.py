"""G2-DIAG-13：Hybrid Dense/BM25 Channel-Level Diagnostic Snapshot"""

import json

import pytest

from core.loader.base import Document
from core.retriever.hybrid import HybridRetriever
from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment
from evaluation.experiment_workspace import ExperimentWorkspace
from evaluation.index_manifest import FileIndexRecord, IndexManifest
from evaluation.retrieval_diagnostics import (
    RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION,
    RetrievalDiagnosticSnapshot,
    load_diagnostic_snapshot,
)
from evaluation.retrieval_evaluation_set import RetrievalCase, RetrievalEvaluationSet


BASE_CONFIG_YAML = """\
embedding:
  provider: bge
  model: BAAI/bge-small-zh-v1.5
chunker:
  strategy: recursive
  size_tokens: 512
  overlap_tokens: 64
retriever:
  strategy: hybrid
  top_k: 5
  dense_candidate_k: 30
  sparse_candidate_k: 30
  rrf_k: 60.0
reranker:
  enabled: true
  candidate_k: 20
  final_k: 5
generator:
  provider: deepseek
  model: deepseek-v4-flash
vector_store:
  path: ./data/vector_store
"""


# ============================================================
# Part 1：HybridRetriever retrieve_with_trace（retriever 层）
# ============================================================


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
    def __init__(self, hits, metas=None):
        self._hits = list(hits)
        self._metas = metas or {}

    def search(self, query, top_k=10):
        return self._hits[:top_k]

    def get_text(self, doc_id):
        return f"text {doc_id}"

    def get_meta(self, doc_id):
        return dict(self._metas.get(doc_id) or {})


def _doc(chunk_id, document_id, **extra):
    meta = {"id": chunk_id, "document_id": document_id}
    meta.update(extra)
    return Document(content=f"content {chunk_id}", metadata=meta)


def _trace_retriever(dense_docs, sparse_hits, metas=None):
    r = HybridRetriever(
        _Embedding(), _DenseStore(dense_docs),
        dense_candidate_k=30, sparse_candidate_k=30, final_k=20, rrf_k=60.0,
    )
    r._bm25 = _BM25Stub(sparse_hits, metas)
    return r


def test_retrieve_behavior_unchanged_contract():
    dense = [
        _doc("cA", "docA", score=0.9),
        _doc("cB", "docB", score=0.8),
    ]
    r = _trace_retriever(dense, [("cA", 5.0), ("cC", 3.0)], {
        "cC": {"document_id": "docC"},
    })
    first = r.retrieve("q", top_k=5)
    second = r.retrieve("q", top_k=5)
    first_ids = [d.metadata["id"] for d in first]
    assert first_ids == [d.metadata["id"] for d in second]
    for d1, d2 in zip(first, second):
        assert d1.metadata["rrf_score"] == d2.metadata["rrf_score"]
        assert d1.metadata["dense_rank"] == d2.metadata["dense_rank"]
        assert d1.metadata["sparse_rank"] == d2.metadata["sparse_rank"]


def test_trace_dense_rank_1_to_n():
    dense = [_doc("c1", "d1"), _doc("c2", "d2"), _doc("c3", "d3")]
    r = _trace_retriever(dense, [])
    trace = r.retrieve_with_trace("q", top_k=5)
    assert [c["rank"] for c in trace["dense_candidates"]] == [1, 2, 3]


def test_trace_sparse_rank_1_to_n():
    r = _trace_retriever([], [("s1", 5.0), ("s2", 4.0), ("s3", 3.0)], {
        "s1": {"document_id": "d1"},
        "s2": {"document_id": "d2"},
        "s3": {"document_id": "d3"},
    })
    trace = r.retrieve_with_trace("q", top_k=5)
    assert [c["rank"] for c in trace["sparse_candidates"]] == [1, 2, 3]


def test_absent_channel_does_not_fabricate_scores():
    dense = [_doc("c1", "d1")]  # 无 score/distance
    r = _trace_retriever(dense, [("s1", 5.0)], {"s1": {"document_id": "d9"}})
    trace = r.retrieve_with_trace("q", top_k=5)
    dense_item = trace["dense_candidates"][0]
    assert "score" not in dense_item
    assert "distance" not in dense_item
    assert dense_item["chunk_id"] == "c1"
    sparse_item = trace["sparse_candidates"][0]
    assert sparse_item["sparse_score"] == 5.0


def test_sparse_only_candidate_document_id_from_meta():
    r = _trace_retriever([], [("s1", 5.0)], {"s1": {"document_id": "docC"}})
    trace = r.retrieve_with_trace("q", top_k=5)
    assert trace["sparse_candidates"][0]["document_id"] == "docC"
    assert trace["sparse_candidates"][0]["chunk_id"] == "s1"


def test_final_hit_matches_retrieve_contract():
    dense = [_doc("cA", "docA", score=0.9), _doc("cB", "docB", score=0.8)]
    r = _trace_retriever(dense, [("cA", 5.0), ("cC", 3.0)], {
        "cC": {"document_id": "docC"},
    })
    normal = r.retrieve("q", top_k=5)
    trace = r.retrieve_with_trace("q", top_k=5)
    normal_ids = [d.metadata["id"] for d in normal]
    trace_ids = [d.metadata["id"] for d in trace["final_results"]]
    assert normal_ids == trace_ids
    for d1, d2 in zip(normal, trace["final_results"]):
        assert d1.metadata["dense_rank"] == d2.metadata["dense_rank"]
        assert d1.metadata["sparse_rank"] == d2.metadata["sparse_rank"]
        assert d1.metadata["rrf_score"] == d2.metadata["rrf_score"]


# ============================================================
# Part 2：Runner run_retrieval_diagnostics（runner 层）
# ============================================================


class _FakeDoc:
    def __init__(self, metadata):
        self.metadata = metadata


class _TraceRetriever:
    def __init__(self, traces):
        self._traces = traces
        self.calls = []

    def retrieve_with_trace(self, query, top_k=5):
        self.calls.append((query, top_k))
        return self._traces[query]


class _FakePipeline:
    def __init__(self, retriever):
        self.retriever = retriever


def _prepare(tmp_path, config, retriever):
    base = tmp_path / "base_config.yaml"
    base.write_text(BASE_CONFIG_YAML, encoding="utf-8")
    paths = ExperimentWorkspace(base, tmp_path / "runs", config, "run1").prepare()
    return PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=_FakePipeline(retriever)
    )


def _make_manifest(config):
    records = [
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="d1", chunks=1, status="create",
        ),
        FileIndexRecord(
            relative_path="docs/x.md", sha256="b" * 64, size_bytes=10,
            document_id="d2", chunks=1, status="create",
        ),
    ]
    return IndexManifest(
        schema_version=1,
        experiment_id=config.experiment_id,
        corpus_id="corpus-001",
        chunk_strategy=config.chunk_strategy,
        retriever_strategy=config.retriever_strategy,
        config=config.to_dict(),
        corpus_entries=(),
        files=tuple(records),
        file_count=2,
        total_chunks=2,
        vector_store_count=2,
        sparse_index_count=2,
    )


def _write_baseline(path, cases):
    path.write_text(json.dumps({
        "schema_version": 1,
        "cases": cases,
    }, ensure_ascii=False), encoding="utf-8")


def _default_traces():
    return {
        "query one": {
            "dense_candidates": [
                {"rank": 1, "chunk_id": "c1", "document_id": "d1",
                 "score": 0.9},
                {"rank": 2, "chunk_id": "cX", "document_id": "d2",
                 "score": 0.7},
            ],
            "sparse_candidates": [
                {"rank": 1, "chunk_id": "c1", "document_id": "d1",
                 "sparse_score": 5.0},
                {"rank": 2, "chunk_id": "cS", "document_id": "d2",
                 "sparse_score": 3.0},
            ],
            "final_results": [
                _FakeDoc({
                    "id": "c1", "document_id": "d1", "score": 0.9,
                    "rrf_score": 0.032787, "dense_rank": 1, "sparse_rank": 1,
                }),
            ],
        },
        "query two": {
            "dense_candidates": [
                {"rank": 1, "chunk_id": "c2", "document_id": "d2",
                 "score": 0.8},
            ],
            "sparse_candidates": [
                {"rank": 1, "chunk_id": "c2", "document_id": "d2",
                 "sparse_score": 4.0},
            ],
            "final_results": [
                _FakeDoc({
                    "id": "c2", "document_id": "d2", "score": 0.8,
                    "rrf_score": 0.032787, "dense_rank": 1, "sparse_rank": 1,
                }),
            ],
        },
    }


def _eval_set():
    return RetrievalEvaluationSet(
        corpus_id="corpus-001",
        cases=(
            RetrievalCase("q001", "query one", ("core/pipeline.py",)),
            RetrievalCase("q002", "query two", ("docs/x.md",)),
        ),
        evaluation_set_id="evalset-001",
    )


def _run_diagnostics(tmp_path, traces=None, baseline_hits=None):
    config = ExperimentConfig()
    retriever = _TraceRetriever(traces or _default_traces())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config)
    manifest.write_json(prepared.paths.index_manifest_path)
    baseline_hits = baseline_hits or {
        "q001": [{"chunk_id": "c1"}],
        "q002": [{"chunk_id": "c2"}],
    }
    baseline_path = tmp_path / "baseline_results.json"
    _write_baseline(baseline_path, [
        {"case_id": cid, "hits": hits}
        for cid, hits in baseline_hits.items()
    ])
    eval_set = _eval_set()
    runner = ExperimentRunner(tmp_path / "base_config.yaml", tmp_path / "runs")
    snapshot = runner.run_retrieval_diagnostics(
        prepared,
        manifest,
        eval_set,
        baseline_retrieval_run_id="baseline-run-1",
        baseline_results_path=baseline_path,
    )
    return snapshot, prepared, retriever


def test_dense_only_candidate_maps_relative_path(tmp_path):
    traces = _default_traces()
    traces["query one"]["sparse_candidates"] = []
    snapshot, prepared, _ = _run_diagnostics(tmp_path, traces=traces)
    case = snapshot.cases[0]
    dense = case.dense_candidates[0]
    assert dense.relative_path == "core/pipeline.py"
    assert dense.scores["score"] == 0.9
    raw = json.loads(
        prepared.paths.retrieval_diagnostics_path.read_text(encoding="utf-8")
    )
    assert raw["cases"][0]["dense_candidates"][0]["relative_path"] == (
        "core/pipeline.py"
    )


def test_sparse_only_candidate_maps_relative_path(tmp_path):
    traces = _default_traces()
    traces["query one"]["dense_candidates"] = []
    snapshot, _, _ = _run_diagnostics(tmp_path, traces=traces)
    sparse = snapshot.cases[0].sparse_candidates[1]
    assert sparse.relative_path == "docs/x.md"
    assert sparse.scores["sparse_score"] == 3.0


def test_final_match_baseline_success(tmp_path):
    snapshot, prepared, retriever = _run_diagnostics(tmp_path)
    assert prepared.paths.retrieval_diagnostics_path.is_file()
    assert len(retriever.calls) == 2
    assert [h.chunk_id for h in snapshot.cases[0].final_hits] == ["c1"]
    payload = load_diagnostic_snapshot(prepared.paths.retrieval_diagnostics_path)
    assert payload["baseline_retrieval_run_id"] == "baseline-run-1"
    assert payload["dense_candidate_k"] == 30
    assert payload["sparse_candidate_k"] == 30


def test_final_mismatch_baseline_fails(tmp_path):
    baseline_hits = {"q001": [{"chunk_id": "WRONG"}], "q002": [{"chunk_id": "c2"}]}
    config = ExperimentConfig()
    retriever = _TraceRetriever(_default_traces())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config)
    manifest.write_json(prepared.paths.index_manifest_path)
    baseline_path = tmp_path / "baseline_results.json"
    _write_baseline(baseline_path, [
        {"case_id": cid, "hits": hits}
        for cid, hits in baseline_hits.items()
    ])
    with pytest.raises(RuntimeError, match="diagnostic != baseline"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval_diagnostics(
            prepared, manifest, _eval_set(),
            baseline_retrieval_run_id="baseline-run-1",
            baseline_results_path=baseline_path,
        )
    assert not prepared.paths.retrieval_diagnostics_path.exists()


def test_schema_stable_serialization():
    from evaluation.retrieval_diagnostics import ChannelCandidate, DiagnosticCase
    candidate = ChannelCandidate(
        rank=1, chunk_id="c1", document_id="d1",
        relative_path="a.md", scores={"score": 0.9},
    )
    case = DiagnosticCase(
        case_id="q001", query="q", relevant_files=("a.md",),
        dense_candidates=(candidate,), sparse_candidates=(),
        final_hits=(candidate,),
    )
    snapshot = RetrievalDiagnosticSnapshot(
        schema_version=RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION,
        diagnostic_id="id-1",
        experiment_id="e",
        corpus_id="c",
        evaluation_set_id="s",
        baseline_retrieval_run_id="r",
        dense_candidate_k=30,
        sparse_candidate_k=30,
        cases=(case,),
    )
    assert snapshot.to_json() == snapshot.to_json()
    d = snapshot.to_dict()
    assert d["schema_version"] == RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION
    assert d["cases"][0]["dense_candidates"][0]["relative_path"] == "a.md"


def test_diagnostic_id_stable_and_binds_baseline_run_id():
    kwargs = dict(
        schema_version=1,
        experiment_id="e",
        corpus_id="c",
        evaluation_set_id="s",
        baseline_retrieval_run_id="r",
        dense_candidate_k=30,
        sparse_candidate_k=30,
    )
    assert RetrievalDiagnosticSnapshot.compute_diagnostic_id(**kwargs) == (
        RetrievalDiagnosticSnapshot.compute_diagnostic_id(**kwargs)
    )
    changed = dict(kwargs, baseline_retrieval_run_id="r2")
    assert RetrievalDiagnosticSnapshot.compute_diagnostic_id(**kwargs) != (
        RetrievalDiagnosticSnapshot.compute_diagnostic_id(**changed)
    )
    changed_k = dict(kwargs, dense_candidate_k=10)
    assert RetrievalDiagnosticSnapshot.compute_diagnostic_id(**kwargs) != (
        RetrievalDiagnosticSnapshot.compute_diagnostic_id(**changed_k)
    )


def test_load_rejects_invalid_and_non_object(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="解析"):
        load_diagnostic_snapshot(bad)
    arr = tmp_path / "arr.json"
    arr.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="顶层不是 JSON object"):
        load_diagnostic_snapshot(arr)
    missing = tmp_path / "missing.json"
    missing.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="缺少字段"):
        load_diagnostic_snapshot(missing)


def test_atomic_write_failure_leaves_no_file(tmp_path, monkeypatch):
    import evaluation.retrieval_diagnostics as diag_module
    from evaluation.retrieval_diagnostics import ChannelCandidate, DiagnosticCase

    candidate = ChannelCandidate(
        rank=1, chunk_id="c1", document_id="d1",
        relative_path="a.md", scores={"score": 0.9},
    )
    case = DiagnosticCase(
        case_id="q001", query="q", relevant_files=("a.md",),
        dense_candidates=(candidate,), sparse_candidates=(),
        final_hits=(candidate,),
    )
    snapshot = RetrievalDiagnosticSnapshot(
        diagnostic_id="id", experiment_id="e", corpus_id="c",
        evaluation_set_id="s", baseline_retrieval_run_id="r",
        dense_candidate_k=30, sparse_candidate_k=30, cases=(case,),
    )
    target = tmp_path / "retrieval_diagnostics.json"

    def boom(src, dst):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(diag_module.os, "replace", boom)
    with pytest.raises(OSError, match="atomic replace failed"):
        snapshot.write_json(target)
    assert not target.exists()
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_diagnostics_path_is_dedicated(tmp_path):
    config = ExperimentConfig()
    prepared = _prepare(tmp_path, config, _TraceRetriever({}))
    assert prepared.paths.retrieval_diagnostics_path == (
        prepared.paths.workspace_path / "retrieval_diagnostics.json"
    )
    assert prepared.paths.retrieval_diagnostics_path != (
        prepared.paths.retrieval_results_path
    )
