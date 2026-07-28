from abc import ABC, abstractmethod
from typing import List, Optional

from core.loader.base import Document


class BaseVectorStore(ABC):

    @abstractmethod
    def add(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        ...

    @abstractmethod
    def upsert(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        ...

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5,
               where: Optional[dict] = None) -> List[Document]:
        ...

    @abstractmethod
    def delete(self, ids: List[str]):
        ...

    @abstractmethod
    def delete_by_document_id(self, document_id: str):
        ...

    @abstractmethod
    def count(self) -> int:
        ...

    @abstractmethod
    def list_ids(self, limit: int = 100) -> List[str]:
        ...
