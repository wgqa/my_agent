"""G2-DIAG-18：Chunk Budget vs BGE Tokenizer Alignment Diagnostic。

只读诊断：从冻结 Benchmark Corpus 用项目正式 Fixed/Recursive Chunker
重新构造 Chunk，统计 cl100k_base（TokenCounter）与实际 BGE tokenizer
（BAAI/bge-small-zh-v1.5）的长度差异，判断是否存在"Chunker 判定未超
512 但 BGE tokenizer 超过 512"的 would-truncate 工程边界。

G2-DIAG-18-R1：长度契约绑定实际 SentenceTransformer 运行时——使用
与 core/embeddings/bge_emb.py 一致的本地模型加载方式读取
model.max_seq_length 与首个 Transformer module 的真实 tokenizer，
不做任何 encode()。

本脚本不调用 SentenceTransformer.encode() / BGEEmbedding.embed() /
Chroma / BM25 / Retriever / ExperimentRunner，不计算 Retrieval
Metrics，不修改任何正式实验 Artifact。
"""

import argparse
from collections import Counter
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.chunker.fixed_size import FixedSizeChunker
from core.chunker.recursive import RecursiveChunker
from core.chunker.token_counter import TokenCounter
from core.loader.base import Document
from evaluation.experiment_corpus import ExperimentCorpus

SCHEMA_VERSION = 1
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
EXPECTED_CHUNK_COUNTS = {"recursive": 215, "fixed": 237}
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EXPECTED_MAX_SEQ_LENGTH = 512
TOKEN_BUDGET_TOKENIZER = "cl100k_base"
PREVIEW_LEN = 80
MAX_TRUNCATED_RECORDS = 20


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """线性插值百分位，与 numpy.percentile(method="linear") 一致。

    rank = q * (n - 1)，在 floor(rank) 与 ceil(rank) 之间线性插值；
    n == 1 时返回唯一值。方法固定，避免不同库插值歧义。
    """
    values = list(sorted_values)
    if not values:
        raise ValueError("percentile 输入不能为空")
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q 必须在 [0,1] 内，实际 {q}")
    values.sort()
    n = len(values)
    if n == 1:
        return float(values[0])
    rank = q * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(values[lo])
    frac = rank - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def bge_lengths(tokenizer, text: str) -> tuple:
    """返回 (bge_token_count, bge_content_token_count)。

    bge_token_count 使用 add_special_tokens=True（包含 [CLS]/[SEP] 等
    特殊 token 的最终输入长度）；truncation=False 不做截断。
    bge_content_token_count 额外记录去掉特殊 token 后的内容长度。
    """
    with_special = tokenizer(
        text,
        add_special_tokens=True,
        truncation=False,
    )
    without_special = tokenizer(
        text,
        add_special_tokens=False,
        truncation=False,
    )
    return len(with_special["input_ids"]), len(without_special["input_ids"])


def would_truncate(bge_token_count: int, max_seq_length: int) -> bool:
    return bge_token_count > max_seq_length


def overflow_tokens(bge_token_count: int, max_seq_length: int) -> int:
    return max(0, bge_token_count - max_seq_length)


def compute_behavior_fingerprint(
    records_by_strategy: Dict[str, List[tuple]],
    tokenizer,
) -> str:
    """基于实际 tokenization output 的稳定行为指纹。

    按固定顺序（strategy → relative_path → chunk_index）遍历全部冻结
    诊断 Chunk，使用真正 runtime tokenizer 以 add_special_tokens=True、
    truncation=False 取得 input_ids，流式写入 SHA-256。

    fingerprint 绑定 normalizer / pre-tokenizer / vocabulary /
    special-token 行为与当前 Corpus 上的实际 tokenization output；
    不包含对象地址、repr 或绝对路径。全部 input_ids 不写入 JSON。
    """
    h = hashlib.sha256()
    for strategy in ("recursive", "fixed"):
        records = records_by_strategy.get(strategy, [])
        for relative_path, chunk in sorted(
            records,
            key=lambda item: (item[0], item[1].metadata.get("chunk_index", 0)),
        ):
            input_ids = tokenizer(
                chunk.content,
                add_special_tokens=True,
                truncation=False,
            )["input_ids"]
            h.update(
                json.dumps(
                    [
                        strategy,
                        relative_path,
                        chunk.metadata.get("chunk_index", 0),
                        input_ids,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
    return h.hexdigest()[:16]


def load_corpus(corpus_root: Path) -> ExperimentCorpus:
    relative_paths = sorted(
        p.relative_to(corpus_root).as_posix()
        for p in corpus_root.rglob("*")
        if p.is_file() and p.suffix.lower() == ".md"
    )
    if not relative_paths:
        raise ValueError(f"corpus_root 下没有 .md 文件: {corpus_root}")
    return ExperimentCorpus.build(corpus_root, relative_paths)


def load_documents(corpus: ExperimentCorpus) -> Dict[str, Document]:
    docs = {}
    for entry in corpus.entries:
        full = (corpus.corpus_root / entry.relative_path).resolve()
        content = full.read_text(encoding="utf-8")
        docs[entry.relative_path] = Document(
            content=content,
            metadata={
                "source": str(full),
                "source_name": Path(entry.relative_path).name,
                "type": "text",
                "relative_path": entry.relative_path,
            },
        )
    return docs


def chunk_documents(
    strategy: str,
    docs: Dict[str, Document],
    token_counter: TokenCounter,
) -> List[tuple]:
    if strategy == "fixed":
        chunker = FixedSizeChunker(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            token_counter=token_counter,
        )
    elif strategy == "recursive":
        chunker = RecursiveChunker(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            token_counter=token_counter,
        )
    else:
        raise ValueError(f"未知 chunk strategy: {strategy}")
    records = []
    for relative_path in sorted(docs):
        for chunk in chunker.chunk([docs[relative_path]]):
            records.append((relative_path, chunk))
    return records


def validate_chunk_count(strategy: str, records: List[tuple]) -> None:
    expected = EXPECTED_CHUNK_COUNTS[strategy]
    actual = len(records)
    if actual != expected:
        raise RuntimeError(
            f"{strategy} 诊断重建 chunk_count={actual}，与正式实验 "
            f"{expected} 不一致，诊断重建路径和正式实验不一致，"
            "不允许继续统计"
        )


def analyze_records(
    strategy: str,
    records: List[tuple],
    token_counter: TokenCounter,
    tokenizer,
    max_seq_length: int,
) -> dict:
    rows = []
    for relative_path, chunk in records:
        meta = chunk.metadata
        cl100k = token_counter.count(chunk.content)
        bge, bge_content = bge_lengths(tokenizer, chunk.content)
        rows.append({
            "strategy": strategy,
            "relative_path": relative_path,
            "chunk_index": meta.get("chunk_index"),
            "char_start": meta.get("char_start"),
            "char_end": meta.get("char_end"),
            "cl100k_token_count": cl100k,
            "bge_token_count": bge,
            "bge_content_token_count": bge_content,
            "would_truncate": would_truncate(bge, max_seq_length),
            "overflow_tokens": overflow_tokens(bge, max_seq_length),
            "oversized": bool(meta.get("oversized")),
            "preview": chunk.content[:PREVIEW_LEN],
        })

    cl100k_counts = [r["cl100k_token_count"] for r in rows]
    bge_counts = [r["bge_token_count"] for r in rows]
    ratios = [
        r["bge_token_count"] / r["cl100k_token_count"]
        for r in rows
        if r["cl100k_token_count"] > 0
    ]
    truncated = [r for r in rows if r["would_truncate"]]
    overflows = sorted(r["overflow_tokens"] for r in truncated)
    over_budget = [r for r in rows if r["cl100k_token_count"] > CHUNK_SIZE]
    truncated_file_counts = Counter(r["relative_path"] for r in truncated)

    truncated_sorted = [
        {
            "strategy": r["strategy"],
            "relative_path": r["relative_path"],
            "chunk_index": r["chunk_index"],
            "char_start": r["char_start"],
            "char_end": r["char_end"],
            "cl100k_token_count": r["cl100k_token_count"],
            "bge_token_count": r["bge_token_count"],
            "overflow_tokens": r["overflow_tokens"],
            "preview": r["preview"],
        }
        for r in sorted(
            truncated,
            key=lambda r: (
                r["overflow_tokens"],
                r["relative_path"],
                r["chunk_index"],
            ),
            reverse=True,
        )[:MAX_TRUNCATED_RECORDS]
    ]

    return {
        "chunk_count": len(rows),
        "cl100k_max": max(cl100k_counts) if cl100k_counts else 0,
        "cl100k_over_budget_count": len(over_budget),
        "cl100k_over_budget_chunks": [
            {
                "relative_path": r["relative_path"],
                "chunk_index": r["chunk_index"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "cl100k_token_count": r["cl100k_token_count"],
                "oversized": r["oversized"],
            }
            for r in sorted(
                over_budget,
                key=lambda r: (r["cl100k_token_count"], r["relative_path"], r["chunk_index"]),
                reverse=True,
            )
        ],
        "bge_token": {
            "min": min(bge_counts) if bge_counts else 0,
            "median": percentile(bge_counts, 0.5) if bge_counts else 0.0,
            "p90": percentile(bge_counts, 0.9) if bge_counts else 0.0,
            "p95": percentile(bge_counts, 0.95) if bge_counts else 0.0,
            "p99": percentile(bge_counts, 0.99) if bge_counts else 0.0,
            "max": max(bge_counts) if bge_counts else 0,
        },
        "would_truncate_count": len(truncated),
        "would_truncate_percentage": (
            (len(truncated) / len(rows)) * 100.0 if rows else 0.0
        ),
        "truncated_files": [
            {"relative_path": path, "truncated_count": count}
            for path, count in sorted(
                truncated_file_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "overflow_max": max(overflows) if overflows else 0,
        "overflow_median": percentile(overflows, 0.5) if overflows else 0.0,
        "token_ratio": {
            "median": percentile(ratios, 0.5) if ratios else 0.0,
            "p90": percentile(ratios, 0.9) if ratios else 0.0,
            "p95": percentile(ratios, 0.95) if ratios else 0.0,
            "max": max(ratios) if ratios else 0.0,
        },
        "truncated_chunks": truncated_sorted,
    }


def compute_diagnostic_id(
    corpus_id: str,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
    chunk_counts: Dict[str, int],
    runtime_embedding_tokenizer: str,
    runtime_tokenizer_behavior_fingerprint: str,
    effective_embedding_max_seq_length: int,
) -> str:
    payload = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "corpus_id": corpus_id,
            "embedding_model": embedding_model,
            "chunk_budget_tokenizer": TOKEN_BUDGET_TOKENIZER,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "runtime_embedding_tokenizer": runtime_embedding_tokenizer,
            "runtime_tokenizer_behavior_fingerprint": (
                runtime_tokenizer_behavior_fingerprint
            ),
            "effective_embedding_max_seq_length": (
                effective_embedding_max_seq_length
            ),
            "strategy_chunk_counts": chunk_counts,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def validate_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("分析 Artifact 顶层必须是 object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version 必须是 {SCHEMA_VERSION}，"
            f"实际 {payload.get('schema_version')!r}"
        )
    strategies = payload.get("strategies")
    if not isinstance(strategies, dict):
        raise ValueError("payload['strategies'] 必须是 object")
    for name in EXPECTED_CHUNK_COUNTS:
        if name not in strategies:
            raise ValueError(f"payload['strategies'] 缺少 {name}")
    return payload


def build_payload(
    corpus: ExperimentCorpus,
    token_counter: TokenCounter,
    runtime_contract: dict,
    runtime_tokenizer_behavior_fingerprint: str,
    strategy_stats: Dict[str, dict],
) -> dict:
    counts = {
        name: strategy_stats[name]["chunk_count"]
        for name in ("recursive", "fixed")
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_id": compute_diagnostic_id(
            corpus.corpus_id,
            EMBEDDING_MODEL,
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            counts,
            runtime_contract["runtime_tokenizer_class"],
            runtime_tokenizer_behavior_fingerprint,
            runtime_contract["effective_embedding_max_seq_length"],
        ),
        "corpus_id": corpus.corpus_id,
        "file_count": len(corpus.entries),
        "embedding_model": EMBEDDING_MODEL,
        "chunk_budget_tokenizer": token_counter.name,
        "sentence_transformer_class": (
            runtime_contract["sentence_transformer_class"]
        ),
        "sentence_transformer_max_seq_length": (
            runtime_contract["sentence_transformer_max_seq_length"]
        ),
        "embedding_tokenizer": runtime_contract["runtime_tokenizer_class"],
        "runtime_tokenizer_class": (
            runtime_contract["runtime_tokenizer_class"]
        ),
        "runtime_tokenizer_behavior_fingerprint": (
            runtime_tokenizer_behavior_fingerprint
        ),
        "runtime_tokenizer_model_max_length": (
            runtime_contract["runtime_tokenizer_model_max_length"]
        ),
        "effective_embedding_max_seq_length": (
            runtime_contract["effective_embedding_max_seq_length"]
        ),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "strategies": {
            "recursive": strategy_stats["recursive"],
            "fixed": strategy_stats["fixed"],
        },
    }
    return validate_payload(payload)


def read_runtime_contract(model) -> dict:
    """从实际 SentenceTransformer 对象读取运行时输入长度契约。

    effective max 来自 model.max_seq_length（正式 encode 路径的真实
    截断上限），要求等于预期值 512（否则 fail-fast）；
    runtime tokenizer 的 model_max_length 只作为运行态事实记录，
    不要求与 effective max 相同（was-truncate 一律按 effective max
    判断）。只读配置，不调用 encode()。
    """
    max_len = model.max_seq_length
    if max_len != EXPECTED_MAX_SEQ_LENGTH:
        raise RuntimeError(
            f"SentenceTransformer.max_seq_length={max_len}，"
            f"与预期 {EXPECTED_MAX_SEQ_LENGTH} 不一致，停止诊断"
        )
    first = model[0]
    tokenizer = getattr(first, "tokenizer", None)
    if tokenizer is None:
        raise RuntimeError(
            "SentenceTransformer 首个 Transformer module 没有 "
            "实际 tokenizer，停止诊断"
        )
    runtime_max = int(tokenizer.model_max_length)
    return {
        "sentence_transformer_class": type(model).__name__,
        "sentence_transformer_max_seq_length": max_len,
        "runtime_tokenizer_class": type(tokenizer).__name__,
        "runtime_tokenizer_model_max_length": runtime_max,
        "effective_embedding_max_seq_length": max_len,
        "tokenizer": tokenizer,
    }


def load_runtime_embedding_contract() -> dict:
    """使用与 core/embeddings/bge_emb.py 一致的本地模型加载方式。"""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        EMBEDDING_MODEL,
        local_files_only=True,
    )
    return read_runtime_contract(model)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="G2-DIAG-18 tokenizer alignment diagnostic"
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    corpus_root = Path(args.corpus_root).resolve()
    corpus = load_corpus(corpus_root)
    if corpus.corpus_id != "870e5864df67":
        raise RuntimeError(
            f"corpus_id={corpus.corpus_id}，与冻结 Benchmark "
            "870e5864df67 不一致，停止诊断"
        )
    if len(corpus.entries) != 37:
        raise RuntimeError(
            f"file_count={len(corpus.entries)}，与冻结 Benchmark 37 不一致"
        )

    docs = load_documents(corpus)
    token_counter = TokenCounter()
    if token_counter.name != TOKEN_BUDGET_TOKENIZER:
        raise RuntimeError(
            f"TokenCounter 实际 tokenizer={token_counter.name!r}，"
            f"预期 {TOKEN_BUDGET_TOKENIZER}，停止诊断"
        )
    runtime_contract = load_runtime_embedding_contract()
    tokenizer = runtime_contract["tokenizer"]
    max_len = runtime_contract["effective_embedding_max_seq_length"]

    strategy_stats = {}
    records_by_strategy = {}
    for strategy in ("recursive", "fixed"):
        records = chunk_documents(strategy, docs, token_counter)
        validate_chunk_count(strategy, records)
        records_by_strategy[strategy] = records
        strategy_stats[strategy] = analyze_records(
            strategy,
            records,
            token_counter,
            tokenizer,
            max_len,
        )
    behavior_fingerprint = compute_behavior_fingerprint(
        records_by_strategy,
        tokenizer,
    )

    payload = build_payload(
        corpus,
        token_counter,
        runtime_contract,
        behavior_fingerprint,
        strategy_stats,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "diagnostic_id": payload["diagnostic_id"],
            "corpus_id": payload["corpus_id"],
            "file_count": payload["file_count"],
            "strategies": {
                name: {
                    "chunk_count": stats["chunk_count"],
                    "would_truncate_count": stats["would_truncate_count"],
                    "would_truncate_percentage": stats["would_truncate_percentage"],
                    "bge_max": stats["bge_token"]["max"],
                    "overflow_max": stats["overflow_max"],
                }
                for name, stats in strategy_stats.items()
            },
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
