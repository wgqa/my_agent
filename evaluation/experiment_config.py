"""ExperimentRunner 第一步：强类型实验配置模型。

替代后续 ExperimentRunner 中无约束的配置字典：字段受限、边界校验、
稳定可复现的 experiment_id。
"""

import hashlib
from dataclasses import asdict, dataclass
from typing import Optional

VALID_CHUNK_STRATEGIES = ("fixed", "recursive", "semantic")
# 正式实验（可复现基线）允许的策略
STABLE_CHUNK_STRATEGIES = ("fixed", "recursive")
# 实验性实现：保留手动学习/调试入口，但不得进入正式 ExperimentConfig
EXPERIMENTAL_CHUNK_STRATEGIES = ("semantic",)
VALID_RETRIEVER_STRATEGIES = ("simple", "hybrid", "mmr", "bm25")
VALID_RRF_TIE_BREAKERS = ("chunk_id_asc",)
VALID_CHUNK_BUDGET_POLICIES = (
    "cl100k_content_v1",
    "embedding_runtime_model_input_v1",
)
CL100K_POLICY = "cl100k_content_v1"
EMBEDDING_RUNTIME_POLICY = "embedding_runtime_model_input_v1"
_FINGERPRINT_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class ExperimentConfig:
    """一次实验的完整参数；frozen 保证配置与 ID 不可突变"""

    embedding_provider: str = "bge"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    chunk_strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    retriever_strategy: str = "hybrid"
    top_k: int = 5
    dense_candidate_k: int = 30
    sparse_candidate_k: int = 30
    rrf_k: float = 60.0
    rrf_tie_breaker: str = "chunk_id_asc"
    chunk_budget_policy: str = CL100K_POLICY
    effective_embedding_max_seq_length: Optional[int] = None
    special_token_overhead: Optional[int] = None
    tokenizer_contract_probe_version: Optional[str] = None
    tokenizer_contract_fingerprint: Optional[str] = None

    def __post_init__(self):
        # Embedding 身份：strict str 且非空，直接参与 experiment_id
        for name in ("embedding_provider", "embedding_model"):
            value = getattr(self, name)
            if type(value) is not str:
                raise TypeError(
                    f"{name} 必须是 str（不允许 bool/数字/None），"
                    f"当前类型: {type(value).__name__}"
                )
            if value == "":
                raise ValueError(f"{name} 不能为空字符串")
        for name in ("chunk_strategy", "retriever_strategy"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{name} 必须是 str，当前类型: {type(value).__name__}"
                )
        if self.chunk_strategy not in VALID_CHUNK_STRATEGIES:
            raise ValueError(
                f"未知 chunk_strategy: {self.chunk_strategy}，"
                f"支持 {VALID_CHUNK_STRATEGIES}"
            )
        if self.chunk_strategy in EXPERIMENTAL_CHUNK_STRATEGIES:
            raise ValueError(
                f"chunk_strategy={self.chunk_strategy} 当前是实验性实现："
                "尚未满足原文 Span、严格预算与 Embedding 对齐契约，"
                "不能用于正式可复现实验"
            )
        if self.retriever_strategy not in VALID_RETRIEVER_STRATEGIES:
            raise ValueError(
                f"未知 retriever_strategy: {self.retriever_strategy}，"
                f"支持 {VALID_RETRIEVER_STRATEGIES}"
            )
        # 严格整数（bool 是 int 子类，先排除）
        for name in ("chunk_size", "chunk_overlap", "top_k",
                     "dense_candidate_k", "sparse_candidate_k"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"{name} 必须是整数（不允许 bool），当前: {value!r}"
                )
        for name in ("chunk_size", "top_k", "dense_candidate_k",
                     "sparse_candidate_k"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须 > 0，当前: {getattr(self, name)}")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) 必须 >= 0 且 < "
                f"chunk_size ({self.chunk_size})"
            )
        # rrf_k：int/float 均合法，统一规范化为 float（60 与 60.0 同配置同 ID）
        rrf = self.rrf_k
        if isinstance(rrf, bool) or not isinstance(rrf, (int, float)):
            raise TypeError(
                f"rrf_k 必须是 int 或 float（不允许 bool），当前: {rrf!r}"
            )
        if rrf <= 0:
            raise ValueError(f"rrf_k 必须 > 0，当前: {rrf}")
        object.__setattr__(self, "rrf_k", float(rrf))

        tie_breaker = self.rrf_tie_breaker
        if type(tie_breaker) is not str or tie_breaker == "":
            raise TypeError(
                "rrf_tie_breaker 必须是非空字符串，"
                f"实际 {type(tie_breaker).__name__}（{tie_breaker!r}）"
            )
        if tie_breaker not in VALID_RRF_TIE_BREAKERS:
            raise ValueError(
                f"未知 rrf_tie_breaker: {tie_breaker}，"
                f"支持 {VALID_RRF_TIE_BREAKERS}"
            )

        policy = self.chunk_budget_policy
        if type(policy) is not str or policy == "":
            raise TypeError(
                "chunk_budget_policy 必须是非空字符串，"
                f"实际 {type(policy).__name__}"
            )
        if policy not in VALID_CHUNK_BUDGET_POLICIES:
            raise ValueError(
                f"未知 chunk_budget_policy: {policy}，"
                f"支持 {VALID_CHUNK_BUDGET_POLICIES}"
            )

        if policy == EMBEDDING_RUNTIME_POLICY:
            max_len = self.effective_embedding_max_seq_length
            if isinstance(max_len, bool) or not isinstance(max_len, int):
                raise TypeError(
                    "aligned policy 要求 effective_embedding_max_seq_length "
                    "是整数（不允许 bool/None）"
                )
            if max_len <= 0:
                raise ValueError(
                    f"effective_embedding_max_seq_length 必须 > 0，实际 {max_len}"
                )
            if self.chunk_size != max_len:
                raise ValueError(
                    "aligned policy（v1）要求 chunk_size == "
                    "effective_embedding_max_seq_length："
                    f"chunk_size={self.chunk_size} runtime_max={max_len}，"
                    "禁止身份/预算漂移；可变 model-input budget 需要"
                    "新版本化 policy"
                )
            overhead = self.special_token_overhead
            if isinstance(overhead, bool) or not isinstance(overhead, int):
                raise TypeError(
                    "aligned policy 要求 special_token_overhead 是整数"
                )
            if overhead < 0 or overhead >= max_len:
                raise ValueError(
                    f"special_token_overhead={overhead} 必须 >= 0 且 < "
                    f"effective_embedding_max_seq_length={max_len}"
                )
            probe_version = self.tokenizer_contract_probe_version
            if type(probe_version) is not str or probe_version == "":
                raise TypeError(
                    "aligned policy 要求 tokenizer_contract_probe_version "
                    "是非空字符串"
                )
            fingerprint = self.tokenizer_contract_fingerprint
            if (
                type(fingerprint) is not str
                or len(fingerprint) != 16
                or any(c not in _FINGERPRINT_HEX for c in fingerprint)
            ):
                raise ValueError(
                    "aligned policy 要求 tokenizer_contract_fingerprint 是 "
                    "16 位 hex 字符串"
                )
        else:
            for name in (
                "effective_embedding_max_seq_length",
                "special_token_overhead",
                "tokenizer_contract_probe_version",
                "tokenizer_contract_fingerprint",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"policy={CL100K_POLICY} 不允许 {name} 非 None"
                        f"（实际 {getattr(self, name)!r}），"
                        "禁止半解析配置"
                    )

    def to_dict(self) -> dict:
        """字段序固定（dataclass 声明序），与 dict 插入顺序无关"""
        return asdict(self)

    @property
    def experiment_id(self) -> str:
        """稳定 ID：按 dataclass 字段名序序列化后 SHA-256 取前 12 位。

        不依赖对象地址（无 id() 参与），不依赖 dict 插入顺序（字段序固定）；
        相同配置恒得相同 ID，任一字段变化 ID 必变。
        """
        payload = "|".join(
            f"{name}={getattr(self, name)}" for name in self.__dataclass_fields__
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
