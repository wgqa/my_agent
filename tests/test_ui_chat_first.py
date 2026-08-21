"""G7-UI-01 Chat-first state and layering tests."""

from __future__ import annotations

from types import SimpleNamespace

from ui import app, renderers


class _Expander:
    def __init__(self, calls, label, expanded):
        self.calls = calls
        self.label = label
        self.expanded = expanded

    def __enter__(self):
        self.calls.append((self.label, self.expanded))
        return self

    def __exit__(self, *_args):
        return False


def test_conversations_create_switch_and_keep_mode_isolated(monkeypatch):
    monkeypatch.setattr(
        app.st,
        "session_state",
        SimpleNamespace(api_client=None),
    )
    app._init_state()
    first_id = app.st.session_state.active_conversation_id
    first = app._active_conversation()
    first["mode"] = "agent"
    first["messages"].append({"role": "user", "content": "first"})

    second_id = app._new_conversation()
    second = app._active_conversation()
    second["messages"].append({"role": "user", "content": "second"})
    second["title"] = app._title_for_question("second")

    assert second_id != first_id
    assert second["mode"] == "agent"
    assert second["messages"][0]["content"] == "second"
    app._switch_conversation(first_id)
    assert app._active_conversation()["messages"][0]["content"] == "first"
    assert app._active_conversation()["mode"] == "agent"


def test_title_is_local_truncated_first_question():
    title = app._title_for_question("  A very long first question " + "x" * 80)
    assert len(title) <= app.MAX_TITLE_LENGTH
    assert title.endswith("…")
    assert "A very long first question" in title


def test_agent_answer_keeps_execution_details_collapsed(monkeypatch):
    expanders = []
    monkeypatch.setattr(
        renderers.st,
        "expander",
        lambda label, expanded=False: _Expander(expanders, label, expanded),
    )
    monkeypatch.setattr(renderers.st, "markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(renderers.st, "caption", lambda *_args, **_kwargs: None)

    renderers.render_agent_result(
        {
            "status": "completed",
            "answer": "你好。",
            "planner": {"plan": {"action": "direct_answer"}},
            "trace": [{"event_type": "decision_completed"}],
        }
    )

    assert expanders == [("▶ View execution details", False)]


def test_tool_evidence_and_details_are_separate_collapsed_layers(monkeypatch):
    expanders = []
    monkeypatch.setattr(
        renderers.st,
        "expander",
        lambda label, expanded=False: _Expander(expanders, label, expanded),
    )
    monkeypatch.setattr(renderers.st, "markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(renderers.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(renderers.st, "text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(renderers.st, "columns", lambda *_args, **_kwargs: [
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
    ])

    renderers.render_tool_result(
        {
            "status": "completed",
            "answer": "工程答案",
            "evidence": [{
                "evidence_id": "E1",
                "kind": "project_code",
                "path": "src/app.py",
                "start_line": 1,
                "end_line": 2,
                "snippet": "answer = True",
            }],
            "tool_calls_used": 1,
        }
    )

    assert expanders == [
        ("Engineering Evidence (1)", False),
        ("▶ View execution details", False),
    ]


def test_api_unavailable_hides_chat_input(monkeypatch):
    state = SimpleNamespace(
        api_available=False,
        runtime_capabilities={"features": {"basic_rag": True}},
        conversations={"c1": {"id": "c1", "title": "x", "mode": "basic", "messages": []}},
        active_conversation_id="c1",
    )
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "error", lambda value: setattr(state, "error", value))
    monkeypatch.setattr(
        app.st,
        "chat_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("chat input must be hidden while API is unavailable")
        ),
    )

    app._tab_console("basic", 5)
    assert state.error.startswith("API unavailable")


def test_empty_conversation_renderer_has_no_debug_sections(monkeypatch):
    rendered = []
    monkeypatch.setattr(app.st, "markdown", lambda value, **_kwargs: rendered.append(value))
    app._render_empty_conversation()
    assert "How can I help?" in rendered[0]
    assert "Planner" not in rendered[0]
