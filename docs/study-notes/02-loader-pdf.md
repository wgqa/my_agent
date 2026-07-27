# File: core/loader/pdf_loader.py

## 作用

使用 PyMuPDF（fitz）库加载 PDF 文件，按页提取文本内容，每页生成一个 Document。

## 完整代码（逐行讲解）

```python
from typing import List
import fitz  # PyMuPDF

from core.loader.base import BaseLoader, Document


class PDFLoader(BaseLoader):
    """使用 PyMuPDF 加载 PDF 文件，按页提取文本"""

    def load(self, source: str) -> List[Document]:
        docs = []
        doc = fitz.open(source)
        for page_num, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                docs.append(Document(
                    content=text,
                    metadata={
                        "source": source,
                        "page_num": page_num + 1,
                        "type": "pdf",
                    }
                ))
        doc.close()
        return docs
```

---

**逐行讲解：**

- `import fitz` — PyMuPDF 库的导入名。MuPDF 是一个轻量级的 PDF/文档解析库。
- `doc = fitz.open(source)` — 打开 PDF 文件。返回一个 Document 对象（fitz 的 Document，不是我们自己的）。
- `for page_num, page in enumerate(doc):` — `enumerate` 同时拿到页码索引和页面对象。页码从 0 开始。
- `page.get_text().strip()` — 提取页面的文本内容。`strip()` 去除首尾空白字符。
- `if text:` — **过滤空页**。只有提取到文本的页面才加入结果。这是对 PDF 扫描件（图片格式）的容错——空页会被跳过而不是返回空字符串。
- `"page_num": page_num + 1` — 页码从 1 开始（用户习惯），而 `enumerate` 从 0 开始。
- `doc.close()` — 手动关闭文件。Python 虽然没有 Java 的 `try-with-resources`，但可以用 `with fitz.open(source) as doc:` 语法更安全。

> **Python 对比 Java：** Java 的 `try (Document doc = fitz.open(source)) { ... }` 等价于 Python 的 `with fitz.open(source) as doc: ...`。都是自动资源管理。

## 重点总结

1. **单页单 Document** — 每个 PDF 页面作为一个独立 Document，不是整个 PDF 作为一个 Document。
2. **空页过滤** — `if text:` 跳过空页，防止向量库中出现无意义的内容。
3. **metadata 追溯** — 记录 `source`、`page_num`、`type`，方便后续定位文档来源。

## 大厂面试可能问

- **Q: 遇到扫描件（图片 PDF）怎么办？** — 当前代码 `page.get_text()` 返回空字符串。生产环境需要加 OCR（如 pytesseract）。可以在 `if not text:` 分支中加入 OCR 逻辑。

- **Q: 1000 页的大 PDF 会不会 OOM？** — `fitz.open` 是懒加载的，不会一次性加载所有页。但 `docs` 列表会保存所有页的文本，大文件确实会占用大量内存。生产环境可以按页流式处理。

- **Q: 为什么手动 close 而不是用 `with` 语句？** — 这里确实可以用 `with fitz.open(source) as doc:` 更安全。手动 close 如果前面代码抛异常就关不掉了。
