from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseReranker(ABC):

    @abstractmethod
    def rerank(self, query: str, documents: List[Document], top_k: int = 5) -> List[Document]:
        ...
