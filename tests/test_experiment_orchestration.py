"""G2-EXP-10：单实验端到端 Orchestrator（run_experiment）"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.experiment_runner import ExperimentRunner
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


def _make_runner(tmp_path):
    base = tmp_path / "base_config.yaml"
    base.write_text(BASE_CONFIG_YAML, encoding="utf-8")
    return ExperimentRunner(base, tmp_path / "runs")


def _corpus_and_eval_set(corpus_id="corpus-001", eval_corpus_id=None):
    corpus = SimpleNamespace(corpus_id=corpus_id)
    eval_set = SimpleNamespace(
        corpus_id=eval_corpus_id if eval_corpus_id is not None else corpus_id
    )
    return corpus, eval_set


def _install_spies(runner, monkeypatch, failure=None):
    """把五个阶段替换为记录调用顺序的 spy；failure 指定抛异常的阶段名"""
    calls = []
    prepared = object()
    manifest = object()
    retrieval = object()
    metrics = object()
    final = object()

    def _make(name, result, args_count):
        def spy(*args):
            calls.append((name, args))
            if failure == name:
                raise RuntimeError(f"{name} 失败")
            return result
        return spy

    monkeypatch.setattr(runner, "prepare", _make("prepare", prepared, 2))
    monkeypatch.setattr(runner, "index_corpus", _make("index_corpus", manifest, 2))
    monkeypatch.setattr(
        runner, "run_retrieval", _make("run_retrieval", retrieval, 3)
    )
    monkeypatch.setattr(
        runner, "compute_retrieval_metrics", _make("compute_retrieval_metrics", metrics, 3)
    )
    monkeypatch.setattr(
        runner, "finalize_result", _make("finalize_result", final, 5)
    )
    return calls, prepared, manifest, retrieval, metrics, final


def test_stage_order_and_pass_through(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    config = ExperimentConfig()
    corpus, eval_set = _corpus_and_eval_set()
    calls, prepared, manifest, retrieval, metrics, final = _install_spies(
        runner, monkeypatch
    )

    returned = runner.run_experiment(config, "run1", corpus, eval_set)

    assert returned is final
    assert [name for name, _ in calls] == [
        "prepare",
        "index_corpus",
        "run_retrieval",
        "compute_retrieval_metrics",
        "finalize_result",
    ]
    assert calls[0][1] == (config, "run1")
    assert calls[1][1] == (prepared, corpus)
    assert calls[2][1] == (prepared, manifest, eval_set)
    assert calls[3][1] == (prepared, retrieval, eval_set)
    assert calls[4][1] == (prepared, manifest, retrieval, metrics, eval_set)


def test_each_stage_called_exactly_once(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    corpus, eval_set = _corpus_and_eval_set()
    calls, *_ = _install_spies(runner, monkeypatch)
    runner.run_experiment(ExperimentConfig(), "run1", corpus, eval_set)
    names = [name for name, _ in calls]
    for stage in (
        "prepare",
        "index_corpus",
        "run_retrieval",
        "compute_retrieval_metrics",
        "finalize_result",
    ):
        assert names.count(stage) == 1, f"{stage} 应恰好调用一次"


def test_corpus_id_mismatch_no_prepare_no_workspace(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    corpus, eval_set = _corpus_and_eval_set(corpus_id="corpus-A", eval_corpus_id="corpus-B")
    calls = []
    monkeypatch.setattr(
        runner, "prepare", lambda config, run_id: calls.append(("prepare", config, run_id))
    )
    with pytest.raises(ValueError, match="corpus_id"):
        runner.run_experiment(ExperimentConfig(), "run1", corpus, eval_set)
    assert calls == []
    assert not (tmp_path / "runs").exists(), "不得创建实验 Workspace"


@pytest.mark.parametrize("failure", [
    "prepare",
    "index_corpus",
    "run_retrieval",
    "compute_retrieval_metrics",
    "finalize_result",
])
def test_stage_failure_stops_later_stages_and_preserves_error(tmp_path, monkeypatch, failure):
    runner = _make_runner(tmp_path)
    corpus, eval_set = _corpus_and_eval_set()
    calls, *_ = _install_spies(runner, monkeypatch, failure=failure)

    with pytest.raises(RuntimeError) as excinfo:
        runner.run_experiment(ExperimentConfig(), "run1", corpus, eval_set)

    assert str(excinfo.value) == f"{failure} 失败"
    names = [name for name, _ in calls]
    order = ["prepare", "index_corpus", "run_retrieval",
             "compute_retrieval_metrics", "finalize_result"]
    failed_index = order.index(failure)
    assert names == order[:failed_index + 1]
    assert names.count(failure) == 1, "不得自动重试失败阶段"


def test_no_workspace_deletion_on_failure(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    corpus, eval_set = _corpus_and_eval_set()
    workspace_marker = tmp_path / "runs" / "marker"

    def fake_prepare(config, run_id):
        workspace_marker.parent.mkdir(parents=True)
        workspace_marker.write_text("kept", encoding="utf-8")
        return object()

    def fake_index(prepared, corpus):
        raise RuntimeError("index 失败")

    monkeypatch.setattr(runner, "prepare", fake_prepare)
    monkeypatch.setattr(runner, "index_corpus", fake_index)
    with pytest.raises(RuntimeError, match="index 失败"):
        runner.run_experiment(ExperimentConfig(), "run1", corpus, eval_set)
    assert workspace_marker.is_file(), "失败后不得自动删除 Workspace"


def test_explicit_run_id_passed_through(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    corpus, eval_set = _corpus_and_eval_set()
    received = {}
    monkeypatch.setattr(
        runner,
        "prepare",
        lambda config, run_id: received.update(config=config, run_id=run_id) or object(),
    )
    monkeypatch.setattr(runner, "index_corpus", lambda prepared, corpus: object())
    monkeypatch.setattr(runner, "run_retrieval", lambda prepared, manifest, eval_set: object())
    monkeypatch.setattr(
        runner, "compute_retrieval_metrics", lambda prepared, retrieval, eval_set: object()
    )
    monkeypatch.setattr(
        runner, "finalize_result", lambda *args: object()
    )
    runner.run_experiment(ExperimentConfig(), "my-run-42", corpus, eval_set)
    assert received["run_id"] == "my-run-42", "必须显式透传调用方 run_id"


# ============================================================
# 轻量集成：真实五阶段 + FakePipeline 完整 Artifact 状态
# ============================================================


class _FakeDoc:
    def __init__(self, metadata):
        self.metadata = metadata


class _FakeBM25:
    def __init__(self, doc_count):
        self.doc_count = doc_count


class _FakeVectorStore:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _FakeConfig:
    def __init__(self, config_path):
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.embedding_provider = raw["embedding"]["provider"]
        self.embedding_model = raw["embedding"]["model"]
        self.chunker_strategy = raw["chunker"]["strategy"]
        self.chunk_size = raw["chunker"]["size_tokens"]
        self.chunk_overlap = raw["chunker"]["overlap_tokens"]
        self.retriever_strategy = raw["retriever"]["strategy"]
        self.top_k = raw["retriever"]["top_k"]
        self.dense_candidate_k = raw["retriever"]["dense_candidate_k"]
        self.sparse_candidate_k = raw["retriever"]["sparse_candidate_k"]
        self.rrf_k = raw["retriever"]["rrf_k"]
        self.vector_store_path = raw["vector_store"]["path"]


class _FakeRetriever:
    def __init__(self, results, bm25_count):
        self._results = results
        self._bm25 = _FakeBM25(bm25_count)

    def retrieve(self, query, top_k=5):
        return [_FakeDoc(m) for m in self._results[query]]


class _FakePipeline:
    def __init__(self, config_path, retriever, vector_count):
        self.config = _FakeConfig(config_path)
        self.retriever = retriever
        self.vector_store = _FakeVectorStore(vector_count)

    def index_file(self, path):
        return {
            "status": "create",
            "document_id": Path(path).name,
            "chunks": 1,
        }

    def _rebuild_sparse_index(self, strict=False):
        return self.retriever._bm25.doc_count


def test_integration_full_experiment_produces_all_artifacts(tmp_path):
    root = tmp_path / "corpus"
    (root / "core").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "core" / "pipeline.py").write_text("def p(): pass\n", encoding="utf-8")
    (root / "docs" / "x.md").write_text("# X\n", encoding="utf-8")
    corpus = ExperimentCorpus.build(
        root, ["core/pipeline.py", "docs/x.md"]
    )
    eval_set = RetrievalEvaluationSet(
        corpus_id=corpus.corpus_id,
        cases=(
            RetrievalCase("q001", "query one", ("core/pipeline.py",)),
            RetrievalCase("q002", "query two", ("docs/x.md",)),
        ),
        evaluation_set_id="evalset-001",
    )
    results = {
        "query one": [
            {"id": "c1", "document_id": "pipeline.py", "score": 0.9},
        ],
        "query two": [
            {"id": "c2", "document_id": "x.md", "score": 0.8},
        ],
    }

    base = tmp_path / "base_config.yaml"
    base.write_text(BASE_CONFIG_YAML, encoding="utf-8")
    runner = ExperimentRunner(
        base,
        tmp_path / "runs",
        pipeline_factory=lambda config_path: _FakePipeline(
            config_path,
            _FakeRetriever(results, bm25_count=2),
            vector_count=2,
        ),
    )

    result = runner.run_experiment(
        ExperimentConfig(), "run1", corpus, eval_set
    )
    ws = tmp_path / "runs" / ExperimentConfig().experiment_id / "run1"
    assert (ws / "index_manifest.json").is_file()
    assert (ws / "retrieval_results.json").is_file()
    assert (ws / "retrieval_metrics.json").is_file()
    assert (ws / "result.json").is_file()
    assert result.result_id
    raw = json.loads((ws / "result.json").read_text(encoding="utf-8"))
    assert raw["case_count"] == 2
    assert raw["mean_hit_at_k"] == 1.0
