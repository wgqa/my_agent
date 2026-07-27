# File: core/chunker/fixed_size.py

## 作用

基于词数（word count）的固定大小分块器。按指定 chunk_size 和 chunk_overlap 将文本切成等长的块，是最基础的分块策略。

## 完整代码（逐行讲解）

```python
from typing import List

from core.loader.base import Document
from core.chunker.base import BaseChunker


class FixedSizeChunker(BaseChunker):
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
```

- `chunk_size: int = 512` — 每个块的目标词数。默认 512 词约等于 350-400 个英文 token。
- `chunk_overlap: int = 64` — 相邻块之间的重叠词数。重叠的作用是保证被切在边界上的内容不会丢失上下文。

---

```python
    def chunk(self, documents: List[Document]) -> List[Document]:
        chunked = []
        for doc in documents:
            words = doc.content.split()
            if len(words) <= self.chunk_size:
                chunked.append(doc)
                continue
```

- `doc.content.split()` — 默认按空白字符分割成词列表。
- `if len(words) <= self.chunk_size: continue` — 如果文档本身就比 chunk_size 小，直接整篇返回，不分块。

```python
            start = 0
            for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
                chunk_words = words[i:i + self.chunk_size]
                if len(chunk_words) < self.chunk_size * 0.3:
                    break
                chunked.append(Document(
                    content=" ".join(chunk_words),
                    metadata={**doc.metadata, "chunk_index": start}
                ))
                start += 1
        return chunked
```

- `range(0, len(words), self.chunk_size - self.chunk_overlap)` — **滑动窗口**。步长 = chunk_size - overlap。比如 chunk_size=100, overlap=20，则窗口每次前进 80 个词。
- `chunk_words = words[i:i + self.chunk_size]` — 取从 i 开始的 chunk_size 个词。
- `if len(chunk_words) < self.chunk_size * 0.3: break` — **尾部丢弃**。如果最后一块不到目标大小的 30%，直接丢弃（信息量太少）。
- `{**doc.metadata, "chunk_index": start}` — `**dict` 解包合并，保留原始 metadata 的同时添加 chunk_index。

> **`{**dict1, "key": val}` 语法：** 这是 Python 合并字典的语法。等价于先复制 dict1 再添加新字段。不会修改原字典。

## 重点总结

1. **词级分割（word-level），不是 token 级。** 中文是按空格分割的单个字/词，英文是按单词。实际生产环境用 tokenizer（如 `tiktoken`）计算更准确。
2. **滑动窗口机制：** 步长 = chunk_size - overlap，保证相邻块之间有重叠内容。
3. **尾部碎片丢弃：** 最后不足 30% 的碎片直接丢弃，防止过短的 chunk 引入噪音。

## 大厂面试可能问

- **Q: chunk_size 和 chunk_overlap 怎么选？** — chunk_size 取决于 embedding 模型的 max_seq_length（BGE-small 是 512 token，text-embedding-3-small 是 8191 token）。overlap 一般是 chunk_size 的 10%-25%。
- **Q: 为什么按词分而不是按字符分？** — embedding 模型以 token（词/子词）为单位，按词分更接近模型的处理粒度。按字符分会导致一个词被切到两个 chunk 里。
- **Q: 30% 这个阈值为什么这么定？** — 经验值。太小的 chunk 信息量不足，且 embedding 质量会下降。也可以改成 `chunk_size * 0.5` 更保守。
