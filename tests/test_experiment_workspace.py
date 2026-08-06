"""ExperimentRunner 第二步：ExperimentWorkspace 独立实验工作区"""

import yaml
import pytest

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_workspace import ExperimentPaths, ExperimentWorkspace


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


def test_paths_structure(tmp_path):
    base = _write_base_config(tmp_path)
    config = ExperimentConfig(chunk_size=256, top_k=8)
    ws = ExperimentWorkspace(base, tmp_path / "runs", config, "run_001")
    paths = ws.prepare()
    expected_ws = tmp_path / "runs" / config.experiment_id / "run_001"
    assert paths.workspace_path == expected_ws
    assert paths.config_path == expected_ws / "config.yaml"
    assert paths.vector_store_path == expected_ws / "vector_store"
    assert paths.result_path == expected_ws / "result.json"
    assert paths.config_path.is_file()
    assert paths.vector_store_path.is_dir()


def test_experiment_fields_overridden(tmp_path):
    base = _write_base_config(tmp_path)
    config = ExperimentConfig(
        chunk_strategy="fixed", chunk_size=256, chunk_overlap=32,
        retriever_strategy="mmr", top_k=10,
        dense_candidate_k=40, sparse_candidate_k=20, rrf_k=60.0,
    )
    ws = ExperimentWorkspace(base, tmp_path / "runs", config, "run1")
    paths = ws.prepare()
    raw = yaml.safe_load(paths.config_path.read_text(encoding="utf-8"))
    assert raw["chunker"]["strategy"] == "fixed"
    assert raw["chunker"]["size_tokens"] == 256
    assert raw["chunker"]["overlap_tokens"] == 32
    assert raw["retriever"]["strategy"] == "mmr"
    assert raw["retriever"]["top_k"] == 10
    assert raw["retriever"]["dense_candidate_k"] == 40
    assert raw["retriever"]["sparse_candidate_k"] == 20
    assert raw["retriever"]["rrf_k"] == 60.0
    assert raw["vector_store"]["path"] == str(paths.vector_store_path)


def test_non_experiment_fields_preserved(tmp_path):
    base = _write_base_config(tmp_path)
    config = ExperimentConfig(chunk_size=256)
    ws = ExperimentWorkspace(base, tmp_path / "runs", config, "run1")
    paths = ws.prepare()
    raw = yaml.safe_load(paths.config_path.read_text(encoding="utf-8"))
    assert raw["embedding"]["provider"] == "bge"
    assert raw["embedding"]["model"] == "BAAI/bge-small-zh-v1.5"
    assert raw["reranker"]["enabled"] is True
    assert raw["reranker"]["final_k"] == 5
    assert raw["generator"]["provider"] == "deepseek"
    assert raw["generator"]["model"] == "deepseek-v4-flash"


def test_base_config_unchanged(tmp_path):
    base = _write_base_config(tmp_path)
    original = base.read_text(encoding="utf-8")
    config = ExperimentConfig(chunk_size=256)
    ws = ExperimentWorkspace(base, tmp_path / "runs", config, "run1")
    ws.prepare()
    assert base.read_text(encoding="utf-8") == original


def test_different_run_id_different_vector_store(tmp_path):
    base = _write_base_config(tmp_path)
    config = ExperimentConfig()
    p1 = ExperimentWorkspace(base, tmp_path / "runs", config, "run_a").prepare()
    p2 = ExperimentWorkspace(base, tmp_path / "runs", config, "run_b").prepare()
    assert p1.vector_store_path != p2.vector_store_path
    assert p1.workspace_path != p2.workspace_path


def test_repeated_prepare_raises(tmp_path):
    base = _write_base_config(tmp_path)
    ws = ExperimentWorkspace(base, tmp_path / "runs", ExperimentConfig(), "run1")
    ws.prepare()
    with pytest.raises(FileExistsError):
        ws.prepare()


@pytest.mark.parametrize("run_id", ["../x", "", "a/b", "..", "a b", "run;1"])
def test_invalid_run_id_rejected(tmp_path, run_id):
    base = _write_base_config(tmp_path)
    with pytest.raises(ValueError):
        ExperimentWorkspace(base, tmp_path / "runs", ExperimentConfig(), run_id)


def test_all_paths_inside_workspace_root(tmp_path):
    base = _write_base_config(tmp_path)
    ws = ExperimentWorkspace(base, tmp_path / "runs", ExperimentConfig(), "run1")
    paths = ws.prepare()
    root = str((tmp_path / "runs").resolve())
    for p in (paths.workspace_path, paths.config_path,
              paths.vector_store_path, paths.result_path):
        assert str(p.resolve()).startswith(root), f"{p} 不在 workspace_root 内"


def test_prepare_returns_experiment_paths_and_no_tmp_leftover(tmp_path):
    base = _write_base_config(tmp_path)
    ws = ExperimentWorkspace(base, tmp_path / "runs", ExperimentConfig(), "run1")
    paths = ws.prepare()
    assert isinstance(paths, ExperimentPaths)
    leftovers = list(paths.workspace_path.glob("*.tmp"))
    assert leftovers == []
