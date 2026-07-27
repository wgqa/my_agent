from abc import ABC, abstractmethod
from typing import List

class BaseEmbedding(ABC):
    @abstractmethod
    def embed(self,texts: List[str]) -> List[List[float]]:
            """批量计算embedding"""
    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
          """计算单条查询的embedding"""