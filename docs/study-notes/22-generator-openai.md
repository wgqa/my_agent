# File: core/generator/openai_gen.py

## 作用

使用 OpenAI API 生成回答。和 DeepSeekGenerator 结构几乎相同，但支持自定义 base_url（可用于调用 OpenAI 官方或其他兼容服务）。

## 完整代码（逐行讲解）

```python
from typing import List, Optional
from openai import OpenAI

from core.loader.base import Document
from core.generator.base import BaseGenerator


class OpenAIGenerator(BaseGenerator):

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self.temperature = temperature
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
```

- `model: str = "gpt-4o-mini"` — 默认使用 gpt-4o-mini（经济高效，适合 RAG 场景）。
- `base_url: Optional[str] = None` — 可选参数。不传则使用 OpenAI 默认地址 `https://api.openai.com/v1`。传了可以指向任意兼容 OpenAI 格式的服务（如 Azure OpenAI、本地 vLLM 等）。
- `kwargs = {"api_key": api_key}` — 用字典动态构造参数。如果 base_url 不为空才加入 kwargs。
- `OpenAI(**kwargs)` — 字典解包，等价于 `OpenAI(api_key=api_key, base_url=base_url)`（如果 base_url 有值）或 `OpenAI(api_key=api_key)`（如果 base_url 为 None）。

**为什么不像 DeepSeekGenerator 那样直接用具名参数？** — 因为 DeepSeek 一定有固定的 base_url，而 OpenAI 的 base_url 是可选的（使用默认值）。用 **kwargs 是条件传参的惯用写法。

```python
    def generate(self, query: str, context_docs: List[Document]) -> str:
        prompt = self._build_prompt(query, context_docs)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
        )
        return resp.choices[0].message.content
```

- 和 DeepSeekGenerator 的 `generate` 方法**完全一样**。因为两个 API 兼容。

## 重点总结

1. **与 DeepSeekGenerator 对称设计：** 两个生成器结构几乎相同，只是默认模型和 base_url 不同。体现了"策略模式"——通过接口统一，实现可以互换。
2. **灵活的 base_url：** 支持任意 OpenAI 兼容服务，包括 Azure OpenAI、本地部署的 vLLM、Ollama 等。
3. ****kwargs 条件传参：** Python 中根据条件决定是否传入某个参数的常用技巧。

## 大厂面试可能问

- **Q: OpenAIGenerator 和 DeepSeekGenerator 代码几乎一样，为什么不合并成一个？** — 如果合并成一个 Generator，就需要在配置中同时管理两个 API 的认证信息、base_url、模型名。分开的好处：①职责清晰，每个类只负责一个 LLM 供应商；②如果某个供应商的 API 有特殊处理（比如流式输出、函数调用），不会互相影响；③符合"开闭原则"——对扩展开放，对修改关闭，新增供应商不需要改已有代码。

- **Q: `**kwargs` 在 Python 中什么作用？** — ①定义函数时：`def func(**kwargs)` 表示接收任意关键字参数，kwargs 是一个字典。②调用函数时：`func(**dict)` 表示将字典解包为关键字参数。等价于 `func(key1=value1, key2=value2)`。常用于条件传参和函数装饰器。

- **Q: OpenAI 的 base_url 什么场景下需要自定义？** — ①使用 Azure OpenAI 服务时（`https://{resource}.openai.azure.com`）；②使用 API 代理/网关（如 Cloudflare AI Gateway）；③使用本地部署的 LLM 服务（如 vLLM、Ollama、LocalAI）暴露的 OpenAI 兼容接口；④使用其他兼容 OpenAI 格式的 API 服务商（如智谱、月之暗面等）。

- **Q: gpt-4o-mini 和 deepseek-v4-flash 对比有什么优劣势？** — gpt-4o-mini：OpenAI 的经济模型，综合能力强，但价格比 DeepSeek 贵。deepseek-v4-flash：性价比极高，中文能力优秀，速度也快。实际选型取决于预算、延迟要求、语言偏好。
