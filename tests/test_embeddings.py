from core.embeddings.base import BaseEmbedding


def test_base_embedding_abstract():
    """BaseEmbedding 是抽象类，不能直接实例化"""
    try:
        BaseEmbedding()
        assert False
    except TypeError:
        pass


def test_openai_embedding_init():
    """OpenAIEmbedding 能正常初始化"""
    from core.embeddings.openai_emb import OpenAIEmbedding
    emb = OpenAIEmbedding(api_key="test-key")
    assert emb.model == "text-embedding-3-small"
    assert emb.client is not None


def test_bge_embedding_init():
    """BGEEmbedding 能正常初始化，model 延迟加载"""
    from core.embeddings.bge_emb import BGEEmbedding
    emb = BGEEmbedding()
    assert emb.model_name == "BAAI/bge-small-zh-v1.5"
    assert emb._model is None  # 还没加载
