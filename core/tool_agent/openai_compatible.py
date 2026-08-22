"""G4-AGENT-04：OpenAI-compatible Tool 决策 Provider。

单次模型调用：temperature=0 / max_tokens=600 / timeout=20s / max_retries=0。
api_key 只用于构造 SDK client，不保存在实例；Fake Client 通过 client 注入。
已知 Provider/超时异常映射为 ACTION_PROVIDER_ERROR / ACTION_TIMEOUT，未知
编程异常向上传播。本 Provider 只做单步 Decision，不执行 Tool、不把
Observation 喂回模型。
"""

from __future__ import annotations

import time
from typing import Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from core.tool_agent.action_parser import parse_agent_action_text
from core.tool_agent.actions import (
    ACTION_PROVIDER_ERROR,
    ACTION_TIMEOUT,
    AgentDecisionCallMetadata,
    AgentDecisionOutcome,
)
from core.tool_agent.decision_prompt import (
    DECISION_MAX_OUTPUT_TOKENS,
    DECISION_MAX_RETRIES,
    DECISION_TEMPERATURE,
    DECISION_TIMEOUT_SECONDS,
    DecisionPromptProfile,
    LEGACY_DECISION_PROMPT_PROFILE,
    compute_toolset_sha256,
)
from core.tool_agent.models import ACTION_PARSE_FAILED
from core.tool_agent.registry import ToolRegistry


class AgentDecisionTimeoutError(Exception):
    """项目私有超时异常：Fake Client 注入时使用（可被直接构造）。"""


class AgentDecisionProviderError(Exception):
    """项目私有 Provider 异常：Fake Client 注入时使用（可被直接构造）。"""


class _ProviderResponseError(Exception):
    """响应结构缺损：choices/message/content/usage 异常，映射 PROVIDER_ERROR。"""


def _validate_nonempty_str(value: object, label: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} 必须是字符串，实际 {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")
    if value != value.strip():
        raise ValueError(f"{label} 首尾不允许空白")


def _classify_provider_exception(exc: Exception) -> Optional[str]:
    if isinstance(exc, AgentDecisionTimeoutError):
        return ACTION_TIMEOUT
    if isinstance(exc, AgentDecisionProviderError):
        return ACTION_PROVIDER_ERROR
    if isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError):
        return ACTION_TIMEOUT
    if isinstance(
        exc,
        (AuthenticationError, RateLimitError, APIConnectionError, APIStatusError),
    ):
        return ACTION_PROVIDER_ERROR
    return None


# 只捕获明确列出的已知异常；RuntimeError/AttributeError 等程序错误不在其中，
# 会自然向上传播，不伪装成 Provider 不可用。
_KNOWN_PROVIDER_EXCEPTIONS = (
    AgentDecisionTimeoutError,
    AgentDecisionProviderError,
    APITimeoutError,
    TimeoutError,
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APIStatusError,
)


def _extract_content(response: object) -> str:
    """逐层检查 response 结构；任何缺损统一抛 _ProviderResponseError。"""
    try:
        choices = response.choices
    except AttributeError as exc:
        raise _ProviderResponseError("response.choices 缺失") from exc
    if not isinstance(choices, list):
        raise _ProviderResponseError("response.choices 必须是数组")
    if not choices:
        raise _ProviderResponseError("choices 为空")
    try:
        message = choices[0].message
    except AttributeError as exc:
        raise _ProviderResponseError("choice.message 缺失") from exc
    if message is None:
        raise _ProviderResponseError("choice.message 缺失")
    try:
        content = message.content
    except AttributeError as exc:
        raise _ProviderResponseError("message.content 缺失") from exc
    if type(content) is not str:
        raise _ProviderResponseError("message.content 非字符串")
    return content


def _extract_usage(response: object) -> tuple[Optional[int], Optional[int]]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    try:
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
    except AttributeError as exc:
        raise _ProviderResponseError("usage 字段缺损") from exc
    for label, value in (
        ("prompt_tokens", prompt_tokens),
        ("completion_tokens", completion_tokens),
    ):
        if type(value) is not int or isinstance(value, bool):
            raise _ProviderResponseError(f"usage.{label} 必须是非负严格 int")
        if value < 0:
            raise _ProviderResponseError(f"usage.{label} 必须非负")
    return prompt_tokens, completion_tokens


class OpenAICompatibleAgentDecisionProvider:
    """OpenAI-compatible 单次调用 Decision Provider。

    构造参数至少含 provider/model/api_key；base_url 可选；client 用于注入
    Fake Client（测试）。api_key 只用于构造 SDK client，不保存在 self 上。
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        client: Optional[object] = None,
        prompt_profile: Optional[DecisionPromptProfile] = None,
    ):
        _validate_nonempty_str(provider, "provider")
        _validate_nonempty_str(model, "model")
        _validate_nonempty_str(api_key, "api_key")
        if base_url is not None:
            _validate_nonempty_str(base_url, "base_url")
        self._provider = provider
        self._model = model
        self._base_url = base_url
        if prompt_profile is not None and not isinstance(
            prompt_profile, DecisionPromptProfile
        ):
            raise TypeError("prompt_profile 必须是 DecisionPromptProfile 或 None")
        self._prompt_profile = prompt_profile or LEGACY_DECISION_PROMPT_PROFILE
        self._client = (
            client if client is not None else self._build_default_client(api_key)
        )

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleAgentDecisionProvider(provider={self._provider!r}, "
            f"model={self._model!r}, base_url={self._base_url!r})"
        )

    def _build_default_client(self, api_key: str) -> OpenAI:
        kwargs = {
            "api_key": api_key,
            "timeout": DECISION_TIMEOUT_SECONDS,
            "max_retries": DECISION_MAX_RETRIES,
        }
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        return OpenAI(**kwargs)

    def decide(
        self,
        registry: ToolRegistry,
        user_query: str,
        *,
        context=(),
    ) -> AgentDecisionOutcome:
        """单步结构化决策：看见 ToolSpec + 用户请求（+ 可选 Observation context）。

        只调用一次 LLM；不执行任何 Tool；不把 Observation 喂回模型以外的
        任何东西。context 默认空，保持与 G4-AGENT-04 单步接口兼容。
        JSON mode（response_format）只保证"语法上是 JSON"，不替代
        Parser / Registry / JSON Schema 的语义约束。
        """
        tool_specs = registry.list_specs()
        toolset_sha256 = compute_toolset_sha256(tool_specs)
        messages = self._prompt_profile.build_messages(
            tool_specs, user_query, context=context
        )

        start = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=DECISION_TEMPERATURE,
                max_tokens=DECISION_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )
        except _KNOWN_PROVIDER_EXCEPTIONS as exc:
            failure_code = _classify_provider_exception(exc)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return AgentDecisionOutcome(
                action=None,
                failure_code=failure_code,
                call_metadata=self._build_metadata(latency_ms, toolset_sha256),
            )
        latency_ms = (time.perf_counter() - start) * 1000.0

        try:
            content = _extract_content(response)
            input_tokens, output_tokens = _extract_usage(response)
        except _ProviderResponseError:
            return AgentDecisionOutcome(
                action=None,
                failure_code=ACTION_PROVIDER_ERROR,
                call_metadata=self._build_metadata(latency_ms, toolset_sha256),
            )

        if content.strip() == "":
            return AgentDecisionOutcome(
                action=None,
                failure_code=ACTION_PARSE_FAILED,
                call_metadata=self._build_metadata(
                    latency_ms, toolset_sha256, input_tokens, output_tokens
                ),
            )

        action, failure_code = parse_agent_action_text(content, registry)
        return AgentDecisionOutcome(
            action=action,
            failure_code=failure_code,
            call_metadata=self._build_metadata(
                latency_ms, toolset_sha256, input_tokens, output_tokens
            ),
        )

    def _build_metadata(
        self,
        latency_ms: float,
        toolset_sha256: str,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> AgentDecisionCallMetadata:
        return AgentDecisionCallMetadata(
            provider=self._provider,
            model=self._model,
            prompt_version=self._prompt_profile.version,
            prompt_sha256=self._prompt_profile.sha256,
            toolset_sha256=toolset_sha256,
            call_count=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
