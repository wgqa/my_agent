"""G2-EVAL-09：ExperimentResult 最终实验摘要与事实快照绑定"""

import dataclasses
import json
import math

import pytest

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_result import (
    EXPERIMENT_RESULT_SCHEMA_VERSION,
    ExperimentResult,
)
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment
from evaluation.experiment_workspace import ExperimentWorkspace
from evaluation.index_manifest import FileIndexRecord, IndexManifest
from evaluation.retrieval_evaluation_set import RetrievalCase, RetrievalEvaluationSet
from evaluation.retrieval_metrics import (
    AGGREGATION,
    METRICS_SCHEMA_VERSION,
    METRIC_SCOPE,
    RELEVANCE,
    RetrievalCaseMetrics,
    RetrievalMetricsResult,
)
from evaluation.retrieval_result import (
    RETRIEVAL_RESULT_SCHEMA_VERSION,
    RetrievalCaseResult,
    RetrievalHit,
    RetrievalRunResult,
)


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


def _write_base_config(tmp_path):
    path = tmp_path / "base_config.yaml"
    path.write_text(BASE_CONFIG_YAML, encoding="utf-8")
    return path


def _prepare(tmp_path, config=None):
    config = config or ExperimentConfig()
    base = _write_base_config(tmp_path)
    paths = ExperimentWorkspace(base, tmp_path / "runs", config, "run1").prepare()
    return PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=object()
    )


def _make_manifest(
    config=None,
    corpus_id="corpus-001",
    *,
    experiment_id=None,
    chunk_strategy=None,
    retriever_strategy=None,
    sparse_index_count=None,
    file_count=None,
    total_chunks=None,
    vector_store_count=None,
):
    config = config or ExperimentConfig()
    records = [
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="d1", chunks=2, status="create",
        ),
        FileIndexRecord(
            relative_path="docs/x.md", sha256="b" * 64, size_bytes=10,
            document_id="d2", chunks=1, status="create",
        ),
    ]
    total = total_chunks if total_chunks is not None else sum(f.chunks for f in records)
    vs = vector_store_count if vector_store_count is not None else total
    effective_retriever = (
        retriever_strategy if retriever_strategy is not None
        else config.retriever_strategy
    )
    if sparse_index_count is None and effective_retriever == "hybrid":
        sparse_index_count = vs
    return IndexManifest(
        schema_version=1,
        experiment_id=experiment_id if experiment_id is not None else config.experiment_id,
        corpus_id=corpus_id,
        chunk_strategy=chunk_strategy if chunk_strategy is not None else config.chunk_strategy,
        retriever_strategy=effective_retriever,
        config=config.to_dict(),
        corpus_entries=(),
        files=tuple(records),
        file_count=file_count if file_count is not None else len(records),
        total_chunks=total,
        vector_store_count=vs,
        sparse_index_count=sparse_index_count,
    )


def _hit(rank, chunk_id, document_id, relative_path):
    return RetrievalHit(
        rank=rank,
        chunk_id=chunk_id,
        document_id=document_id,
        relative_path=relative_path,
        scores={},
    )


def _case_result(case_id, query, relevant_files, hits):
    files = []
    for h in hits:
        if h.relative_path not in files:
            files.append(h.relative_path)
    return RetrievalCaseResult(
        case_id=case_id,
        query=query,
        relevant_files=tuple(relevant_files),
        hits=tuple(hits),
        retrieved_files=tuple(files),
    )


def _default_run_cases():
    return [
        _case_result("q001", "query one", ("a.md",), [_hit(1, "c1", "d1", "a.md")]),
        _case_result(
            "q002", "query two", ("a.md", "b.md", "c.md"),
            [_hit(1, "c7", "d2", "b.md"), _hit(2, "c1", "d1", "a.md")],
        ),
    ]


def _default_eval_cases():
    return [
        RetrievalCase("q001", "query one", ("a.md",)),
        RetrievalCase("q002", "query two", ("a.md", "b.md", "c.md")),
    ]


def _make_run_result(
    config=None,
    corpus_id="corpus-001",
    evaluation_set_id="evalset-001",
    *,
    cases=None,
    experiment_id=None,
    retriever_strategy=None,
    top_k=None,
    retrieval_run_id=None,
):
    config = config or ExperimentConfig()
    experiment_id = experiment_id or config.experiment_id
    retriever_strategy = retriever_strategy or config.retriever_strategy
    top_k = top_k if top_k is not None else config.top_k
    run_id = retrieval_run_id or RetrievalRunResult.compute_run_id(
        schema_version=RETRIEVAL_RESULT_SCHEMA_VERSION,
        experiment_id=experiment_id,
        corpus_id=corpus_id,
        evaluation_set_id=evaluation_set_id,
        retriever_strategy=retriever_strategy,
        top_k=top_k,
    )
    return RetrievalRunResult(
        schema_version=RETRIEVAL_RESULT_SCHEMA_VERSION,
        retrieval_run_id=run_id,
        experiment_id=experiment_id,
        corpus_id=corpus_id,
        evaluation_set_id=evaluation_set_id,
        retriever_strategy=retriever_strategy,
        top_k=top_k,
        cases=tuple(cases if cases is not None else _default_run_cases()),
    )


def _default_case_metrics():
    ndcg_q2 = (1.0 + 1.0 / math.log2(3)) / (
        1.0 + 1.0 / math.log2(3) + 0.5
    )
    return [
        RetrievalCaseMetrics(
            case_id="q001", hit_at_k=1.0, recall_at_k=1.0, mrr=1.0,
            ndcg_at_k=1.0, relevant_file_count=1, retrieved_file_count=1,
            first_relevant_rank=1,
        ),
        RetrievalCaseMetrics(
            case_id="q002", hit_at_k=1.0, recall_at_k=2.0 / 3.0, mrr=1.0,
            ndcg_at_k=ndcg_q2, relevant_file_count=3, retrieved_file_count=2,
            first_relevant_rank=1,
        ),
    ]


def _make_metrics_result(
    config=None,
    corpus_id="corpus-001",
    evaluation_set_id="evalset-001",
    retrieval_run_id="run-1",
    *,
    cases=None,
    experiment_id=None,
    retriever_strategy=None,
    top_k=None,
    metrics_run_id=None,
    case_count=None,
    means=None,
):
    config = config or ExperimentConfig()
    experiment_id = experiment_id or config.experiment_id
    retriever_strategy = retriever_strategy or config.retriever_strategy
    top_k = top_k if top_k is not None else config.top_k
    cases = cases if cases is not None else _default_case_metrics()
    run_id = metrics_run_id or RetrievalMetricsResult.compute_metrics_run_id(
        schema_version=METRICS_SCHEMA_VERSION,
        retrieval_run_id=retrieval_run_id,
        evaluation_set_id=evaluation_set_id,
        top_k=top_k,
        metric_scope=METRIC_SCOPE,
        relevance=RELEVANCE,
        aggregation=AGGREGATION,
    )
    means = means if means is not None else {
        "hit": sum(c.hit_at_k for c in cases) / len(cases),
        "recall": sum(c.recall_at_k for c in cases) / len(cases),
        "mrr": sum(c.mrr for c in cases) / len(cases),
        "ndcg": sum(c.ndcg_at_k for c in cases) / len(cases),
    }
    return RetrievalMetricsResult(
        schema_version=METRICS_SCHEMA_VERSION,
        metrics_run_id=run_id,
        experiment_id=experiment_id,
        corpus_id=corpus_id,
        evaluation_set_id=evaluation_set_id,
        retrieval_run_id=retrieval_run_id,
        retriever_strategy=retriever_strategy,
        top_k=top_k,
        case_count=case_count if case_count is not None else len(cases),
        cases=tuple(cases),
        mean_hit_at_k=means["hit"],
        mean_recall_at_k=means["recall"],
        mean_mrr=means["mrr"],
        mean_ndcg_at_k=means["ndcg"],
    )


def _default_objects(config=None, corpus_id="corpus-001"):
    config = config or ExperimentConfig()
    run_result = _make_run_result(config=config, corpus_id=corpus_id)
    metrics_result = _make_metrics_result(
        config=config,
        corpus_id=corpus_id,
        retrieval_run_id=run_result.retrieval_run_id,
    )
    manifest = _make_manifest(config, corpus_id)
    eval_set = RetrievalEvaluationSet(
        corpus_id=corpus_id,
        cases=tuple(_default_eval_cases()),
        evaluation_set_id="evalset-001",
    )
    return manifest, run_result, metrics_result, eval_set


def _write_all(prepared, manifest, run_result, metrics_result):
    manifest.write_json(prepared.paths.index_manifest_path)
    run_result.write_json(prepared.paths.retrieval_results_path)
    metrics_result.write_json(prepared.paths.retrieval_metrics_path)


def _finalize(tmp_path, config=None, objects=None):
    config = config or ExperimentConfig()
    objects = objects or _default_objects(config)
    manifest, run_result, metrics_result, eval_set = objects
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    result = ExperimentRunner(
        tmp_path / "base_config.yaml", tmp_path / "runs"
    ).finalize_result(
        prepared, manifest, run_result, metrics_result, eval_set
    )
    return result, prepared


def test_finalize_success(tmp_path):
    result, prepared = _finalize(tmp_path)
    assert prepared.paths.result_path.is_file()
    assert result.experiment_id == ExperimentConfig().experiment_id
    assert result.corpus_id == "corpus-001"
    assert result.evaluation_set_id == "evalset-001"
    assert result.retrieval_run_id
    assert result.metrics_run_id
    assert result.result_id


def test_result_json_fields_correct(tmp_path):
    config = ExperimentConfig()
    result, prepared = _finalize(tmp_path, config=config)
    raw = json.loads(prepared.paths.result_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == EXPERIMENT_RESULT_SCHEMA_VERSION
    assert raw["result_id"] == result.result_id
    assert raw["experiment_id"] == config.experiment_id
    assert raw["corpus_id"] == "corpus-001"
    assert raw["evaluation_set_id"] == "evalset-001"
    assert raw["config"] == config.to_dict()
    assert raw["config"]["embedding_provider"] == "bge"
    assert raw["config"]["embedding_model"] == "BAAI/bge-small-zh-v1.5"
    assert raw["config"]["rrf_tie_breaker"] == "chunk_id_asc"
    assert raw["chunk_strategy"] == config.chunk_strategy
    assert raw["retriever_strategy"] == config.retriever_strategy
    assert raw["top_k"] == config.top_k
    assert raw["file_count"] == 2
    assert raw["total_chunks"] == 3
    assert raw["case_count"] == 2
    assert raw["artifacts"] == {
        "index_manifest": "index_manifest.json",
        "retrieval_results": "retrieval_results.json",
        "retrieval_metrics": "retrieval_metrics.json",
    }


def test_summary_matches_metrics_result(tmp_path):
    result, _ = _finalize(tmp_path)
    _, _, metrics_result, _ = _default_objects()
    assert result.case_count == metrics_result.case_count
    assert result.mean_hit_at_k == pytest.approx(metrics_result.mean_hit_at_k)
    assert result.mean_recall_at_k == pytest.approx(metrics_result.mean_recall_at_k)
    assert result.mean_mrr == pytest.approx(metrics_result.mean_mrr)
    assert result.mean_ndcg_at_k == pytest.approx(metrics_result.mean_ndcg_at_k)


def test_config_matches_experiment_config(tmp_path):
    config = ExperimentConfig(chunk_strategy="fixed", top_k=8)
    result, _ = _finalize(tmp_path, config=config)
    assert result.config == config.to_dict()


def test_manifest_config_contains_embedding_identity(tmp_path):
    config = ExperimentConfig()
    manifest, _, _, _ = _default_objects(config)
    assert manifest.config["embedding_provider"] == "bge"
    assert manifest.config["embedding_model"] == "BAAI/bge-small-zh-v1.5"
    assert manifest.config["rrf_tie_breaker"] == "chunk_id_asc"
    assert manifest.config == config.to_dict()


@pytest.mark.parametrize("file_name", [
    "index_manifest.json",
    "retrieval_results.json",
    "retrieval_metrics.json",
])
def test_missing_snapshot_fails(tmp_path, file_name):
    config = ExperimentConfig()
    objects = _default_objects(config)
    prepared = _prepare(tmp_path, config)
    manifest, run_result, metrics_result, eval_set = objects
    _write_all(prepared, manifest, run_result, metrics_result)
    (prepared.paths.workspace_path / file_name).unlink()
    with pytest.raises((FileNotFoundError, RuntimeError), match=file_name):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)
    assert not prepared.paths.result_path.exists()


@pytest.mark.parametrize("file_name,mutate", [
    ("index_manifest.json", lambda p: p["files"][0].__setitem__("sha256", "f" * 64)),
    ("retrieval_results.json", lambda p: p["cases"][0]["hits"][0].__setitem__("chunk_id", "cX")),
    ("retrieval_metrics.json", lambda p: p.__setitem__("mean_mrr", 0.0)),
])
def test_disk_snapshot_mismatch_fails(tmp_path, file_name, mutate):
    config = ExperimentConfig()
    objects = _default_objects(config)
    prepared = _prepare(tmp_path, config)
    manifest, run_result, metrics_result, eval_set = objects
    _write_all(prepared, manifest, run_result, metrics_result)
    path = prepared.paths.workspace_path / file_name
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="不一致"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)
    assert not prepared.paths.result_path.exists()


@pytest.mark.parametrize("file_name", [
    "index_manifest.json",
    "retrieval_results.json",
    "retrieval_metrics.json",
])
def test_disk_snapshot_invalid_json_fails(tmp_path, file_name):
    config = ExperimentConfig()
    objects = _default_objects(config)
    prepared = _prepare(tmp_path, config)
    manifest, run_result, metrics_result, eval_set = objects
    _write_all(prepared, manifest, run_result, metrics_result)
    (prepared.paths.workspace_path / file_name).write_text(
        "{ not valid json", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="解析"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)
    assert not prepared.paths.result_path.exists()


def test_experiment_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, _, eval_set = _default_objects(config)
    metrics_result = _make_metrics_result(
        config, retrieval_run_id=run_result.retrieval_run_id,
        experiment_id="other-exp",
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="experiment_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_corpus_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, _, eval_set = _default_objects(config)
    metrics_result = _make_metrics_result(
        config, corpus_id="other-corpus",
        retrieval_run_id=run_result.retrieval_run_id,
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="corpus_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_evaluation_set_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, _, eval_set = _default_objects(config)
    metrics_result = _make_metrics_result(
        config, evaluation_set_id="other-eval",
        retrieval_run_id=run_result.retrieval_run_id,
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="evaluation_set_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_retrieval_run_id_cross_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, _, eval_set = _default_objects(config)
    metrics_result = _make_metrics_result(
        config, retrieval_run_id="other-run-id",
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="retrieval_run_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_metrics_run_id_tampered_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, metrics_result, eval_set = _default_objects(config)
    metrics_result = dataclasses.replace(
        metrics_result, metrics_run_id="deadbeefdead"
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="metrics_run_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_retrieval_run_id_tampered_fails(tmp_path):
    config = ExperimentConfig()
    manifest, _, _, eval_set = _default_objects(config)
    run_result = _make_run_result(config, retrieval_run_id="deadbeefdead")
    metrics_result = _make_metrics_result(
        config, retrieval_run_id="deadbeefdead"
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="retrieval_run_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_top_k_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, _, eval_set = _default_objects(config)
    metrics_result = _make_metrics_result(
        config, top_k=3, retrieval_run_id=run_result.retrieval_run_id,
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="top_k"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_retriever_strategy_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, _, eval_set = _default_objects(config)
    metrics_result = _make_metrics_result(
        config, retriever_strategy="simple",
        retrieval_run_id=run_result.retrieval_run_id,
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="retriever_strategy"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_chunk_strategy_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, metrics_result, eval_set = _default_objects(config)
    manifest = _make_manifest(config, chunk_strategy="fixed")
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="chunk_strategy"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_hybrid_sparse_count_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, metrics_result, eval_set = _default_objects(config)
    manifest = _make_manifest(config, sparse_index_count=2)
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="sparse_index_count"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_case_count_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    manifest, run_result, metrics_result, eval_set = _default_objects(config)
    metrics_result = dataclasses.replace(metrics_result, case_count=99)
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="case_count"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_result_id_stable_same_fact_chain():
    kwargs = dict(
        schema_version=1,
        experiment_id="exp-1",
        corpus_id="corpus-1",
        evaluation_set_id="eval-1",
        retrieval_run_id="run-1",
        metrics_run_id="metrics-1",
    )
    assert ExperimentResult.compute_result_id(**kwargs) == (
        ExperimentResult.compute_result_id(**kwargs)
    )


@pytest.mark.parametrize("field,value", [
    ("experiment_id", "exp-2"),
    ("corpus_id", "corpus-2"),
    ("evaluation_set_id", "eval-2"),
    ("retrieval_run_id", "run-2"),
    ("metrics_run_id", "metrics-2"),
])
def test_result_id_changes_on_bound_id(field, value):
    base = dict(
        schema_version=1,
        experiment_id="exp-1",
        corpus_id="corpus-1",
        evaluation_set_id="eval-1",
        retrieval_run_id="run-1",
        metrics_run_id="metrics-1",
    )
    before = ExperimentResult.compute_result_id(**base)
    after = ExperimentResult.compute_result_id(**{**base, field: value})
    assert before != after


def test_result_json_has_no_sensitive_content(tmp_path):
    result, prepared = _finalize(tmp_path)
    text = prepared.paths.result_path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert str(tmp_path) not in text
    assert "api_key" not in lowered
    assert "object at" not in text
    assert "0x" not in lowered
    assert result.result_id


def test_existing_result_file_rejects(tmp_path):
    config = ExperimentConfig()
    objects = _default_objects(config)
    prepared = _prepare(tmp_path, config)
    manifest, run_result, metrics_result, eval_set = objects
    _write_all(prepared, manifest, run_result, metrics_result)
    prepared.paths.result_path.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="result.json"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)


def test_atomic_write_failure_leaves_no_result_file(tmp_path, monkeypatch):
    import evaluation.experiment_result as result_module

    config = ExperimentConfig()
    objects = _default_objects(config)
    prepared = _prepare(tmp_path, config)
    manifest, run_result, metrics_result, eval_set = objects
    _write_all(prepared, manifest, run_result, metrics_result)

    def boom(src, dst):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(result_module.os, "replace", boom)
    with pytest.raises(OSError, match="atomic replace failed"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)
    assert not prepared.paths.result_path.exists()
    leftovers = [
        p for p in prepared.paths.workspace_path.iterdir() if p.suffix == ".tmp"
    ]
    assert leftovers == []


def test_model_immutable():
    result = ExperimentResult(
        schema_version=1,
        result_id="id",
        experiment_id="e",
        corpus_id="c",
        evaluation_set_id="s",
        retrieval_run_id="r",
        metrics_run_id="m",
        config={},
        chunk_strategy="recursive",
        retriever_strategy="hybrid",
        top_k=5,
        file_count=1,
        total_chunks=1,
        case_count=1,
        mean_hit_at_k=1.0,
        mean_recall_at_k=1.0,
        mean_mrr=1.0,
        mean_ndcg_at_k=1.0,
        artifacts={},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.result_id = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.mean_mrr = 0.0


# ============================================================
# G2-EVAL-09-R1：Retriever Strategy 四阶段闭合 + Hybrid 判定依据
# ============================================================


def test_manifest_retriever_strategy_mismatch_fails(tmp_path):
    """Manifest 顶层 retriever_strategy=simple 但 config/retrieval/metrics
    均为 hybrid 时，finalize 必须在生成 result.json 前失败。"""
    config = ExperimentConfig()  # hybrid
    manifest = _make_manifest(
        config, retriever_strategy="simple", sparse_index_count=None
    )
    run_result = _make_run_result(config)
    metrics_result = _make_metrics_result(
        config, retrieval_run_id=run_result.retrieval_run_id
    )
    eval_set = RetrievalEvaluationSet(
        corpus_id="corpus-001",
        cases=tuple(_default_eval_cases()),
        evaluation_set_id="evalset-001",
    )
    prepared = _prepare(tmp_path, config)
    _write_all(prepared, manifest, run_result, metrics_result)
    with pytest.raises(RuntimeError, match="retriever_strategy"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)
    assert not prepared.paths.result_path.exists()


@pytest.mark.parametrize("file_name", [
    "index_manifest.json",
    "retrieval_results.json",
    "retrieval_metrics.json",
])
def test_snapshot_top_level_list_fails(tmp_path, file_name):
    """三份事实快照任一 JSON 顶层为 list 时必须拒绝且不生成 result.json。"""
    config = ExperimentConfig()
    objects = _default_objects(config)
    prepared = _prepare(tmp_path, config)
    manifest, run_result, metrics_result, eval_set = objects
    _write_all(prepared, manifest, run_result, metrics_result)
    (prepared.paths.workspace_path / file_name).write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="object"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).finalize_result(prepared, manifest, run_result, metrics_result, eval_set)
    assert not prepared.paths.result_path.exists()
