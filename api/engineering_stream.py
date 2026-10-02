"""Product-safe SSE presentation for the Engineering Agent.

The bounded Runtime remains synchronous and owns all decisions. This module
only observes its existing safe trace events, then presents the completed
public response without exposing actions, observations, prompts, or CoT.
"""

from __future__ import annotations

import logging
from queue import Empty, Queue
from threading import Event, Thread
from typing import Callable, Iterator

from api.engineering_stream_common import (
    ANSWER_CHUNK_CHARS,
    KEEP_ALIVE_SECONDS,
    encode_event as _encode_event,
    run_worker as _run_worker,
)
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult


logger = logging.getLogger(__name__)

STREAM_SCHEMA_VERSION = "engineering_query_stream_v1"


def _trace_status(event: RuntimeTraceEvent) -> dict | None:
    """Reduce existing safe Runtime trace to a smaller UI status contract."""

    if event.event_type == "tool_call_created":
        return {
            "type": "status",
            "stage": "tool",
            "state": "started",
            "tool_name": event.tool_name,
            "iteration": event.iteration,
        }
    if event.event_type == "tool_observation":
        return {
            "type": "status",
            "stage": "tool",
            "state": "completed" if event.tool_status == "ok" else "error",
            "tool_name": event.tool_name,
            "iteration": event.iteration,
        }
    if event.event_type == "finalization_guard_blocked":
        return {
            "type": "status",
            "stage": "verification",
            "state": "blocked",
            "iteration": event.iteration,
        }
    return None


def _result_payload(response) -> dict:
    """Convert the already validated public API response to JSON data."""

    return response.model_dump(mode="json")


def stream_engineering_query(
    facade: EngineeringAgentFacade,
    question: str,
    *,
    conversation_context=None,
    build_response: Callable[[ToolAgentRunResult], object],
    before_public_result: Callable[[dict], None] | None = None,
    cancel_event: Event | None = None,
    on_worker_done: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Start one Runtime worker and yield product-safe SSE frames.

    Answer deltas are guarded presentation chunks, not provider-token output:
    they are emitted only after the final Runtime result is completed.

    ``before_public_result`` is an optional product seam (the Engineering
    conversation persistence hook).  When provided, it runs on the validated
    public result strictly before any evidence/answer/final event is emitted;
    a callback failure therefore surfaces as ``error`` + ``done`` without the
    stream ever claiming a successful answer.  The frozen question-only
    endpoints pass nothing and keep their exact previous behavior.

    ``cancel_event`` is the disconnect-cancellation signal
    (PRODUCT-ENGINEERING-24B): when the consumer abandons the stream, the
    generator's ``finally`` sets it and the Runtime stops at its next safe
    boundary — no new LLM or Tool call is started. Persistence semantics are
    unchanged: either no turn is stored, or the turn that already completed
    atomically.
    """

    if cancel_event is None:
        cancel_event = Event()
    events: Queue = Queue()
    worker = Thread(
        target=_run_worker,
        args=(facade, question, events, conversation_context),
        kwargs={
            "cancel_requested": cancel_event.is_set,
            "on_worker_done": on_worker_done,
            "worker_logger": logger,
        },
        daemon=True,
        name="engineering-sse-runtime",
    )
    worker.start()

    def generate() -> Iterator[str]:
        try:
            yield _encode_event(
                {
                    "type": "status",
                    "stage": "analysis",
                    "state": "started",
                }
            )
            while True:
                try:
                    kind, value = events.get(timeout=KEEP_ALIVE_SECONDS)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue

                if kind == "trace":
                    status = _trace_status(value)
                    if status is not None:
                        yield _encode_event(status)
                    continue
                if kind == "error":
                    yield _encode_event(
                        {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"}
                    )
                    yield _encode_event({"type": "done"})
                    return
                if kind != "result":
                    continue

                try:
                    response = build_response(value)
                    public_result = _result_payload(response)
                    if before_public_result is not None:
                        before_public_result(public_result)
                    for evidence in public_result["evidence"]:
                        yield _encode_event({"type": "evidence", "evidence": evidence})

                    if public_result["status"] == "completed":
                        yield _encode_event({"type": "answer_start"})
                        answer = public_result["answer"]
                        for start in range(0, len(answer), ANSWER_CHUNK_CHARS):
                            yield _encode_event(
                                {
                                    "type": "answer_delta",
                                    "delta": answer[start : start + ANSWER_CHUNK_CHARS],
                                }
                            )
                    yield _encode_event({"type": "final", "result": public_result})
                except Exception:
                    logger.exception("Engineering stream presentation failed")
                    yield _encode_event(
                        {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"}
                    )
                yield _encode_event({"type": "done"})
                return
        finally:
            # Client disconnect / generator close: signal cooperative
            # cancellation so the worker stops at the next safe boundary.
            # On a normally completed stream the worker already finished and
            # the signal is a no-op.
            cancel_event.set()

    return generate()


__all__ = [
    "ANSWER_CHUNK_CHARS",
    "KEEP_ALIVE_SECONDS",
    "STREAM_SCHEMA_VERSION",
    "stream_engineering_query",
]
