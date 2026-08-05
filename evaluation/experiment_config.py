"""ExperimentRunner 第一步：强类型实验配置模型。

替代后续 ExperimentRunner 中无约束的配置字典：字段受限、边界校验、
稳定可复现的 experiment_id。
"""

import hashlib
from dataclasses import asdict, dataclass

VALID_CHUNK_STRATEGIES = ("fixed", "recursive", "semantic")
VALID_RETRIEVER_STRATEGIES = ("simple", "hybrid", "mmr")


@dataclass(frozen=True)
class ExperimentConfig:
    """一次实验的完整参数；frozen 保证配置与 ID 不可突变"""

    chunk_strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    retriever_strategy: str = "hybrid"
    top_k: int = 5
    dense_candidate_k: int = 30
    sparse_candidate_k: int = 30
    rrf_k: float = 60.0

    def __post_init__(self):
        if self.chunk_strategy not in VALID_CHUNK_STRATEGIES:
            raise ValueError(
                f"未知 chunk_strategy: {self.chunk_strategy}，"
                f"支持 {VALID_CHUNK_STRATEGIES}"
            )
        if self.retriever_strategy not in VALID_RETRIEVER_STRATEGIES:
            raise ValueError(
                f"未知 retriever_strategy: {self.retriever_strategy}，"
                f"支持 {VALID_RETRIEVER_STRATEGIES}"
            )
        for name in ("chunk_size", "top_k", "dense_candidate_k",
                     "sparse_candidate_k"):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} 必须 > 0，当前: {value}")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) 必须 >= 0 且 < "
                f"chunk_size ({self.chunk_size})"
            )
        if self.rrf_k <= 0:
            raise ValueError(f"rrf_k 必须 > 0，当前: {self.rrf_k}")

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
