"""G2-IMPL-20：用户声明的 unresolved 实验输入。

ExperimentSpec 只描述用户声明字段，不拥有正式 experiment_id；
必须经过唯一 resolver（evaluation.experiment_resolver.
resolve_experiment_config）解析出 Final ExperimentConfig 后，
才能访问 experiment_id。
"""

from dataclasses import dataclass

from evaluation.experiment_config import (
    CL100K_POLICY,
    EMBEDDING_RUNTIME_POLICY,
)


@dataclass(frozen=True)
class ExperimentSpec:
    embedding_provider: str = "bge"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    chunk_strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    chunk_budget_policy: str = CL100K_POLICY
    retriever_strategy: str = "hybrid"
    top_k: int = 5
    dense_candidate_k: int = 30
    sparse_candidate_k: int = 30
    rrf_k: float = 60.0
    rrf_tie_breaker: str = "chunk_id_asc"

    # 注意：这里刻意不提供 experiment_id property。
