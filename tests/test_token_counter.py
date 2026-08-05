"""REWORK-P0-03: TokenCounter 一致性 + 预算二分"""

from core.chunker.token_counter import TokenCounter


def _counter_without_tiktoken():
    counter = TokenCounter()
    counter._enc = None  # 模拟 tiktoken 不可用
    return counter


# ── fallback：一致单位（1 字符 = 1 token） ────────────

def test_fallback_consistent_units():
    counter = _counter_without_tiktoken()
    text = "缓存穿透 🎉 abc"
    assert counter.count(text) == len(text)          # count 与 encode 同单位
    assert len(counter.encode(text)) == len(text)
    assert counter.decode(counter.encode(text)) == text  # roundtrip 精确


def test_fallback_emoji_and_mixed_roundtrip():
    counter = _counter_without_tiktoken()
    for text in ["🎉🎊🚀", "中文 mixed 🚀 text", "缓存�穿透"]:
        assert counter.decode(counter.encode(text)) == text


# ── max_substring：预算二分 ───────────────────────────

def test_max_substring_respects_budget():
    counter = TokenCounter()
    text = "缓存穿透是指查询不存在的数据"
    end = counter.max_substring(text, 0, 8)
    assert end > 0 and end <= len(text)
    assert counter.count(text[:end]) <= 8


def test_max_substring_full_fit():
    counter = TokenCounter()
    text = "short"
    assert counter.max_substring(text, 0, 100) == len(text)


def test_max_substring_tiny_budget_still_returns_one_char():
    """预算小于单字符 token 跨度时放行一个字符（allow_oversize=True 的例外，不丢字）"""
    counter = TokenCounter()
    text = "缓存穿透"
    end = counter.max_substring(text, 0, 1, allow_oversize=True)
    assert end >= 1
    assert text[:end] != ""  # 有内容，不是空切


def test_max_substring_strict_mode_returns_start():
    """严格模式（默认）：预算放不下一个完整字符时返回 start，不超预算"""
    counter = TokenCounter()
    text = "缓存穿透"
    assert counter.max_substring(text, 0, 1) == 0


class RecordingCounter(TokenCounter):
    """记录每次 count 的窗口长度，验证探测窗口不脱离起点"""

    def __init__(self):
        self._enc = None
        self.max_window = 0

    def count(self, text):
        self.max_window = max(self.max_window, len(text))
        return len(text)  # fallback 单位：1 字符 = 1 token


def test_max_substring_probe_relative_to_start():
    """指数探测基于 start 相对跨度：start=5000、limit=1 时探测窗口不接近全文"""
    counter = RecordingCounter()
    text = "a" * 10000
    end = counter.max_substring(text, 5000, 1)
    assert end == 5001
    assert counter.max_window <= 4, f"最大探测窗口 {counter.max_window} 字符，远超相对跨度"


def test_max_substring_zero_start_still_small_windows():
    """start=0 场景回归：探测窗口仍是相对跨度，不因翻倍而爆炸"""
    counter = RecordingCounter()
    text = "a" * 10000
    end = counter.max_substring(text, 0, 1)
    assert end == 1
    assert counter.max_window <= 4
