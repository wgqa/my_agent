"""G7-UI-01 Chat-first state and layering tests."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from ui.api_client import ApiError
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
    assert second["mode"] == app.DEFAULT_MODE == "engineering"
    assert second["messages"][0]["content"] == "second"
    app._switch_conversation(first_id)
    assert app._active_conversation()["messages"][0]["content"] == "first"
    assert app._active_conversation()["mode"] == "agent"


def test_default_conversation_uses_engineering_agent():
    assert app._conversation()["mode"] == app.DEFAULT_MODE == "engineering"


def test_legacy_demo_modes_remain_in_advanced_demo_selection():
    assert app.ADVANCED_DEMO_OPTIONS == [
        "Engineering Agent",
        "Basic RAG",
        "Agentic RAG",
        "Structured Tool Agent",
    ]
    assert "st.radio" not in inspect.getsource(app.main)


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
    assert "What can I help with?" in rendered[0]
    assert "Trace a config value" in rendered[0]
    assert "Assess a commit's impact" in rendered[0]
    assert "Compare documented API behavior" in rendered[0]
    assert "Diagnose a configuration issue" in rendered[0]
    assert "Planner" not in rendered[0]


def test_product_shell_does_not_fake_streaming():
    source = inspect.getsource(app)
    assert "time.sleep" not in source
    assert "write_stream" not in source
    assert "for character in" not in source


class _Placeholder:
    def markdown(self, *_args, **_kwargs):
        return None

    def caption(self, *_args, **_kwargs):
        return None

    def empty(self):
        return None


class _Status(_Placeholder):
    def empty(self):
        return _Placeholder()

    def update(self, *_args, **_kwargs):
        return None


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _install_live_ui_stubs(monkeypatch):
    monkeypatch.setattr(app.st, "columns", lambda *_args, **_kwargs: (_Column(), _Column()))
    monkeypatch.setattr(app.st, "status", lambda *_args, **_kwargs: _Status())
    monkeypatch.setattr(app.st, "empty", lambda *_args, **_kwargs: _Placeholder())
    monkeypatch.setattr(app.st, "markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app.st, "error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app.st, "rerun", lambda: None)


def test_engineering_chat_persists_only_a_complete_sse_result(monkeypatch):
    calls = []

    class Client:
        def engineering_query(self, *_args):
            raise AssertionError("live Engineering UI must not use synchronous query")

        def engineering_query_stream(self, question):
            calls.append(question)
            yield {"type": "status", "stage": "analysis", "state": "started"}
            yield {"type": "answer_start"}
            yield {"type": "answer_delta", "delta": "Final answer"}
            yield {
                "type": "final",
                "result": {"status": "completed", "answer": "Final answer"},
            }
            yield {"type": "done"}

    state = SimpleNamespace(
        api_client=Client(),
        api_available=True,
        runtime_capabilities={"features": {"engineering_agent": True}},
        conversations={
            "c1": {"id": "c1", "title": "New conversation", "mode": "engineering", "messages": []}
        },
        active_conversation_id="c1",
    )
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "chat_input", lambda *_args, **_kwargs: "Trace config")
    _install_live_ui_stubs(monkeypatch)

    app._tab_console("engineering", 5)

    assert calls == ["Trace config"]
    assert state.conversations["c1"]["messages"] == [
        {"role": "user", "content": "Trace config"},
        {
            "role": "assistant",
            "content": "Final answer",
            "kind": "engineering",
            "result": {"status": "completed", "answer": "Final answer"},
        },
    ]


def test_engineering_chat_discards_partial_answer_on_stream_error(monkeypatch):
    class Client:
        def engineering_query_stream(self, _question):
            yield {"type": "status", "stage": "analysis", "state": "started"}
            yield {"type": "answer_start"}
            yield {"type": "answer_delta", "delta": "partial"}
            raise ApiError("connection_error", "offline")

    state = SimpleNamespace(
        api_client=Client(),
        api_available=True,
        runtime_capabilities={"features": {"engineering_agent": True}},
        conversations={
            "c1": {"id": "c1", "title": "New conversation", "mode": "engineering", "messages": []}
        },
        active_conversation_id="c1",
    )
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "chat_input", lambda *_args, **_kwargs: "Trace config")
    _install_live_ui_stubs(monkeypatch)

    app._tab_console("engineering", 5)

    assert state.conversations["c1"]["messages"] == [
        {"role": "user", "content": "Trace config"}
    ]
