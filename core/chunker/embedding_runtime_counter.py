"""G2-IMPL-20：BGE-aligned chunk budget counter。

count() 表示 content token count（不含 special tokens），供 Chunker
做 boundary / overlap 预算；count_model_input() 表示含 special tokens
的最终模型输入长度，用于 correctness 校验。

max_substring / substring_start 使用 correctness-safe 线性扫描，
不依赖 "token count 随 substring 扩展单调非减" 的假设（该假设尚未对
runtime tokenizer 证明）；post-condition 只作为额外防线。
"""

from typing import Optional


class EmbeddingRuntimeTokenCounter:
    policy = "embedding_runtime_model_input_v1"

    def __init__(self, tokenizer, model_input_budget: int):
        self._tokenizer = tokenizer
        self.model_input_budget = int(model_input_budget)
        self.special_token_overhead = int(
            tokenizer.num_special_tokens_to_add(pair=False)
        )
        self.content_budget = self.model_input_budget - self.special_token_overhead
        if self.content_budget <= 0:
            raise ValueError(
                f"content_budget={self.content_budget} 必须 > 0"
                f"（model_input_budget={self.model_input_budget}，"
                f"overhead={self.special_token_overhead}）"
            )
        self.name = "embedding_runtime"

    @property
    def tokenizer(self):
        """正式模型实例的 runtime tokenizer（与 encode 同一来源）。"""
        return self._tokenizer

    # ── 计数 ──────────────────────────────────────────────

    def count(self, text: str) -> int:
        """正文 token 数（Chunker 内统一表示 content token count）。"""
        return len(
            self._tokenizer(
                text,
                add_special_tokens=False,
                truncation=False,
            )["input_ids"]
        )

    def count_content(self, text: str) -> int:
        return self.count(text)

    def count_model_input(self, text: str) -> int:
        """含 special tokens 的最终输入长度。"""
        return len(
            self._tokenizer(
                text,
                add_special_tokens=True,
                truncation=False,
            )["input_ids"]
        )

    # ── 正确性安全边界搜索（不依赖 monotonicity）──────────

    def max_substring(
        self,
        text: str,
        start: int,
        limit: int,
        end: Optional[int] = None,
        allow_oversize: bool = False,
    ) -> int:
        """返回使 count(text[start:end']) <= limit 的最远 end'。

        线性扫描所有候选点，即使 token count 非单调也能找到真正最远
        合法 boundary；allow_oversize=True 且单字符也超限时返回
        start+1（保留一个完整字符，语义与现有 Chunker 一致）。
        """
        hi = end if end is not None else len(text)
        if limit <= 0 or start >= hi:
            return start
        best = start
        for probe in range(start + 1, hi + 1):
            if self.count(text[start:probe]) <= limit:
                best = probe
        if best == start and allow_oversize and start < hi:
            return start + 1
        if best > start and self.count(text[start:best]) > limit:
            raise RuntimeError(
                "EmbeddingRuntimeTokenCounter.max_substring post-condition "
                f"失败：end={best} count>limit"
            )
        return best

    def substring_start(
        self,
        text: str,
        end: int,
        limit: int,
        min_start: int = 0,
    ) -> int:
        """返回使 count(text[start:end]) <= limit 的最小 start。

        线性扫描 [min_start, end)，不依赖 monotonicity；无合法点时
        返回 end（无重叠）。
        """
        if limit <= 0 or end <= min_start:
            return end
        best = end
        for start in range(end - 1, min_start - 1, -1):
            if self.count(text[start:end]) <= limit:
                best = start
        if best < end and self.count(text[best:end]) > limit:
            raise RuntimeError(
                "EmbeddingRuntimeTokenCounter.substring_start "
                f"post-condition 失败：start={best} count>limit"
            )
        return best
