# File: core/generator/deepseek_gen.py

## 作用

使用 DeepSeek API 生成回答。通过 OpenAI 兼容的 SDK 调用 DeepSeek 模型，封装了 API 调用细节。

## 完整代码（逐行讲解）

```python
from typing import List
from openai import OpenAI

from core.loader.base import Document
from core.generator.base import BaseGenerator

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
```

- `from openai import OpenAI` — DeepSeek API 完全兼容 OpenAI 的接口格式，所以可以用 OpenAI 的 Python SDK 来调用 DeepSeek。只需要换 `base_url` 和 `api_key`。
- `DEEPSEEK_BASE_URL` — 模块级常量，DeepSeek API 的入口地址。OpenAI 的默认地址是 `https://api.openai.com/v1`。

```python
class DeepSeekGenerator(BaseGenerator):

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        temperature: float = 0.3,
        base_url: str = DEEPSEEK_BASE_URL,
    ):
        self.model = model
        self.temperature = temperature
        self.client = OpenAI(api_key=api_key, base_url=base_url)
```

- `model: str = "deepseek-v4-flash"` — 默认使用 deepseek-v4-flash 模型（快速、经济）。
- `temperature: float = 0.3` — 温度系数，控制输出的随机性。0.3 相对较低，适合事实性问答（更确定、更专注）。如果要做创意写作可以调高到 0.7+。
- `self.client = OpenAI(api_key=api_key, base_url=base_url)` — 创建 OpenAI 客户端，但指向 DeepSeek 的 API 地址。这是"偷梁换柱"——用 OpenAI 的 SDK 调用 DeepSeek 的 API。

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

- `self._build_prompt(query, context_docs)` — 调用基类的 `_build_prompt` 方法构建 RAG prompt（包含 context 和 query）。
- `messages=[{"role": "user", "content": prompt}]` — DeepSeek 的 chat API 接受消息列表。这里只传了 user 消息，没有 system 消息（因为 prompt 模板已经包含了角色设定）。
- `resp.choices[0].message.content` — 解析 API 响应：`choices` 是返回的候选列表（通常只有 1 个），`message.content` 是模型生成的文本。

## 重点总结

1. **OpenAI 兼容 SDK：** DeepSeek 使用和 OpenAI 完全相同的 API 格式，只需要换 base_url 和 api_key。这降低了集成成本。
2. **低温度（0.3）：** RAG 问答场景下，希望 LLM 严格基于检索结果作答，低温度减少幻觉和随机发散。
3. **极简封装：** `_build_prompt` 在基类中完成，子类只需要组装 API 调用。

## 大厂面试可能问

- **Q: OpenAI SDK 怎么调用非 OpenAI 的 API？** — 核心在于 `base_url` 参数。OpenAI 的 `OpenAI(api_key=..., base_url=...)` 允许指定任意兼容 OpenAI 格式的 API 地址。DeepSeek、零一万物、百川、智谱等国内厂商都兼容 OpenAI 的 API 格式。

- **Q: temperature 的作用是什么？取值范围多少？** — temperature 控制输出概率分布的"尖锐程度"。0~2 之间（OpenAI 标准），0 表示每次都选概率最高的 token（确定性输出），1 表示按概率采样（适度随机），2 表示高度随机。RAG 问答一般用 0~0.3，追求事实性。

- **Q: 为什么 messages 只传了 user 角色，没有 system 角色？** — DeepSeek 支持 system 消息，但这里的 prompt 模板已经在开头设定了角色（"你是一个知识库问答助手"），不需要额外的 system 消息。如果未来需要更复杂的角色控制（比如安全限制、输出格式要求），可以改为 system + user 的消息结构。

- **Q: `resp.choices[0].message.content` 有可能为 None 吗？** — 有可能。如果 API 返回了内容过滤（content filter）触发，或者模型返回了空的 finish_reason，`content` 可能为 None。生产环境需要做 None 检查或提供默认值。



1. 不支持流式输出
前端聊天场景一般需要流式打字效果。
可以增加一个 stream_generate 方法，开启 stream=True。
2. 缺少异常捕获
网络波动、API 限额、key 错误、接口超时都会直接抛异常，建议增加 try-except。
3. 没有最大上下文长度限制
context_docs 太多，拼接后超长，触发模型截断，建议控制送入文档数量。
4. 仅单轮对话，无历史记忆
现在是纯单次 RAG 问答；如果做多轮对话，需要维护 messages 列表。
5. 缺少参数可控
没有暴露 max_tokens；可以加到构造函数或 generate 参数。