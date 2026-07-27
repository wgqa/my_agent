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

    def embed(self, texts: List[str]) -> List[List[float]]:
        self._lazy_load()
        return self._model.encode(texts, normalize_embeddings=True).tolist()
    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]
        