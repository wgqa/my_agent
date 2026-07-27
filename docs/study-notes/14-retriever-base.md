# File: core/retriever/base.py

## 作用

定义检索器的抽象接口 `BaseRetriever`。所有检索策略（Simple、MMR、Hybrid）统一实现 `retrieve` 方法。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseRetriever(ABC):

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        ...
```

- 输入：查询字符串 + 返回数量
- 输出：Document 列表
- `top_k` 默认 5

## 重点总结

1. **统一接口：** 无论哪种检索策略，上层代码（Pipeline）都通过 `retrieve(query, top_k)` 调用。
2. **返回 Document：** 检索结果包含全文和 metadata，可供后续 Reranker 和 Generator 使用。

## 大厂面试可能问

- **Q: 为什么 retrieve 返回的是 Document 而不是 ID？** — 因为后续步骤（Reranker、Generator）需要完整的文本内容，如果只返回 ID 还需要额外查询一次。
