"""ExperimentRunner 第三步：最小版 Runner——工作区 + 独立 Pipeline 接通；
含 G2-ER-05 可复现语料入库与索引 Manifest。"""

import json
from pathlib import Path

import pytest
import yaml

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment
from evaluation.experiment_workspace import ExperimentWorkspace


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


class FakeConfig:
    """从派生 config.yaml 读取字段的替身 Config（属性名与 core Config 一致）"""

    def __init__(self, config_path):
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.embedding_provider = raw["embedding"]["provider"]
        self.embedding_model = raw["embedding"]["model"]
        self.chunker_strategy = raw["chunker"]["strategy"]
        self.chunk_size = raw["chunker"]["size_tokens"]
        self.chunk_overlap = raw["chunker"]["overlap_tokens"]
        self.chunk_budget_policy = raw["chunker"].get(
            "budget_policy", "cl100k_content_v1"
        )
        self.effective_embedding_max_seq_length = raw["chunker"].get(
            "effective_embedding_max_seq_length"
        )
        self.special_token_overhead = raw["chunker"].get(
            "special_token_overhead"
        )
        self.tokenizer_contract_probe_version = raw["chunker"].get(
            "tokenizer_contract_probe_version"
        )
        self.tokenizer_contract_fingerprint = raw["chunker"].get(
            "tokenizer_contract_fingerprint"
        )
        self.retriever_strategy = raw["retriever"]["strategy"]
        self.top_k = raw["retriever"]["top_k"]
        self.dense_candidate_k = raw["retriever"]["dense_candidate_k"]
        self.sparse_candidate_k = raw["retriever"]["sparse_candidate_k"]
        self.rrf_k = raw["retriever"]["rrf_k"]
        self.rrf_tie_breaker = raw["retriever"]["rrf_tie_breaker"]
        self.vector_store_path = raw["vector_store"]["path"]


def _make_real_retriever(strategy):
    """按策略构造真实 Retriever 实例（构造参数不参与 retrieve，测试安全）"""
    from core.retriever.simple import SimpleRetriever
    from core.retriever.hybrid import HybridRetriever
    from core.retriever.bm25_only import BM25OnlyRetriever
    from core.retriever.mmr import MMRRetriever
    if strategy == "simple":
        return SimpleRetriever(None, None)
    if strategy == "hybrid":
        return HybridRetriever(None, None)
    if strategy == "bm25":
        return BM25OnlyRetriever()
    return MMRRetriever(None, None)


class FakePipeline:
    def __init__(self, config):
        self.config = config
        self.retriever = _make_real_retriever(config.retriever_strategy)
        from core.chunker.fixed_size import FixedSizeChunker
        from core.chunker.recursive import RecursiveChunker
        if config.chunker_strategy == "fixed":
            self.chunker = FixedSizeChunker(
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
            )
        else:
            self.chunker = RecursiveChunker(
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
            )


def _make_factory(recorder, mutate=None):
    """记录收到的 config_path；mutate 可注入字段不一致"""
    def factory(config_path):
        recorder.append(str(config_path))
        cfg = FakeConfig(config_path)
        if mutate:
            mutate(cfg)
        return FakePipeline(cfg)
    return factory


def _switch_strategy(value):
    return {"recursive": "fixed", "hybrid": "simple"}.get(value, "fixed")


def test_factory_receives_derived_config_not_base(tmp_path):
    base = _write_base_config(tmp_path)
    recorder = []
    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory(recorder))
    result = runner.prepare(ExperimentConfig(), "run1")
    assert len(recorder) == 1
    assert Path(recorder[0]) == result.paths.config_path
    assert Path(recorder[0]) != base


def test_prepared_experiment_contains_pipeline(tmp_path):
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([]))
    result = runner.prepare(ExperimentConfig(), "run1")
    assert isinstance(result, PreparedExperiment)
    assert isinstance(result.pipeline, FakePipeline)
    assert result.experiment_config == ExperimentConfig()


def test_all_fields_match_succeeds(tmp_path):
    base = _write_base_config(tmp_path)
    config = ExperimentConfig(
        chunk_strategy="fixed", chunk_size=256, chunk_overlap=32,
        retriever_strategy="mmr", top_k=10,
        dense_candidate_k=40, sparse_candidate_k=20, rrf_k=60.0,
    )
    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([]))
    result = runner.prepare(config, "run1")
    assert result.pipeline.config.chunker_strategy == "fixed"
    assert result.pipeline.config.rrf_k == 60.0


@pytest.mark.parametrize("field", [
    "embedding_provider", "embedding_model",
    "chunker_strategy", "chunk_size", "chunk_overlap",
    "retriever_strategy", "top_k", "dense_candidate_k",
    "sparse_candidate_k", "rrf_k", "rrf_tie_breaker",
    "chunk_budget_policy",
])
def test_any_field_mismatch_fails(tmp_path, field):
    base = _write_base_config(tmp_path)

    def mutate(cfg):
        cur = getattr(cfg, field)
        if isinstance(cur, str):
            setattr(cfg, field, _switch_strategy(cur))
        else:
            setattr(cfg, field, cur + 1)

    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([], mutate))
    with pytest.raises(RuntimeError, match="不一致"):
        runner.prepare(ExperimentConfig(), "run1")


def test_vector_store_path_mismatch_fails(tmp_path):
    base = _write_base_config(tmp_path)

    def mutate(cfg):
        cfg.vector_store_path = str(tmp_path / "elsewhere")

    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([], mutate))
    with pytest.raises(RuntimeError, match="vector_store|不一致"):
        runner.prepare(ExperimentConfig(), "run1")


def test_embedding_provider_mismatch_fails(tmp_path):
    base = _write_base_config(tmp_path)

    def mutate(cfg):
        cfg.embedding_provider = "openai"

    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([], mutate))
    with pytest.raises(RuntimeError, match="embedding_provider"):
        runner.prepare(ExperimentConfig(), "run1")


def test_embedding_model_mismatch_fails(tmp_path):
    base = _write_base_config(tmp_path)

    def mutate(cfg):
        cfg.embedding_model = "other-embedding-model"

    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([], mutate))
    with pytest.raises(RuntimeError, match="embedding_model"):
        runner.prepare(ExperimentConfig(), "run1")


def test_hybrid_retriever_tie_breaker_mismatch_fails(tmp_path):
    base = _write_base_config(tmp_path)

    def factory(config_path):
        cfg = FakeConfig(config_path)
        pipeline = FakePipeline(cfg)
        pipeline.retriever.rrf_tie_breaker = "other"
        return pipeline

    runner = ExperimentRunner(base, tmp_path / "runs", factory)
    with pytest.raises(RuntimeError, match="HybridRetriever.rrf_tie_breaker"):
        runner.prepare(ExperimentConfig(), "run1")


def _factory_with_retriever(config_path, retriever):
    from core.retriever.simple import SimpleRetriever
    from core.retriever.bm25_only import BM25OnlyRetriever
    from core.retriever.mmr import MMRRetriever

    cfg = FakeConfig(config_path)
    pipeline = FakePipeline(cfg)
    pipeline.retriever = retriever
    return pipeline


def test_simple_retriever_runtime_type_passes(tmp_path):
    from core.retriever.simple import SimpleRetriever
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(
        base, tmp_path / "runs",
        lambda p: _factory_with_retriever(p, SimpleRetriever(None, None)),
    )
    runner.prepare(ExperimentConfig(retriever_strategy="simple"), "run1")


def test_simple_retriever_wrong_runtime_type_fails(tmp_path):
    from core.retriever.bm25_only import BM25OnlyRetriever
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(
        base, tmp_path / "runs",
        lambda p: _factory_with_retriever(p, BM25OnlyRetriever()),
    )
    with pytest.raises(RuntimeError, match="实际 Retriever 类型"):
        runner.prepare(ExperimentConfig(retriever_strategy="simple"), "run1")


def test_bm25_retriever_runtime_type_passes(tmp_path):
    from core.retriever.bm25_only import BM25OnlyRetriever
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(
        base, tmp_path / "runs",
        lambda p: _factory_with_retriever(p, BM25OnlyRetriever()),
    )
    runner.prepare(ExperimentConfig(retriever_strategy="bm25"), "run1")


def test_bm25_retriever_wrong_runtime_type_fails(tmp_path):
    from core.retriever.simple import SimpleRetriever
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(
        base, tmp_path / "runs",
        lambda p: _factory_with_retriever(p, SimpleRetriever(None, None)),
    )
    with pytest.raises(RuntimeError, match="实际 Retriever 类型"):
        runner.prepare(ExperimentConfig(retriever_strategy="bm25"), "run1")


def test_hybrid_retriever_runtime_type_passes(tmp_path):
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory([]))
    runner.prepare(ExperimentConfig(retriever_strategy="hybrid"), "run1")


def test_hybrid_retriever_wrong_runtime_type_fails(tmp_path):
    from core.retriever.bm25_only import BM25OnlyRetriever
    base = _write_base_config(tmp_path)
    runner = ExperimentRunner(
        base, tmp_path / "runs",
        lambda p: _factory_with_retriever(p, BM25OnlyRetriever()),
    )
    with pytest.raises(RuntimeError, match="实际 Retriever 类型"):
        runner.prepare(ExperimentConfig(retriever_strategy="hybrid"), "run1")


# ============================================================
# G2-ABL-16-R1：BM25 Sparse Index Integrity（index_corpus 层）
# ============================================================


def test_bm25_sparse_count_consistent_manifest(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="bm25")
    pipeline = FakeIndexPipeline(vector_count=2, bm25_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert manifest.sparse_index_count == 2
    raw = json.loads(
        prepared.paths.index_manifest_path.read_text(encoding="utf-8")
    )
    assert raw["sparse_index_count"] == 2


def test_bm25_sparse_count_mismatch_fails(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="bm25")
    pipeline = FakeIndexPipeline(vector_count=2, bm25_count=1)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="sparse_index_count"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()


def test_bm25_sparse_count_zero_fails(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="bm25")
    pipeline = FakeIndexPipeline(vector_count=2, bm25_count=0)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="sparse_index_count"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()


def test_simple_manifest_sparse_index_count_none(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert manifest.sparse_index_count is None


def test_pipeline_factory_error_propagates(tmp_path):
    base = _write_base_config(tmp_path)

    def factory(config_path):
        raise RuntimeError("pipeline 构建失败")

    runner = ExperimentRunner(base, tmp_path / "runs", factory)
    with pytest.raises(RuntimeError, match="pipeline 构建失败"):
        runner.prepare(ExperimentConfig(), "run1")


def test_invalid_run_id_rejected_without_factory_call(tmp_path):
    base = _write_base_config(tmp_path)
    recorder = []
    runner = ExperimentRunner(base, tmp_path / "runs", _make_factory(recorder))
    with pytest.raises(ValueError):
        runner.prepare(ExperimentConfig(), "../x")
    assert recorder == [], "非法 run_id 时 pipeline_factory 不得被调用"


# ============================================================
# G2-ER-05：ExperimentRunner 可复现语料入库与索引 Manifest
# ============================================================


class FakeIndexVectorStore:
    """记录 count() 调用并返回可注入数量"""

    def __init__(self, count=0):
        self._count = count
        self.count_calls = 0

    def count(self):
        self.count_calls += 1
        return self._count


class FakeBM25Index:
    def __init__(self, doc_count=0):
        self.doc_count = doc_count


class FakeIndexRetriever:
    def __init__(self, bm25):
        self._bm25 = bm25


class FakeIndexPipeline:
    """G2-ER-05 用：index_file 记录调用顺序；可选 Hybrid 严格重建"""

    def __init__(self, vector_count=0, results=None, raise_paths=(),
                 bm25_count=None, rebuild_raise=None):
        self.calls = []
        self.vector_store = FakeIndexVectorStore(vector_count)
        self._results = results or {}
        self._raise_paths = set(raise_paths)
        self.rebuild_calls = []
        self._rebuild_raise = rebuild_raise
        if bm25_count is None:
            self.retriever = None
        else:
            self.retriever = FakeIndexRetriever(FakeBM25Index(bm25_count))

    def index_file(self, path):
        self.calls.append(path)
        if path in self._raise_paths:
            raise RuntimeError("index_file 异常注入")
        return self._results.get(path, {
            "status": "create",
            "document_id": Path(path).name,
            "chunks": 1,
        })

    def _rebuild_sparse_index(self, strict=False):
        self.rebuild_calls.append(strict)
        if self._rebuild_raise is not None:
            raise self._rebuild_raise
        return self.retriever._bm25.doc_count


def _make_runner(tmp_path):
    return ExperimentRunner(tmp_path / "base_config.yaml", tmp_path / "runs")


def _prepare_experiment(base_tmp, workspace_root, config, pipeline):
    base = _write_base_config(base_tmp)
    paths = ExperimentWorkspace(base, workspace_root, config, "run1").prepare()
    return PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=pipeline
    )


def _make_corpus(tmp_path, files):
    root = tmp_path / "corpus"
    root.mkdir()
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return ExperimentCorpus.build(root, list(files))


def _link_dir(link, target):
    import subprocess
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("当前平台/权限不支持目录链接")


def test_index_manifest_path_is_dedicated(tmp_path):
    config = ExperimentConfig(retriever_strategy="simple")
    prepared = _prepare_experiment(
        tmp_path, tmp_path / "runs", config, FakeIndexPipeline(vector_count=1)
    )
    assert prepared.paths.index_manifest_path == (
        prepared.paths.workspace_path / "index_manifest.json"
    )
    assert prepared.paths.index_manifest_path != prepared.paths.result_path


def test_index_file_called_in_corpus_entry_order(tmp_path):
    corpus = _make_corpus(tmp_path, {"b.txt": "bbb", "a.md": "aaa"})
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert manifest is not None
    assert pipeline.calls == [
        str(corpus.corpus_root / "a.md"),
        str(corpus.corpus_root / "b.txt"),
    ]


def test_all_create_generates_manifest_with_expected_content(tmp_path):
    from evaluation.index_manifest import IndexManifest

    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(chunk_strategy="fixed", retriever_strategy="simple")
    results = {
        str(corpus.corpus_root / "a.md"): {
            "status": "create", "document_id": "a.md", "chunks": 2,
        },
        str(corpus.corpus_root / "b.txt"): {
            "status": "create", "document_id": "b.txt", "chunks": 3,
        },
    }
    pipeline = FakeIndexPipeline(vector_count=5, results=results)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)

    assert isinstance(manifest, IndexManifest)
    assert manifest.experiment_id == config.experiment_id
    assert manifest.corpus_id == corpus.corpus_id
    assert manifest.file_count == 2
    assert manifest.total_chunks == 5
    assert manifest.vector_store_count == 5
    assert manifest.sparse_index_count is None

    manifest_path = prepared.paths.index_manifest_path
    assert manifest_path.is_file()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["experiment_id"] == config.experiment_id
    assert raw["corpus_id"] == corpus.corpus_id
    assert raw["chunk_strategy"] == "fixed"
    assert raw["retriever_strategy"] == "simple"
    assert raw["config"] == config.to_dict()
    assert [e["relative_path"] for e in raw["corpus_entries"]] == [
        e.relative_path for e in corpus.entries
    ]
    assert raw["file_count"] == 2
    files = raw["files"]
    assert [f["relative_path"] for f in files] == [
        e.relative_path for e in corpus.entries
    ]
    assert [f["chunks"] for f in files] == [2, 3]
    assert [f["status"] for f in files] == ["create", "create"]
    assert [f["document_id"] for f in files] == ["a.md", "b.txt"]
    assert raw["total_chunks"] == 5
    assert raw["vector_store_count"] == 5
    assert raw["sparse_index_count"] is None


def test_modified_file_fails_before_any_index_file(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    (corpus.corpus_root / "b.txt").write_text("changed content", encoding="utf-8")
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(ValueError, match="SHA-256|size_bytes"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.calls == []
    assert not prepared.paths.index_manifest_path.exists()


def test_deleted_file_fails_before_any_index_file(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    (corpus.corpus_root / "b.txt").unlink()
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises((FileNotFoundError, ValueError), match="不存在"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.calls == []
    assert not prepared.paths.index_manifest_path.exists()


def test_no_change_status_fails_without_manifest(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="simple")
    results = {
        str(corpus.corpus_root / "b.txt"): {
            "status": "no_change", "document_id": "b.txt", "chunks": 0,
        },
    }
    pipeline = FakeIndexPipeline(vector_count=1, results=results)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="no_change"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()


def test_update_status_fails_without_manifest(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="simple")
    results = {
        str(corpus.corpus_root / "b.txt"): {
            "status": "update", "document_id": "b.txt", "chunks": 1,
        },
    }
    pipeline = FakeIndexPipeline(vector_count=1, results=results)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="update"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()


def test_second_file_exception_propagates_without_manifest(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(
        vector_count=1,
        raise_paths=[str(corpus.corpus_root / "b.txt")],
    )
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="index_file 异常注入"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.calls == [
        str(corpus.corpus_root / "a.md"),
        str(corpus.corpus_root / "b.txt"),
    ]
    assert not prepared.paths.index_manifest_path.exists()


def test_vector_store_count_mismatch_fails(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=3)  # 两个文件共产生 2 个 chunk
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="不一致"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()


def test_hybrid_calls_strict_rebuild_and_records_sparse_count(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="hybrid")
    pipeline = FakeIndexPipeline(vector_count=2, bm25_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.rebuild_calls == [True]
    assert manifest.sparse_index_count == 2
    raw = json.loads(prepared.paths.index_manifest_path.read_text(encoding="utf-8"))
    assert raw["sparse_index_count"] == 2


def test_hybrid_sparse_count_mismatch_fails(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(retriever_strategy="hybrid")
    pipeline = FakeIndexPipeline(vector_count=2, bm25_count=1)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(RuntimeError, match="不一致"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.rebuild_calls == [True]
    assert not prepared.paths.index_manifest_path.exists()


@pytest.mark.parametrize("strategy", ["simple", "mmr"])
def test_non_hybrid_does_not_require_bm25(tmp_path, strategy):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa"})
    config = ExperimentConfig(retriever_strategy=strategy)
    pipeline = FakeIndexPipeline(vector_count=1)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.rebuild_calls == []
    assert manifest.sparse_index_count is None
    raw = json.loads(prepared.paths.index_manifest_path.read_text(encoding="utf-8"))
    assert raw["sparse_index_count"] is None


def test_existing_manifest_rejects_second_execution_before_indexing(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa"})
    config = ExperimentConfig(retriever_strategy="simple")
    prepared = _prepare_experiment(
        tmp_path, tmp_path / "runs", config, FakeIndexPipeline(vector_count=1)
    )
    _make_runner(tmp_path).index_corpus(prepared, corpus)

    fresh = FakeIndexPipeline(vector_count=1)
    prepared2 = PreparedExperiment(
        experiment_config=config, paths=prepared.paths, pipeline=fresh
    )
    with pytest.raises(FileExistsError, match="index_manifest"):
        _make_runner(tmp_path).index_corpus(prepared2, corpus)
    assert fresh.calls == []


def test_manifest_json_has_no_sensitive_or_unstable_content(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa"})
    config = ExperimentConfig(retriever_strategy="simple")
    prepared = _prepare_experiment(
        tmp_path, tmp_path / "runs", config, FakeIndexPipeline(vector_count=1)
    )
    _make_runner(tmp_path).index_corpus(prepared, corpus)
    text = prepared.paths.index_manifest_path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "api_key" not in lowered
    assert str(corpus.corpus_root) not in text
    assert str(prepared.paths.workspace_path) not in text
    assert "0x" not in lowered
    assert "object at" not in lowered
    assert json.loads(text)


def test_manifest_business_content_deterministic_across_workspaces(tmp_path):
    corpus = _make_corpus(tmp_path, {"a.md": "aaa", "b.txt": "bbb"})
    config = ExperimentConfig(chunk_strategy="fixed", retriever_strategy="simple")
    results = {
        str(corpus.corpus_root / "a.md"): {
            "status": "create", "document_id": "a.md", "chunks": 2,
        },
        str(corpus.corpus_root / "b.txt"): {
            "status": "create", "document_id": "b.txt", "chunks": 3,
        },
    }
    base_a = tmp_path / "base_a"
    base_a.mkdir()
    base_b = tmp_path / "base_b"
    base_b.mkdir()
    p1 = _prepare_experiment(base_a, tmp_path / "runs_a", config,
                             FakeIndexPipeline(vector_count=5, results=results))
    p2 = _prepare_experiment(base_b, tmp_path / "runs_b", config,
                             FakeIndexPipeline(vector_count=5, results=results))
    ExperimentRunner(base_a / "base_config.yaml", tmp_path / "runs_a").index_corpus(
        p1, corpus
    )
    ExperimentRunner(base_b / "base_config.yaml", tmp_path / "runs_b").index_corpus(
        p2, corpus
    )
    d1 = json.loads(p1.paths.index_manifest_path.read_text(encoding="utf-8"))
    d2 = json.loads(p2.paths.index_manifest_path.read_text(encoding="utf-8"))
    assert d1 == d2


def test_atomic_write_failure_leaves_no_manifest(tmp_path, monkeypatch):
    import evaluation.index_manifest as manifest_module

    corpus = _make_corpus(tmp_path, {"a.md": "aaa"})
    config = ExperimentConfig(retriever_strategy="simple")
    prepared = _prepare_experiment(
        tmp_path, tmp_path / "runs", config, FakeIndexPipeline(vector_count=1)
    )

    def boom(src, dst):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(manifest_module.os, "replace", boom)
    with pytest.raises(OSError, match="atomic replace failed"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()
    leftovers = [
        p for p in prepared.paths.workspace_path.iterdir() if p.suffix == ".tmp"
    ]
    assert leftovers == []


def test_corpus_path_escape_after_build_fails_before_index(tmp_path):
    import shutil

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    root = tmp_path / "corpus"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "file.md").write_text("secret", encoding="utf-8")
    corpus = ExperimentCorpus.build(root, ["sub/file.md"])

    shutil.rmtree(root / "sub")
    _link_dir(root / "sub", outside)

    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=1)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(ValueError, match="逃逸|escape"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.calls == []
    assert not prepared.paths.index_manifest_path.exists()


def test_corpus_root_redirect_after_build_fails_before_index(tmp_path):
    """G2-ER-05-R1：整个 corpus_root 在 build 后被替换成指向外部的
    junction/symlink 时，必须在第一次 index_file() 前失败。"""
    import shutil

    content = "same bytes\n"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.md").write_text(content, encoding="utf-8")

    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text(content, encoding="utf-8")
    corpus = ExperimentCorpus.build(root, ["a.md"])

    # 删除整个 corpus_root，并替换为指向外部目录的 junction/symlink；
    # 外部目录中放置同名、同大小、同 SHA-256 的 a.md。
    shutil.rmtree(root)
    _link_dir(root, outside)

    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=1)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    with pytest.raises(ValueError, match="重定向|替换"):
        _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert pipeline.calls == []
    assert not prepared.paths.index_manifest_path.exists()


def test_no_redirect_indexes_in_entry_order(tmp_path):
    """G2-ER-05-R1：未发生重定向时，仍按 corpus.entries 原顺序入库。"""
    corpus = _make_corpus(tmp_path, {"b.txt": "bbb", "a.md": "aaa"})
    config = ExperimentConfig(retriever_strategy="simple")
    pipeline = FakeIndexPipeline(vector_count=2)
    prepared = _prepare_experiment(tmp_path, tmp_path / "runs", config, pipeline)
    manifest = _make_runner(tmp_path).index_corpus(prepared, corpus)
    assert manifest is not None
    anchor = Path(corpus.corpus_root)
    assert pipeline.calls == [
        str(anchor / e.relative_path) for e in corpus.entries
    ]
    assert prepared.paths.index_manifest_path.is_file()
