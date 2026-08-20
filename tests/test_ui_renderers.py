"""Minimal UI rendering regression tests."""

from __future__ import annotations

from types import SimpleNamespace

from ui import app, renderers


def test_basic_submit_renders_answer_and_sources_immediately(monkeypatch):
    result = {
        "answer": "即时答案",
        "sources": [{"source": "a.md", "content": "证据", "score": 0.9}],
    }
    rendered = []

    class FakeClient:
        def query(self, question, top_k):
            assert question == "问题"
            assert top_k == 5
            return result

    monkeypatch.setattr(app.st, "session_state", SimpleNamespace(api_client=FakeClient()))
    monkeypatch.setattr(renderers.st, "markdown", lambda value: rendered.append(("markdown", value)))
    monkeypatch.setattr(
        renderers,
        "render_basic_sources",
        lambda sources: rendered.append(("sources", sources)),
    )

    reply = app._submit("问题", "basic", 5)

    assert reply["result"] == result
    assert rendered == [("markdown", "即时答案"), ("sources", result["sources"])]


def test_planner_renderer_reads_api_contract_fields(monkeypatch):
    values = []
    markdown = []
    planner = {
        "fallback_used": True,
        "failure_code": "PLANNER_TIMEOUT",
        "reason_code": "old-top-level-value",
        "plan": {
            "plan_id": "abc123",
            "query_type": "comparison",
            "retrieval_required": True,
            "action": "decomposed_retrieval",
            "reason_code": "COMPARISON_EVIDENCE",
            "subqueries": [{"id": "api-sq-a", "query": "甲"}],
        },
    }

    monkeypatch.setattr(
        renderers,
        "_kv",
        lambda key, value, label=None: values.append((label or key, value)),
    )
    monkeypatch.setattr(renderers.st, "markdown", lambda value: markdown.append(value))

    renderers.render_agent_planner(planner)

    assert ("Plan ID", "abc123") in values
    assert ("Query Type", "comparison") in values
    assert ("Action", "decomposed_retrieval") in values
    assert ("Retrieval Required", True) in values
    assert ("Reason Code", "COMPARISON_EVIDENCE") in values
    assert ("Fallback Used", True) in values
    assert ("Failure Code", "PLANNER_TIMEOUT") in values
    assert "**api-sq-a**  —  甲" in markdown
    assert ("Reason", "old-top-level-value") not in values


def test_tool_evidence_renderer_shows_doc_and_code(monkeypatch):
    markdown = []
    captions = []
    snippets = []
    headers = []
    monkeypatch.setattr(renderers.st, "subheader", lambda value: headers.append(value))
    monkeypatch.setattr(renderers.st, "markdown", lambda value: markdown.append(value))
    monkeypatch.setattr(renderers.st, "caption", lambda value: captions.append(value))
    monkeypatch.setattr(renderers.st, "text", lambda value: snippets.append(value))

    renderers.render_tool_evidence([
        {
            "evidence_id": "E1",
            "kind": "project_doc",
            "path": "README.md",
            "start_line": 1,
            "end_line": 1,
            "snippet": "ENABLE_CACHE=true enables application caching.",
        },
        {
            "evidence_id": "E2",
            "kind": "project_code",
            "path": "src/config.py",
            "start_line": 1,
            "end_line": 3,
            "snippet": "def load_settings():",
        },
    ])

    assert headers == ["Evidence"]
    assert markdown == ["**E1 · DOC**", "**E2 · CODE**"]
    assert captions == ["README.md · lines 1-1", "src/config.py · lines 1-3"]
    assert snippets == [
        "ENABLE_CACHE=true enables application caching.",
        "def load_settings():",
    ]
