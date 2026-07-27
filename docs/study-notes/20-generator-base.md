# File: core/generator/base.py

## 作用

定义生成器的抽象接口 `BaseGenerator`。所有 LLM 生成器（DeepSeek、OpenAI）统一实现 `generate` 方法。基类中实现了 prompt 模板构建方法 `_build_prompt`。

## 完整代码（逐行讲解）

```python
from abc import ABC, abstractmethod
from typing import List

from core.loader.base import Document


class BaseGenerator(ABC):

    @abstractmethod
    def generate(self, query: str, context_docs: List[Document]) -> str:
        ...
```

- 输入：query + 检索到的上下文文档
- 输出：生成的回答字符串
- 为什么不返回结构化的东西？—— 因为 LLM 的返回值天然是字符串，上层代码需要什么格式可以在 prompt 中要求 LLM 输出 JSON。

```python
    def _build_prompt(self, query: str, context_docs: List[Document]) -> str:
        context = "\n\n".join([
            f"[来源: {d.metadata.get('source', 'unknown')}]\n{d.content}"
            for d in context_docs
        ])
        return f"""你是一个知识库问答助手。请根据以下提供的参考资料回答问题。
如果参考资料不足以回答问题，请如实说明。

参考资料：
{context}

问题：{query}

请基于参考资料给出准确的回答，并在回答中引用信息来源。"""
```

- `_build_prompt` — 以下划线开头表示"保护方法"（protected），约定只在子类内部使用（Python 没有真正的私有，只是约定）。
- `"\n\n".join([...])` — 把每个文档的内容用两个换行拼接起来，形成上下文文本块。
- `d.metadata.get('source', 'unknown')` — 从文档 metadata 中获取来源信息，如果没有则显示 "unknown"。
- **prompt 模板的核心设计：**
  1. **角色设定：** "你是一个知识库问答助手" — 给 LLM 一个明确的身份。
  2. **约束条件：** "如果参考资料不足以回答问题，请如实说明" — 防止 LLM 胡编乱造（幻觉）。
  3. **参考资料在前：** context 放在 query 前面，因为 LLM 对输入末尾的内容更关注（recency bias）。
  4. **引用来源：** "在回答中引用信息来源" — 让回答可追溯、可验证。

## 重点总结

1. **统一接口：** DeepSeek 和 OpenAI 生成器共享同一个基类，Pipeline 不关心具体是哪个 LLM。
2. **Prompt 模板在基类中实现：** 所有子类共享同一个 prompt 构建逻辑，不需要重复实现。
3. **RAG 的 prompt 设计关键：** 角色设定 + 约束条件 + 引用来源，这是 RAG 应用的标准 prompt 模式。

## 大厂面试可能问

- **Q: _build_prompt 为什么设计在基类而不是子类？** — 因为所有 LLM 生成器的 prompt 逻辑是相同的（都属于 RAG 问答场景）。放在基类中避免重复代码。如果未来某个 LLM 需要特殊的 prompt 格式（比如某些模型有 system/assistant 角色区分），子类可以覆盖（override）这个方法。

- **Q: context 放在 query 之前有什么讲究？** — LLM 有"近因偏差"（recency bias），对输入末尾的内容更敏感。把 context 放在前面、query 放在后面，可以让 LLM 更关注问题本身。但也有研究认为把最重要的信息放在开头和结尾效果最好（Lost in the Middle 现象）。

- **Q: 为什么 generate 返回 str 而不是完整的响应对象？** — 上层（Pipeline 或 API）只需要最终的文本答案。如果返回完整的 API 响应对象，就暴露了底层实现细节（是 DeepSeek 还是 OpenAI？），违反了依赖倒置原则。

- **Q: "请如实说明" 真的能防止幻觉吗？** — 不能完全防止，但能显著降低概率。防止幻觉需要多管齐下：①好的 prompt 约束；②高质量的检索结果；③Reranker 过滤低质量文档；④如果 LLM 评分服务可用，可以用 LLM-as-judge 做自动化评估。
