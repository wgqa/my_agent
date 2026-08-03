import os
from typing import List
import fitz

from core.loader.base import BaseLoader, Document


class PDFLoader(BaseLoader):
    def load(self, source: str) -> List[Document]:
        docs = []
        # with 上下文管理，解析失败也保证文件句柄关闭
        with fitz.open(source) as doc:
            if doc.is_encrypted:
                return [Document(
                    content="",
                    metadata={
                        "source": source,
                        "source_name": os.path.basename(source),
                        "type": "pdf",
                        "status": "encrypted",
                    }
                )]

            for page_num, page in enumerate(doc):
                text = page.get_text().strip()
                if text:
                    docs.append(Document(
                        content=text,
                        metadata={
                            "source": source,
                            "source_name": os.path.basename(source),
                            "page_num": page_num + 1,
                            "type": "pdf",
                        }
                    ))
        return docs