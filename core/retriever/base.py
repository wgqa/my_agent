from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseRetriever(ABC):

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        ...
