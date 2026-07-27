from typing import List

from core.loader.base import Document
from core.reranker.base import BaseReranker


class BGEReranker(BaseReranker):

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self._model = None

    def _lazy_load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name, local_files_only=True)

    def rerank(self, query: str, documents: List[Document], top_k: int = 5) -> List[Document]:
        if not documents:
            return []

        self._lazy_load()
        pairs = [[query, d.content] for d in documents]
        scores = self._model.predict(pairs)

        scored = list(zip(scores, documents))
        scored.sort(key=lambda x: x[0], reverse=True)

        return [doc for _, doc in scored[:top_k]]
