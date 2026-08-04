"""P0-4: TokenCounter 无 tiktoken 时的 fallback 行为"""

from core.chunker.token_counter import TokenCounter


def _counter_without_tiktoken():
    counter = TokenCounter()
    counter._enc = None  # 模拟 tiktoken 不可用
    return counter


def test_fallback_roundtrip():
    counter = _counter_without_tiktoken()
    text = "缓存穿透是指查询不存在的数据"
    assert counter.decode(counter.encode(text)) == text


def test_fallback_truncation_no_garbage():
    """缺 tiktoken 时，截断落在多字节字符中间不产生 U+FFFD 乱码"""
    counter = _counter_without_tiktoken()
    text = "缓存穿透是指查询不存在的数据"
    truncated = counter.decode(counter.encode(text)[:-1])  # 故意截断最后一个字节
    assert "�" not in truncated
    assert truncated in text


def test_tiktoken_slice_no_garbage():
    """有 tiktoken 时，token 切片跨字符边界同样不能产生 U+FFFD（FixedSizeChunker 路径）"""
    counter = TokenCounter()
    text = (
        "深度学习是机器学习的一个分支 它通过多层神经网络来学习数据的层次化表示 "
        "卷积神经网络在图像领域取得了巨大成功 循环神经网络则擅长处理序列数据 "
        "近年来大语言模型成为了AI领域的热点 GPT系列模型展示了惊人的文本生成能力"
    )
    tokens = counter.encode(text)
    for end in range(1, len(tokens)):
        dec = counter.decode(tokens[:end])
        assert "�" not in dec, f"tokens[:{end}] contains U+FFFD"
        assert dec in text, f"tokens[:{end}] not a substring of text"
