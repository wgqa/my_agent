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

    def max_substring(
        self, text: str, start: int, limit: int,
        end: int | None = None, allow_oversize: bool = False,
    ) -> int:
        """返回最大的 end（字符位置），使 count(text[start:end]) <= limit。

        - end：可选结束边界，结果不跨出该字符位置。
        - allow_oversize：limit 小于单字符 token 跨度时放行一个完整字符。
          Chunker 传 True（预算超支但语义上优于丢字）；
          ContextAssembler 用默认 False（严格预算，放不下就返回 start）。
        二分依赖 BPE 编码长度随文本增长的单调非减性。
        """
        hi = end if end is not None else len(text)
        if limit <= 0 or start >= hi:
            return start
        # 指数试探找第一个超预算位置，再在其内二分：
        # 探测窗口相对 start 扩张（绝对下标翻倍会让 start>0 时第一次
        # 加倍就跳到全文长度，小 limit 场景接近二次复杂度）
        lo = start
        step = 1
        probe = start + 1
        while probe <= hi:
            if self.count(text[start:probe]) > limit:
                break
            lo = probe
            if probe == hi:
                break
            step *= 2
            probe = min(hi, start + step)
        while lo + 1 < probe:
            mid = (lo + probe) // 2
            if self.count(text[start:mid]) <= limit:
                lo = mid
            else:
                probe = mid
        if lo == start and allow_oversize and start < hi:
            lo = start + 1
        return lo

    def substring_start(
        self, text: str, end: int, limit: int, min_start: int = 0,
    ) -> int:
        """返回最小的 start（字符位置），使 count(text[start:end]) <= limit。

        用于 overlap 回退：从 end 往前找最多 limit 个 token 的起始位置。
        返回范围 [min_start, end]；limit<=0 或 end<=min_start 时返回 end（无重叠）。
        二分依赖 BPE 编码长度随文本增长的单调非减性。
        """
        if limit <= 0 or end <= min_start:
            return end
        # 指数回退探测窗口找第一个超限位置，再在其内二分：
        # 窗口相对 end 扩张，小 limit 时只 count 小窗口
        lo = end  # 可行（空文本 0 token）
        step = 1
        while True:
            probe = max(min_start, end - step)
            if self.count(text[probe:end]) > limit:
                break
            lo = probe
            if probe == min_start:
                return lo
            step *= 2
        # probe 不可行（count > limit）、lo 可行：二分找最小可行点
        left, right = probe, lo
        while left + 1 < right:
            mid = (left + right) // 2
            if self.count(text[mid:end]) <= limit:
                right = mid
            else:
                left = mid
        return right

    @property
    def name(self) -> str:
        return self._enc.name if self._enc else "char"
