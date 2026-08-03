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
