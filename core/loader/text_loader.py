import os
from typing import List
from core.loader.base import BaseLoader, Document


class TextLoader(BaseLoader):
    def load(self, source: str) -> List[Document]:
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()
        # os.path.basename 兼容 Windows 反斜杠路径
        filename = os.path.basename(source)
        return [Document(
            content=content,
            metadata={
                "source": source,
                "source_name": filename,
                "type": "text",
            }
        )]