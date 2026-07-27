# File: core/vector_store/chroma_store.py

## 作用

使用 ChromaDB 实现向量存储。支持持久化（PersistentClient）和内存模式（in-memory），封装了 ChromaDB 的增删查操作。

## 完整代码（逐行讲解）

```python
from typing import List, Optional
import chromadb
from chromadb.config import Settings

from core.loader.base import Document
from core.vector_store.base import BaseVectorStore


class ChromaStore(BaseVectorStore):
    def __init__(self, path: str = "./data/vector_store", collection_name: str = "documents"):
        self.client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
```

- `path` — 持久化路径。设为 `None` 时使用内存模式（`chromadb.Client()`），适合测试。
- `Settings(anonymized_telemetry=False)` — 关闭 Chroma 的匿名遥测。
- `get_or_create_collection` — 集合不存在则创建，存在则获取。保证重复创建不会报错。
- `metadata={"hnsw:space": "cosine"}` — 指定距离函数为余弦距离。HNSW 是高性能的近似最近邻算法。

---

```python
    def add(self, documents: List[Document], embeddings: List[List[float]]) -> List[str]:
        ids = [f"doc_{i}" for i in range(
            self.collection.count(),
            self.collection.count() + len(documents)
        )]
        metadatas = [d.metadata for d in documents]
        texts = [d.content for d in documents]

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,
        )
        return ids
```

- ID 生成策略：基于当前文档数自增。`f"doc_{i}"` 是 f-string 语法，等价于 `"doc_" + str(i)`。
- `metadatas` — 注意这里直接将 Document 的 metadata 传入。ChromaDB 会验证 metadata 的格式。
- ChromaDB 的 `add` 同时接收 ids、embeddings、metadatas、documents 四个列表。

> **ChromaDB 的坑：** 如果 `metadatas` 中的某个字典是空 `{}`，Chroma 会抛出 `ValueError: Expected metadata to be a non-empty dict`。需要把空 dict 转成 `None`。

---

```python
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Document]:
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        docs = []
        if results["documents"]:
            for i, doc_text in enumerate(results["documents"][0]):
                docs.append(Document(
                    content=doc_text,
                    metadata={
                        **(results["metadatas"][0][i] if results["metadatas"] else {}),
                        "id": results["ids"][0][i] if results["ids"] else "",
                        "distance": results["distances"][0][i] if results["distances"] else 0.0,
                    }
                ))
        return docs
```

- `query_embeddings=[query_embedding]` — Chroma 接受 embedding 列表（批量查询），这里把单条 query 包装成列表。
- Chroma 返回结果的格式：`results["documents"][0][i]` 是第 i 个结果的文本。
- metadata 合并：把 Chroma 返回的原始 metadata、id、distance 合并到 Document 的 metadata 中。

---

```python
    def delete(self, ids: List[str]):
        self.collection.delete(ids=ids)

    def count(self) -> int:
        return self.collection.count()
```

- `delete` 按 ID 列表删除。
- `count` 返回集合中的文档总数。

## 重点总结

1. **两种模式：** `path=None` 时用 `chromadb.Client()`（内存模式，测试用，不持久化）。`path="..."` 时用 `PersistentClient`（数据持久化到磁盘）。
2. **HNSW 算法：** Chroma 底层使用 HNSW（Hierarchical Navigable Small World）算法做近似最近邻搜索，速度快，支持百万级向量。
3. **空 metadata 陷阱：** ChromaDB 不接受空字典作为 metadata。生产环境需要做 `d.metadata if d.metadata else None` 的转换。

## 大厂面试可能问

- **Q: ChromaDB 和 Faiss 有什么不同？** — Faiss 是 Meta 开源的向量搜索库，只做向量搜索，不管理文档。ChromaDB 是一个完整的向量数据库，管理文档、元数据和向量，支持持久化。

- **Q: 为什么用 `get_or_create_collection` 而不是 `create_collection`？** — 幂等性。`create_collection` 在集合已存在时会报错。`get_or_create_collection` 无论执行多少次都安全。

- **Q: 向量库中的 distance 是什么？** — 当前配置使用的是 cosine distance（余弦距离），范围 [0, 2]。0 表示完全相同，2 表示完全相反。实际使用时还要看 embedding 是否归一化。
