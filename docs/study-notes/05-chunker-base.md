# File: core/chunker/base.py

## 作用

定义 Chunker（文本分块器）的抽象接口 `BaseChunker`。所有分块策略（FixedSize、Recursive、Semantic）都继承这个接口，保证上层代码可以统一调用。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseChunker(ABC):

    @abstractmethod
    def chunk(self, documents: List[Document]) -> List[Document]:
        ...
```

**设计要点：**
- 输入 `List[Document]` — 从 Loader 加载出来的文档列表
- 输出 `List[Document]` — 分块后的文档列表，每个 Document 包含一段文本
- `@abstractmethod` 强制子类实现

> **为什么输入输出都是 `List[Document]`？** 因为 Document 是整个系统的数据传递格式。Loader 返回 Document 列表，Chunker 接收并返回 Document 列表（metadata 会继承原始信息并添加 `chunk_index`）。

## 重点总结

1. **接口统一性：** 所有 chunker 接收相同输入，返回相同输出，上层 Pipeline 代码不需要关心具体策略。
2. **Document 传递：** metadata 在分块过程中会保留并扩展（追加 `chunk_index`），保证来源可追溯。

## 大厂面试可能问

- **Q: 为什么分块是单独一个模块而不是合并在 Loader 里？** — 单一职责原则。Loader 负责"从文件读内容"，Chunker 负责"把长文本切成短块"。两者可以独立替换（不同的 loader × 不同的 chunker 组合）。
