from typing import List
from openai import OpenAI

from core.loader.base import Document
from core.generator.base import BaseGenerator

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


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

    def generate(self, query: str, context_docs: List[Document]) -> str:
        prompt = self._build_prompt(query, context_docs)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"[生成失败: {type(e).__name__}] {str(e)[:300]}"
