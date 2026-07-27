# File: core/chunker/semantic.py

## 作用

通过句子 embedding 的余弦相似度变化来检测语义边界，在"话题转变"的地方分块。比 FixedSize 和 Recursive 更智能，但需要 embedding 模型支持。

## 完整代码（逐行讲解）

```python
from typing import List, Optional
import numpy as np

from core.loader.base import Document
from core.chunker.base import BaseChunker


class SemanticChunker(BaseChunker):
    """基于句子 embedding 相似度变化进行语义分割"""

    def __init__(
        self,
        embedding_fn=None,
        threshold: float = 0.7,
        min_chunk_len: int = 50,
        max_chunk_len: int = 1000,
    ):
        self.embedding_fn = embedding_fn
        self.threshold = threshold
        self.min_chunk_len = min_chunk_len
        self.max_chunk_len = max_chunk_len
```

- `embedding_fn=None` — 外部传入的 embedding 函数。接收句子列表，返回向量列表。
- `threshold=0.7` — 相似度阈值。低于这个值表示"话题变了"，在此处分块。
- `min_chunk_len=50` — 合并过短的 chunk，防止出现只有一句话的碎片。
- `max_chunk_len=1000` — 如果 chunk 超过此长度强制拆分（防止失控）。

---

```python
    def _split_sentences(self, text: str) -> List[str]:
        import re
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        return [s.strip() for s in sentences if s.strip()]
```

- 用正则按句号/感叹号/问号分割句子。
- `(?<=[。！？.!?])` — **正向后顾**（lookbehind）。匹配在句号之后、可选空白之前的位置。这样分割时**保留句号**在句子末尾。
- `if s.strip()` — 过滤空句子。

---

```python
    def chunk(self, documents: List[Document]) -> List[Document]:
        if self.embedding_fn is None:
            from core.chunker.recursive import RecursiveChunker
            return RecursiveChunker().chunk(documents)
```

**退化策略：** 如果没有提供 embedding_fn（比如用户不想额外调 API），自动降级为 RecursiveChunker。保证不会因为配置不当而报错。

```python
        chunked = []
        for doc in documents:
            sentences = self._split_sentences(doc.content)
            if len(sentences) <= 1:
                chunked.append(doc)
                continue

            embeddings = self.embedding_fn(sentences)
            groups = self._group_sentences(sentences, embeddings)
```

- 对每句编码 embedding，然后调用 `_group_sentences` 进行语义分组。
- `if len(sentences) <= 1` — 只有一个句子就不用分块了。

---

**`_group_sentences` 方法：**

```python
    def _group_sentences(self, sentences: List[str], embeddings: List[List[float]]) -> List[List[str]]:
        groups = [[sentences[0]]]
        for i in range(1, len(sentences)):
            sim = self._cosine_sim(embeddings[i - 1], embeddings[i])
            if sim < self.threshold:
                groups.append([])
            groups[-1].append(sentences[i])
```

**核心逻辑：** 遍历句子，计算相邻句子的余弦相似度。如果相似度低于阈值，说明话题变了，在此处开一个新的组。

- `groups = [[sentences[0]]]` — 第一个句子单独成组。
- `groups[-1].append(sentences[i])` — `groups[-1]` 是最后一个组（最新组），把当前句子加进去。

---

```python
        merged = []
        for group in groups:
            merged_text = "".join(group)
            if merged and len(merged[-1]) < self.min_chunk_len:
                merged[-1].extend(group)
            elif len(merged_text) > self.max_chunk_len:
                merged.append(group)
            else:
                merged.append(group)
        return merged
```

**后处理合并：** 如果前一个 chunk 太短（< min_chunk_len），把当前组合并到前一个 chunk 中。避免出现只有一句话的碎片。

---

**`_cosine_sim` 方法：**

```python
    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        a_arr = np.array(a)
        b_arr = np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
```

余弦相似度 = 点积 / (向量长度的乘积 + 极小值)。`1e-10` 防止除零。

## 重点总结

1. **阈值是关键超参数：** threshold=0.7 表示相邻句子相似度低于 0.7 就认为话题转变。阈值越高，分块越多（更敏感）。
2. **自动降级：** 没有 embedding_fn 时退化为 RecursiveChunker，保证系统可用。
3. **缺陷：** ①每句都要算 embedding，速度慢；②中文句号分割可能不准确；③threshold 需要针对语料调参。

## 大厂面试可能问

- **Q: SemanticChunker 比 RecursiveChunker 好在哪？** — Semantic 能检测到"话题转变"（比如文档从"介绍"到"原理"的边界），而 Recursive 只能按固定分隔符切。Semantic 的块内容更内聚。

- **Q: 为什么 threshold=0.7 这个值？** — 经验值。太高（0.9）会导致过于敏感，每个句子都成一个块。太低（0.3）会导致几乎不分割。0.7 在大部分场景表现良好。

- **Q: 性能问题怎么解决？** — 每条句子都要调 embedding_fn，如果 embedding 是 API 调用（如 OpenAI），费用和延迟都很高。生产环境建议用本地 BGE 模型。或者先用 RecursiveChunker 粗切，再对边界附近的句子做语义检测。

- **Q: 这个算法的缺陷？** — 只能检测"相邻句子之间的"话题转变。如果文档结构是 A-B-A-B（话题来回切换），效果不好。


还是没有重叠部分是吧
每次循环反复拼接字符串、重复统计 token；
优化：缓存每组实时 token 数量，不要每次 join 重新计算。
缺陷 4：边界 case
如果单句本身 token 长度 > max_chunk_len，代码没有处理，会生成超上限 chunk。
需要提前对超长单句做兜底硬切。