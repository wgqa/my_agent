"""G3-DECOMP-04B-01：OpenAI-compatible Planner Provider。

实现 BaseQueryPlanner 的真实 Provider 子类：单次模型调用、固定
temperature/max_tokens/timeout/retries、已知异常映射 fallback、
PlannerCallMetadata 附加。生产默认使用 openai SDK；测试通过 client
参数注入 Fake Client（不进入生产默认路径）。不读取环境变量，
不暴露 api_key，不调用第二次模型。
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

from core.query_planning.models import build_fallback_query_plan
from core.query_planning.planner import (
    BaseQueryPlanner,
    PlannerCallMetadata,
    PlannerOutcome,
    build_planner_fallback_outcome,
    parse_planner_output,
)
from core.query_planning.prompt import (
    PLANNER_MAX_OUTPUT_TOKENS,
    PLANNER_MAX_RETRIES,
    PLANNER_PROMPT_SHA256,
    PLANNER_PROMPT_VERSION,
    PLANNER_TEMPERATURE,
    PLANNER_TIMEOUT_SECONDS,
    build_planner_messages,
)


class PlannerTimeoutError(Exception):
    """项目私有超时异常：Fake Client 注入时使用（可被直接构造）。"""


class PlannerProviderError(Exception):
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
    """把已知 Provider/超时异常映射为失败代码；未知异常返回 None。

    同时识别项目私有异常（Fake 用）与真实 openai SDK 异常（映射分支由
    真实 SDK 异常构造测试证明）。
    """
    if isinstance(exc, PlannerTimeoutError):
        return "PLANNER_TIMEOUT"
    if isinstance(exc, PlannerProviderError):
        return "PLANNER_PROVIDER_ERROR"
    if isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError):
        return "PLANNER_TIMEOUT"
    if isinstance(
        exc,
        (AuthenticationError, RateLimitError, APIConnectionError, APIStatusError),
    ):
        return "PLANNER_PROVIDER_ERROR"
    return None


# 只捕获明确列出的已知异常；RuntimeError/AttributeError/程序错误不在其中，
# 会自然向上传播，不会伪装成 Provider 不可用。
_KNOWN_PROVIDER_EXCEPTIONS = (
    PlannerTimeoutError,
    PlannerProviderError,
    APITimeoutError,
    TimeoutError,
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APIStatusError,
)


def _extract_content(response: object) -> str:
    """逐层检查 response 结构；任何缺损统一抛 _ProviderResponseError。

    只对“属性访问缺失”捕获 AttributeError；不宽泛捕获整个函数。若
    content 属性内部主动抛出 RuntimeError 等未知编程错误，则向上传播。
    """
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


class OpenAICompatibleQueryPlanner(BaseQueryPlanner):
    """OpenAI-compatible 单次调用 Planner Provider。

    构造参数至少含 provider/model/api_key；base_url 可选；client 用于注入
    Fake Client（测试），为 None 时生产默认构造 openai SDK client。
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        client: Optional[object] = None,
    ):
        _validate_nonempty_str(provider, "provider")
        _validate_nonempty_str(model, "model")
        _validate_nonempty_str(api_key, "api_key")
        if base_url is not None:
            _validate_nonempty_str(base_url, "base_url")
        self._provider = provider
        self._model = model
        self._base_url = base_url
        # api_key 不保存在 self 上（repr/异常不会泄漏）；Fake Client 注入时
        # 直接使用，不进入生产默认路径。
        self._client = (
            client if client is not None else self._build_default_client(api_key)
        )

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleQueryPlanner(provider={self._provider!r}, "
            f"model={self._model!r}, base_url={self._base_url!r})"
        )

    def _build_default_client(self, api_key: str) -> OpenAI:
        kwargs = {
            "api_key": api_key,
            "timeout": PLANNER_TIMEOUT_SECONDS,
            "max_retries": PLANNER_MAX_RETRIES,
        }
        if self._base_url is not None:
            kwargs["base_url"] = self._base_url
        return OpenAI(**kwargs)

    def plan(self, original_query: str) -> PlannerOutcome:
        # 调用模型之前先验证 original_query：复用 fallback factory 的校验，
        # 不复制长度与空白规则。非法则抛 TypeError/ValueError，且不触碰 client。
        build_fallback_query_plan(original_query)

        start = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=build_planner_messages(original_query),
                temperature=PLANNER_TEMPERATURE,
                max_tokens=PLANNER_MAX_OUTPUT_TOKENS,
            )
        except _KNOWN_PROVIDER_EXCEPTIONS as exc:
            failure_code = _classify_provider_exception(exc)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return build_planner_fallback_outcome(
                original_query,
                failure_code,
                call_metadata=self._build_metadata(latency_ms),
            )
        latency_ms = (time.perf_counter() - start) * 1000.0

        try:
            content = _extract_content(response)
            input_tokens, output_tokens = _extract_usage(response)
        except _ProviderResponseError:
            return build_planner_fallback_outcome(
                original_query,
                "PLANNER_PROVIDER_ERROR",
                call_metadata=self._build_metadata(latency_ms),
            )

        outcome = parse_planner_output(
            original_query=original_query, raw_output=content
        )
        return PlannerOutcome(
            plan=outcome.plan,
            fallback_used=outcome.fallback_used,
            failure_code=outcome.failure_code,
            call_metadata=self._build_metadata(
                latency_ms, input_tokens, output_tokens
            ),
        )

    def _build_metadata(
        self,
        latency_ms: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> PlannerCallMetadata:
        return PlannerCallMetadata(
            provider=self._provider,
            model=self._model,
            prompt_version=PLANNER_PROMPT_VERSION,
            prompt_sha256=PLANNER_PROMPT_SHA256,
            call_count=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
