from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseVectorStore(ABC):

    @abstractmethod
    def add(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        """存入文档和向量，返回这批文档的 ID 列表"""
        ...

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Document]:
        """按向量搜索，返回最相似的 top_k 个文档"""
        ...

    @abstractmethod
    def delete(self, ids: List[str]):
        """删除指定 ID 的文档"""
        ...

    @abstractmethod
    def count(self) -> int:
        """返回当前存储的文档总数"""
        ...
