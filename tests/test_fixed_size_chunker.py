from core.chunker.token_counter import TokenCounter
from core.loader.base import Document
from core.chunker.fixed_size import FixedSizeChunker


def test_chunker_small_doc():
    doc = Document(content="hello world")
    chunker = FixedSizeChunker(chunk_size=512, chunk_overlap=0)
    result = chunker.chunk([doc])
    assert len(result) == 1
    assert result[0].content == "hello world"


def test_chunker_large_doc():
    content = "word " * 1000
    doc = Document(content=content)
    chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=20)
    result = chunker.chunk([doc])
    assert len(result) > 5
    assert all(len(c.content.split()) <= 100 for c in result)


def test_chunker_metadata_preserved():
    doc = Document(content="hello " * 500, metadata={"source": "test.txt"})
    chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=10)
    result = chunker.chunk([doc])
    assert result[0].metadata["source"] == "test.txt"
    assert "chunk_index" in result[0].metadata


# ── M1-T3 补充测试 ─────────────────────────────────────

def test_chinese_long_text_splits():
    """700 字无空格中文能按预算切分"""
    content = "缓存穿透是指查询一个不存在的数据。" * 100
    doc = Document(content=content)
    chunker = FixedSizeChunker(chunk_size=200, chunk_overlap=20)
    result = chunker.chunk([doc])
    assert len(result) > 1
    for c in result:
        assert c.metadata["token_count"] <= 200


def test_chunk_index_resets_per_document():
    """多文档时 chunk_index 按文档重置"""
    docs = [
        Document(content="a" * 2000, metadata={"source": "doc1.txt"}),
        Document(content="b" * 2000, metadata={"source": "doc2.txt"}),
    ]
    chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=0)
    result = chunker.chunk(docs)
    doc1_indexes = [c.metadata["chunk_index"] for c in result if c.metadata["source"] == "doc1.txt"]
    doc2_indexes = [c.metadata["chunk_index"] for c in result if c.metadata["source"] == "doc2.txt"]
    assert doc1_indexes == list(range(len(doc1_indexes)))
    assert doc2_indexes == list(range(len(doc2_indexes)))


def test_empty_and_whitespace_docs_skipped():
    """空字符串和纯空白文档不生成空块"""
    docs = [
        Document(content=""),
        Document(content="   \n\t  "),
        Document(content="real content here"),
    ]
    chunker = FixedSizeChunker(chunk_size=100, chunk_overlap=10)
    result = chunker.chunk(docs)
    assert len(result) == 1
    assert "real content" in result[0].content


def test_reassembly_does_not_lose_content():
    """原始文本经过分块重组后没有静默丢失"""
    content = "abc def ghi " * 100
    doc = Document(content=content)
    chunker = FixedSizeChunker(chunk_size=50, chunk_overlap=0)
    result = chunker.chunk([doc])
    reassembled = "".join(c.content for c in result)
    assert len(reassembled) >= len(content)


# ── REWORK-P0-03: overlap=0 精确重组 + 极小 chunk_size ──

LONG_ZH = (
    "缓存穿透是指查询不存在的数据由于缓存中没有请求会穿过缓存直接打到数据库"
    "常见解决方案包括布隆过滤器和缓存空值布隆过滤器将所有可能存在的数据哈希"
    "到一个足够大的bitmap中一个一定不存在的数据会被这个bitmap拦截掉"
    "缓存击穿是指热点key在失效的瞬间大量并发请求同时打到数据库"
    "与缓存穿透不同击穿的key在数据库中是有值的解决方案包括互斥锁和逻辑过期"
)

LONG_EN = "the quick brown fox jumps over the lazy dog " * 8

LONG_MIXED = "🎉🎊🚀 中文混排 mixed content 测试 🎯 emoji 与汉字并存 " * 6

WITH_REPLACEMENT = "缓存�穿透与击穿的区别�"


def _join(chunks):
    return "".join(c.content for c in chunks)


def test_fixed_overlap0_joins_to_original():
    """overlap=0 时全部 chunk 拼接必须精确还原原文（中文/英文/Emoji/混排）"""
    for text in [LONG_ZH, LONG_EN, LONG_MIXED]:
        for size in (7, 16, 32):
            chunks = FixedSizeChunker(chunk_size=size, chunk_overlap=0).chunk(
                [Document(content=text, metadata={})]
            )
            assert _join(chunks) == text


def test_fixed_small_chunk_size_chinese_no_loss():
    """chunk_size=1/2/3 中文边界：不丢字、无额外 U+FFFD"""
    for size in (1, 2, 3):
        chunks = FixedSizeChunker(chunk_size=size, chunk_overlap=0).chunk(
            [Document(content=LONG_ZH, metadata={})]
        )
        assert _join(chunks) == LONG_ZH
        assert all("�" not in c.content for c in chunks)


def test_fixed_token_budget_respected():
    """每块 token 数不超预算；预算小于单字符 token 跨度时放行一个字符（例外，注释记录）"""
    for size in (3, 7, 16):
        chunks = FixedSizeChunker(chunk_size=size, chunk_overlap=0).chunk(
            [Document(content=LONG_MIXED, metadata={})]
        )
        for c in chunks:
            assert c.metadata["token_count"] <= max(size, 4), (
                f"chunk {c.metadata['chunk_index']} token_count={c.metadata['token_count']} > {size}"
            )


def test_fixed_keeps_legit_replacement_chars():
    """原文合法的 U+FFFD 必须保留且不新增"""
    chunks = FixedSizeChunker(chunk_size=7, chunk_overlap=0).chunk(
        [Document(content=WITH_REPLACEMENT, metadata={})]
    )
    assert _join(chunks) == WITH_REPLACEMENT
    assert sum(c.content.count("�") for c in chunks) == WITH_REPLACEMENT.count("�")


def test_fixed_chunks_are_exact_substrings():
    """每个 chunk 必须是原文精确子串，char_start/char_end 能映射回原文"""
    from core.chunker.token_counter import TokenCounter
    counter = TokenCounter()
    for text in [LONG_ZH, LONG_EN, LONG_MIXED, WITH_REPLACEMENT]:
        chunks = FixedSizeChunker(chunk_size=16, chunk_overlap=4).chunk(
            [Document(content=text, metadata={})]
        )
        for c in chunks:
            s, e = c.metadata["char_start"], c.metadata["char_end"]
            assert text[s:e] == c.content
            assert counter.count(c.content) == c.metadata["token_count"]


# ── REWORK-P0-03-R1: 严格预算 + 游标前进保证 ───────────

class Char3TokenCounter(TokenCounter):
    """每字符 3 token 的确定性计数器（构造死循环/预算边界场景）"""

    def __init__(self):
        self._enc = None

    def count(self, text):
        return len(text) * 3


def test_fixed_no_deadlock_char3_overlap():
    """每字符 3 token、chunk_size=3、overlap=2：不前进的极端场景必须不死循环"""
    text = "缓存穿透是指查询不存在的数据缓存击穿"
    chunker = FixedSizeChunker(chunk_size=3, chunk_overlap=2, token_counter=Char3TokenCounter())
    chunks = chunker.chunk([Document(content=text, metadata={})])
    assert _join(chunks) == text
    assert all(c.metadata["token_count"] <= 3 for c in chunks)


def test_fixed_overlap_token_budget_respected():
    """overlap 按 token 配置：相邻块重叠区的 token 数不超过配置"""
    text = "缓存穿透是指查询不存在的数据" * 10
    for overlap in (0, 4, 10):
        chunker = FixedSizeChunker(chunk_size=24, chunk_overlap=overlap,
                                   token_counter=Char3TokenCounter())
        chunks = chunker.chunk([Document(content=text, metadata={})])
        for prev, cur in zip(chunks, chunks[1:]):
            ov = prev.metadata["char_end"] - cur.metadata["char_start"]
            assert ov >= 0
            ov_tokens = Char3TokenCounter().count(
                text[cur.metadata["char_start"]:prev.metadata["char_end"]]
            )
            assert ov_tokens <= overlap, f"重叠区 {ov_tokens} token > 配置 {overlap}"


def test_fixed_oversized_marked_for_over_budget_char():
    """chunk_size=1：超预算的完整字符块必须标记 oversized=True（文本完整优先）"""
    chunks = FixedSizeChunker(chunk_size=1, chunk_overlap=0).chunk(
        [Document(content="缓存", metadata={})]
    )
    assert _join(chunks) == "缓存"
    assert any(c.metadata["oversized"] for c in chunks)  # "缓"=2 token > 1
