import time
from typing import List

from openai import OpenAI
from openai import APITimeoutError, RateLimitError, AuthenticationError, APIStatusError

from core.loader.base import Document
from core.generator.base import BaseGenerator

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# 可重试的错误类型（429 / 5xx / 超时）
_RETRYABLE = (RateLimitError, APITimeoutError)


class DeepSeekGenerator(BaseGenerator):

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        temperature: float = 0.3,
        base_url: str = DEEPSEEK_BASE_URL,
        max_retries: int = 2,
        timeout_seconds: float = 60.0,
        **budget_kwargs,
    ):
        super().__init__(**budget_kwargs)
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,  # 我们自己控制重试，不用 SDK 默认
        )

    def generate(self, query: str, context_docs: List[Document]) -> str:
        # 发送前防御校验：只校验不截断（预算由 ContextAssembler 完成）
        self.validate_budget(query, context_docs)
        messages = self._build_messages(query, context_docs)
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_output_tokens,
                )
                return resp.choices[0].message.content
            except AuthenticationError as e:
                # 认证错误不重试
                return f"[GENERATOR_AUTH_ERROR] API key 无效"
            except APIStatusError as e:
                if e.status_code >= 500 and attempt < self.max_retries:
                    last_error = e
                    time.sleep(2 ** attempt)  # 指数退避: 1s, 2s
                    continue
                if e.status_code == 429 and attempt < self.max_retries:
                    last_error = e
                    time.sleep(2 ** attempt)
                    continue
                return f"[GENERATOR_UNAVAILABLE] HTTP {e.status_code}"
            except _RETRYABLE as e:
                if attempt < self.max_retries:
                    last_error = e
                    time.sleep(2 ** attempt)
                    continue
                return f"[GENERATOR_TIMEOUT] 请求超时"
            except Exception as e:
                return f"[生成失败: {type(e).__name__}] {str(e)[:300]}"

        return f"[生成失败: {type(last_error).__name__}]"
