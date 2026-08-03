import os
import re
from typing import List

from core.loader.base import BaseLoader, Document


class CodeLoader(BaseLoader):
    def __init__(self, language: str = "python"):
        self.language = language

    def load(self, source: str) -> List[Document]:
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()

        # 只有 Python 用结构正则切分；Java/JS 先用整文件
        if self.language == "python":
            return self._split_python(source, content)
        return [Document(
            content=content,
            metadata={
                "source": source,
                "source_name": os.path.basename(source),
                "type": "code",
                "language": self.language,
            }
        )]

    def _split_python(self, source: str, content: str) -> List[Document]:
        pattern = r"^(class |def |async def )"
        lines = content.split("\n")
        docs = []
        last_split = 0
        for i, line in enumerate(lines):
            if re.match(pattern, line, re.M) and i > 0:
                block = "\n".join(lines[last_split:i]).strip()
                if block:
                    docs.append(Document(
                        content=block,
                        metadata={
                            "source": source,
                            "source_name": os.path.basename(source),
                            "type": "code",
                            "language": "python",
                            "header": line.strip(),
                        }
                    ))
                last_split = i
        remaining = "\n".join(lines[last_split:]).strip()
        if remaining:
            docs.append(Document(
                content=remaining,
                metadata={
                    "source": source,
                    "source_name": os.path.basename(source),
                    "type": "code",
                    "language": "python",
                    "header": remaining.split("\n")[0],
                }
            ))

        return docs if docs else [Document(
            content=content,
            metadata={
                "source": source,
                "source_name": os.path.basename(source),
                "type": "code",
                "language": "python",
            }
        )]