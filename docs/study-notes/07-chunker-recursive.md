# File: core/chunker/recursive.py

## 作用

按分隔符优先级递归分割文本，尽可能保留语义边界。这是 LangChain 默认的分块策略，也是实践中最常用的分块方式。

## 完整代码（逐行讲解）

```python
from typing import List

from core.loader.base import Document
from core.chunker.base import BaseChunker


class RecursiveChunker(BaseChunker):
    """按分隔符优先级递归分割，保留语义边界"""

    SEPARATORS = ["\n\n", "\n", "。", ".", " ", ""]
```

- `SEPARATORS` 定义了分割优先级：段落 → 行 → 句号 → 空格 → 字符。
- **核心思路：** 先用高级分隔符（段落）切，如果切出来的块还是太大，用下一个级别的分隔符继续切，直到块大小合适或用尽所有分隔符。

---

```python
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, documents: List[Document]) -> List[Document]:
        chunked = []
        for doc in documents:
            chunks = self._split_text(doc.content)
            for i, chunk_text in enumerate(chunks):
                chunked.append(Document(
                    content=chunk_text,
                    metadata={**doc.metadata, "chunk_index": i}
                ))
        return chunked

    def _split_text(self, text: str) -> List[str]:
        return self._recursive_split(text, self.SEPARATORS, 0)
```

- `_split_text` 是入口，调用 `_recursive_split` 从优先级 0（段落）开始分割。

---

```python
    def _recursive_split(self, text: str, separators: List[str], depth: int) -> List[str]:
        if len(text) <= self.chunk_size or depth >= len(separators):
            return [text]
```

**递归终止条件：** ①文本长度小于 chunk_size（已经够小了）；②分隔符用完了（降级到按字符分割）。

```python
        separator = separators[depth]
        if not separator:
            # 按字符分割
            return [text[i:i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]
```

**最底层的兜底：** 当 separator 是空字符串时，按字符切。`text[i:i+chunk_size]` 是字符串切片，相当于 Java 的 `substring()`。

```python
        parts = text.split(separator)
        chunks = []
        current = ""

        for part in parts:
            candidate = current + (separator if current else "") + part
            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    chunks.extend(self._recursive_split(current, separators, depth + 1))
                current = part
```

**核心算法（贪心合并）：**
1. 用当前分隔符切割文本得到 `parts`
2. 遍历每个片段，尝试合并到 `current` 中
3. 如果合并后不超过 chunk_size → 继续合并
4. 如果超过 → 把已积累的 `current` 交给下一级递归（`depth + 1`），当前片段作为新起点
5. `(separator if current else "")` ——只在有已积累内容时才加分隔符，防止开头多出分隔符

```python
        if current:
            chunks.extend(self._recursive_split(current, separators, depth + 1))

        return chunks
```

- 循环结束后，最後一段也要处理。

## 重点总结

1. **递归深度优先：** 先用段落分割，如果段落太大，再递归到行→句→词→字符级别。
2. **贪心合并：** 同一层级的片段尽可能合并到接近 chunk_size，减少过度分割。
3. **对比 FixedSize：** Recursive 的块边界在自然语义边界上（段落/句子结束处），不会切断句子。但块大小不均匀。

## 大厂面试可能问

- **Q: 为什么 RecursiveChunker 比 FixedSize 更常用？** — 因为它尊重语义边界（段落、句子），不会把一个句子切到两个 chunk 里。Embedding 质量更好。

- **Q: 递归深度会不会太深导致性能问题？** — 不会。最深层是空字符串（按字符切），最多 6 层。每次递归文本长度递减，深度有限。

- **Q: 中文的句号 `。` 和英文的句号 `.` 被分开处理，为什么？** — 中文不常用 `.` 作为句子结束。分开处理可以分别控制。如果在英文文本时，`.` 优先级更高会更合适。

- **Q: 这个方法能处理超大文本吗？** — 可以。因为每次递归都会减小文本长度，最终要么被切小，要么降到按字符切。但极端情况下（比如一段 10 万字的段落），递归深度只有 6 层，最终会走到字符级分割。


复盘时发现的问题：1、没有chunk的重叠区域2、在寻找token分界点的这个函数中是按照比例分界的并不是实际的字符一一对应来分界的