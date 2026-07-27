from core.pipeline import Pipeline


def test_pipeline_init():
    pipeline = Pipeline(
        config_path=None,
        deepseek_api_key="sk-test",
        openai_api_key="sk-test",
    )
    assert pipeline.embedding is not None
    assert pipeline.chunker is not None
    assert pipeline.retriever is not None
    assert pipeline.generator is not None


def test_pipeline_loader_mapping():
    pipeline = Pipeline(config_path=None, deepseek_api_key="sk-test", openai_api_key="sk-test")
    assert ".py" in pipeline.loader_map
    assert ".pdf" in pipeline.loader_map
    assert ".txt" in pipeline.loader_map
    assert ".md" in pipeline.loader_map


def test_pipeline_with_bge_embedding():
    """使用 BGE（本地）embedding 初始化，不需要 API key"""
    config = {
        "embedding": {"provider": "bge", "model": "BAAI/bge-small-zh-v1.5"},
        "chunker": {"strategy": "recursive", "chunk_size": 256, "chunk_overlap": 32},
        "retriever": {"strategy": "hybrid", "top_k": 3},
        "generator": {"provider": "deepseek", "model": "deepseek-v4-flash", "temperature": 0.3},
        "vector_store": {"path": "./data/test_store"},
    }
    import yaml, tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "test_config.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        pipeline = Pipeline(config_path=config_path, deepseek_api_key="sk-test")
        assert pipeline.embedding is not None
        assert pipeline.chunker is not None
        assert pipeline.retriever is not None
        assert pipeline.generator is not None
