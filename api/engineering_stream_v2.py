"""Rich, product-safe SSE presentation for post-G12 observability.

The v2 transport carries only immutable activity events emitted by one
ToolAgentRuntime run. It shares the v1 final-answer safety rule: answer
chunks are sent only for a completed, Guard-approved public result.
"""

from __future__ import annotations

import json
import logging
from queue import Empty, Queue
from threading import Thread
from typing import Callable, Iterator

from api.engineering_stream import ANSWER_CHUNK_CHARS, KEEP_ALIVE_SECONDS
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent.activity import (
    ActivityEvent,
    EvidenceAddedActivity,
    RunStartedActivity,
    ToolActivityEvent,
    VerificationBlockedActivity,
)
from core.tool_agent.runtime_models import ToolAgentRunResult


logger = logging.getLogger(__name__)
STREAM_SCHEMA_VERSION = "engineering_query_stream_v2"

_ACTIVITY_EVENT_TYPES = (
    RunStartedActivity,
    ToolActivityEvent,
    EvidenceAddedActivity,
    VerificationBlockedActivity,
)


def _encode_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _run_worker(
    facade: EngineeringAgentFacade,
    question: str,
    events: Queue,
) -> None:
    try:
        result = facade.run(
            question,
            activity_sink=lambda event: events.put(("activity", event)),
        )
        events.put(("result", result))
    except Exception:
        logger.exception("Engineering v2 stream worker failed")
        events.put(("error", None))
    finally:
        events.put(("worker_done", None))


def _result_payload(response: object) -> dict:
    if isinstance(response, dict):
        return response
    model_dump = getattr(response, "model_dump", None)
    if not callable(model_dump):
        raise TypeError("engineering response is not serializable")
    payload = model_dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("engineering response payload must be an object")
    return payload


def stream_engineering_query_v2(
    facade: EngineeringAgentFacade,
    question: str,
    *,
    build_response: Callable[[ToolAgentRunResult], object],
) -> Iterator[str]:
    """Start one Runtime worker and yield rich activity frames."""

    events: Queue = Queue()
    worker = Thread(
        target=_run_worker,
        args=(facade, question, events),
        daemon=True,
        name="engineering-sse-runtime-v2",
    )
    worker.start()

    def generate() -> Iterator[str]:
        while True:
            try:
                kind, value = events.get(timeout=KEEP_ALIVE_SECONDS)
            except Empty:
                yield ": keep-alive\n\n"
                continue

            if kind == "activity":
                if not isinstance(value, _ACTIVITY_EVENT_TYPES):
                    yield _encode_event(
                        {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"}
                    )
                    yield _encode_event({"type": "done"})
                    return
                yield _encode_event(value.to_dict())
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
                public_result = _result_payload(build_response(value))
                if not isinstance(public_result.get("evidence"), list):
                    raise TypeError("engineering response evidence must be a list")
                if public_result.get("status") == "completed":
                    answer = public_result.get("answer")
                    if not isinstance(answer, str):
                        raise TypeError("completed engineering response needs an answer")
                    yield _encode_event({"type": "answer_start"})
                    for start in range(0, len(answer), ANSWER_CHUNK_CHARS):
                        yield _encode_event(
                            {
                                "type": "answer_delta",
                                "delta": answer[start : start + ANSWER_CHUNK_CHARS],
                            }
                        )
                if public_result.get("status") not in {"completed", "refused", "failed"}:
                    raise TypeError("unknown engineering response status")
                yield _encode_event({"type": "final", "result": public_result})
            except Exception:
                logger.exception("Engineering v2 stream presentation failed")
                yield _encode_event(
                    {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"}
                )
            yield _encode_event({"type": "done"})
            return

    return generate()


__all__ = ["STREAM_SCHEMA_VERSION", "stream_engineering_query_v2"]
