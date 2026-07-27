from typing import List

from core.loader.base import Document
from core.retriever.base import BaseRetriever
from core.embeddings.base import BaseEmbedding
from core.vector_store.base import BaseVectorStore


class SimpleRetriever(BaseRetriever):

    def __init__(self, embedding: BaseEmbedding, vector_store: BaseVectorStore):
        self.embedding = embedding
        self.vector_store = vector_store

    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        query_vec = self.embedding.embed_query(query)
        return self.vector_store.search(query_vec, top_k=top_k)
