from core.chunker.token_counter import TokenCounter
from core.loader.base import Document
from core.chunker.recursive import RecursiveChunker


def test_recursive_chunker_short_text():
    doc = Document(content="Hello world")
    chunker = RecursiveChunker(chunk_size=512)
    result = chunker.chunk([doc])
    assert len(result) == 1


def test_recursive_chunker_respects_boundary():
    text = ("Short para.\n\n" * 100)
    doc = Document(content=text)
    chunker = RecursiveChunker(chunk_size=200)
    result = chunker.chunk([doc])
    for r in result:
        assert r.metadata["token_count"] <= 200


def test_recursive_chunker_multiple_docs():
    docs = [
        Document(content="Hello world." * 200),
        Document(content="Another doc." * 200),
    ]
    chunker = RecursiveChunker(chunk_size=200)
    result = chunker.chunk(docs)
    assert len(result) >= 2


def test_recursive_chunker_oversized_segment_hard_split():
    """无分隔符的超长段落必须被硬切，不产出超限 chunk"""
    content = "a" * 3000
    doc = Document(content=content)
    chunker = RecursiveChunker(chunk_size=100, chunk_overlap=10)
    result = chunker.chunk([doc])
    assert len(result) > 1
    for c in result:
        assert c.metadata["token_count"] <= 100


def test_recursive_chunker_empty_doc_skipped():
    """空文档不生成空块"""
    docs = [Document(content=""), Document(content="hello world")]
    chunker = RecursiveChunker(chunk_size=50)
    result = chunker.chunk(docs)
    assert len(result) == 1
    assert "hello" in result[0].content


# ── REWORK-P0-03: 不丢标点/汉字/Emoji ────────────────

LONG_ZH = (
    "缓存穿透是指查询不存在的数据由于缓存中没有请求会穿过缓存直接打到数据库"
    "常见解决方案包括布隆过滤器和缓存空值布隆过滤器将所有可能存在的数据哈希"
    "到一个足够大的bitmap中一个一定不存在的数据会被这个bitmap拦截掉"
    "缓存击穿是指热点key在失效的瞬间大量并发请求同时打到数据库"
    "与缓存穿透不同击穿的key在数据库中是有值的解决方案包括互斥锁和逻辑过期"
)


def _join(chunks):
    return "".join(c.content for c in chunks)


def test_recursive_overlap0_joins_to_original():
    """overlap=0 时拼接精确还原原文，不丢标点/汉字/Emoji"""
    texts = [
        LONG_ZH,
        "第一段。第二段\n\n第三段！含标点，和英文 mixed text. 🎉",
        "🎉🎊🚀 emoji 混排 text " * 10,
    ]
    for text in texts:
        chunks = RecursiveChunker(chunk_size=24, chunk_overlap=0).chunk(
            [Document(content=text, metadata={})]
        )
        assert _join(chunks) == text
        assert all("�" not in c.content for c in chunks)


def test_recursive_small_chunk_size_no_loss():
    """chunk_size=3 时硬切路径也不丢字"""
    chunks = RecursiveChunker(chunk_size=3, chunk_overlap=0).chunk(
        [Document(content=LONG_ZH, metadata={})]
    )
    assert _join(chunks) == LONG_ZH
    assert all("�" not in c.content for c in chunks)


def test_recursive_chunks_are_exact_substrings():
    """每个 chunk 必须是原文精确子串，token_count 与 count 一致"""
    from core.chunker.token_counter import TokenCounter
    counter = TokenCounter()
    text = LONG_ZH + " 含标点，mixed text 🎉 和代码 `def f(): pass`"
    chunks = RecursiveChunker(chunk_size=24, chunk_overlap=4).chunk(
        [Document(content=text, metadata={})]
    )
    for c in chunks:
        s, e = c.metadata["char_start"], c.metadata["char_end"]
        assert text[s:e] == c.content
        assert counter.count(c.content) == c.metadata["token_count"]


# ── REWORK-P0-03-R1: 严格预算 ───────────────────────

class Char3TokenCounter(TokenCounter):
    """每字符 3 token 的确定性计数器"""

    def __init__(self):
        self._enc = None

    def count(self, text):
        return len(text) * 3


def test_recursive_char3_budget_respected():
    """每字符 3 token、预算 3：每块恰 1 字符，全部不超过预算"""
    chunker = RecursiveChunker(chunk_size=3, chunk_overlap=0, token_counter=Char3TokenCounter())
    chunks = chunker.chunk([Document(content="ab", metadata={})])
    assert _join(chunks) == "ab"
    assert all(c.metadata["token_count"] <= 3 for c in chunks)


def test_recursive_segments_overlap_token_budget():
    """overlap 配置按 token：重叠区 token 数不超过配置"""
    text = "第一段内容。第二段内容。第三段内容。"
    for overlap in (0, 3, 6):
        chunker = RecursiveChunker(chunk_size=6, chunk_overlap=overlap,
                                   token_counter=Char3TokenCounter())
        chunks = chunker.chunk([Document(content=text, metadata={})])
        for prev, cur in zip(chunks, chunks[1:]):
            ov = prev.metadata["char_end"] - cur.metadata["char_start"]
            assert ov >= 0
            ov_tokens = Char3TokenCounter().count(
                text[cur.metadata["char_start"]:prev.metadata["char_end"]]
            )
            assert ov_tokens <= overlap, f"重叠区 {ov_tokens} token > 配置 {overlap}"
