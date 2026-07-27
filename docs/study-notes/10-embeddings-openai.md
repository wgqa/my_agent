# File: core/embeddings/openai_emb.py

## 作用

封装 OpenAI Embedding API（兼容 DeepSeek 等第三方 API），用于将文本转换为向量。

## 完整代码（逐行讲解）

```python
from typing import List
from openai import OpenAI

from core.embeddings.base import BaseEmbedding


class OpenAIEmbedding(BaseEmbedding):
    def __init__(self, model: str = "text-embedding-3-small", api_key: str = None, base_url: str = None):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)
```

- `OpenAI(api_key=api_key, base_url=base_url)` — 使用 OpenAI Python SDK。`base_url` 参数是关键：传 None 时使用 OpenAI 官方地址；传 `"https://api.deepseek.com/v1"` 时调用 DeepSeek 的 embedding API（DeepSeek 兼容 OpenAI 接口格式）。

```python
    def embed(self, texts: List[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in resp.data]
```

- `self.client.embeddings.create(...)` — 调用 embedding API。
- `resp.data` — 返回的数据列表，每个 item 包含 `embedding` 字段。
- `[item.embedding for item in resp.data]` — 列表推导式，提取每个文本的向量。

```python
    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]
```

- 封装单个查询：把 query 包装成列表调 `embed`，取第一个结果。

## 重点总结

1. **Base URL 是关键：** 换 base_url 就可以切换不同的 API 提供商。OpenAI、DeepSeek、智谱等都兼容。
2. **batch 编码：** `embed` 通过 API 的批量接口一次编码多个文本，比逐个调用更高效。
3. **embed_query 复用 embed：** OpenAI 不区分 query/document instruction，所以直接复用。

## 大厂面试可能问

- **Q: API 调用失败怎么办？** — 当前代码没有错误处理和重试机制。生产环境应该加 `try/except` 和指数退避重试（exponential backoff）。

- **Q: API key 怎么管理？** — 应该从环境变量读取而不是硬编码。可以通过 `os.getenv("OPENAI_API_KEY")` 读取。
