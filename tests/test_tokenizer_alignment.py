"""G2-DIAG-18 纯数据诊断测试：不访问网络、不加载真实 BGE 模型。"""

import json

import pytest

from core.loader.base import Document
from scripts import analyze_tokenizer_alignment as ta


class FakeTokenizer:
    def __init__(self, specials=2):
        self.specials = specials
        self.calls = []

    def __call__(self, text, add_special_tokens=True, truncation=False):
        self.calls.append((text, add_special_tokens, truncation))
        n = len(text) + (self.specials if add_special_tokens else 0)
        return {"input_ids": list(range(n))}


class FakeCounter:
    def __init__(self, count_map=None):
        self._map = count_map or {}

    def count(self, text):
        return self._map.get(text, len(text))


class FakeModule:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer


class FakeRuntimeModel:
    def __init__(self, max_len=512, tokenizer=None):
        self.max_seq_length = max_len
        self._first = FakeModule(tokenizer)

    def __getitem__(self, index):
        return self._first


def _record(relative_path, content, chunk_index=0, start=0, end=None,
            oversized=False):
    doc = Document(
        content=content,
        metadata={
            "chunk_index": chunk_index,
            "token_count": len(content),
            "char_start": start,
            "char_end": end if end is not None else len(content),
            "oversized": oversized,
        },
    )
    return (relative_path, doc)


def test_bge_length_includes_special_tokens():
    tok = FakeTokenizer(specials=2)
    bge, content = ta.bge_lengths(tok, "你好")
    assert bge == 4  # 2 内容 + 2 特殊 token
    assert content == 2
    assert tok.calls == [
        ("你好", True, False),
        ("你好", False, False),
    ]


def test_would_truncate_boundary():
    assert ta.would_truncate(512, 512) is False
    assert ta.would_truncate(513, 512) is True
    assert ta.would_truncate(511, 512) is False


def test_overflow_tokens():
    assert ta.overflow_tokens(513, 512) == 1
    assert ta.overflow_tokens(512, 512) == 0
    assert ta.overflow_tokens(500, 512) == 0


def test_percentile_linear_deterministic():
    values = list(range(1, 101))
    assert ta.percentile(values, 0.5) == pytest.approx(50.5)
    assert ta.percentile(values, 0.9) == pytest.approx(90.1)
    assert ta.percentile(values, 0.95) == pytest.approx(95.05)
    assert ta.percentile(values, 0.99) == pytest.approx(99.01)
    assert ta.percentile([7], 0.9) == pytest.approx(7.0)
    assert ta.percentile(values, 0.5) == ta.percentile(list(reversed(values)), 0.5)


def test_percentile_rejects_empty_and_bad_q():
    with pytest.raises(ValueError):
        ta.percentile([], 0.5)
    with pytest.raises(ValueError):
        ta.percentile([1, 2], 1.5)


def test_artifact_contains_no_absolute_path():
    records = [
        _record("llm/x.md", "证据文本" * 30),
        _record("rag/y.md", "内容" * 200, chunk_index=3),
    ]
    tok = FakeTokenizer(specials=2)
    counter = FakeCounter()
    stats = ta.analyze_records("recursive", records, counter, tok, 512)
    runtime_tok = FakeTokenizer(specials=2)
    runtime_tok.model_max_length = 512
    runtime_contract = ta.read_runtime_contract(
        FakeRuntimeModel(max_len=512, tokenizer=runtime_tok)
    )
    payload = ta.build_payload(
        corpus=type(
            "Corpus",
            (),
            {"corpus_id": "abc123", "entries": (object(), object())},
        )(),
        token_counter=type("Counter", (), {"name": "cl100k_base"})(),
        runtime_contract=runtime_contract,
        strategy_stats={
            "recursive": stats,
            "fixed": stats,
        },
    )
    text = json.dumps(payload, ensure_ascii=False)
    assert "D:" not in text
    assert "\\" not in text
    assert payload["sentence_transformer_max_seq_length"] == 512
    assert payload["effective_embedding_max_seq_length"] == 512
    assert payload["runtime_tokenizer_model_max_length"] == 512


def test_validate_payload_rejects_invalid_top_level():
    with pytest.raises(ValueError):
        ta.validate_payload([])
    with pytest.raises(ValueError):
        ta.validate_payload({"schema_version": 99})
    with pytest.raises(ValueError):
        ta.validate_payload({
            "schema_version": 1,
            "strategies": {"recursive": {}},
        })
    assert ta.validate_payload({
        "schema_version": 1,
        "strategies": {"recursive": {}, "fixed": {}},
    }) is not None


def test_script_does_not_import_forbidden_modules():
    import ast

    source = open(ta.__file__.replace("\\", "/"), encoding="utf-8").read()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in (
        "chromadb",
        "evaluation.experiment_runner",
        "core.retriever",
        "core.embeddings",
        "BM25",
    ):
        assert forbidden not in imported, f"脚本不应导入 {forbidden}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "embed":
                pytest.fail("脚本不应调用 embed()")
            if node.func.attr == "encode" and not isinstance(
                node.func.value, ast.Call
            ):
                pytest.fail("脚本不应直接调用模型风格 encode()")


def test_chunk_count_mismatch_fails_fast():
    ta.validate_chunk_count("recursive", [_record("a.md", "x")] * 215)
    with pytest.raises(RuntimeError, match="不一致"):
        ta.validate_chunk_count("recursive", [_record("a.md", "x")] * 214)


def test_analyze_records_stats_and_truncation_ranking():
    records = [
        _record("llm/a.md", "a" * 600),   # 602 bge tokens
        _record("rag/b.md", "b" * 300),   # 302 bge tokens
        _record("llm/c.md", "c" * 700),   # 702 bge tokens
    ]
    stats = ta.analyze_records(
        "fixed", records, FakeCounter(), FakeTokenizer(specials=2), 512,
    )
    assert stats["chunk_count"] == 3
    assert stats["would_truncate_count"] == 2
    assert stats["overflow_max"] == 190
    assert stats["overflow_median"] == pytest.approx(140.0)
    ids = [(r["relative_path"], r["chunk_index"]) for r in stats["truncated_chunks"]]
    assert ids == [("llm/c.md", 0), ("llm/a.md", 0)]
    assert stats["bge_token"]["max"] == 702
    assert stats["bge_token"]["min"] == 302
    assert stats["truncated_files"] == [
        {"relative_path": "llm/a.md", "truncated_count": 1},
        {"relative_path": "llm/c.md", "truncated_count": 1},
    ]


def test_runtime_contract_effective_max_from_runtime_model():
    tokenizer = FakeTokenizer(specials=2)
    tokenizer.model_max_length = 512
    contract = ta.read_runtime_contract(
        FakeRuntimeModel(max_len=512, tokenizer=tokenizer)
    )
    assert contract["sentence_transformer_class"] == "FakeRuntimeModel"
    assert contract["sentence_transformer_max_seq_length"] == 512
    assert contract["runtime_tokenizer_class"] == "FakeTokenizer"
    assert contract["runtime_tokenizer_model_max_length"] == 512
    assert contract["effective_embedding_max_seq_length"] == 512
    assert contract["tokenizer"] is tokenizer


def test_runtime_contract_fails_fast_when_max_mismatch():
    tokenizer = FakeTokenizer(specials=2)
    tokenizer.model_max_length = 512
    with pytest.raises(RuntimeError, match="不一致"):
        ta.read_runtime_contract(
            FakeRuntimeModel(max_len=511, tokenizer=tokenizer)
        )
    tokenizer.model_max_length = 511
    with pytest.raises(RuntimeError, match="不一致"):
        ta.read_runtime_contract(
            FakeRuntimeModel(max_len=512, tokenizer=tokenizer)
        )


def test_runtime_contract_fails_fast_without_actual_tokenizer():
    with pytest.raises(RuntimeError, match="没有"):
        ta.read_runtime_contract(FakeRuntimeModel(max_len=512, tokenizer=None))


def test_diagnostic_id_binds_max_length_and_tokenizer_identity():
    base = dict(
        corpus_id="870e5864df67",
        embedding_model="BAAI/bge-small-zh-v1.5",
        chunk_size=512,
        chunk_overlap=64,
        chunk_counts={"recursive": 215, "fixed": 237},
        runtime_embedding_tokenizer="BertTokenizer",
        effective_embedding_max_seq_length=512,
    )
    id_a = ta.compute_diagnostic_id(**base)
    assert id_a == ta.compute_diagnostic_id(**base)
    assert id_a != ta.compute_diagnostic_id(
        **{**base, "effective_embedding_max_seq_length": 513}
    )
    assert id_a != ta.compute_diagnostic_id(
        **{**base, "runtime_embedding_tokenizer": "BertTokenizerFast"}
    )
