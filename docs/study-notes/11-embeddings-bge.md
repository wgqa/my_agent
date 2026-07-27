# File: core/embeddings/bge_emb.py

## 作用

封装本地的 BGE（BAAI General Embedding）模型，通过 sentence-transformers 库在本地运行 embedding，不需要调用外部 API。

## 完整代码（逐行讲解）

```python
from typing import List

from core.embeddings.base import BaseEmbedding


class BGEEmbedding(BaseEmbedding):
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        self.model_name = model_name
        self._model = None
```

- `_model = None` — 延迟加载的模型实例。初始为 None，第一次使用时才加载。
- 下划线前缀 `_` 表示"内部使用，外部不应访问"（Python 惯例）。不是真正的 private（Python 没有 Java 的 `private` 关键字），只是一个约定。

```python
    def _lazy_load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
```

- **延迟加载（Lazy Loading）：** 模型只在第一次 `embed` 调用时才加载，而不是在 `__init__` 时加载。好处：①构造对象很快，不需要等模型下载；②如果不做 embedding（比如只用 BM25），就不需要加载模型。
- `from sentence_transformers import SentenceTransformer` 写在方法体内部而不是文件顶部。这是 Python 的**延迟导入**，只有实际用到时才导入。可以避免启动时未安装 sentence-transformers 导致报错。

```python
    def embed(self, texts: List[str]) -> List[List[float]]:
        self._lazy_load()
        return self._model.encode(texts, normalize_embeddings=True).tolist()
```

- `encode(texts, normalize_embeddings=True)` — 把文本列表编码为向量。`normalize_embeddings=True` 对向量做 L2 归一化（长度变为 1），这样余弦相似度等价于点积，计算更快。
- `.tolist()` — NumPy 数组转 Python 列表，确保返回类型是 `List[List[float]]`。

```python
    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]
```

## 重点总结

1. **延迟加载模式：** 模型在第一次使用时加载，不是构造时加载。这是资源敏感型应用的常见模式。
2. **本地运行：** BGE 模型完全本地运行，不需要网络和 API key，数据不会离开你的机器。
3. **归一化：** `normalize_embeddings=True` 让向量的 L2 范数为 1，余弦相似度 = 点积，计算更快。

## 大厂面试可能问

- **Q: BGE 和 OpenAI Embedding 有什么区别？** — BGE：本地运行、免费、数据隐私好、但精度略低（尤其是中文外的语言）。OpenAI：云端 API、精度高、但需要付费且有数据隐私问题。

- **Q: BGE 模型系列有哪些？如何选择？** — BGE-small-zh（512 维，轻量快速）、BGE-base-zh（768 维，均衡）、BGE-large-zh（1024 维，精度最高但最慢）。日常实验用 small，生产上线用 base 或 large。

- **Q: 为什么 `_lazy_load` 中的 import 写在方法内部？** — 这叫"延迟导入"（lazy import），避免因未安装 sentence-transformers 而影响其他功能（比如只用 OpenAI embedding 时）。

- **Q: `normalize_embeddings=True` 的作用？** — 向量归一化后长度为 1，余弦相似度公式 `a·b / (|a|×|b|)` 就变成了 `a·b`（因为分母是 1×1=1）。在向量库（如 Chroma）中如果距离函数设为 cosine，归一化后的向量可以使搜索更快。
