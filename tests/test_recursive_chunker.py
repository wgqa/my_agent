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
