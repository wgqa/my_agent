"""Pure state reduction for the Engineering Agent SSE presentation.

The reducer stores observable execution status and the final public result.
It never stores prompts, provider output, reasoning text, or requirement
metadata, and it rejects protocol violations instead of accepting a partial
answer as conversation history.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


STREAM_EVENT_TYPES = frozenset(
    {"status", "evidence", "answer_start", "answer_delta", "final", "error", "done"}
)
TOOL_LABELS = {
    "knowledge_search": "正在检索技术知识",
    "code_search": "正在搜索项目代码",
    "read_project_context": "正在读取项目上下文",
    "changed_files": "正在检查变更文件",
    "git_diff": "正在分析代码变更",
    "find_tests": "正在定位相关测试",
    "calculator": "正在计算",
}


class StreamProtocolError(ValueError):
    """Raised when an SSE sequence cannot be treated as a valid run."""


@dataclass(frozen=True)
class EngineeringStreamStep:
    """One logical observable step, combining tool start and completion."""

    identity: tuple[int, str]
    tool_name: str
    label: str
    state: str


@dataclass(frozen=True)
class EngineeringStreamState:
    """Reducer state safe to render or discard without persisting partial text."""

    steps: tuple[EngineeringStreamStep, ...] = ()
    answer_buffer: str = ""
    evidence: tuple[dict, ...] = ()
    final_result: dict | None = None
    answer_started: bool = False
    done: bool = False
    error_code: str | None = None
    analysis_started: bool = False


def tool_label(tool_name: Any) -> str:
    """Map an internal tool identity to a user-safe status label."""

    return TOOL_LABELS.get(tool_name, "正在调用工程工具")


def _copy_state(state: EngineeringStreamState, **changes) -> EngineeringStreamState:
    values = {
        "steps": tuple(state.steps),
        "evidence": tuple(dict(item) for item in state.evidence),
    }
    values.update(changes)
    return replace(
        state,
        **values,
    )


def _require_event(event: object) -> dict:
    if not isinstance(event, dict) or event.get("type") not in STREAM_EVENT_TYPES:
        raise StreamProtocolError("invalid stream event")
    return event


def _require_iteration(event: dict) -> int:
    iteration = event.get("iteration")
    if type(iteration) is not int or iteration < 1:
        raise StreamProtocolError("stream status requires a positive iteration")
    return iteration


def _replace_step(
    steps: tuple[EngineeringStreamStep, ...],
    identity: tuple[int, str],
    state: str,
) -> tuple[EngineeringStreamStep, ...]:
    normalized_state = "complete" if state == "completed" else state
    for index, step in enumerate(steps):
        if step.identity == identity:
            return steps[:index] + (replace(step, state=normalized_state),) + steps[index + 1 :]
    raise StreamProtocolError("tool completion has no matching start")


def consume_event(
    state: EngineeringStreamState,
    event: dict,
) -> EngineeringStreamState:
    """Reduce one decoded SSE event and reject unsafe or incomplete sequences."""

    if not isinstance(state, EngineeringStreamState):
        raise TypeError("state must be EngineeringStreamState")
    event = _require_event(event)
    event_type = event["type"]
    if state.done:
        raise StreamProtocolError("stream contains an event after done")

    if event_type == "status":
        stage = event.get("stage")
        status = event.get("state")
        if stage == "analysis" and status == "started":
            if state.analysis_started:
                raise StreamProtocolError("analysis status repeated")
            return _copy_state(state, analysis_started=True)
        if stage == "tool":
            tool_name = event.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise StreamProtocolError("tool status requires a tool name")
            iteration = _require_iteration(event)
            identity = (iteration, tool_name)
            if status == "started":
                if any(step.identity == identity for step in state.steps):
                    raise StreamProtocolError("tool status started twice")
                step = EngineeringStreamStep(
                    identity=identity,
                    tool_name=tool_name,
                    label=tool_label(tool_name),
                    state="running",
                )
                return _copy_state(state, steps=state.steps + (step,))
            if status in {"completed", "error"}:
                return _copy_state(
                    state,
                    steps=_replace_step(state.steps, identity, status),
                )
        if stage == "verification" and status == "blocked":
            iteration = _require_iteration(event)
            identity = (iteration, "__verification__")
            if any(step.identity == identity for step in state.steps):
                raise StreamProtocolError("verification status repeated")
            step = EngineeringStreamStep(
                identity=identity,
                tool_name="__verification__",
                label="证据仍不充分，继续调查",
                state="blocked",
            )
            return _copy_state(state, steps=state.steps + (step,))
        raise StreamProtocolError("invalid stream status")

    if event_type == "evidence":
        if state.final_result is not None or state.error_code is not None:
            raise StreamProtocolError("evidence arrived after stream terminal state")
        evidence = event.get("evidence")
        if not isinstance(evidence, dict):
            raise StreamProtocolError("evidence event requires an object")
        return _copy_state(state, evidence=state.evidence + (dict(evidence),))

    if event_type == "answer_start":
        if state.answer_started or state.final_result is not None:
            raise StreamProtocolError("answer started more than once")
        return _copy_state(state, answer_started=True)

    if event_type == "answer_delta":
        delta = event.get("delta")
        if not state.answer_started or not isinstance(delta, str) or not delta:
            raise StreamProtocolError("answer delta arrived before answer start")
        if state.final_result is not None:
            raise StreamProtocolError("answer delta arrived after final")
        return _copy_state(state, answer_buffer=state.answer_buffer + delta)

    if event_type == "final":
        if state.final_result is not None or state.error_code is not None:
            raise StreamProtocolError("duplicate stream terminal event")
        result = event.get("result")
        if not isinstance(result, dict):
            raise StreamProtocolError("final event requires a result object")
        status = result.get("status")
        if status == "completed":
            answer = result.get("answer")
            if not state.answer_started or not isinstance(answer, str):
                raise StreamProtocolError("completed final missing answer stream")
            if state.answer_buffer != answer:
                raise StreamProtocolError("answer stream differs from final result")
        elif status in {"refused", "failed"}:
            if state.answer_started or state.answer_buffer:
                raise StreamProtocolError("non-completed result contains answer stream")
        else:
            raise StreamProtocolError("invalid final result status")
        return _copy_state(state, final_result=dict(result))

    if event_type == "error":
        if state.final_result is not None or state.error_code is not None:
            raise StreamProtocolError("duplicate stream error")
        code = event.get("code")
        if not isinstance(code, str) or not code:
            raise StreamProtocolError("error event requires a code")
        if state.answer_started or state.answer_buffer:
            raise StreamProtocolError("stream error after answer output")
        return _copy_state(state, error_code=code)

    if event_type == "done":
        if state.final_result is None and state.error_code is None:
            raise StreamProtocolError("done arrived without final or error")
        return _copy_state(state, done=True)

    raise StreamProtocolError("unhandled stream event")


def validate_complete(state: EngineeringStreamState) -> EngineeringStreamState:
    """Require the terminal ``done`` event before a run can be persisted."""

    if not isinstance(state, EngineeringStreamState) or not state.done:
        raise StreamProtocolError("stream did not finish with done")
    return state


__all__ = [
    "EngineeringStreamState",
    "EngineeringStreamStep",
    "STREAM_EVENT_TYPES",
    "StreamProtocolError",
    "TOOL_LABELS",
    "consume_event",
    "tool_label",
    "validate_complete",
]
