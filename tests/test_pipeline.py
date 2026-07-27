import os, yaml
from core.pipeline import Pipeline
from core.vector_store.chroma_store import ChromaStore
from core.loader.base import Document


def test_pipeline_init():
    pipeline = Pipeline(
        config_path=None,
        deepseek_api_key="sk-00000000000000000000000000000000",
        openai_api_key="sk-test",
    )
    assert pipeline.embedding is not None
    assert pipeline.chunker is not None
    assert pipeline.retriever is not None
    assert pipeline.generator is not None


def test_pipeline_loader_mapping():
    pipeline = Pipeline(config_path=None, deepseek_api_key="sk-00000000000000000000000000000000", openai_api_key="sk-test")
    assert ".py" in pipeline.loader_map
    assert ".pdf" in pipeline.loader_map
    assert ".txt" in pipeline.loader_map
    assert ".md" in pipeline.loader_map


def test_pipeline_with_bge_embedding(tmp_path):
    """BGE embedding 初始化，vector_store 写入 tmp_path"""
    store_dir = tmp_path / "vector_store"
    config = {
        "embedding": {"provider": "bge", "model": "BAAI/bge-small-zh-v1.5"},
        "chunker": {"strategy": "recursive", "chunk_size": 256, "chunk_overlap": 32},
        "retriever": {"strategy": "hybrid", "top_k": 3},
        "generator": {"provider": "deepseek", "model": "deepseek-v4-flash", "temperature": 0.3},
        "vector_store": {"path": str(store_dir)},
    }
    config_path = tmp_path / "test_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    pipeline = Pipeline(config_path=str(config_path), deepseek_api_key="sk-00000000000000000000000000000000")
    assert pipeline.embedding is not None
    assert pipeline.chunker is not None
    assert pipeline.retriever is not None
    assert pipeline.generator is not None


# ── 测试隔离验证 ──────────────────────────────────────

def test_pipeline_does_not_create_default_store_dir():
    """Pipeline(config_path=None) 初始化不崩溃，不要求硬盘写入"""
    pipeline = Pipeline(
        config_path=None,
        deepseek_api_key="sk-00000000000000000000000000000000",
    )
    assert pipeline.embedding is not None
    assert pipeline.chunker is not None
    assert pipeline.retriever is not None


def test_pipeline_uses_injected_in_memory_store():
    """内存模式 ChromaStore 正常增删"""
    store = ChromaStore(path=None, collection_name="test_injected")
    assert store.count() == 0
    store.add([Document(content="test", metadata={})], [[0.1, 0.2, 0.3]])
    assert store.count() == 1


def test_persistent_store_uses_tmp_path(tmp_path):
    """持久化 ChromaStore 写入 tmp_path"""
    store_dir = tmp_path / "chroma_test"
    store = ChromaStore(path=str(store_dir), collection_name="tmp_test")
    assert store.count() == 0
    store.add([Document(content="hello", metadata={})], [[0.1] * 512])
    assert store.count() == 1
    assert store_dir.exists()


def test_tests_are_independent_of_execution_order():
    """不同 collection_name 的 store 互不干扰"""
    s1 = ChromaStore(path=None, collection_name="order_test_a")
    s2 = ChromaStore(path=None, collection_name="order_test_b")
    s1.add([Document(content="x", metadata={})], [[0.1, 0.2, 0.3]])
    assert s1.count() == 1
    assert s2.count() == 0
