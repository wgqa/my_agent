import time
from typing import List

from openai import OpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from core.loader.base import Document
from core.generator.base import BaseGenerator
from core.generator.errors import (
    GeneratorAuthenticationError,
    GeneratorTimeoutError,
    GeneratorUnavailableError,
    extract_response_content,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

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
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_output_tokens,
                )
                return extract_response_content(resp)
            except AuthenticationError:
                # Authentication failure is deterministic; never retry it.
                raise GeneratorAuthenticationError from None
            except APITimeoutError:
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)  # 指数退避: 1s, 2s
                    continue
                raise GeneratorTimeoutError from None
            except RateLimitError:
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise GeneratorUnavailableError from None
            except APIStatusError as error:
                if (
                    (error.status_code >= 500 or error.status_code == 429)
                    and attempt < self.max_retries
                ):
                    time.sleep(2 ** attempt)
                    continue
                raise GeneratorUnavailableError from None
            except APIConnectionError:
                raise GeneratorUnavailableError from None

        # The loop always returns or raises. Keep a defensive typed failure if
        # a future retry policy changes that invariant.
        raise GeneratorUnavailableError from None
