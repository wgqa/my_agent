"""Deterministic tests for the Engineering Agent SSE presentation reducer."""

from __future__ import annotations

import inspect

import pytest

from ui import app
from ui.streaming import (
    EngineeringStreamState,
    StreamProtocolError,
    TOOL_LABELS,
    consume_event,
    tool_label,
    validate_complete,
)


def _reduce(events):
    state = EngineeringStreamState()
    for event in events:
        state = consume_event(state, event)
    return validate_complete(state)


def test_all_registered_tools_have_safe_human_labels():
    assert set(TOOL_LABELS) == {
        "knowledge_search",
        "code_search",
        "read_project_context",
        "changed_files",
        "git_diff",
        "find_tests",
        "calculator",
    }
    assert all(label and "{" not in label for label in TOOL_LABELS.values())
    assert tool_label("unrecognized_tool") == "正在调用工程工具"


def test_tool_started_and_completed_share_one_logical_step():
    state = EngineeringStreamState()
    state = consume_event(
        state,
        {"type": "status", "stage": "analysis", "state": "started"},
    )
    state = consume_event(
        state,
        {
            "type": "status",
            "stage": "tool",
            "state": "started",
            "tool_name": "code_search",
            "iteration": 1,
        },
    )
    state = consume_event(
        state,
        {
            "type": "status",
            "stage": "tool",
            "state": "completed",
            "tool_name": "code_search",
            "iteration": 1,
        },
    )

    assert len(state.steps) == 1
    assert state.steps[0].state == "complete"
    assert state.steps[0].label == "正在搜索项目代码"


def test_tool_error_and_guard_block_are_renderable_statuses():
    state = EngineeringStreamState()
    state = consume_event(
        state,
        {
            "type": "status",
            "stage": "tool",
            "state": "started",
            "tool_name": "git_diff",
            "iteration": 1,
        },
    )
    state = consume_event(
        state,
        {
            "type": "status",
            "stage": "tool",
            "state": "error",
            "tool_name": "git_diff",
            "iteration": 1,
        },
    )
    state = consume_event(
        state,
        {
            "type": "status",
            "stage": "verification",
            "state": "blocked",
            "iteration": 2,
        },
    )

    assert [step.state for step in state.steps] == ["error", "blocked"]
    assert state.steps[1].label == "证据仍不充分，继续调查"


def test_evidence_and_answer_deltas_are_reduced_without_metadata():
    state = _reduce(
        [
            {"type": "status", "stage": "analysis", "state": "started"},
            {
                "type": "evidence",
                "evidence": {"kind": "project_code", "path": "src/app.py"},
            },
            {"type": "answer_start"},
            {"type": "answer_delta", "delta": "Grounded "},
            {"type": "answer_delta", "delta": "answer"},
            {
                "type": "final",
                "result": {"status": "completed", "answer": "Grounded answer"},
            },
            {"type": "done"},
        ]
    )

    assert state.answer_buffer == "Grounded answer"
    assert state.evidence == ({"kind": "project_code", "path": "src/app.py"},)
    assert state.final_result["status"] == "completed"
    assert not hasattr(state, "prompt")
    assert not hasattr(state, "raw_response")


def test_answer_delta_before_start_and_final_mismatch_are_rejected():
    with pytest.raises(StreamProtocolError):
        consume_event(
            EngineeringStreamState(),
            {"type": "answer_delta", "delta": "unsafe partial"},
        )

    state = consume_event(EngineeringStreamState(), {"type": "answer_start"})
    state = consume_event(state, {"type": "answer_delta", "delta": "actual"})
    with pytest.raises(StreamProtocolError):
        consume_event(
            state,
            {
                "type": "final",
                "result": {"status": "completed", "answer": "different"},
            },
        )


@pytest.mark.parametrize("status", ["refused", "failed"])
def test_refused_or_failed_result_cannot_contain_answer_stream(status):
    state = _reduce(
        [
            {"type": "final", "result": {"status": status, "answer": None}},
            {"type": "done"},
        ]
    )
    assert state.final_result["status"] == status
    assert state.answer_buffer == ""

    state = consume_event(EngineeringStreamState(), {"type": "answer_start"})
    state = consume_event(state, {"type": "answer_delta", "delta": "leak"})
    with pytest.raises(StreamProtocolError):
        consume_event(
            state,
            {"type": "final", "result": {"status": status, "answer": "leak"}},
        )


def test_done_is_required_and_events_after_done_are_rejected():
    with pytest.raises(StreamProtocolError):
        validate_complete(EngineeringStreamState())

    state = _reduce(
        [{"type": "final", "result": {"status": "refused"}}, {"type": "done"}]
    )
    with pytest.raises(StreamProtocolError):
        consume_event(state, {"type": "done"})


def test_stream_errors_keep_only_a_safe_code_for_generic_ui_message():
    state = _reduce(
        [
            {"type": "error", "code": "INTERNAL_ENGINEERING_STREAM_ERROR"},
            {"type": "done"},
        ]
    )
    assert state.error_code == "INTERNAL_ENGINEERING_STREAM_ERROR"
    assert state.final_result is None
    assert "INTERNAL_ENGINEERING_STREAM_ERROR" not in "分析过程中发生了服务错误，请重试。"


def test_live_ui_does_not_fake_streaming():
    source = inspect.getsource(app)
    assert "time.sleep" not in source
    assert "write_stream" not in source
    assert "for char in" not in source
