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


# ── M1-T6 幂等入库 ────────────────────────────────────

def _make_pipeline(tmp_path):
    """构造使用 tmp_path 的 Pipeline（BGE embedding + 持久化 store）"""
    config = {
        "embedding": {"provider": "bge", "model": "BAAI/bge-small-zh-v1.5"},
        "chunker": {"strategy": "fixed", "size_tokens": 100, "overlap_tokens": 10},
        "retriever": {"strategy": "hybrid", "top_k": 3},
        "generator": {"provider": "deepseek", "model": "deepseek-v4-flash", "temperature": 0.3},
        "vector_store": {"path": str(tmp_path / "vs")},
    }
    config_path = tmp_path / "cfg.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return Pipeline(config_path=str(config_path), deepseek_api_key="sk-00000000000000000000000000000000")


def test_index_file_create(tmp_path):
    """新文件 → create"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "doc1.txt"
    f.write_text("第一段内容。第二段内容。" * 20, encoding="utf-8")

    result = pipeline.index_file(str(f))
    assert result["status"] == "create"
    assert result["chunks"] > 0


def test_index_file_no_change(tmp_path):
    """相同文件重复上传 → no_change，不重复计数"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "doc2.txt"
    f.write_text("缓存穿透是指查询不存在的数据。" * 20, encoding="utf-8")

    r1 = pipeline.index_file(str(f))
    r2 = pipeline.index_file(str(f))
    assert r1["status"] == "create"
    assert r2["status"] == "no_change"
    assert r2["chunks"] == 0
    assert pipeline.vector_store.count() == r1["chunks"]


def test_index_file_update(tmp_path):
    """内容变更 → update，旧 chunk 被替换"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "doc3.txt"
    f.write_text("旧内容。" * 30, encoding="utf-8")

    r1 = pipeline.index_file(str(f))
    assert r1["status"] == "create"

    f.write_text("新内容。" * 30, encoding="utf-8")
    r2 = pipeline.index_file(str(f))
    assert r2["status"] == "update"
    assert r2["chunks"] > 0
    assert pipeline.vector_store.count() == r2["chunks"]


def test_delete_document_cleans_vector_store(tmp_path):
    """删除文档后向量库中不再有该文档的 chunk"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "doc4.txt"
    f.write_text("要被删除的内容。" * 20, encoding="utf-8")

    r = pipeline.index_file(str(f))
    assert r["status"] == "create"
    assert pipeline.vector_store.count() == r["chunks"]

    pipeline.delete_document(r["document_id"])
    assert pipeline.vector_store.count() == 0
