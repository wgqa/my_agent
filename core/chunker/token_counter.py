from typing import List, Optional


class TokenCounter:
    """统一的 token 计数器，只负责预算判断，不承担文本切片。

    设计原则：原始字符串是事实来源，Chunker/Assembler 始终在字符层
    切片（文本永远是原文的精确子串），token 数只用来判断预算。
    """

    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except ImportError:
            self._enc = None

    def count(self, text: str) -> int:
        """返回文本的 token 数（与 encode 同一单位）"""
        if self._enc:
            return len(self._enc.encode(text))
        return len(text)  # fallback：1 字符 = 1 token

    def encode(self, text: str) -> List[int]:
        if self._enc:
            return self._enc.encode(text)
        return [ord(c) for c in text]  # 字符级编码，任何切片都是合法边界

    def decode(self, token_ids: List[int]) -> str:
        if self._enc:
            return self._enc.decode(token_ids)
        return "".join(chr(t) for t in token_ids)

    def max_substring(self, text: str, start: int, limit: int) -> int:
        """返回最大的 end（字符位置），使 count(text[start:end]) <= limit。

        二分依赖 BPE 编码长度随文本增长的单调非减性。
        例外：limit 小于单个字符的 token 跨度时，放行一个完整字符
        （预算超支但语义上优于丢字，测试 test_fixed_token_budget_respected 记录）。
        """
        if limit <= 0 or start >= len(text):
            return start
        lo, hi = start, len(text) + 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if self.count(text[start:mid]) <= limit:
                lo = mid
            else:
                hi = mid
        if lo == start:
            lo = start + 1
        return lo

    @property
    def name(self) -> str:
        return self._enc.name if self._enc else "char"
