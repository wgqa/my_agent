# File: core/retriever/simple.py

## 作用

最基础的向量检索器：将 query 编码为向量 → 在向量库中搜索最近邻 → 返回结果。没有额外的处理逻辑。

## 完整代码（逐行讲解）

```python
from typing import List

from core.loader.base import Document
from core.retriever.base import BaseRetriever
from core.embeddings.base import BaseEmbedding
from core.vector_store.base import BaseVectorStore


class SimpleRetriever(BaseRetriever):

    def __init__(self, embedding: BaseEmbedding, vector_store: BaseVectorStore):
        self.embedding = embedding
        self.vector_store = vector_store
```

- 依赖 `BaseEmbedding` 和 `BaseVectorStore` 接口（不是具体实现）。这就是**依赖倒置原则**。

```python
    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        query_vec = self.embedding.embed_query(query)
        return self.vector_store.search(query_vec, top_k=top_k)
```

- 三行代码完成检索。这是最纯粹的"向量检索"—— query → 向量 → 搜索。

## 重点总结

1. **极致简单：** embed_query → search，没有中间步骤。
2. **依赖注入：** embedding 和 vector_store 通过构造方法注入，不自己创建。

## 大厂面试可能问

- **Q: SimpleRetriever 的缺陷？** — ①没有多样性控制（top_k 个结果可能高度相似）；②只依赖语义相似度，不依赖关键词匹配，对专有名词（如 "BM25"）的检索效果可能不好。

- **Q: 什么场景用 SimpleRetriever？** — 数据量不大、查询比较明确、需要低延迟的场景。比如 QA 对匹配、FAQ 检索。
