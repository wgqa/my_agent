"""Shared transport helpers for the two Engineering SSE presentations.

The synchronous facade remains the only execution entry. This module owns
event encoding and worker completion plumbing, not decisions or finalization.
"""

from __future__ import annotations

import inspect
import json
import logging
from queue import Queue
from typing import Callable, Literal

from core.engineering_agent import EngineeringAgentFacade


logger = logging.getLogger(__name__)

ANSWER_CHUNK_CHARS = 16
KEEP_ALIVE_SECONDS = 10.0


def encode_event(payload: dict) -> str:
    """Encode the existing JSON data frame shared by v1 and v2."""

    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def run_worker(
    facade: EngineeringAgentFacade,
    question: str,
    events: Queue,
    conversation_context=None,
    cancel_requested: Callable[[], bool] | None = None,
    on_worker_done: Callable[[], None] | None = None,
    *,
    event_kind: Literal["trace", "activity"] = "trace",
    worker_logger: logging.Logger | None = None,
) -> None:
    """Run the facade once and release worker-owned resources after it stops.

    Client disconnect only requests cancellation. The completion callback is
    kept in this worker's finally block so it cannot release admission slots
    while an in-flight provider or tool call is still running.
    """

    active_logger = logger if worker_logger is None else worker_logger
    log_prefix = "Engineering v2 stream" if event_kind == "activity" else "Engineering stream"
    try:
        sink_name = {"trace": "trace_sink", "activity": "activity_sink"}[event_kind]
        kwargs = {sink_name: lambda event: events.put((event_kind, event))}
        if cancel_requested is not None:
            # Preserve the existing compatibility with test doubles and older
            # facades that predate the cooperative cancellation probe.
            parameters = inspect.signature(facade.run).parameters
            if "cancel_requested" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            ):
                kwargs["cancel_requested"] = cancel_requested
        result = facade.run(
            question,
            conversation_context=conversation_context,
            **kwargs,
        )
        events.put(("result", result))
    except Exception:
        active_logger.exception("%s worker failed", log_prefix)
        events.put(("error", None))
    finally:
        try:
            events.put(("worker_done", None))
        finally:
            if on_worker_done is not None:
                try:
                    on_worker_done()
                except Exception:
                    active_logger.exception("%s worker cleanup failed", log_prefix)
