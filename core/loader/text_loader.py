from typing import List
from core.loader.base import BaseLoader,Document

class TextLoader(BaseLoader):
    def load(self,source: str) -> List[Document]:
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()
        filename = source.split("/")[-1]
        return [Document(
            content=content,
            metadata={
                "source":source,
                "type":"text",
                "filename":filename,
            }
        )]