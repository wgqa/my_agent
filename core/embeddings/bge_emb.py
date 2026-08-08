from typing import List

from core.embeddings.base import BaseEmbedding

class BGEEmbedding(BaseEmbedding):
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        self.model_name = model_name
        self._model = None

    def _lazy_load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, local_files_only=True)

    def get_runtime_model(self):
        """返回正式 encode() 使用的同一个 SentenceTransformer 实例。"""
        self._lazy_load()
        return self._model

    def get_runtime_tokenizer(self):
        """返回正式模型实例的 tokenizer（与 encode 同一来源）。"""
        return self.get_runtime_model()[0].tokenizer

    def get_runtime_contract(self) -> dict:
        """读取运行时 contract（max/overhead/probe/fingerprint），不 encode。"""
        from core.embeddings.runtime_contract import compute_tokenizer_contract
        model = self.get_runtime_model()
        return compute_tokenizer_contract(model[0].tokenizer, model=model)

    def embed(self, texts: List[str]) -> List[List[float]]:
        self._lazy_load()
        return self._model.encode(texts, normalize_embeddings=True).tolist()
    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]
        
