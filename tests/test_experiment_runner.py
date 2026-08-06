"""ExperimentRunner 第三步：最小版 Runner——工作区 + 独立 Pipeline 接通"""

from pathlib import Path

import pytest
import yaml

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment


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
        self.chunker_strategy = raw["chunker"]["strategy"]
        self.chunk_size = raw["chunker"]["size_tokens"]
        self.chunk_overlap = raw["chunker"]["overlap_tokens"]
        self.retriever_strategy = raw["retriever"]["strategy"]
        self.top_k = raw["retriever"]["top_k"]
        self.dense_candidate_k = raw["retriever"]["dense_candidate_k"]
        self.sparse_candidate_k = raw["retriever"]["sparse_candidate_k"]
        self.rrf_k = raw["retriever"]["rrf_k"]
        self.vector_store_path = raw["vector_store"]["path"]


class FakePipeline:
    def __init__(self, config):
        self.config = config


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
    "chunker_strategy", "chunk_size", "chunk_overlap",
    "retriever_strategy", "top_k", "dense_candidate_k",
    "sparse_candidate_k", "rrf_k",
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
