"""Single-call standalone-query resolver for Agentic RAG follow-ups."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Sequence

from openai import OpenAI

from core.conversation_context.models import ContextMessage

CONTEXT_RESOLUTION_FALLBACK = "CONTEXT_RESOLUTION_FALLBACK"
RESOLVER_PROMPT_VERSION = "agentic_rag_context_resolver_v1"
RESOLVER_TEMPERATURE = 0.0
RESOLVER_MAX_RETRIES = 0
RESOLVER_MAX_OUTPUT_TOKENS = 160

_SYSTEM_PROMPT = (
    "Rewrite a follow-up question into one standalone query using only the "
    "conversation context. Preserve a new topic when the question changes topic. "
    "Return exactly one JSON object with exactly one string field: "
    '{"standalone_query":"..."}. Do not answer the question, add knowledge, '
    "choose tools, or include explanations."
)


@dataclass(frozen=True)
class ConversationQueryResolution:
    standalone_query: str
    resolver_used: bool
    fallback: bool


def _valid_query(value: object) -> bool:
    return type(value) is str and bool(value.strip())


class OpenAICompatibleConversationQueryResolver:
    """An independent, bounded resolver. It never calls the provider without history."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        client: Optional[object] = None,
    ) -> None:
        for label, value in (("provider", provider), ("model", model), ("api_key", api_key)):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        if base_url is not None and (type(base_url) is not str or not base_url.strip()):
            raise ValueError("base_url must be a non-empty string")
        self._provider = provider
        self._model = model
        self._client = (
            client if client is not None else self._build_default_client(api_key, base_url)
        )

    @staticmethod
    def _build_default_client(api_key: str, base_url: Optional[str]) -> OpenAI:
        kwargs = {"api_key": api_key, "timeout": 20.0, "max_retries": RESOLVER_MAX_RETRIES}
        if base_url is not None:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    @staticmethod
    def _messages(history: Sequence[ContextMessage], question: str) -> list[dict[str, str]]:
        context = [
            {"role": message.role, "content": message.content}
            for message in history
        ]
        context.append({"role": "user", "content": question})
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(
                {"history": context[:-1], "current_question": question},
                ensure_ascii=False,
                separators=(",", ":"),
            )},
        ]

    def resolve(
        self,
        history: Sequence[ContextMessage],
        question: str,
    ) -> ConversationQueryResolution:
        if not _valid_query(question):
            raise ValueError("question must be a non-empty string")
        if not history:
            return ConversationQueryResolution(question, False, False)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(history, question),
                temperature=RESOLVER_TEMPERATURE,
                max_tokens=RESOLVER_MAX_OUTPUT_TOKENS,
            )
            content = response.choices[0].message.content
            if type(content) is not str:
                raise ValueError("resolver response content is invalid")
            payload = json.loads(content)
            if (
                type(payload) is not dict
                or set(payload) != {"standalone_query"}
                or not _valid_query(payload["standalone_query"])
            ):
                raise ValueError("resolver response schema is invalid")
            return ConversationQueryResolution(
                payload["standalone_query"].strip(), True, False
            )
        except Exception:
            return ConversationQueryResolution(question, True, True)
