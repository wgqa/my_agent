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
    "retriever": ("simple", "hybrid", "mmr", "bm25"),
}
_VALID_CHUNK_BUDGET_POLICIES = (
    "cl100k_content_v1",
    "embedding_runtime_model_input_v1",
)
_FINGERPRINT_HEX = frozenset("0123456789abcdef")


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

        # ── chunk budget policy（G2-IMPL-20）──────────────────
        policy = chk.get("budget_policy", "cl100k_content_v1")
        if policy not in _VALID_CHUNK_BUDGET_POLICIES:
            raise ConfigError(
                f"未知 chunker.budget_policy: {policy}，"
                f"支持 {_VALID_CHUNK_BUDGET_POLICIES}"
            )
        self.chunk_budget_policy = policy
        if policy == "embedding_runtime_model_input_v1":
            max_len = chk.get("effective_embedding_max_seq_length")
            if isinstance(max_len, bool) or not isinstance(max_len, int) or max_len <= 0:
                raise ConfigError(
                    "aligned policy 要求 chunker.effective_embedding_"
                    f"max_seq_length 是正整数，实际 {max_len!r}"
                )
            overhead = chk.get("special_token_overhead")
            if (
                isinstance(overhead, bool)
                or not isinstance(overhead, int)
                or not 0 <= overhead < max_len
            ):
                raise ConfigError(
                    f"aligned policy 要求 chunker.special_token_overhead "
                    f"满足 0 <= value < {max_len}，实际 {overhead!r}"
                )
            probe_version = chk.get("tokenizer_contract_probe_version")
            if type(probe_version) is not str or probe_version == "":
                raise ConfigError(
                    "aligned policy 要求 chunker.tokenizer_contract_"
                    "probe_version 是非空字符串"
                )
            fingerprint = chk.get("tokenizer_contract_fingerprint")
            if (
                type(fingerprint) is not str
                or len(fingerprint) != 16
                or any(c not in _FINGERPRINT_HEX for c in fingerprint)
            ):
                raise ConfigError(
                    "aligned policy 要求 chunker.tokenizer_contract_"
                    "fingerprint 是 16 位 hex 字符串"
                )
            self.effective_embedding_max_seq_length = max_len
            self.special_token_overhead = overhead
            self.tokenizer_contract_probe_version = probe_version
            self.tokenizer_contract_fingerprint = fingerprint
        else:
            self.effective_embedding_max_seq_length = None
            self.special_token_overhead = None
            self.tokenizer_contract_probe_version = None
            self.tokenizer_contract_fingerprint = None

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
        self.rrf_tie_breaker = ret.get("rrf_tie_breaker", "chunk_id_asc")
        if (
            type(self.rrf_tie_breaker) is not str
            or self.rrf_tie_breaker == ""
        ):
            raise ConfigError(
                f"retriever.rrf_tie_breaker 必须是非空字符串，"
                f"当前: {self.rrf_tie_breaker!r}"
            )
        if self.rrf_tie_breaker != "chunk_id_asc":
            raise ConfigError(
                f"未知 retriever.rrf_tie_breaker: {self.rrf_tie_breaker}，"
                "当前只支持 chunk_id_asc"
            )

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

        # ── Prompt 预算（G1-CTX-03B） ────────────────────
        for name in ("max_total_tokens", "max_output_tokens",
                     "message_overhead_tokens"):
            value = gen.get(name)
            if value is None:
                continue  # 用默认值
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    f"generator.{name} 必须是正整数（不允许 bool），当前: {value!r}"
                )
        self.generator_max_total_tokens = gen.get("max_total_tokens", 4096)
        self.generator_max_output_tokens = gen.get("max_output_tokens", 800)
        self.generator_message_overhead_tokens = gen.get("message_overhead_tokens", 16)
        if self.generator_max_output_tokens >= self.generator_max_total_tokens:
            raise ConfigError(
                f"generator.max_output_tokens ({self.generator_max_output_tokens}) "
                f"必须 < max_total_tokens ({self.generator_max_total_tokens})"
            )

        # ── vector_store ──────────────────────────────
        vs = raw.get("vector_store", {})
        self.vector_store_path = vs.get("path", "./data/vector_store")

        # ── 拒答阈值（M4 测试集校准后启用） ─────────────
        gen2 = raw.get("generator", {})
        self.min_score = gen2.get("min_score", 0.0)  # top 分低于此值拒答

    def dump(self) -> dict:
        """脱敏配置摘要（不含 API Key）"""
        return {
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "chunker_strategy": self.chunker_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunk_budget_policy": self.chunk_budget_policy,
            "effective_embedding_max_seq_length": (
                self.effective_embedding_max_seq_length
            ),
            "special_token_overhead": self.special_token_overhead,
            "tokenizer_contract_probe_version": (
                self.tokenizer_contract_probe_version
            ),
            "tokenizer_contract_fingerprint": (
                self.tokenizer_contract_fingerprint
            ),
            "retriever_strategy": self.retriever_strategy,
            "top_k": self.top_k,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "rrf_k": self.rrf_k,
            "rrf_tie_breaker": self.rrf_tie_breaker,
            "reranker_enabled": self.reranker_enabled,
            "reranker_candidate_k": self.reranker_candidate_k,
            "reranker_final_k": self.reranker_final_k,
            "generator_provider": self.generator_provider,
            "generator_model": self.generator_model,
            "generator_temperature": self.generator_temperature,
            "generator_max_total_tokens": self.generator_max_total_tokens,
            "generator_max_output_tokens": self.generator_max_output_tokens,
            "generator_message_overhead_tokens": self.generator_message_overhead_tokens,
            "vector_store_path": self.vector_store_path,
        }
