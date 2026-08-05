"""ExperimentRunner 第一步：ExperimentConfig 强类型配置模型"""

import pytest

from evaluation.experiment_config import ExperimentConfig


def test_default_config_is_valid():
    config = ExperimentConfig()
    assert config.chunk_strategy == "recursive"
    assert config.retriever_strategy == "hybrid"


def test_to_dict_contains_all_fields():
    config = ExperimentConfig(
        chunk_strategy="fixed", chunk_size=256, chunk_overlap=32,
        retriever_strategy="mmr", top_k=10,
        dense_candidate_k=40, sparse_candidate_k=20, rrf_k=60.0,
    )
    d = config.to_dict()
    assert d == {
        "chunk_strategy": "fixed",
        "chunk_size": 256,
        "chunk_overlap": 32,
        "retriever_strategy": "mmr",
        "top_k": 10,
        "dense_candidate_k": 40,
        "sparse_candidate_k": 20,
        "rrf_k": 60.0,
    }


# ── 非法边界 ──────────────────────────────────────────

def test_invalid_chunk_strategy_rejected():
    with pytest.raises(ValueError, match="chunk_strategy"):
        ExperimentConfig(chunk_strategy="graph")


def test_invalid_retriever_strategy_rejected():
    with pytest.raises(ValueError, match="retriever_strategy"):
        ExperimentConfig(retriever_strategy="graph_rag")


@pytest.mark.parametrize("field", ["chunk_size", "top_k", "dense_candidate_k",
                                   "sparse_candidate_k"])
@pytest.mark.parametrize("value", [0, -1])
def test_positive_fields_must_be_gt_zero(field, value):
    with pytest.raises(ValueError, match=field):
        ExperimentConfig(**{field: value})


def test_chunk_overlap_negative_rejected():
    with pytest.raises(ValueError, match="chunk_overlap"):
        ExperimentConfig(chunk_overlap=-1)


def test_chunk_overlap_must_be_less_than_chunk_size():
    with pytest.raises(ValueError, match="chunk_overlap"):
        ExperimentConfig(chunk_size=128, chunk_overlap=128)


def test_rrf_k_must_be_positive():
    with pytest.raises(ValueError, match="rrf_k"):
        ExperimentConfig(rrf_k=0.0)


# ── 稳定 experiment_id ─────────────────────────────────

def test_same_config_same_id():
    a = ExperimentConfig(chunk_size=128, top_k=8)
    b = ExperimentConfig(chunk_size=128, top_k=8)
    assert a.experiment_id == b.experiment_id
    assert a.experiment_id == a.experiment_id  # 同一实例重复读取也稳定


def test_each_field_change_changes_id():
    base = ExperimentConfig()
    for field in ("chunk_strategy", "chunk_size", "chunk_overlap",
                  "retriever_strategy", "top_k", "dense_candidate_k",
                  "sparse_candidate_k", "rrf_k"):
        kwargs = {field: _changed_value(base, field)}
        changed = ExperimentConfig(**kwargs)
        assert changed.experiment_id != base.experiment_id, f"{field} 变化后 ID 应变化"


def _changed_value(config, field):
    """每个字段取一个不同的合法值"""
    valid = {
        "chunk_strategy": "fixed",
        "chunk_size": config.chunk_size + 1,
        "chunk_overlap": max(0, config.chunk_overlap + 1),
        "retriever_strategy": "simple",
        "top_k": config.top_k + 1,
        "dense_candidate_k": config.dense_candidate_k + 1,
        "sparse_candidate_k": config.sparse_candidate_k + 1,
        "rrf_k": config.rrf_k + 1.0,
    }
    return valid[field]


def test_id_is_hex_string():
    config = ExperimentConfig()
    assert len(config.experiment_id) == 12
    assert all(c in "0123456789abcdef" for c in config.experiment_id)


def test_id_independent_of_dict_order():
    """ID 不依赖字典插入顺序：同字段不同 dict 顺序产生相同 ID"""
    a = ExperimentConfig(top_k=9, chunk_size=200)
    b = ExperimentConfig(chunk_size=200, top_k=9)
    assert a.experiment_id == b.experiment_id
