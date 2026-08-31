"""Product-safe SSE presentation for the Engineering Agent.

The bounded Runtime remains synchronous and owns all decisions. This module
only observes its existing safe trace events, then presents the completed
public response without exposing actions, observations, prompts, or CoT.
"""

from __future__ import annotations

import json
import logging
from queue import Empty, Queue
from threading import Thread
from typing import Callable, Iterator

from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent.runtime_models import RuntimeTraceEvent, ToolAgentRunResult


logger = logging.getLogger(__name__)

STREAM_SCHEMA_VERSION = "engineering_query_stream_v1"
ANSWER_CHUNK_CHARS = 16
KEEP_ALIVE_SECONDS = 10.0


def _encode_event(payload: dict) -> str:
    """Encode one JSON product event without an SSE event-name dependency."""

    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


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


def _run_worker(
    facade: EngineeringAgentFacade,
    question: str,
    events: Queue,
    conversation_context=None,
) -> None:
    try:
        result = facade.run(
            question,
            conversation_context=conversation_context,
            trace_sink=lambda event: events.put(("trace", event)),
        )
        events.put(("result", result))
    except Exception:
        logger.exception("Engineering stream worker failed")
        events.put(("error", None))
    finally:
        events.put(("worker_done", None))


def stream_engineering_query(
    facade: EngineeringAgentFacade,
    question: str,
    *,
    conversation_context=None,
    build_response: Callable[[ToolAgentRunResult], object],
) -> Iterator[str]:
    """Start one Runtime worker and yield product-safe SSE frames.

    Answer deltas are guarded presentation chunks, not provider-token output:
    they are emitted only after the final Runtime result is completed.
    """

    events: Queue = Queue()
    worker = Thread(
        target=_run_worker,
        args=(facade, question, events, conversation_context),
        daemon=True,
        name="engineering-sse-runtime",
    )
    worker.start()

    def generate() -> Iterator[str]:
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

    return generate()


__all__ = [
    "ANSWER_CHUNK_CHARS",
    "KEEP_ALIVE_SECONDS",
    "STREAM_SCHEMA_VERSION",
    "stream_engineering_query",
]
