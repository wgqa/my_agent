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
