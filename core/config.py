import os
import yaml


class ConfigError(ValueError):
    """配置校验错误"""


_VALID_PROVIDERS = {
    "embedding": ("bge", "openai"),
    "generator": ("deepseek", "openai"),
}
_VALID_STRATEGIES = {
    "chunker": ("fixed", "recursive", "semantic"),
    "retriever": ("simple", "hybrid", "mmr"),
}


class Config:
    """从 yaml 加载并校验，Fail Fast"""

    def __init__(self, config_path: str | None = "config.yaml"):
        self._path = config_path
        raw = {}
        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

        # ── embedding ────────────────────────────────
        emb = raw.get("embedding", {})
        prov = emb.get("provider", "bge")
        if prov not in _VALID_PROVIDERS["embedding"]:
            raise ConfigError(f"未知 embedding provider: {prov}")
        self.embedding_provider = prov
        self.embedding_model = emb.get("model", "BAAI/bge-small-zh-v1.5")

        # ── chunker ───────────────────────────────────
        chk = raw.get("chunker", {})
        strat = chk.get("strategy", "recursive")
        if strat not in _VALID_STRATEGIES["chunker"]:
            raise ConfigError(f"未知 chunker strategy: {strat}")
        self.chunker_strategy = strat
        self.chunk_size = chk.get("size_tokens", 512)
        self.chunk_overlap = chk.get("overlap_tokens", 64)
        if self.chunk_size <= 0:
            raise ConfigError(f"chunk_size 必须 > 0，当前: {self.chunk_size}")
        if self.chunk_overlap < 0:
            raise ConfigError(f"chunk_overlap 必须 >= 0，当前: {self.chunk_overlap}")
        if self.chunk_overlap >= self.chunk_size:
            raise ConfigError(
                f"chunk_overlap ({self.chunk_overlap}) 不能 >= chunk_size ({self.chunk_size})"
            )

        # ── retriever ─────────────────────────────────
        ret = raw.get("retriever", {})
        rstrat = ret.get("strategy", "hybrid")
        if rstrat not in _VALID_STRATEGIES["retriever"]:
            raise ConfigError(f"未知 retriever strategy: {rstrat}")
        self.retriever_strategy = rstrat
        self.top_k = ret.get("top_k", 5)
        if not 1 <= self.top_k <= 100:
            raise ConfigError(f"top_k 必须在 [1, 100]，当前: {self.top_k}")
        self.dense_candidate_k = ret.get("dense_candidate_k", 30)
        self.sparse_candidate_k = ret.get("sparse_candidate_k", 30)
        self.rrf_k = ret.get("rrf_k", 60.0)

        # ── reranker ──────────────────────────────────
        rrk = raw.get("reranker", {})
        self.reranker_enabled = rrk.get("enabled", True)
        self.reranker_candidate_k = rrk.get("candidate_k", 20)
        self.reranker_final_k = rrk.get("final_k", 5)
        if self.reranker_candidate_k < self.reranker_final_k:
            raise ConfigError(
                f"reranker candidate_k ({self.reranker_candidate_k}) "
                f"不能小于 final_k ({self.reranker_final_k})"
            )

        # ── generator ─────────────────────────────────
        gen = raw.get("generator", {})
        gprov = gen.get("provider", "deepseek")
        if gprov not in _VALID_PROVIDERS["generator"]:
            raise ConfigError(f"未知 generator provider: {gprov}")
        self.generator_provider = gprov
        self.generator_model = gen.get("model", "deepseek-v4-flash")
        self.generator_temperature = gen.get("temperature", 0.3)
        if not 0.0 <= self.generator_temperature <= 2.0:
            raise ConfigError(
                f"temperature 必须在 [0, 2]，当前: {self.generator_temperature}"
            )

        # ── vector_store ──────────────────────────────
        vs = raw.get("vector_store", {})
        self.vector_store_path = vs.get("path", "./data/vector_store")

    def dump(self) -> dict:
        """脱敏配置摘要（不含 API Key）"""
        return {
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "chunker_strategy": self.chunker_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "retriever_strategy": self.retriever_strategy,
            "top_k": self.top_k,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "rrf_k": self.rrf_k,
            "reranker_enabled": self.reranker_enabled,
            "reranker_candidate_k": self.reranker_candidate_k,
            "reranker_final_k": self.reranker_final_k,
            "generator_provider": self.generator_provider,
            "generator_model": self.generator_model,
            "generator_temperature": self.generator_temperature,
            "vector_store_path": self.vector_store_path,
        }
