from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from typing import List,Optional

@dataclass
class Document:
    content:str
    metadata:dict = field(default_factory=dict)

class BaseLoader(ABC):
    @abstractmethod
    def load(self,source:str)->List[Document]:
        ...