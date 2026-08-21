"""Stable, secret-free failure types for provider-backed generators."""

from __future__ import annotations


class GeneratorError(RuntimeError):
    """Base class for expected generator/provider failures.

    Instances intentionally carry only a stable code.  Provider messages,
    response bodies, credentials, prompts, and local paths stay out of the
    exception object and can therefore not leak through API error handling.
    """

    code = "GENERATOR_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class GeneratorAuthenticationError(GeneratorError):
    code = "GENERATOR_AUTHENTICATION_ERROR"


class GeneratorTimeoutError(GeneratorError):
    code = "GENERATOR_TIMEOUT_ERROR"


class GeneratorUnavailableError(GeneratorError):
    code = "GENERATOR_UNAVAILABLE_ERROR"


class GeneratorResponseError(GeneratorError):
    code = "GENERATOR_RESPONSE_ERROR"


def extract_response_content(response: object) -> str:
    """Return a non-blank provider answer or raise a stable response error."""

    try:
        choices = response.choices
    except AttributeError:
        raise GeneratorResponseError from None
    if not isinstance(choices, list) or not choices:
        raise GeneratorResponseError from None
    try:
        message = choices[0].message
        content = message.content
    except AttributeError:
        raise GeneratorResponseError from None
    if type(content) is not str or not content.strip():
        raise GeneratorResponseError from None
    return content


__all__ = [
    "GeneratorError",
    "GeneratorAuthenticationError",
    "GeneratorTimeoutError",
    "GeneratorUnavailableError",
    "GeneratorResponseError",
    "extract_response_content",
]
