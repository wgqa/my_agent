# File: core/reranker/base.py

## 作用

定义重排序器的抽象接口 `BaseReranker`。所有重排序策略统一实现 `rerank` 方法。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseReranker(ABC):

    @abstractmethod
    def rerank(self, query: str, documents: List[Document], top_k: int = 5) -> List[Document]:
        ...
```

- `BaseReranker(ABC)` — 继承 `ABC`（Abstract Base Class），标记为抽象类，不能直接实例化。
- `@abstractmethod` — 装饰器，强制子类实现该方法。子类不实现会报 `TypeError: Can't instantiate abstract class ... with abstract methods ...`。
- 输入：query 字符串 + 候选 Document 列表 + 返回数量
- 输出：重新排序后的 Document 列表（top_k 个）
- 和 Retriever 的 `retrieve` 签名很像，区别在于：retrieve 从向量库搜索，rerank 从已有的候选列表重新排序。

## 重点总结

1. **统一接口：** 无论哪种重排序策略，上层代码（Pipeline）都通过 `rerank(query, documents, top_k)` 调用。
2. **Retriever vs Reranker：** Retriever 是"召回阶段"（海量文档→候选集），Reranker 是"精排阶段"（候选集→更精确的排序）。Reranker 通常使用更精细（也更慢）的模型。

## 大厂面试可能问

- **Q: Retriever 和 Reranker 有什么区别？** — Retriever 负责从大量文档中快速召回候选（如向量检索、BM25），追求高召回率和高速度。Reranker 对候选集做精细化排序，使用更复杂的模型（如交叉编码器 CrossEncoder），追求高精确率。典型的级联架构：Retriever（百→十）→ Reranker（十→五）。

- **Q: 为什么不在 Retriever 里直接排序好？** — 计算成本。向量检索可以用近似最近邻（HNSW）在百万级数据上毫秒级返回。而 Reranker（如 BGE Reranker）对每一对 query-document 都要做一次完整的 Transformer 前向计算，复杂度 O(N) 不可近似，适合对小规模候选集做精排。
