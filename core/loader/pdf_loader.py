from typing import List
import fitz

from core.loader.base import BaseLoader, Document

class PDFLoader(BaseLoader):
    def load(self, source: str) -> List[Document]:
        docs = []
        doc = fitz.open(source)

        for page_num, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                docs.append(Document(
                    content=text,
                    metadata={
                        "source":source,
                        "page_num":page_num + 1,
                        "type":"pdf",
                    }
                ))
        doc.close()
        return docs