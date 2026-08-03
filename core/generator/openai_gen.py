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
        timeout_seconds: float = 60.0,
    ):
        self.model = model
        self.temperature = temperature
        kwargs = {"api_key": api_key, "timeout": timeout_seconds}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def generate(self, query: str, context_docs: List[Document]) -> str:
        messages = self._build_messages(query, context_docs)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=800,
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"[生成失败: {type(e).__name__}] {str(e)[:300]}"
