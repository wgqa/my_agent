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
