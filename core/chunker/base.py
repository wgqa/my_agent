from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, documents: List[Document]) -> List[Document]:
        ...
