# File: core/embeddings/base.py

## 作用

定义 Embedding 模型的抽象接口 `BaseEmbedding`。所有 embedding 实现（OpenAI、BGE）都必须实现 `embed` 和 `embed_query` 两个方法。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from typing import List


class BaseEmbedding(ABC):

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        ...

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        ...
```

- `embed(self, texts: List[str]) -> List[List[float]]` — 批量编码文档文本，返回向量列表。输入是字符串列表，输出是浮点数向量的列表。每个向量的维度取决于模型（BGE-small 是 512 维，text-embedding-3-small 是 1536 维）。
- `embed_query(self, text: str) -> List[float]` — 编码单个查询文本，返回一个向量。单独拆分出这个方法是因为有些模型对 query 和 document 使用不同的 instruction（提示词）。

> **为什么要把 embed 和 embed_query 分开？** — 以 BGE 为例，它会对 document 加 "Represent this document for retrieval: " 前缀，对 query 加 "Represent this question for searching: " 前缀。分开可以支持这种差异。

## 重点总结

1. **两个方法分工明确：** `embed` 批量编码文档，`embed_query` 编码单条查询。
2. **接口抽象的意义：** 上层代码（Retriever、Pipeline）只依赖 `BaseEmbedding`，不需要知道底层用的是 OpenAI 还是 BGE。

## 大厂面试可能问

- **Q: 为什么 `embed_query` 单独存在而不是直接复用 `embed([text])[0]`？** — 因为有些模型对 query 和 document 使用不同的 instruction。`embed_query` 给子类提供了定制化的机会。

- **Q: embedding 维度对检索有什么影响？** — 维度越高，表达能力越强，但计算成本越大、存储空间越大。BGE-small-zh 是 512 维，OpenAI text-embedding-3-small 是 1536 维。高维向量在 HNSW 索引中的搜索速度也受维度影响（"维度诅咒"）。
