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
        "embedding_provider": "bge",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
    }


# ── 非法边界 ──────────────────────────────────────────

def test_invalid_chunk_strategy_rejected():
    with pytest.raises(ValueError, match="chunk_strategy"):
        ExperimentConfig(chunk_strategy="graph")


def test_semantic_strategy_rejected_as_experimental():
    """semantic 是实验性实现：不得用于正式可复现实验"""
    with pytest.raises(ValueError, match="实验性"):
        ExperimentConfig(chunk_strategy="semantic")


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
                  "sparse_candidate_k", "rrf_k",
                  "embedding_provider", "embedding_model"):
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
        "embedding_provider": "openai",
        "embedding_model": "BAAI/bge-large-zh-v1.5",
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


# ── 类型契约（复审补强） ───────────────────────────────

@pytest.mark.parametrize("field", ["chunk_size", "chunk_overlap", "top_k",
                                   "dense_candidate_k", "sparse_candidate_k"])
def test_bool_rejected_for_int_fields(field):
    with pytest.raises(TypeError, match=field):
        ExperimentConfig(**{field: True})


@pytest.mark.parametrize("field", ["chunk_size", "top_k",
                                   "dense_candidate_k", "sparse_candidate_k"])
def test_float_rejected_for_int_fields(field):
    with pytest.raises(TypeError, match=field):
        ExperimentConfig(**{field: 30.5})


def test_float_rejected_for_chunk_overlap():
    with pytest.raises(TypeError, match="chunk_overlap"):
        ExperimentConfig(chunk_overlap=1.5)


def test_rrf_k_bool_rejected():
    with pytest.raises(TypeError, match="rrf_k"):
        ExperimentConfig(rrf_k=True)


def test_rrf_k_normalized_to_float():
    config = ExperimentConfig(rrf_k=60)
    assert config.rrf_k == 60.0
    assert isinstance(config.rrf_k, float)


def test_rrf_k_int_and_float_same_id():
    """rrf_k=60 与 60.0 语义相同，必须产生相同 experiment_id"""
    a = ExperimentConfig(rrf_k=60)
    b = ExperimentConfig(rrf_k=60.0)
    assert a == b
    assert a.experiment_id == b.experiment_id


def test_strategy_fields_must_be_str():
    with pytest.raises(TypeError, match="chunk_strategy"):
        ExperimentConfig(chunk_strategy=123)
    with pytest.raises(TypeError, match="retriever_strategy"):
        ExperimentConfig(retriever_strategy=None)


# ============================================================
# G2-REAL-11-R1：Embedding 身份纳入 ExperimentConfig
# ============================================================


def test_default_embedding_identity_present():
    config = ExperimentConfig()
    assert config.embedding_provider == "bge"
    assert config.embedding_model == "BAAI/bge-small-zh-v1.5"
    d = config.to_dict()
    assert d["embedding_provider"] == "bge"
    assert d["embedding_model"] == "BAAI/bge-small-zh-v1.5"


def test_embedding_model_change_changes_experiment_id():
    a = ExperimentConfig(embedding_model="A")
    b = ExperimentConfig(embedding_model="B")
    assert a.experiment_id != b.experiment_id


def test_embedding_provider_change_changes_experiment_id():
    a = ExperimentConfig(embedding_provider="bge")
    b = ExperimentConfig(embedding_provider="openai")
    assert a.experiment_id != b.experiment_id


@pytest.mark.parametrize("field", ["embedding_provider", "embedding_model"])
@pytest.mark.parametrize("value", [123, None, True, 1.0])
def test_embedding_fields_reject_non_string(field, value):
    with pytest.raises(TypeError, match=field):
        ExperimentConfig(**{field: value})


@pytest.mark.parametrize("field", ["embedding_provider", "embedding_model"])
def test_embedding_fields_reject_empty_string(field):
    with pytest.raises(ValueError, match=field):
        ExperimentConfig(**{field: ""})
