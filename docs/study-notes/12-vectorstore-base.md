# File: core/vector_store/base.py

## 作用

定义向量存储的抽象接口 `BaseVectorStore`，提供增（add）、查（search）、删（delete）、计数（count）四个核心操作。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from typing import List, Optional

from core.loader.base import Document


class BaseVectorStore(ABC):

    @abstractmethod
    def add(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        ...
```

- 接收文档列表和对应的向量列表，返回生成的 ID 列表。
- 文档和向量分开传入，因为 embedding 已经由 Embedding 模块算好了，VectorStore 只负责存储和索引。

```python
    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Document]:
        ...
```

- 接收查询向量，返回最相似的 top_k 个文档。注意是单条 query 向量，不是批量。

```python
    @abstractmethod
    def delete(self, ids: List[str]):
        ...

    @abstractmethod
    def count(self) -> int:
        ...
```

- `delete` 按 ID 列表删除文档。
- `count` 返回文档总数，用于监控和测试。

## 重点总结

1. **四个核心操作：** add（增）、search（查）、delete（删）、count（计数）。这是向量存储的最小 CRUD 接口。
2. **文档和向量分离：** add 时文档和向量分开传入，因为向量的计算（embedding）是 Embedding 模块的职责。
3. **接口抽象：** 当前实现是 ChromaDB，但接口设计可以对接 Faiss、Pinecone、Weaviate 等任何向量数据库。

## 大厂面试可能问

- **Q: 为什么不在 VectorStore 内部做 embedding？** — 单一职责原则。VectorStore 负责"存和查"，Embedding 负责"文本转向量"。分开使得可以任意组合不同的 embedding 和 vector store。

- **Q: `search` 为什么只接受单条 query 而不是批量？** — RAG 场景每次只处理一个问题（单条 query）。如果需要批量评估，可以在上层循环调用。
