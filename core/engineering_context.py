"""Engineering Runtime context component.

This module owns only the bounded G8 context preparation and standalone-query
resolution seam.  It is deliberately not an Agent, controller, planner,
retriever, finalizer, or budget ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from core.conversation_context import (
    ContextMessage,
    ConversationQueryResolution,
    RecentContextWindow,
)


_EXPECTED_RESOLVER_FAILURES = (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    APIStatusError,
    TimeoutError,
)


@dataclass(frozen=True)
class EngineeringContextSnapshot:
    """Trusted, bounded context state passed across the Runtime seam.

    ``selected_messages`` is intentionally excluded from ``repr`` so a
    snapshot cannot accidentally put conversation content into logs or safe
    observability output.  The Runtime consumes only ``resolved_input``.
    """

    original_input: str
    resolved_input: str
    selected_messages: tuple[ContextMessage, ...] = field(repr=False)
    received_count: int
    used_count: int
    used_tokens: int
    truncated: bool
    resolver_used: bool
    resolver_fallback: bool

    def __post_init__(self) -> None:
        for label, value in (
            ("original_input", self.original_input),
            ("resolved_input", self.resolved_input),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        if type(self.selected_messages) is not tuple:
            raise TypeError("selected_messages must be a tuple")
        if not all(isinstance(message, ContextMessage) for message in self.selected_messages):
            raise TypeError("selected_messages must contain ContextMessage values")
        for label, value in (
            ("received_count", self.received_count),
            ("used_count", self.used_count),
            ("used_tokens", self.used_tokens),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if self.used_count != len(self.selected_messages):
            raise ValueError("used_count must match selected_messages")
        if self.used_count > self.received_count:
            raise ValueError("used_count cannot exceed received_count")
        for label, value in (
            ("truncated", self.truncated),
            ("resolver_used", self.resolver_used),
            ("resolver_fallback", self.resolver_fallback),
        ):
            if type(value) is not bool:
                raise TypeError(f"{label} must be a bool")
        if not self.selected_messages and self.used_tokens != 0:
            raise ValueError("used_tokens must be zero without selected messages")


class EngineeringContextResolver:
    """Prepare G8 context and resolve one Engineering query at most once."""

    def __init__(
        self,
        query_resolver=None,
        *,
        context_window: RecentContextWindow | None = None,
    ) -> None:
        if context_window is not None and not isinstance(
            context_window, RecentContextWindow
        ):
            raise TypeError("context_window must be RecentContextWindow")
        if query_resolver is not None and not callable(
            getattr(query_resolver, "resolve", None)
        ):
            raise TypeError("query_resolver must implement resolve")
        self._context_window = context_window or RecentContextWindow()
        self._query_resolver = query_resolver

    def resolve(
        self,
        user_input: str,
        conversation_context: Sequence[object] | None,
    ) -> EngineeringContextSnapshot:
        """Return one trusted snapshot without owning any downstream policy."""

        context = self._context_window.prepare(conversation_context)
        resolution = ConversationQueryResolution(user_input, False, False)
        if context.selected_messages:
            if self._query_resolver is None:
                raise RuntimeError(
                    "query_resolver is required when conversation context is non-empty"
                )
            # The existing resolver normally owns expected provider/response
            # failure classification and returns a safe fallback resolution.
            # Keep the same boundary for compatible injected resolvers, but do
            # not catch-all: programming errors must propagate.
            try:
                resolution = self._query_resolver.resolve(
                    context.selected_messages,
                    user_input,
                )
            except _EXPECTED_RESOLVER_FAILURES:
                resolution = ConversationQueryResolution(user_input, True, True)

        return EngineeringContextSnapshot(
            original_input=user_input,
            resolved_input=resolution.standalone_query,
            selected_messages=context.selected_messages,
            received_count=context.received_count,
            used_count=context.used_count,
            used_tokens=context.used_tokens,
            truncated=context.truncated,
            resolver_used=resolution.resolver_used,
            resolver_fallback=resolution.fallback,
        )


__all__ = ["EngineeringContextResolver", "EngineeringContextSnapshot"]
