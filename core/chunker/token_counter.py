from typing import List, Optional


class TokenCounter:
    """统一的 token 计数器，隔离不同模型的分词实现"""

    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except ImportError:
            self._enc = None

    def count(self, text: str) -> int:
        """返回文本的 token 数"""
        if self._enc:
            return len(self._enc.encode(text))
        # fallback：中文字符算 1.5 token，其他算 1 token
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars)

    def encode(self, text: str) -> List[int]:
        if self._enc:
            return self._enc.encode(text)
        return list(text.encode("utf-8"))

    def decode(self, token_ids: List[int]) -> str:
        if self._enc:
            return self._enc.decode(token_ids)
        try:
            return bytes(token_ids).decode("utf-8", errors="replace")
        except Exception:
            return "<decode_error>"

    @property
    def name(self) -> str:
        return self._enc.name if self._enc else "char_estimate"
