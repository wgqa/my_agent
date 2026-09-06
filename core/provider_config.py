"""Small, immutable configuration boundary for OpenAI-compatible providers.

The object in this module describes public transport metadata only.  It never
contains an API key; callers resolve ``api_key_env`` at the point where an SDK
client is constructed and pass the resulting value directly to the SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
import re

from core.generator.deepseek_gen import DEEPSEEK_BASE_URL


DEEPSEEK_PROVIDER_ID = "deepseek"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"

OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
OPENCODE_GO_API_KEY_ENV = "OPENCODE_API_KEY"
DEFAULT_PROJECT_USER_AGENT = "rag-knowledge-base/provider-port-01"

_MAX_PUBLIC_FIELD_LENGTH = 256
_MAX_HEADER_COUNT = 8
_MAX_HEADER_NAME_LENGTH = 64
_MAX_HEADER_VALUE_LENGTH = 256
_MAX_SESSION_ID_LENGTH = 96
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")

# Header names are intentionally denied by meaning, rather than by an allowlist
# of today's headers.  This keeps the contract safe as public metadata grows.
_SECRET_HEADER_MARKERS = (
    "authorization",
    "api-key",
    "apikey",
    "secret",
    "password",
    "credential",
    "cookie",
    "proxy-auth",
    "token",
)
_SECRET_VALUE_MARKERS = (
    "api_key=",
    "api-key=",
    "authorization:",
    "bearer ",
    "basic ",
    "password=",
    "secret=",
    "token=",
)


def _validate_public_string(value: object, label: str, *, limit: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be a string")
    if not value or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{label} must not have leading/trailing whitespace")
    if len(value) > limit:
        raise ValueError(f"{label} is too long")
    return value


def _validate_api_key_env(value: object) -> str:
    value = _validate_public_string(value, "api_key_env", limit=64)
    if _ENV_NAME_RE.fullmatch(value) is None:
        raise ValueError("api_key_env must be an environment variable name")
    return value


def _looks_secret_header(name: str, value: str) -> bool:
    folded_name = name.casefold()
    folded_value = value.casefold()
    return (
        any(marker in folded_name for marker in _SECRET_HEADER_MARKERS)
        or any(marker in folded_value for marker in _SECRET_VALUE_MARKERS)
        or folded_value.startswith("sk-")
    )


def freeze_public_headers(
    headers: Mapping[str, str] | None,
) -> Mapping[str, str]:
    """Validate and freeze bounded, non-secret transport headers.

    The returned mapping is a ``mappingproxy``.  A plain dict copy can be
    obtained for the SDK's client-level ``default_headers`` parameter through
    :func:`openai_default_headers`.
    """

    if headers is None:
        return MappingProxyType({})
    if not isinstance(headers, Mapping):
        raise TypeError("extra_headers must be a mapping")
    if len(headers) > _MAX_HEADER_COUNT:
        raise ValueError("extra_headers has too many headers")

    normalized: dict[str, str] = {}
    folded_names: set[str] = set()
    for raw_name, raw_value in headers.items():
        name = _validate_public_string(
            raw_name, "extra_headers name", limit=_MAX_HEADER_NAME_LENGTH
        )
        value = _validate_public_string(
            raw_value, "extra_headers value", limit=_MAX_HEADER_VALUE_LENGTH
        )
        folded_name = name.casefold()
        if folded_name in folded_names:
            raise ValueError("extra_headers contains duplicate header names")
        folded_names.add(folded_name)
        if _looks_secret_header(name, value):
            raise ValueError("extra_headers cannot contain secret headers or values")
        if folded_name == "x-opencode-session" and (
            len(value) > _MAX_SESSION_ID_LENGTH
            or _SESSION_ID_RE.fullmatch(value) is None
        ):
            raise ValueError("x-opencode-session must be a bounded stable session id")
        normalized[name] = value
    return MappingProxyType(
        dict(sorted(normalized.items(), key=lambda item: item[0].casefold()))
    )


def openai_default_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return a fresh safe dict for OpenAI SDK ``default_headers``."""

    return dict(freeze_public_headers(headers))


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProviderConfig:
    """Public, immutable identity for one OpenAI-compatible transport.

    ``api_key_env`` identifies where a caller may obtain a key; the key itself
    is deliberately not a field of this object.
    """

    provider_id: str
    model: str
    base_url: str
    api_key_env: str
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_id",
            _validate_public_string(
                self.provider_id, "provider_id", limit=_MAX_PUBLIC_FIELD_LENGTH
            ),
        )
        object.__setattr__(
            self,
            "model",
            _validate_public_string(
                self.model, "model", limit=_MAX_PUBLIC_FIELD_LENGTH
            ),
        )
        object.__setattr__(
            self,
            "base_url",
            _validate_public_string(
                self.base_url, "base_url", limit=_MAX_PUBLIC_FIELD_LENGTH
            ),
        )
        object.__setattr__(self, "api_key_env", _validate_api_key_env(self.api_key_env))
        object.__setattr__(
            self, "extra_headers", freeze_public_headers(self.extra_headers)
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.provider_id,
                self.model,
                self.base_url,
                self.api_key_env,
                tuple(self.extra_headers.items()),
            )
        )


def deepseek_provider_config() -> OpenAICompatibleProviderConfig:
    """Return the unchanged historical DeepSeek transport defaults."""

    return OpenAICompatibleProviderConfig(
        provider_id=DEEPSEEK_PROVIDER_ID,
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        api_key_env=DEEPSEEK_API_KEY_ENV,
    )


def build_opencode_go_provider_config(
    *,
    model: str,
    session_id: str,
    user_agent: str = DEFAULT_PROJECT_USER_AGENT,
) -> OpenAICompatibleProviderConfig:
    """Build an explicit development profile for OpenCode Go.

    A work-unit session is mandatory and must be supplied by the caller.  The
    factory never creates a UUID per request or per component.
    """

    _validate_public_string(session_id, "session_id", limit=_MAX_SESSION_ID_LENGTH)
    if _SESSION_ID_RE.fullmatch(session_id) is None:
        raise ValueError("session_id must be a bounded stable session id")
    _validate_public_string(user_agent, "user_agent", limit=_MAX_HEADER_VALUE_LENGTH)
    return OpenAICompatibleProviderConfig(
        provider_id="opencode-go",
        model=model,
        base_url=OPENCODE_GO_BASE_URL,
        api_key_env=OPENCODE_GO_API_KEY_ENV,
        extra_headers={
            "User-Agent": user_agent,
            "x-opencode-session": session_id,
        },
    )


__all__ = [
    "DEFAULT_PROJECT_USER_AGENT",
    "DEEPSEEK_API_KEY_ENV",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PROVIDER_ID",
    "OPENCODE_GO_API_KEY_ENV",
    "OPENCODE_GO_BASE_URL",
    "OpenAICompatibleProviderConfig",
    "build_opencode_go_provider_config",
    "deepseek_provider_config",
    "freeze_public_headers",
    "openai_default_headers",
]
