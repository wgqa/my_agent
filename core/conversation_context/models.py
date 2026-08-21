"""Deterministic bounded recent conversation context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from core.chunker.token_counter import TokenCounter

CONTEXT_MAX_MESSAGES = 6
CONTEXT_TOKEN_BUDGET = 1200
_ROLES = frozenset(("user", "assistant"))


@dataclass(frozen=True)
class ContextMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise ValueError("conversation message role must be user or assistant")
        if type(self.content) is not str or not self.content.strip():
            raise ValueError("conversation message content must be non-empty")


@dataclass(frozen=True)
class RecentContextResult:
    selected_messages: tuple[ContextMessage, ...]
    received_count: int
    used_count: int
    used_tokens: int
    truncated: bool


class RecentContextWindow:
    """Select the newest bounded context without summarization or reordering."""

    def __init__(
        self,
        *,
        max_messages: int = CONTEXT_MAX_MESSAGES,
        token_budget: int = CONTEXT_TOKEN_BUDGET,
        token_counter: TokenCounter | None = None,
    ) -> None:
        if type(max_messages) is not int or max_messages <= 0:
            raise ValueError("max_messages must be a positive integer")
        if type(token_budget) is not int or token_budget <= 0:
            raise ValueError("token_budget must be a positive integer")
        self._max_messages = max_messages
        self._token_budget = token_budget
        self._counter = token_counter or TokenCounter()

    @staticmethod
    def _coerce(message: object) -> ContextMessage:
        if isinstance(message, ContextMessage):
            return message
        if isinstance(message, Mapping):
            return ContextMessage(role=message.get("role"), content=message.get("content"))
        try:
            return ContextMessage(
                role=getattr(message, "role"),
                content=getattr(message, "content"),
            )
        except AttributeError as exc:
            raise TypeError("conversation messages need role and content") from exc

    def prepare(self, history: Sequence[object] | None) -> RecentContextResult:
        if history is None:
            history = ()
        if isinstance(history, (str, bytes)):
            raise TypeError("history must be a sequence of messages")
        messages = tuple(self._coerce(message) for message in history)
        candidates = messages[-self._max_messages:]
        selected_reversed: list[ContextMessage] = []
        used_tokens = 0
        truncated = len(messages) > len(candidates)

        # Add from newest to oldest. Once the next oldest message cannot fit,
        # it and all still-older messages are evicted as one suffix boundary.
        for message in reversed(candidates):
            message_tokens = self._counter.count(message.content)
            remaining = self._token_budget - used_tokens
            if message_tokens <= remaining:
                selected_reversed.append(message)
                used_tokens += message_tokens
                continue
            if not selected_reversed and remaining > 0:
                start = self._counter.substring_start(
                    message.content, len(message.content), remaining
                )
                content = message.content[start:]
                if content:
                    selected_reversed.append(
                        ContextMessage(role=message.role, content=content)
                    )
                    used_tokens += self._counter.count(content)
                    truncated = True
            else:
                truncated = True
                break

        selected = tuple(reversed(selected_reversed))
        return RecentContextResult(
            selected_messages=selected,
            received_count=len(messages),
            used_count=len(selected),
            used_tokens=used_tokens,
            truncated=truncated,
        )
