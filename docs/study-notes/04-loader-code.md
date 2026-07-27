# File: core/loader/code_loader.py

## 作用

加载 Python 代码文件，按函数（`def`）和类（`class`）定义分割成多个 Document。这样每个函数的代码块独立索引，检索时可以精确定位到函数级。

## 完整代码（逐行讲解）

```python
import re
from typing import List

from core.loader.base import BaseLoader, Document


class CodeLoader(BaseLoader):
    def __init__(self, language: str = "python"):
        self.language = language

    def load(self, source: str) -> List[Document]:
        with open(source, "r", encoding="utf-8") as f:
            content = f.read()
        return self._split_python(source, content)
```

- `language` 参数预留用于支持其他语言（Java/JS），但目前只实现了 Python 分割。
- `_split_python` 处理实际的分割逻辑。

---

```python
    def _split_python(self, source: str, content: str) -> List[Document]:
        pattern = r"^(class |def |async def )"
        lines = content.split("\n")
        docs = []
        last_split = 0
```

- `pattern = r"^(class |def |async def )"` — 正则表达式，匹配以 `class `、`def `、`async def ` 开头的行。
  - `r"..."` — raw string，告诉 Python 不要处理反斜杠转义。
  - `^` — 行首。
  - `(...|...|...)` — 匹配三者之一。
- `lines = content.split("\n")` — 按换行分割成行列表。
- `last_split = 0` — 上一个分割点的行号。

```python
        for i, line in enumerate(lines):
            if re.match(pattern, line, re.M) and i > 0:
                block = "\n".join(lines[last_split:i]).strip()
                if block:
                    docs.append(Document(
                        content=block,
                        metadata={
                            "source": source,
                            "type": "code",
                            "header": line.strip(),
                        }
                    ))
                last_split = i
```

- `re.match(pattern, line, re.M)` — 用多行模式匹配当前行。`re.M` 让 `^` 匹配每一行的开头。
- `and i > 0` — 跳过第一行（文件开头的 import 等），避免在文件开头就空分割。
- `"\n".join(lines[last_split:i]).strip()` — 把从上一次分割到当前行的代码块拼回来。
- `header: line.strip()` — 记录函数/类的定义行，方便区分哪个函数是哪段代码。

```python
        remaining = "\n".join(lines[last_split:]).strip()
        if remaining:
            docs.append(Document(
                content=remaining,
                metadata={"source": source, "type": "code", "header": remaining.split("\n")[0]}
            ))

        return docs if docs else [Document(
            content=content,
            metadata={"source": source, "type": "code"}
        )]
```

- **最后一块处理：** 循环结束后，把从 `last_split` 到文件末尾的剩余部分作为一个 Document。
- **兜底逻辑：** 如果 `docs` 为空（比如文件中没有函数/类定义），返回整个文件作为一个 Document。

## 重点总结

1. **正则分割不是解析** — 用 `re.match` 检测函数/类定义行，而不是用 AST 解析器。这样简单但不够准确（比如字符串中的 `def` 也会被匹配）。
2. **边界处理：** 第一行跳过（`i > 0`），最后一块收尾（`lines[last_split:]`），没有匹配时返回整个文件。
3. **预留扩展：** `language` 参数为支持 Java、JS 等语言做了准备。

## 大厂面试可能问

- **Q: 为什么不用 AST（抽象语法树）而是用正则分割？** — AST 更准确但实现复杂。正则方案 20 行就能工作，覆盖 90% 的常见代码。生产环境可以用 tree-sitter 做精确解析。

- **Q: 这个正则匹配有什么缺陷？** — ①注释中的 `def` 会被误匹配；②多行定义 `def foo(\n    arg1,\n    arg2\n):` 只匹配到第一行；③没有处理装饰器（`@staticmethod` 会被切到上一个函数）。

- **Q: 如果文件中有一个 5000 行的巨型函数，分块效果会很差吧？** — 是的。`CodeLoader` 只按函数/类分块，不会进一步拆分大函数。这种情况需要配合 Chunker 再做二次分块。
