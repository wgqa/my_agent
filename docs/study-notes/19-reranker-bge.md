# File: core/reranker/bge_reranker.py

## 作用

使用 BGE Reranker（BAAI/bge-reranker-v2-m3）对候选文档进行精细化重排序。这是一个交叉编码器（CrossEncoder）模型，比向量检索（双编码器）更精确但更慢。

## 完整代码（逐行讲解）

```python
from typing import List

from core.loader.base import Document
from core.reranker.base import BaseReranker


class BGEReranker(BaseReranker):

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self._model = None
```

- `model_name` — 使用的模型。bge-reranker-v2-m3 是 BAAI 开源的多语言重排序模型，支持 100+ 语言。
- `_model = None` — 模型初始为 None，真正使用时才加载（延迟加载/懒加载）。

```python
    def _lazy_load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
```

- **延迟加载：** 只在第一次调用 rerank 时才加载模型。好处：①创建 BGEReranker 对象时不耗时；②如果永远没调用 rerank（比如只用向量检索），就不浪费内存加载模型。
- `CrossEncoder` — sentence-transformers 库中的交叉编码器。和"双编码器（Bi-Encoder）"的区别：
  - 双编码器（如 BGE Embedding）：query 和 doc 各自编码成向量，余弦相似度比较。速度快，可以预计算文档向量。
  - 交叉编码器：query 和 doc 拼接后一起输入 Transformer，得到直接的匹配分数。更精确，但不能预计算（每对都要重新算）。

```python
    def rerank(self, query: str, documents: List[Document], top_k: int = 5) -> List[Document]:
        if not documents:
            return []

        self._lazy_load()
        pairs = [[query, d.content] for d in documents]
        scores = self._model.predict(pairs)
```

- `if not documents: return []` — 边界条件：空的候选列表直接返回空。
- `pairs = [[query, d.content] for d in documents]` — 把 query 和每个文档拼接成 pair。列表推导式，等价于：
  ```python
  pairs = []
  for d in documents:
      pairs.append([query, d.content])
  ```
- `self._model.predict(pairs)` — CrossEncoder 的 predict 接收 `[[q1, d1], [q2, d2], ...]` 格式，返回每个 pair 的相关性分数列表。

```python
        scored = list(zip(scores, documents))
        scored.sort(key=lambda x: x[0], reverse=True)

        return [doc for _, doc in scored[:top_k]]
```

- `list(zip(scores, documents))` — 把分数和文档一一配对。`zip` 返回迭代器，`list` 将其转换为 `[(score1, doc1), (score2, doc2), ...]` 列表。
- `scored.sort(key=lambda x: x[0], reverse=True)` — 按分数降序排列。`lambda x: x[0]` 取出 tuple 的第一个元素（score）作为排序键。
- `[doc for _, doc in scored[:top_k]]` — 取前 top_k 个结果，只保留 Document 对象，丢弃分数。`_` 是 Python 惯例，表示"不需要这个值"。

## 重点总结

1. **延迟加载：** CrossEncoder 模型几百 MB，只有在真正使用的时候才加载，初始化不耗时。
2. **交叉编码器：** 比双编码器（向量检索）更精确，但 O(N) 复杂度，适合做精排（重排序）而不是召回。
3. **简单接口：** query + 候选列表 → predict 打分 → 排序 → 取 top_k。

## 大厂面试可能问

- **Q: 交叉编码器和双编码器的区别和应用场景？** — 双编码器把 query 和 doc 分别编码为向量，适合召回阶段（海量候选，可预计算向量）。交叉编码器把 query 和 doc 拼接后一起编码，适合精排阶段（少量候选，每对都要算）。双编码器快但精度低，交叉编码器慢但精度高。

- **Q: CrossEncoder 的 predict 返回什么？** — 返回一个 numpy 数组，每个元素是 [0,1] 之间的分数，表示 query 和对应文档的相关性。1 表示高度相关，0 表示不相关。

- **Q: 为什么用 `_lazy_load` 而不是在 `__init__` 里直接加载模型？** — ①Pipeline 初始化时会创建所有组件，如果 BGEReranker 初始化就要加载模型，Pipeline 的启动速度会变慢；②有些场景可能只索引不查询，或者不使用 Reranker（降级为 try/except），延迟加载避免了不必要的模型加载。

- **Q: BGE Reranker 有几种模型版本？** — 常见的有 bge-reranker-base（基础版）、bge-reranker-large（大模型版）、bge-reranker-v2-m3（多语言版）。v2-m3 是目前 BAAI 推荐的多语言版本，平衡了性能和效果。
