"""G2-IMPL-20：BGE-Aligned Chunk Budget Infrastructure 测试。

全部使用 fake tokenizer / fake SentenceTransformer / synthetic
documents / temporary workspace；不访问网络、不加载真实 BGE、
不运行真实 Benchmark Retrieval。
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from core.chunker.embedding_runtime_counter import EmbeddingRuntimeTokenCounter
from core.chunker.fixed_size import FixedSizeChunker
from core.chunker.recursive import RecursiveChunker
from core.chunker.token_counter import TokenCounter
from core.config import Config, ConfigError
from core.embeddings import runtime_contract as rc
from core.loader.base import Document
from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_resolver import resolve_experiment_config
from evaluation.experiment_runner import PreparedExperiment, ExperimentRunner
from evaluation.experiment_spec import ExperimentSpec
from evaluation.experiment_workspace import ExperimentWorkspace
from evaluation.index_manifest import MANIFEST_SCHEMA_VERSION, IndexManifest


# ── fakes ───────────────────────────────────────────────────


class FakeRuntimeTokenizer:
    """同 class/max 可模拟不同 behavior 的 runtime tokenizer。"""

    def __init__(self, behavior="default", overhead=2, model_max_length=512):
        self.behavior = behavior
        self.model_max_length = model_max_length
        self.overhead = overhead

    def num_special_tokens_to_add(self, pair=False):
        return self.overhead

    def __call__(self, text, add_special_tokens=True, truncation=False):
        if self.behavior == "lower":
            ids = [1000 + i for i in range(len(text))]
        else:
            ids = list(range(len(text)))
        if add_special_tokens:
            ids = [101] + ids + [102]
        return {"input_ids": ids}


class NonMonotonicTokenizer:
    """按窗口长度返回非单调 token 数（真实 Bug 模拟）。"""

    def __init__(self, length_map):
        self.length_map = length_map
        self.model_max_length = 512

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, text, add_special_tokens=True, truncation=False):
        n = self.length_map.get(len(text), len(text))
        ids = list(range(n))
        if add_special_tokens:
            ids = [101] + ids + [102]
        return {"input_ids": ids}


class FakeST:
    def __init__(self, max_seq_length=512, tokenizer=None):
        self.max_seq_length = max_seq_length
        self.tokenizer = tokenizer or FakeRuntimeTokenizer()
        self._first = SimpleNamespace(tokenizer=self.tokenizer)

    def __getitem__(self, index):
        return self._first


class FakeBGEEmbedding:
    """与 BGEEmbedding 同语义的窄接口替身。"""

    def __init__(self, model=None):
        self._model = model or FakeST()
        self.encode_calls = 0

    def get_runtime_model(self):
        return self._model

    def get_runtime_tokenizer(self):
        return self._model[0].tokenizer

    def get_runtime_contract(self):
        return rc.compute_tokenizer_contract(
            self._model[0].tokenizer, model=self._model
        )

    def embed(self, texts):
        self.encode_calls += 1
        return [[0.0] * 8 for _ in texts]


class FakeStore:
    def __init__(self, count=0, chunks=None):
        self._count = count
        self._chunks = list(chunks or [])

    def count(self):
        return self._count

    def get_all_indexed(self):
        return list(self._chunks)


class FakeAlignedPipeline:
    def __init__(self, config, embedding, counter, store):
        self.config = config
        self.embedding = embedding
        self.chunker = SimpleNamespace(_counter=counter)
        self.vector_store = store
        self.retriever = None

    def index_file(self, path):
        return {
            "status": "create",
            "document_id": Path(path).name,
            "chunks": 1,
        }


def _aligned_config(embedding, spec=None):
    spec = spec or ExperimentSpec(
        chunk_budget_policy="embedding_runtime_model_input_v1",
        retriever_strategy="simple",
    )
    import core.embeddings.bge_emb as bge_emb

    orig = bge_emb.BGEEmbedding
    bge_emb.BGEEmbedding = lambda model_name=None: embedding
    try:
        return resolve_experiment_config(spec)
    finally:
        bge_emb.BGEEmbedding = orig


BASE_CONFIG_YAML = """\
embedding:
  provider: bge
  model: BAAI/bge-small-zh-v1.5
chunker:
  strategy: recursive
  size_tokens: 512
  overlap_tokens: 64
retriever:
  strategy: simple
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


def _write_base(tmp_path, extra_chunker=None):
    raw = yaml.safe_load(BASE_CONFIG_YAML)
    if extra_chunker:
        raw["chunker"].update(extra_chunker)
    path = tmp_path / "base_config.yaml"
    path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


class LocalFakeConfig:
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


# ── runtime contract ────────────────────────────────────────


def test_contract_fingerprint_stable_for_fixed_probe():
    tok = FakeRuntimeTokenizer()
    a = rc.compute_tokenizer_contract(tok)
    b = rc.compute_tokenizer_contract(tok)
    assert a == b
    assert len(a["tokenizer_contract_fingerprint"]) == 16


def test_same_class_max_different_behavior_changes_fingerprint():
    tok_a = FakeRuntimeTokenizer(behavior="default")
    tok_b = FakeRuntimeTokenizer(behavior="lower")
    assert type(tok_a).__name__ == type(tok_b).__name__
    assert tok_a.model_max_length == tok_b.model_max_length == 512
    ca = rc.compute_tokenizer_contract(tok_a)
    cb = rc.compute_tokenizer_contract(tok_b)
    assert ca["runtime_tokenizer_class"] == cb["runtime_tokenizer_class"]
    assert ca["effective_embedding_max_seq_length"] == 512
    assert ca["tokenizer_contract_fingerprint"] != cb[
        "tokenizer_contract_fingerprint"
    ]


def test_probe_version_change_changes_contract_identity(monkeypatch):
    tok = FakeRuntimeTokenizer()
    v1 = rc.compute_tokenizer_contract(tok)
    monkeypatch.setattr(rc, "TOKENIZER_CONTRACT_PROBE_VERSION", "v2")
    v2 = rc.compute_tokenizer_contract(tok)
    assert v2["tokenizer_contract_probe_version"] == "v2"
    assert v1["tokenizer_contract_fingerprint"] != v2[
        "tokenizer_contract_fingerprint"
    ]


def test_special_overhead_comes_from_runtime_not_hardcoded():
    tok = FakeRuntimeTokenizer(overhead=3)
    contract = rc.compute_tokenizer_contract(tok)
    assert contract["special_token_overhead"] == 3
    assert contract["effective_embedding_max_seq_length"] == 512


# ── resolver / identity ─────────────────────────────────────


def test_unresolved_spec_has_no_experiment_id():
    assert not hasattr(ExperimentSpec(), "experiment_id")


def test_cl100k_resolve_does_not_touch_bge(monkeypatch):
    import core.embeddings.bge_emb as bge_emb

    def boom(*args, **kwargs):
        raise AssertionError("cl100k 不得加载 SentenceTransformer")

    monkeypatch.setattr(bge_emb, "BGEEmbedding", boom)
    config = resolve_experiment_config(ExperimentSpec())
    assert config.chunk_budget_policy == "cl100k_content_v1"
    assert config.effective_embedding_max_seq_length is None
    assert config.tokenizer_contract_fingerprint is None


def test_aligned_resolve_runs_preflight_and_binds_contract():
    embedding = FakeBGEEmbedding()
    config = _aligned_config(embedding)
    assert config.chunk_budget_policy == "embedding_runtime_model_input_v1"
    assert config.effective_embedding_max_seq_length == 512
    assert config.special_token_overhead == 2
    assert config.tokenizer_contract_probe_version == "v1"
    assert len(config.tokenizer_contract_fingerprint) == 16


def test_runtime_identity_change_changes_experiment_id():
    a = _aligned_config(FakeBGEEmbedding(FakeST(tokenizer=FakeRuntimeTokenizer("default"))))
    b = _aligned_config(FakeBGEEmbedding(FakeST(tokenizer=FakeRuntimeTokenizer("lower"))))
    assert a.experiment_id != b.experiment_id
    cl100k = resolve_experiment_config(ExperimentSpec())
    assert cl100k.experiment_id != a.experiment_id


def test_aligned_half_parsed_config_rejected():
    with pytest.raises(ValueError, match="fingerprint"):
        ExperimentConfig(
            chunk_budget_policy="embedding_runtime_model_input_v1",
            effective_embedding_max_seq_length=512,
            special_token_overhead=2,
            tokenizer_contract_probe_version="v1",
            tokenizer_contract_fingerprint=None,
        )
    with pytest.raises(ValueError, match="不允许"):
        ExperimentConfig(
            chunk_budget_policy="cl100k_content_v1",
            tokenizer_contract_fingerprint="a" * 16,
        )


def test_aligned_chunk_size_must_equal_runtime_max():
    with pytest.raises(ValueError, match="chunk_size"):
        _aligned_config(
            FakeBGEEmbedding(),
            ExperimentSpec(
                chunk_budget_policy="embedding_runtime_model_input_v1",
                chunk_size=256,
                retriever_strategy="simple",
            ),
        )
    config = _aligned_config(
        FakeBGEEmbedding(),
        ExperimentSpec(
            chunk_budget_policy="embedding_runtime_model_input_v1",
            chunk_size=512,
            retriever_strategy="simple",
        ),
    )
    assert config.chunk_size == 512
    assert config.chunk_size == config.effective_embedding_max_seq_length
    with pytest.raises(ValueError, match="chunk_size"):
        ExperimentConfig(
            chunk_budget_policy="embedding_runtime_model_input_v1",
            chunk_size=256,
            effective_embedding_max_seq_length=512,
            special_token_overhead=2,
            tokenizer_contract_probe_version="v1",
            tokenizer_contract_fingerprint="a" * 16,
        )


def test_preflight_failure_leaves_zero_workspace_side_effect(tmp_path, monkeypatch):
    class BrokenEmbedding(FakeBGEEmbedding):
        def get_runtime_contract(self):
            raise RuntimeError("runtime contract 解析失败")

    workspace_root = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="runtime contract"):
        _aligned_config(BrokenEmbedding())
    assert not workspace_root.exists(), "Preflight 失败不得创建任何 Workspace"


# ── same-instance binding ───────────────────────────────────


def test_counter_tokenizer_is_same_model_instance_as_encode():
    tok = FakeRuntimeTokenizer()
    model = FakeST(tokenizer=tok)
    embedding = FakeBGEEmbedding(model)
    counter = EmbeddingRuntimeTokenCounter(
        embedding.get_runtime_tokenizer(), 512
    )
    assert counter.tokenizer is embedding.get_runtime_model()[0].tokenizer
    assert counter.tokenizer is tok


def test_wrong_counter_prepare_fails_before_index(tmp_path):
    embedding = FakeBGEEmbedding()
    config = _aligned_config(embedding)
    base = _write_base(tmp_path)

    def factory(config_path):
        cfg = LocalFakeConfig(config_path)
        pipeline = SimpleNamespace(
            config=cfg,
            embedding=embedding,
            retriever=None,
            chunker=SimpleNamespace(_counter=TokenCounter()),
        )
        return pipeline

    runner = ExperimentRunner(base, tmp_path / "runs", factory)
    with pytest.raises(RuntimeError, match="EmbeddingRuntimeTokenCounter"):
        runner.prepare(config, "run1")


def test_pipeline_contract_mismatch_fails_before_index(tmp_path):
    base = _write_base(tmp_path)
    preflight_embedding = FakeBGEEmbedding(
        FakeST(tokenizer=FakeRuntimeTokenizer("default"))
    )
    config = _aligned_config(preflight_embedding)
    other_embedding = FakeBGEEmbedding(
        FakeST(tokenizer=FakeRuntimeTokenizer("lower"))
    )
    counter = EmbeddingRuntimeTokenCounter(
        other_embedding.get_runtime_tokenizer(), 512
    )

    def factory(config_path):
        cfg = LocalFakeConfig(config_path)
        from core.retriever.simple import SimpleRetriever
        return SimpleNamespace(
            config=cfg,
            embedding=other_embedding,
            retriever=SimpleRetriever(None, None),
            chunker=SimpleNamespace(_counter=counter),
        )

    runner = ExperimentRunner(base, tmp_path / "runs", factory)
    with pytest.raises(RuntimeError, match="runtime contract"):
        runner.prepare(config, "run1")


def test_same_contract_different_tokenizer_object_fails(tmp_path):
    """同类型/同 max/同 behavior/同 fingerprint，但 Python 对象不同 → fail。"""
    tokenizer_a = FakeRuntimeTokenizer("default")
    tokenizer_b = FakeRuntimeTokenizer("default")
    contract_a = rc.compute_tokenizer_contract(tokenizer_a)
    contract_b = rc.compute_tokenizer_contract(tokenizer_b)
    assert contract_a == contract_b  # contract 完全相同
    assert tokenizer_a is not tokenizer_b

    embedding = FakeBGEEmbedding(FakeST(tokenizer=tokenizer_a))
    config = _aligned_config(embedding)
    counter = EmbeddingRuntimeTokenCounter(tokenizer_b, 512)
    base = _write_base(tmp_path)

    def factory(config_path):
        from core.retriever.simple import SimpleRetriever

        cfg = LocalFakeConfig(config_path)
        return SimpleNamespace(
            config=cfg,
            embedding=embedding,
            retriever=SimpleRetriever(None, None),
            chunker=SimpleNamespace(_counter=counter),
        )

    runner = ExperimentRunner(base, tmp_path / "runs", factory)
    with pytest.raises(RuntimeError, match="同一个 tokenizer 对象"):
        runner.prepare(config, "run1")


# ── budget / chunking ───────────────────────────────────────


def test_content_budget_is_max_minus_overhead():
    counter = EmbeddingRuntimeTokenCounter(FakeRuntimeTokenizer(), 512)
    assert counter.model_input_budget == 512
    assert counter.special_token_overhead == 2
    assert counter.content_budget == 510
    assert counter.name == "embedding_runtime"
    assert counter.policy == "embedding_runtime_model_input_v1"


def test_aligned_chunks_respect_content_and_model_budget():
    counter = EmbeddingRuntimeTokenCounter(FakeRuntimeTokenizer(), 512)
    chunker = RecursiveChunker(
        chunk_size=counter.content_budget,
        chunk_overlap=64,
        token_counter=counter,
    )
    text = "证据内容" * 200
    chunks = chunker.chunk([Document(content=text, metadata={})])
    assert chunks
    for chunk in chunks:
        assert counter.count_model_input(chunk.content) <= 512
        assert counter.count(chunk.content) <= 510
        assert chunk.content in text  # 原文精确 substring


def test_model_input_exactly_512_is_ok_513_would_truncate():
    class SizedTokenizer(FakeRuntimeTokenizer):
        def __call__(self, text, add_special_tokens=True, truncation=False):
            n = len(text)
            ids = list(range(n))
            if add_special_tokens:
                ids = [101] + ids + [102]
            return {"input_ids": ids}

    tok = SizedTokenizer()
    counter = EmbeddingRuntimeTokenCounter(tok, 512)
    text_510 = "x" * 510
    text_511 = "x" * 511
    assert counter.count_model_input(text_510) == 512
    assert counter.count_model_input(text_511) == 513


def test_non_monotonic_max_substring_finds_true_furthest_boundary():
    length_map = {100: 509, 101: 513, 102: 510, 103: 513}
    counter = EmbeddingRuntimeTokenCounter(
        NonMonotonicTokenizer(length_map), 512
    )
    text = "x" * 103
    # 单调二分会停在 100；真实最远合法 boundary 是 102。
    assert counter.max_substring(text, 0, 512) == 102


def test_non_monotonic_substring_start_finds_true_min_start():
    length_map = {60: 65, 61: 63, 62: 66, 63: 62, 64: 66}
    counter = EmbeddingRuntimeTokenCounter(
        NonMonotonicTokenizer(length_map), 512
    )
    text = "y" * 100
    # 窗口长度 63（start=37）合法且是最小 start；
    # 62（start=38）非法、61（start=39）合法——单调二分会漏掉 37。
    assert counter.substring_start(text, 100, 64, min_start=30) == 37


def test_oversize_single_char_not_lost_and_no_infinite_loop():
    counter = EmbeddingRuntimeTokenCounter(
        NonMonotonicTokenizer({1: 999}), 512
    )
    assert counter.max_substring("x", 0, 510, allow_oversize=True) == 1
    assert counter.max_substring("x", 0, 510, allow_oversize=False) == 0
    assert counter.substring_start("xx", 2, 64, min_start=0) == 0


# ── pipeline / config wiring ────────────────────────────────


def test_core_config_parses_aligned_policy_and_rejects_bad_fingerprint(tmp_path):
    base = _write_base(
        tmp_path,
        {
            "budget_policy": "embedding_runtime_model_input_v1",
            "effective_embedding_max_seq_length": 512,
            "special_token_overhead": 2,
            "tokenizer_contract_probe_version": "v1",
            "tokenizer_contract_fingerprint": "a" * 16,
        },
    )
    cfg = Config(str(base))
    assert cfg.chunk_budget_policy == "embedding_runtime_model_input_v1"
    assert cfg.effective_embedding_max_seq_length == 512
    bad = _write_base(
        tmp_path,
        {
            "budget_policy": "embedding_runtime_model_input_v1",
            "effective_embedding_max_seq_length": 512,
            "special_token_overhead": 2,
            "tokenizer_contract_probe_version": "v1",
            "tokenizer_contract_fingerprint": "not-hex",
        },
    )
    with pytest.raises(ConfigError, match="fingerprint"):
        Config(str(bad))


def test_aligned_prepare_success_and_same_instance_counter(tmp_path):
    embedding = FakeBGEEmbedding()
    config = _aligned_config(embedding)
    base = _write_base(tmp_path)

    def factory(config_path):
        from core.chunker.embedding_runtime_counter import (
            EmbeddingRuntimeTokenCounter,
        )
        from core.retriever.simple import SimpleRetriever

        cfg = LocalFakeConfig(config_path)
        counter = EmbeddingRuntimeTokenCounter(
            embedding.get_runtime_tokenizer(),
            cfg.effective_embedding_max_seq_length,
        )
        pipeline = SimpleNamespace(
            config=cfg,
            embedding=embedding,
            retriever=SimpleRetriever(None, None),
            chunker=SimpleNamespace(_counter=counter),
        )
        return pipeline

    runner = ExperimentRunner(base, tmp_path / "runs", factory)
    prepared = runner.prepare(config, "run1")
    counter = prepared.pipeline.chunker._counter
    assert counter.tokenizer is embedding.get_runtime_model()[0].tokenizer
    assert counter.model_input_budget == config.chunk_size
    assert counter.model_input_budget == (
        config.effective_embedding_max_seq_length
    )


def test_fixed_non_monotonic_overlap_finds_true_leftmost_start():
    """较短 suffix 超限、更长 suffix 合法：不得第一次超限就提前停止。"""
    length_map = {
        4: 11,   # 短 suffix 超 overlap=10
        5: 10,   # 更长 suffix 恰好合法
        6: 12,   # 再长又超
        7: 9,    # 更长合法
        71: 71,  # 第一块在 71 超 chunk_size=70
        72: 65,  # 72 合法（非单调）
    }
    counter = EmbeddingRuntimeTokenCounter(
        NonMonotonicTokenizer(length_map), 512
    )
    chunker = FixedSizeChunker(
        chunk_size=70, chunk_overlap=10, token_counter=counter
    )
    text = "x" * 100
    chunks = chunker.chunk([Document(content=text, metadata={})])
    assert len(chunks) >= 2
    first, second = chunks[0], chunks[1]
    assert first.metadata["char_start"] == 0
    assert first.metadata["char_end"] == 72
    # 旧实现会在 suffix len=4 超限时停在 69；正确的最左合法 start 是 62。
    assert second.metadata["char_start"] == 62
    assert second.content in text
    assert first.content in text
    assert len(text[62:72]) == 10  # overlap 是 10 个正文 token 对应的字符窗口


def test_recursive_long_document_safe_search_bounded_and_correct():
    """aligned Recursive：max_substring 必须有界（不扫全文后缀）、
    结果正确、无 encode、不死循环、chunk 全部满足预算。"""
    counter = EmbeddingRuntimeTokenCounter(FakeRuntimeTokenizer(), 512)
    original_max_substring = counter.max_substring
    calls = []

    def wrapped(text, start, limit, end=None, allow_oversize=False):
        calls.append(end)
        return original_max_substring(
            text, start, limit, end=end, allow_oversize=allow_oversize
        )

    counter.max_substring = wrapped
    chunker = RecursiveChunker(
        chunk_size=counter.content_budget,
        chunk_overlap=64,
        token_counter=counter,
    )
    text = ("证据内容与代码示例 " * 400) + "\n\n" + ("x" * 2000)
    chunks = chunker.chunk([Document(content=text, metadata={})])
    assert chunks
    for chunk in chunks:
        assert counter.count_model_input(chunk.content) <= 512
        assert chunk.content in text
    assert calls and all(end is not None for end in calls), (
        "aligned Recursive 的 max_substring 不得无界扫描全文后缀"
    )


def test_manifest_schema_version_is_two():
    assert IndexManifest().schema_version == MANIFEST_SCHEMA_VERSION == 2


# ── manifest / post-index observed facts ────────────────────


def _prepared_aligned(base_tmp, workspace_root, config, pipeline):
    base = _write_base(base_tmp)
    paths = ExperimentWorkspace(base, workspace_root, config, "run1").prepare()
    return PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=pipeline
    )


def _aligned_index_pipeline(config, embedding, counter, store):
    return FakeAlignedPipeline(config, embedding, counter, store)


def _aligned_manifest(tmp_path, workspace_root, content, chunk_id="c1"):
    embedding = FakeBGEEmbedding()
    config = _aligned_config(embedding)
    counter = EmbeddingRuntimeTokenCounter(
        embedding.get_runtime_tokenizer(), 512
    )
    store = FakeStore(
        count=1,
        chunks=[{"id": chunk_id, "content": content, "metadata": {}}],
    )
    pipeline = _aligned_index_pipeline(config, embedding, counter, store)
    prepared = _prepared_aligned(tmp_path, workspace_root, config, pipeline)
    runner = ExperimentRunner(tmp_path / "base_config.yaml", workspace_root)
    return runner, prepared, config


def test_aligned_manifest_observed_facts_and_hard_contract(tmp_path):
    from evaluation.experiment_corpus import ExperimentCorpus

    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("a" * 400, encoding="utf-8")
    corpus = ExperimentCorpus.build(root, ["a.md"])

    runner, prepared, config = _aligned_manifest(
        tmp_path, tmp_path / "runs", "a" * 400
    )
    manifest = runner.index_corpus(prepared, corpus)
    assert manifest.corpus_scoped_tokenizer_behavior_fingerprint
    assert manifest.actual_would_truncate_count == 0
    assert manifest.actual_model_input_token_max <= 512
    assert manifest.config == config.to_dict()

    raw = json.loads(
        prepared.paths.index_manifest_path.read_text(encoding="utf-8")
    )
    assert raw["schema_version"] == 2
    assert raw["corpus_scoped_tokenizer_behavior_fingerprint"] == (
        manifest.corpus_scoped_tokenizer_behavior_fingerprint
    )
    assert raw["actual_would_truncate_count"] == 0


def test_aligned_observed_fingerprint_stable_across_workspaces(tmp_path):
    from evaluation.experiment_corpus import ExperimentCorpus

    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("a" * 300, encoding="utf-8")
    corpus = ExperimentCorpus.build(root, ["a.md"])

    _, p1, _ = _aligned_manifest(tmp_path, tmp_path / "runs_a", "a" * 300)
    _, p2, _ = _aligned_manifest(tmp_path, tmp_path / "runs_b", "a" * 300)
    m1 = ExperimentRunner(tmp_path / "base_config.yaml", tmp_path / "runs_a").index_corpus(p1, corpus)
    m2 = ExperimentRunner(tmp_path / "base_config.yaml", tmp_path / "runs_b").index_corpus(p2, corpus)
    assert m1.corpus_scoped_tokenizer_behavior_fingerprint == (
        m2.corpus_scoped_tokenizer_behavior_fingerprint
    )
    d1 = json.loads(p1.paths.index_manifest_path.read_text(encoding="utf-8"))
    d2 = json.loads(p2.paths.index_manifest_path.read_text(encoding="utf-8"))
    assert d1 == d2


def test_would_truncate_blocks_success_manifest(tmp_path):
    from evaluation.experiment_corpus import ExperimentCorpus

    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("a" * 600, encoding="utf-8")
    corpus = ExperimentCorpus.build(root, ["a.md"])

    runner, prepared, _ = _aligned_manifest(
        tmp_path, tmp_path / "runs", "a" * 600
    )
    with pytest.raises(RuntimeError, match="intervention failed"):
        runner.index_corpus(prepared, corpus)
    assert not prepared.paths.index_manifest_path.exists()


def test_cl100k_manifest_observed_fields_are_none(tmp_path):
    from evaluation.experiment_corpus import ExperimentCorpus

    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.md").write_text("aaa", encoding="utf-8")
    corpus = ExperimentCorpus.build(root, ["a.md"])

    config = resolve_experiment_config(ExperimentSpec(retriever_strategy="simple"))
    store = FakeStore(count=1, chunks=[{"id": "c1", "content": "aaa", "metadata": {}}])
    pipeline = SimpleNamespace(
        config=None,
        embedding=None,
        retriever=None,
        vector_store=store,
        index_file=lambda path: {
            "status": "create",
            "document_id": "a.md",
            "chunks": 1,
        },
    )
    prepared = _prepared_aligned(
        tmp_path, tmp_path / "runs", config, pipeline
    )
    manifest = ExperimentRunner(
        tmp_path / "base_config.yaml", tmp_path / "runs"
    ).index_corpus(prepared, corpus)
    assert manifest.corpus_scoped_tokenizer_behavior_fingerprint is None
    assert manifest.actual_content_token_max is None
    assert manifest.actual_model_input_token_max is None
    assert manifest.actual_would_truncate_count is None
