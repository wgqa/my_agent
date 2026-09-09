"""Rich, product-safe SSE presentation for post-G12 observability.

The v2 transport carries only immutable activity events emitted by one
ToolAgentRuntime run. It shares the v1 final-answer safety rule: answer
chunks are sent only for a completed, Guard-approved public result.
"""

from __future__ import annotations

import inspect
import json
import logging
from queue import Empty, Queue
from threading import Event, Thread
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
    conversation_context=None,
    cancel_requested: Callable[[], bool] | None = None,
    on_worker_done: Callable[[], None] | None = None,
) -> None:
    try:
        kwargs = {}
        if cancel_requested is not None:
            # Preserve compatibility with provider-free test doubles and
            # legacy facades that predate the cooperative probe.
            parameters = inspect.signature(facade.run).parameters
            if "cancel_requested" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            ):
                kwargs["cancel_requested"] = cancel_requested
        result = facade.run(
            question,
            conversation_context=conversation_context,
            activity_sink=lambda event: events.put(("activity", event)),
            **kwargs,
        )
        events.put(("result", result))
    except Exception:
        logger.exception("Engineering v2 stream worker failed")
        events.put(("error", None))
    finally:
        try:
            events.put(("worker_done", None))
        finally:
            if on_worker_done is not None:
                try:
                    on_worker_done()
                except Exception:
                    logger.exception("Engineering v2 stream worker cleanup failed")


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
    conversation_context=None,
    build_response: Callable[[ToolAgentRunResult], object],
    cancel_event: Event | None = None,
    on_worker_done: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Start one Runtime worker and yield rich activity frames.

    A client disconnect is cooperative: closing the generator sets the event,
    and the Runtime observes it at its next Decision/Tool safe boundary.  An
    in-flight provider or Tool call is never force-killed.
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
        },
        daemon=True,
        name="engineering-sse-runtime-v2",
    )
    worker.start()

    def generate() -> Iterator[str]:
        try:
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
        finally:
            cancel_event.set()

    return generate()


__all__ = ["STREAM_SCHEMA_VERSION", "stream_engineering_query_v2"]
