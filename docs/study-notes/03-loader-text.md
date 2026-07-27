# File: core/loader/text_loader.py

## 作用

加载纯文本文件（TXT、Markdown 等），将整个文件作为一个 Document 返回。

## 完整代码（逐行讲解）

```python
from typing import List

from core.loader.base import BaseLoader, Document


class TextLoader(BaseLoader):
    def load(self, source: str) -> List[Document]:
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()
        return [Document(
            content=content,
            metadata={
                "source": source,
                "type": "text",
                "filename": source.split("/")[-1],
            }
        )]
```

---

**逐行讲解：**

- `with open(source, "r", encoding="utf-8") as f:` — 上下文管理器打开文件。`"r"` 只读模式，`encoding="utf-8"` 指定编码。
  - `with` 语句结束时自动关闭文件，等价于 Java 的 `try-with-resources`。
  - 不指定 `encoding` 时，Windows 默认用 `gbk`，Unix 用 `utf-8`。显式指定 `utf-8` 保证跨平台一致。
- `.read()` — 读取整个文件内容到字符串。文件不大时没问题，超大文件需要逐行读取。
- `source.split("/")[-1]` — 从文件路径中提取文件名。`"a/b/c.txt".split("/") → ["a", "b", "c.txt"]`，取 `[-1]` 得到 `"c.txt"`。在 Windows 上用 `os.path.basename(source)` 更好。

## 重点总结

1. **一个文件一个 Document** — 不像 PDFLoader 按页拆分，TextLoader 把整个文件作为一个 Document。
2. **UTF-8 编码强制指定** — 防止跨平台编码问题。
3. **后续会经过 Chunker 分块** — 大文件在 `load` 阶段不分块，分块是 Chunker 的职责。

## 大厂面试可能问

- **Q: 大文件（比如 100MB）用 `.read()` 会不会内存溢出？** — 会。生产环境应该用流式读取或分块读取。可以在 loader 层加一个 `max_size` 参数限制，或者在 TextLoader 里做文件大小的检查。

- **Q: 为什么 filename 用 `source.split("/")[-1]` 而不是 `os.path.basename`？** — 后者更规范，跨平台兼容。这个写法只是简化版。
