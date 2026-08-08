"""G2-IMPL-20：唯一高层 resolver。

user-declared ExperimentSpec → runtime preflight（仅 aligned policy）
→ Final frozen ExperimentConfig → experiment_id。

cl100k_content_v1 使用 canonical sentinel/None，不加载
SentenceTransformer；embedding_runtime_model_input_v1 通过
BGEEmbedding 本地只读 contract（local_files_only、不 encode、
不创建 Workspace/VectorStore/Pipeline）。
"""

from evaluation.experiment_config import (
    CL100K_POLICY,
    EMBEDDING_RUNTIME_POLICY,
    ExperimentConfig,
)
from evaluation.experiment_spec import ExperimentSpec


def resolve_experiment_config(spec: ExperimentSpec) -> ExperimentConfig:
    """唯一正式解析入口：spec → Final ExperimentConfig。"""
    if spec.chunk_budget_policy == CL100K_POLICY:
        return _build_config(spec, {})
    if spec.chunk_budget_policy == EMBEDDING_RUNTIME_POLICY:
        if spec.embedding_provider != "bge":
            raise ValueError(
                "embedding_runtime_model_input_v1 需要 "
                "embedding_provider='bge'，"
                f"实际 {spec.embedding_provider!r}"
            )
        from core.embeddings.bge_emb import BGEEmbedding

        embedding = BGEEmbedding(model_name=spec.embedding_model)
        contract = embedding.get_runtime_contract()
        return _build_config(spec, contract)
    raise ValueError(
        f"未知 chunk_budget_policy: {spec.chunk_budget_policy!r}"
    )


def _build_config(spec: ExperimentSpec, contract: dict) -> ExperimentConfig:
    if spec.chunk_budget_policy == CL100K_POLICY:
        runtime_fields = {
            "effective_embedding_max_seq_length": None,
            "special_token_overhead": None,
            "tokenizer_contract_probe_version": None,
            "tokenizer_contract_fingerprint": None,
        }
    else:
        runtime_fields = {
            "effective_embedding_max_seq_length": (
                contract["effective_embedding_max_seq_length"]
            ),
            "special_token_overhead": contract["special_token_overhead"],
            "tokenizer_contract_probe_version": (
                contract["tokenizer_contract_probe_version"]
            ),
            "tokenizer_contract_fingerprint": (
                contract["tokenizer_contract_fingerprint"]
            ),
        }
    return ExperimentConfig(
        embedding_provider=spec.embedding_provider,
        embedding_model=spec.embedding_model,
        chunk_strategy=spec.chunk_strategy,
        chunk_size=spec.chunk_size,
        chunk_overlap=spec.chunk_overlap,
        chunk_budget_policy=spec.chunk_budget_policy,
        retriever_strategy=spec.retriever_strategy,
        top_k=spec.top_k,
        dense_candidate_k=spec.dense_candidate_k,
        sparse_candidate_k=spec.sparse_candidate_k,
        rrf_k=spec.rrf_k,
        rrf_tie_breaker=spec.rrf_tie_breaker,
        **runtime_fields,
    )
