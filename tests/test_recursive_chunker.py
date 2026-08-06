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
    """overlap 按 token 真实生效：重叠区存在（>0）且不超过配置，块不突破 chunk_size"""
    text = "第一段内容。第二段内容。第三段内容。"
    for overlap in (0, 3, 6):
        chunker = RecursiveChunker(chunk_size=6, chunk_overlap=overlap,
                                   token_counter=Char3TokenCounter())
        chunks = chunker.chunk([Document(content=text, metadata={})])
        ovs = []
        for prev, cur in zip(chunks, chunks[1:]):
            ov_tokens = Char3TokenCounter().count(
                text[cur.metadata["char_start"]:prev.metadata["char_end"]]
            )
            assert ov_tokens <= overlap, f"重叠区 {ov_tokens} token > 配置 {overlap}"
            ovs.append(ov_tokens)
            assert cur.metadata["token_count"] <= 6, "块不得因 overlap 突破 chunk_size"
        if overlap > 0:
            assert max(ovs) > 0, "overlap>0 时必须存在真实重叠（假阳性）"
        else:
            assert max(ovs) == 0


def test_recursive_hard_split_overlap_audit_scenario():
    """审计场景：chunk_size=12、overlap=6、每字符 3 token，硬切块间真实重叠"""
    text = "a" * 40  # 无分隔符，走硬切路径
    chunker = RecursiveChunker(chunk_size=12, chunk_overlap=6,
                               token_counter=Char3TokenCounter())
    chunks = chunker.chunk([Document(content=text, metadata={})])
    assert len(chunks) > 1
    for prev, cur in zip(chunks, chunks[1:]):
        ov_tokens = Char3TokenCounter().count(
            text[cur.metadata["char_start"]:prev.metadata["char_end"]]
        )
        assert 0 < ov_tokens <= 6, f"硬切块重叠 {ov_tokens} 应满足 0 < x <= 6"
        assert cur.metadata["token_count"] <= 12


def test_recursive_oversized_marked_for_over_budget_char():
    """chunk_size=1：超预算字符块标记 oversized，正常块不标记"""
    chunks = RecursiveChunker(chunk_size=1, chunk_overlap=0).chunk(
        [Document(content="缓存", metadata={})]
    )
    assert _join(chunks) == "缓存"
    assert any(c.metadata["oversized"] for c in chunks)
    assert any(not c.metadata["oversized"] for c in chunks)  # "存"=1 token 正常


# ── G1-CHUNK-05A：普通语义段换块的真实 overlap ─────────
# Char3 下：6 字符段 = 18 token；chunk_size=30（10 字符）、overlap=6（2 字符）

def _segments_within_budget(segments, chunk_size, counter):
    """断言每个语义段本身都不超过 chunk_size（证明走普通路径而非硬切）"""
    for seg in segments:
        assert counter.count(seg) <= chunk_size, f"段超限会走硬切路径: {seg!r}"


def test_normal_switch_overlap_between_segments():
    """三个短语义段：前两个组成一块，第三个触发普通换块，重叠真实生效"""
    counter = Char3TokenCounter()
    segments = ["第一段内容。", "第二段内容。", "第三段内容。"]
    _segments_within_budget(segments, 30, counter)
    text = "".join(segments)
    chunker = RecursiveChunker(chunk_size=30, chunk_overlap=6,
                               token_counter=counter)
    chunks = chunker.chunk([Document(content=text, metadata={})])
    assert len(chunks) >= 2
    for prev, cur in zip(chunks, chunks[1:]):
        ov = counter.count(
            text[cur.metadata["char_start"]:prev.metadata["char_end"]]
        )
        assert 0 < ov <= 6, f"普通换块重叠 {ov} 应满足 0 < x <= 6"
        assert cur.metadata["token_count"] <= 30
        s, e = cur.metadata["char_start"], cur.metadata["char_end"]
        assert text[s:e] == cur.content  # 精确子串


def test_normal_switch_overlap_zero_joins_exact():
    """overlap=0 时普通换块无重叠，拼接精确还原原文"""
    counter = Char3TokenCounter()
    segments = ["第一段内容。", "第二段内容。", "第三段内容。"]
    _segments_within_budget(segments, 30, counter)
    text = "".join(segments)
    chunks = RecursiveChunker(chunk_size=30, chunk_overlap=0,
                              token_counter=counter).chunk(
        [Document(content=text, metadata={})]
    )
    for prev, cur in zip(chunks, chunks[1:]):
        ov = counter.count(
            text[cur.metadata["char_start"]:prev.metadata["char_end"]]
        )
        assert ov == 0
    assert _join(chunks) == text


def test_normal_switch_overlap_shrinks_near_budget():
    """当前片段接近 chunk_size：overlap 自动缩小但块不超预算、片段不丢"""
    counter = Char3TokenCounter()
    segments = ["第一段内容。", "第二段内容很长。", "第三段内容。"]
    _segments_within_budget(segments, 30, counter)
    text = "".join(segments)
    chunker = RecursiveChunker(chunk_size=30, chunk_overlap=6,
                               token_counter=counter)
    chunks = chunker.chunk([Document(content=text, metadata={})])
    for c in chunks:
        assert c.metadata["token_count"] <= 30
        s, e = c.metadata["char_start"], c.metadata["char_end"]
        assert text[s:e] == c.content
    # 存在重叠但至少一对重叠被缩小（< 配置值）
    ovs = [
        counter.count(text[cur.metadata["char_start"]:prev.metadata["char_end"]])
        for prev, cur in zip(chunks, chunks[1:])
    ]
    assert any(0 < ov <= 6 for ov in ovs)
    # 段 2（9 字符 27 token）必须完整保留在某块内
    assert "第二段内容很长。" in "".join(c.content for c in chunks)


def test_normal_switch_consecutive_overlaps_cover_original():
    """连续多个普通换块均有正确 overlap；去重叠区后完整覆盖原文"""
    counter = Char3TokenCounter()
    segments = ["第一段内容。", "第二段内容。", "第三段内容。", "第四段内容。"]
    _segments_within_budget(segments, 30, counter)
    text = "".join(segments)
    chunker = RecursiveChunker(chunk_size=30, chunk_overlap=6,
                               token_counter=counter)
    chunks = chunker.chunk([Document(content=text, metadata={})])
    pairs = list(zip(chunks, chunks[1:]))
    assert len(pairs) >= 2  # 至少两个普通换块
    for prev, cur in pairs:
        ov = counter.count(
            text[cur.metadata["char_start"]:prev.metadata["char_end"]]
        )
        assert 0 < ov <= 6
    # 去重叠区后覆盖 [0, len(text))：取每块相对前一块的"新增区"
    covered = 0
    for c in chunks:
        start = max(c.metadata["char_start"], covered)
        covered = c.metadata["char_end"]
        assert start <= covered
    assert covered == len(text)


def test_normal_switch_mixed_text_no_loss():
    """中英文、标点、Emoji 语义段换块：不丢字、无 U+FFFD、精确子串"""
    counter = Char3TokenCounter()
    segments = [
        "第一段，含标点。",
        "A seg. OK.",
        "🎉🚀 Emoji!",
        "最后 ok.",
    ]
    _segments_within_budget(segments, 30, counter)
    text = "".join(segments)
    chunker = RecursiveChunker(chunk_size=30, chunk_overlap=6,
                               token_counter=counter)
    chunks = chunker.chunk([Document(content=text, metadata={})])
    joined = _join(chunks)
    assert len(chunks) >= 2
    for c in chunks:
        assert "�" not in c.content
        s, e = c.metadata["char_start"], c.metadata["char_end"]
        assert text[s:e] == c.content
    # 重叠区不破坏覆盖：去掉重叠后仍能拼回原文
    merged = ""
    last_end = 0
    for c in chunks:
        s = c.metadata["char_start"]
        merged += text[max(s, last_end):c.metadata["char_end"]]
        last_end = c.metadata["char_end"]
    assert merged == text
