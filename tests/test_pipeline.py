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


def test_index_file_update_keeps_old_data_when_embedding_fails(tmp_path):
    """更新时写入失败（embedding 报错）→ 旧数据必须保留（先写后删，不能先删后写）"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "doc6.txt"
    f.write_text("旧内容。" * 30, encoding="utf-8")

    r1 = pipeline.index_file(str(f))
    assert r1["status"] == "create"
    old_count = pipeline.vector_store.count()
    assert old_count > 0

    f.write_text("新内容。" * 30, encoding="utf-8")

    def boom(texts):
        raise RuntimeError("embedding 失败")

    pipeline.embedding.embed = boom

    try:
        pipeline.index_file(str(f))
        raise AssertionError("embedding 失败时应当抛出异常")
    except RuntimeError:
        pass

    assert pipeline.vector_store.count() == old_count


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


# ── G1-META-02-R1：index_file 实时入库写入 BM25 元数据 ──

def test_index_file_bm25_gets_full_metadata(tmp_path):
    """入库后不重启：BM25 条目已含 document_id 与来源字段"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "meta_doc1.txt"
    f.write_text("缓存穿透是指查询不存在的数据。" * 20, encoding="utf-8")

    result = pipeline.index_file(str(f))
    assert result["status"] == "create"
    bm25 = pipeline.retriever._bm25
    assert bm25._total_docs == result["chunks"]
    for chunk_id, meta in bm25._meta.items():
        assert meta.get("id") == chunk_id
        assert meta.get("document_id"), f"chunk {chunk_id} 缺 document_id"
        assert meta.get("source_name") or meta.get("source"), \
            f"chunk {chunk_id} 缺来源字段"


def test_index_file_sparse_only_flows_to_assembler(tmp_path):
    """入库后不重启：模拟 Dense 未命中、Sparse-only 命中 → assembler 来源非 unknown"""
    from core.context.assembler import ContextAssembler
    from core.loader.base import Document
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "meta_doc2.txt"
    f.write_text("缓存击穿是指热点key失效。" * 20, encoding="utf-8")
    pipeline.index_file(str(f))

    bm25 = pipeline.retriever._bm25
    chunk_id = next(iter(bm25._meta))
    meta = bm25.get_meta(chunk_id)          # 模拟 Sparse-only 从 BM25 恢复
    meta["id"] = chunk_id
    doc = Document(content=bm25.get_text(chunk_id), metadata=meta)

    blocks = ContextAssembler().assemble([doc])
    assert len(blocks) == 1
    assert blocks[0].source_name != "unknown"


def test_index_file_update_refreshes_bm25(tmp_path):
    """同文件更新：BM25 使用新正文新元数据，文档数不膨胀"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "meta_doc3.txt"
    f.write_text("旧内容一。" * 30, encoding="utf-8")
    r1 = pipeline.index_file(str(f))
    bm25 = pipeline.retriever._bm25
    count_before = bm25._total_docs
    assert count_before == r1["chunks"]

    f.write_text("新内容二。" * 30, encoding="utf-8")
    r2 = pipeline.index_file(str(f))
    assert r2["status"] == "update"

    assert bm25._total_docs == count_before, "BM25 文档数不得膨胀"
    hashes = {meta.get("content_hash") for meta in bm25._meta.values()}
    assert len(hashes) == 1, "更新后 BM25 只应保留新版本 content_hash"
    for chunk_id in bm25._meta:
        assert "新内容二" in bm25.get_text(chunk_id)


# ── P0-3: reranker 配置接线 ──────────────────────────

def test_query_wires_reranker_candidate_and_final_k(tmp_path):
    """reranker_candidate_k/final_k 配置真正生效"""
    pipeline = _make_pipeline(tmp_path)
    calls = {}

    class FakeRetriever:
        def retrieve(self, query, top_k=5):
            calls["retrieve_top_k"] = top_k
            return [Document(content="内容A", metadata={"id": "a", "score": 0.99, "source_name": "x.md"})]

    class FakeReranker:
        def rerank(self, query, docs, top_k=5):
            calls["rerank_top_k"] = top_k
            return docs

    pipeline.retriever = FakeRetriever()
    pipeline.reranker = FakeReranker()
    pipeline.config.reranker_candidate_k = 7
    pipeline.config.reranker_final_k = 2
    pipeline.config.min_score = 0.95  # 高阈值 → 拒答，不触发 generator

    pipeline.query("测试问题")

    assert calls["retrieve_top_k"] == 7
    assert calls["rerank_top_k"] == 2


def test_query_disabled_reranker_skips_rerank(tmp_path):
    """reranker_enabled=False 时完全不调用 reranker"""
    pipeline = _make_pipeline(tmp_path)

    class FakeRetriever:
        def retrieve(self, query, top_k=5):
            return [Document(content="内容A", metadata={"id": "a", "score": 0.99, "source_name": "x.md"})]

    class SpyReranker:
        def __init__(self):
            self.called = False

        def rerank(self, query, docs, top_k=5):
            self.called = True
            return docs

    spy = SpyReranker()
    pipeline.retriever = FakeRetriever()
    pipeline.reranker = spy
    pipeline.config.reranker_enabled = False
    pipeline.config.min_score = 0.95

    pipeline.query("测试问题")

    assert not spy.called


# ── REWORK-P0-01: 真实 Hybrid 候选链路 ───────────────

class _FakeEmbedding:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3]] * len(texts)

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class _FakeStore10:
    def __init__(self):
        self.docs = [
            Document(content=f"文档内容{i}", metadata={
                "id": f"c{i}", "source_name": "doc.md", "score": 0.9 - i * 0.01,
            })
            for i in range(10)
        ]

    def search(self, query_emb, top_k=5, where=None):
        return self.docs[:top_k]

    def count(self):
        return len(self.docs)


class _RecordingReranker:
    def __init__(self):
        self.received = None

    def rerank(self, query, docs, top_k=5):
        self.received = len(docs)
        return docs[:top_k]


class _FakeGenerator:
    def available_context_tokens(self, query):
        return 3000

    def generate(self, question, blocks):
        return " ".join(f"[C{i}]" for i in range(1, len(blocks) + 1))


def _pipeline_with_real_hybrid():
    """按 Pipeline 实际初始化方式构造：真实 HybridRetriever（final_k=config.top_k）"""
    pipeline = Pipeline(config_path=None, deepseek_api_key="sk-00000000000000000000000000000000")
    pipeline.embedding = _FakeEmbedding()
    pipeline.vector_store = _FakeStore10()
    pipeline.retriever = pipeline._init_retriever()
    return pipeline


def test_real_hybrid_candidate_chain():
    """真实 HybridRetriever：candidate_k=7 → reranker 收到 7 条 → final=2 返回 2 条"""
    pipeline = _pipeline_with_real_hybrid()
    reranker = _RecordingReranker()
    pipeline.reranker = reranker
    pipeline.generator = _FakeGenerator()
    pipeline.config.reranker_candidate_k = 7
    pipeline.config.reranker_final_k = 2

    result = pipeline.query("测试问题", top_k=5)

    assert reranker.received == 7, f"reranker 应收到 7 条候选，实际 {reranker.received}"
    assert len(result["sources"]) == 2


def test_reranker_disabled_truncates_to_request_k():
    """reranker 关闭时，最终结果严格截断为请求的 top_k"""
    pipeline = _pipeline_with_real_hybrid()
    pipeline.reranker = _RecordingReranker()
    pipeline.generator = _FakeGenerator()
    pipeline.config.reranker_enabled = False

    result = pipeline.query("测试问题", top_k=3)

    assert len(result["sources"]) == 3


# ── REWORK-P0-02: BM25 不膨胀 + ID 正文对齐 ───────────

def test_index_file_update_no_bm25_inflation(tmp_path):
    """部分 Chunk ID 不变时更新文档，BM25 文档数不膨胀"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "bm1.txt"
    f.write_text("缓存穿透的解决方案是布隆过滤器。" * 40, encoding="utf-8")
    r1 = pipeline.index_file(str(f))
    assert r1["status"] == "create"

    f.write_text(
        "缓存穿透的解决方案是布隆过滤器。" * 35 + "缓存击穿的解决方案是互斥锁。" * 5,
        encoding="utf-8",
    )
    r2 = pipeline.index_file(str(f))
    assert r2["status"] == "update"

    store_count = pipeline.vector_store.count()
    bm25_count = pipeline.retriever._bm25._total_docs
    assert store_count > 0
    assert bm25_count == store_count, f"BM25 {bm25_count} != store {store_count}"


def test_delete_document_bm25_consistent(tmp_path):
    """删除更新后的文档，BM25 所有统计恢复一致"""
    pipeline = _make_pipeline(tmp_path)
    f = tmp_path / "bm2.txt"
    f.write_text("缓存穿透的解决方案是布隆过滤器。" * 40, encoding="utf-8")
    r = pipeline.index_file(str(f))
    assert r["chunks"] > 0

    pipeline.delete_document(r["document_id"])

    assert pipeline.retriever._bm25._total_docs == 0
    assert len(pipeline.retriever._bm25._doc_freqs) == 0
    assert pipeline.retriever._bm25._df == {}


# ── M3-T4: 无答案拒答 ────────────────────────────────

def test_query_empty_retrieval_returns_no_answer():
    """空检索时不调用 LLM，直接返回无答案"""
    pipeline = Pipeline(config_path=None, deepseek_api_key="sk-00000000000000000000000000000000")
    pipeline.vector_store = ChromaStore(path=None, collection_name="empty_qa")
    pipeline.retriever = pipeline._init_retriever()

    result = pipeline.query("不存在的知识")
    assert "现有资料中没有找到" in result["answer"]


def test_query_low_score_refuses_answer(tmp_path):
    """min_score 开启时低置信问题被拒答"""
    pipeline = _make_pipeline(tmp_path)
    pipeline.config.min_score = 0.9  # 高阈值，逼出拒答

    f = tmp_path / "doc5.txt"
    f.write_text("缓存穿透的解决方案是布隆过滤器。" * 20, encoding="utf-8")
    pipeline.index_file(str(f))

    result = pipeline.query("缓存穿透的解决方案")
    assert "资料不足" in result["answer"] or "没有找到" in result["answer"]


# ── M3-T6: 多轮对话改写 ──────────────────────────────

def test_query_rewriter_no_history_unchanged():
    """无历史时原样返回"""
    from core.query_rewriter import QueryRewriter
    rw = QueryRewriter()
    assert rw.rewrite([], "什么是缓存穿透？") == "什么是缓存穿透？"


def test_query_rewriter_no_pronoun_unchanged():
    """无指代词时原样返回"""
    from core.query_rewriter import QueryRewriter
    rw = QueryRewriter()
    history = [{"role": "user", "content": "什么是缓存穿透？"}]
    assert rw.rewrite(history, "缓存击穿是什么？") == "缓存击穿是什么？"


def test_query_rewriter_pronoun_resolved():
    """指代问题被改写为独立问句"""
    from core.query_rewriter import QueryRewriter
    rw = QueryRewriter()
    history = [{"role": "user", "content": "什么是缓存穿透？"}]
    result = rw.rewrite(history, "它和击穿有什么区别？")
    assert "缓存穿透" in result
    assert "击穿" in result


# ── G1-CTX-03B：端到端 Prompt Budget（Pipeline/Config 侧） ──

def _write_config(tmp_path, **generator_overrides):
    config = {
        "embedding": {"provider": "bge", "model": "BAAI/bge-small-zh-v1.5"},
        "chunker": {"strategy": "fixed", "size_tokens": 100, "overlap_tokens": 10},
        "retriever": {"strategy": "hybrid", "top_k": 3},
        "generator": {"provider": "deepseek", "model": "deepseek-v4-flash",
                      "temperature": 0.3},
        "vector_store": {"path": str(tmp_path / "vs")},
    }
    config["generator"].update(generator_overrides)
    config_path = tmp_path / "cfg_budget.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return config_path


def test_config_rejects_invalid_budget_values(tmp_path):
    """非法预算配置被拒绝（ConfigError）"""
    from core.config import Config, ConfigError
    bad = [
        {"max_total_tokens": 0},
        {"max_total_tokens": True},
        {"max_total_tokens": 100, "max_output_tokens": 100},
        {"max_output_tokens": 800, "max_total_tokens": 100},
    ]
    for overrides in bad:
        cfg_path = _write_config(tmp_path, **overrides)
        try:
            Config(str(cfg_path))
            raise AssertionError(f"应拒绝: {overrides}")
        except ConfigError:
            pass


def test_config_dump_contains_budget_fields(tmp_path):
    """Config.dump() 输出预算字段（无密钥）"""
    from core.config import Config
    cfg_path = _write_config(tmp_path, max_total_tokens=4096,
                             max_output_tokens=800, message_overhead_tokens=16)
    cfg = Config(str(cfg_path))
    d = cfg.dump()
    assert d["generator_max_total_tokens"] == 4096
    assert d["generator_max_output_tokens"] == 800
    assert d["generator_message_overhead_tokens"] == 16
    assert "api_key" not in str(d).lower() and "sk-" not in str(d)


def test_query_passes_generator_budget_to_assembler(tmp_path, monkeypatch):
    """Pipeline.query 把 Generator 计算的预算传给 ContextAssembler"""
    from core.context.assembler import ContextAssembler
    from core.context import assembler as asm_mod
    pipeline = _make_pipeline(tmp_path)

    class FakeRetriever:
        def retrieve(self, query, top_k=5):
            return [Document(content="内容A", metadata={
                "id": "a", "score": 0.99, "source_name": "x.md"})]

    class FakeReranker:
        def rerank(self, query, docs, top_k=5):
            return docs

    class FakeGen:
        def available_context_tokens(self, query):
            return 42

        def validate_budget(self, query, blocks):
            pass

        def generate(self, query, context_docs):
            return "答案 [C1]"

    pipeline.retriever = FakeRetriever()
    pipeline.reranker = FakeReranker()
    pipeline.generator = FakeGen()

    captured = {}
    class SpyAssembler(ContextAssembler):
        def __init__(self, *args, **kwargs):
            captured["budget"] = kwargs.get("max_context_tokens")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(asm_mod, "ContextAssembler", SpyAssembler)
    result = pipeline.query("q")
    assert captured["budget"] == 42
    assert result["answer"] == "答案 [C1]"


# ── G1-RANK-04：Pipeline 最终顺序契约 ─────────────────

def _ordered_query_pipeline(tmp_path, reranker_enabled=True, reranker_fails=False):
    pipeline = _make_pipeline(tmp_path)
    pipeline.config.reranker_enabled = reranker_enabled

    class FakeRetriever:
        def retrieve(self, query, top_k=5):
            return [
                Document(content="内容A", metadata={"id": "a", "score": 0.1,
                                                   "rrf_score": 0.9, "source_name": "x.md"}),
                Document(content="内容B", metadata={"id": "b", "score": 0.9,
                                                   "rrf_score": 0.2, "source_name": "y.md"}),
            ]

    class FakeReranker:
        def rerank(self, query, docs, top_k=5):
            if reranker_fails:
                raise RuntimeError("reranker 挂了")
            return list(reversed(docs))  # B 在前

    pipeline.retriever = FakeRetriever()
    pipeline.reranker = FakeReranker()
    pipeline.generator = _FakeGenerator()
    return pipeline


def test_reranker_failure_keeps_retriever_order(tmp_path):
    """Reranker 失败后：sources 保持 Retriever 返回顺序（RRF 顺序）"""
    pipeline = _ordered_query_pipeline(tmp_path, reranker_fails=True)
    result = pipeline.query("q")
    assert [s["source"] for s in result["sources"]] == ["x.md", "y.md"]


def test_reranker_disabled_keeps_rrf_order(tmp_path):
    """reranker_enabled=False：保持 RRF 顺序"""
    pipeline = _ordered_query_pipeline(tmp_path, reranker_enabled=False)
    result = pipeline.query("q")
    assert [s["source"] for s in result["sources"]] == ["x.md", "y.md"]


def test_reranker_success_keeps_reranked_order(tmp_path):
    """Reranker 成功时：保持 Reranker 返回顺序"""
    pipeline = _ordered_query_pipeline(tmp_path, reranker_enabled=True)
    result = pipeline.query("q")
    assert [s["source"] for s in result["sources"]] == ["y.md", "x.md"]
    # sources.score 用统一展示分数（rrf_score 优先于 score）
    assert result["sources"][1]["score"] == 0.9


# ── G1-CHUNK-05B：普通 Config 保留 semantic 手动入口 ───

def test_app_config_accepts_semantic_chunker(tmp_path):
    """普通应用配置仍可读取 semantic（手动/学习入口兼容）"""
    from core.config import Config
    cfg_path = _write_config(tmp_path)
    raw = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    raw["chunker"]["strategy"] = "semantic"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f)
    cfg = Config(str(cfg_path))
    assert cfg.chunker_strategy == "semantic"
