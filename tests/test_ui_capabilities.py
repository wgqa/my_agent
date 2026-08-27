"""Capability-aware Streamlit UI logic tests."""

from __future__ import annotations

from types import SimpleNamespace

from ui import app
from ui.api_client import ApiError


def _state(capabilities):
    return SimpleNamespace(
        api_client=None,
        runtime_capabilities=capabilities,
        capabilities_available=capabilities is not None,
        messages_by_mode={"basic": [], "agent": [], "tool_agent": []},
    )


def test_feature_mapping_is_strict_and_conservative(monkeypatch):
    capabilities = {
        "features": {
            "engineering_agent": True,
            "indexing": True,
            "basic_rag": True,
            "agentic_rag": False,
            "structured_tool_agent": False,
        }
    }
    monkeypatch.setattr(app.st, "session_state", _state(capabilities))

    assert app._feature_enabled("engineering_agent") is True
    assert app._feature_enabled("basic_rag") is True
    assert app._feature_enabled("agentic_rag") is False
    assert app._feature_enabled("structured_tool_agent") is False
    assert app._feature_enabled("missing") is False


def test_unavailable_mode_does_not_render_chat_or_call_query(monkeypatch):
    class FailingClient:
        def agent_query(self, *_args):
            raise AssertionError("unavailable mode must not call agent_query")

    monkeypatch.setattr(
        app.st,
        "session_state",
        _state({"features": {"agentic_rag": False}}),
    )
    app.st.session_state.api_client = FailingClient()
    monkeypatch.setattr(app.st, "warning", lambda _value: None)
    monkeypatch.setattr(
        app.st,
        "chat_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unavailable mode must hide chat input")
        ),
    )

    app._tab_console("Agentic RAG", 5)


def test_unavailable_engineering_mode_does_not_render_chat_or_call_query(monkeypatch):
    class FailingClient:
        def engineering_query(self, *_args):
            raise AssertionError("unavailable mode must not call engineering_query")

    monkeypatch.setattr(
        app.st,
        "session_state",
        _state({"features": {"engineering_agent": False}}),
    )
    app.st.session_state.api_client = FailingClient()
    monkeypatch.setattr(app.st, "warning", lambda _value: None)
    monkeypatch.setattr(
        app.st,
        "chat_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unavailable mode must hide chat input")
        ),
    )

    app._tab_console("engineering", 5)


def test_engineering_submission_uses_engineering_endpoint_only(monkeypatch):
    calls = []

    class Client:
        def engineering_query(self, question):
            raise AssertionError("Engineering UI must use the SSE endpoint")

        def engineering_query_stream(self, question):
            calls.append(question)
            yield {"type": "status", "stage": "analysis", "state": "started"}
            yield {"type": "answer_start"}
            yield {"type": "answer_delta", "delta": "Grounded answer"}
            yield {
                "type": "final",
                "result": {"status": "completed", "answer": "Grounded answer"},
            }
            yield {"type": "done"}

    class Placeholder:
        def markdown(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def empty(self):
            return None

    class Status(Placeholder):
        def empty(self):
            return Placeholder()

        def update(self, *_args, **_kwargs):
            return None

    class Column:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

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
    monkeypatch.setattr(app.st, "markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app.st, "chat_input", lambda *_args, **_kwargs: "Trace config")
    monkeypatch.setattr(app.st, "columns", lambda *_args, **_kwargs: (Column(), Column()))
    monkeypatch.setattr(app.st, "status", lambda *_args, **_kwargs: Status())
    monkeypatch.setattr(app.st, "empty", lambda *_args, **_kwargs: Placeholder())
    monkeypatch.setattr(app.st, "rerun", lambda: None)

    app._tab_console("engineering", 9)

    assert calls == ["Trace config"]
    assert state.conversations["c1"]["messages"] == [
        {"role": "user", "content": "Trace config"},
        {
            "role": "assistant",
            "content": "Grounded answer",
            "kind": "engineering",
            "result": {"status": "completed", "answer": "Grounded answer"},
        },
    ]


def test_indexing_disabled_does_not_call_index_file(monkeypatch):
    class Client:
        def index_file(self, *_args):
            raise AssertionError("indexing-disabled UI must not upload")

        def stats(self):
            raise ApiError("connection_error", "offline")

    class Column:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(app.st, "session_state", _state({"features": {"indexing": False}}))
    app.st.session_state.api_client = Client()
    monkeypatch.setattr(app.st, "columns", lambda *_args: (Column(), Column()))
    monkeypatch.setattr(app.st, "subheader", lambda *_args: None)
    monkeypatch.setattr(app.st, "warning", lambda _value: None)
    monkeypatch.setattr(app.st, "info", lambda _value: None)

    def fail_file_uploader(*_args, **_kwargs):
        raise AssertionError("file uploader must be hidden when indexing is unavailable")

    monkeypatch.setattr(app.st, "file_uploader", fail_file_uploader)
    app._tab_knowledge_base()


def test_capabilities_failure_is_converted_to_unavailable(monkeypatch):
    class Client:
        def capabilities(self):
            raise ApiError("connection_error", "offline")

    assert app._read_capabilities(Client()) is None


def test_project_identity_display_uses_only_api_fields(monkeypatch):
    rendered = []
    monkeypatch.setattr(app.st, "markdown", lambda value: rendered.append(value))
    monkeypatch.setattr(app.st, "caption", lambda value: rendered.append(value))

    app._render_project_identity(
        {"project_name": "fastapi", "source": "configured"}
    )

    assert rendered == ["#### Engineering Project", "✓ fastapi"]
