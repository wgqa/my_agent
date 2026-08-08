"""G2-IMPL-20：Runtime Tokenizer Contract 唯一事实源。

Preflight（experiment identity resolution）与 Formal Pipeline
validation 必须调用同一实现；禁止在 CLI / Runner / Embedding 中
复制 fingerprint 数学。

fingerprint 基于固定、版本化 canonical probe suite 的实际
tokenization output（input_ids），不包含路径、时间、对象 repr；
同 class/max 但 probe behavior 不同 → fingerprint 不同。
"""

import hashlib
import json

TOKENIZER_CONTRACT_PROBE_VERSION = "v1"

# canonical probe suite：覆盖中文、英文、大小写、中英混合、代码、
# 数字、空格/换行、标点、特殊符号。
TOKENIZER_CONTRACT_PROBES = (
    "中文测试",
    "Hello world",
    "Mixed 中文 English",
    "ABC abc",
    "def foo(x=1): return x",
    "1234567890",
    "line1\nline2  spaced",
    "标点，。！？:;,.!?",
    "emoji 🚀 special \t tab",
)


def compute_tokenizer_contract(runtime_tokenizer, model=None) -> dict:
    """返回稳定 runtime contract。

    model 为 SentenceTransformer（或其替身）：effective max 以
    model.max_seq_length 为准；model 为 None 时退回读取
    tokenizer.model_max_length（测试 fake 可用）。
    不调用 encode()。
    """
    if model is not None:
        max_len = int(model.max_seq_length)
    else:
        max_len = int(runtime_tokenizer.model_max_length)
    overhead = int(runtime_tokenizer.num_special_tokens_to_add(pair=False))

    probe_outputs = []
    for probe in TOKENIZER_CONTRACT_PROBES:
        input_ids = runtime_tokenizer(
            probe,
            add_special_tokens=True,
            truncation=False,
        )["input_ids"]
        probe_outputs.append(input_ids)

    payload = json.dumps(
        {
            "probe_version": TOKENIZER_CONTRACT_PROBE_VERSION,
            "probes": probe_outputs,
            "effective_embedding_max_seq_length": max_len,
            "special_token_overhead": overhead,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return {
        "effective_embedding_max_seq_length": max_len,
        "special_token_overhead": overhead,
        "tokenizer_contract_probe_version": TOKENIZER_CONTRACT_PROBE_VERSION,
        "tokenizer_contract_fingerprint": hashlib.sha256(payload).hexdigest()[:16],
        "runtime_tokenizer_class": type(runtime_tokenizer).__name__,
    }


def compute_corpus_scoped_fingerprint(indexed_chunks, runtime_tokenizer) -> str:
    """post-index observed fact：基于正式 vector store 实际入库 chunks。

    indexed_chunks: iterable of {"id": chunk_id, "document": content}；
    按 chunk_id 稳定排序；使用 runtime tokenizer 的实际 input_ids
    流式 SHA-256。禁止绝对路径参与。
    """
    h = hashlib.sha256()
    for chunk in sorted(indexed_chunks, key=lambda c: c["id"]):
        if "document" in chunk:
            text = chunk["document"]
        elif "content" in chunk:
            text = chunk["content"]
        else:
            raise ValueError(
                f"indexed chunk {chunk.get('id')!r} 缺少 document/content"
            )
        input_ids = runtime_tokenizer(
            text,
            add_special_tokens=True,
            truncation=False,
        )["input_ids"]
        h.update(
            json.dumps(
                [chunk["id"], input_ids],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return h.hexdigest()[:16]
