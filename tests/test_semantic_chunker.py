from core.loader.base import Document
from core.chunker.semantic import SemanticChunker


def test_semantic_chunker_no_embedding_fallback():
    """没有 embedding 时自动降级为 RecursiveChunker"""
    doc = Document(content="Sentence one. Sentence two. " * 50)
    chunker = SemanticChunker()
    result = chunker.chunk([doc])
    assert len(result) >= 1


def test_semantic_chunker_with_mock_embedding():
    """用 mock embedding 模拟语义变化"""
    def mock_embed(texts):
        # 前3句相似，第4句完全不同
        return [[0.1, 0.2, 0.3]] * 3 + [[0.9, 0.8, 0.7]]

    text = "A. B. C. Z."
    doc = Document(content=text)
    chunker = SemanticChunker(embedding_fn=mock_embed, threshold=0.5)
    result = chunker.chunk([doc])
    assert len(result) >= 1


def test_semantic_chunker_single_sentence():
    doc = Document(content="Just one sentence.")
    chunker = SemanticChunker()
    result = chunker.chunk([doc])
    assert len(result) == 1
