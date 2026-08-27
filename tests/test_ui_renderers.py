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


def test_tool_evidence_renderer_shows_all_evidence_kinds(monkeypatch):
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
            "evidence_id": "E0",
            "kind": "knowledge",
            "path": "guide.md",
            "start_line": 1,
            "end_line": 1,
            "snippet": "Grounding guidance.",
        },
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
        {
            "evidence_id": "E3",
            "kind": "project_change",
            "path": "core/config.py",
            "start_line": 8,
            "end_line": 12,
            "snippet": "changed = True",
        },
        {
            "evidence_id": "E4",
            "kind": "project_test",
            "path": "tests/test_config.py",
            "start_line": 4,
            "end_line": 9,
            "snippet": "def test_config():",
        },
    ])

    assert headers == ["Evidence"]
    assert markdown == [
        "**E0 · KNOWLEDGE**",
        "**E1 · DOC**",
        "**E2 · CODE**",
        "**E3 · CHANGE**",
        "**E4 · TEST**",
    ]
    assert captions == [
        "guide.md · lines 1-1",
        "README.md · lines 1-1",
        "src/config.py · lines 1-3",
        "core/config.py · lines 8-12",
        "tests/test_config.py · lines 4-9",
    ]
    assert snippets == [
        "Grounding guidance.",
        "ENABLE_CACHE=true enables application caching.",
        "def load_settings():",
        "changed = True",
        "def test_config():",
    ]


class _Expander:
    def __init__(self, calls, label, expanded, active):
        self.calls = calls
        self.label = label
        self.expanded = expanded
        self.active = active

    def __enter__(self):
        self.calls.append((self.label, self.expanded))
        self.active.append(self.label)
        return self

    def __exit__(self, *_args):
        self.active.pop()
        return False


def test_engineering_result_collapses_evidence_and_execution_details(monkeypatch):
    expanders = []
    active = []
    markdown = []
    captions = []
    snippets = []
    monkeypatch.setattr(
        renderers.st,
        "expander",
        lambda label, expanded=False: _Expander(expanders, label, expanded, active),
    )
    monkeypatch.setattr(
        renderers.st,
        "markdown",
        lambda value: markdown.append((active[-1] if active else None, value)),
    )
    monkeypatch.setattr(renderers.st, "caption", lambda value: captions.append(value))
    monkeypatch.setattr(renderers.st, "text", lambda value: snippets.append(value))
    monkeypatch.setattr(renderers.st, "columns", lambda *_args, **_kwargs: [
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
    ])

    renderers.render_engineering_result(
        {
            "status": "completed",
            "answer": "Engineering answer",
            "evidence": [
                {"evidence_id": "K1", "kind": "knowledge", "source_name": "guide", "rank": 1, "score": 0.9, "snippet": "k"},
                {"evidence_id": "C1", "kind": "project_code", "path": "src/a.py", "start_line": 1, "end_line": 2, "snippet": "c"},
                {"evidence_id": "D1", "kind": "project_doc", "path": "README.md", "start_line": 1, "end_line": 2, "snippet": "d"},
                {"evidence_id": "H1", "kind": "project_change", "path": "src/a.py", "start_line": 3, "end_line": 4, "snippet": "h"},
                {"evidence_id": "T1", "kind": "project_test", "path": "tests/test_a.py", "start_line": 5, "end_line": 6, "snippet": "t"},
            ],
            "iterations_used": 2,
            "tool_calls_used": 3,
            "tool_errors_used": 0,
        }
    )

    assert expanders == [("Evidence (5)", False), ("Execution details", False)]
    assert [value for _context, value in markdown] == [
        "Engineering answer",
        "**K1 · KNOWLEDGE**",
        "**C1 · CODE**",
        "**D1 · DOC**",
        "**H1 · CHANGE**",
        "**T1 · TEST**",
        "**Status:** completed",
    ]
    assert captions[:5] == [
        "guide · rank 1 · score 0.900",
        "src/a.py · lines 1-2",
        "README.md · lines 1-2",
        "src/a.py · lines 3-4",
        "tests/test_a.py · lines 5-6",
    ]
    assert snippets == ["k", "c", "d", "h", "t"]


def test_engineering_refusal_and_failure_codes_stay_in_execution_details(monkeypatch):
    active = []
    markdown = []
    warnings = []
    errors = []
    monkeypatch.setattr(
        renderers.st,
        "expander",
        lambda label, expanded=False: _Expander([], label, expanded, active),
    )
    monkeypatch.setattr(
        renderers.st,
        "markdown",
        lambda value: markdown.append((active[-1] if active else None, value)),
    )
    monkeypatch.setattr(renderers.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(renderers.st, "warning", lambda value: warnings.append(value))
    monkeypatch.setattr(renderers.st, "error", lambda value: errors.append(value))
    monkeypatch.setattr(renderers.st, "columns", lambda *_args, **_kwargs: [
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
        SimpleNamespace(metric=lambda *_args, **_kwargs: None),
    ])

    renderers.render_engineering_result(
        {
            "status": "refused",
            "answer": "I need more evidence.",
            "reason_code": "INSUFFICIENT_EVIDENCE_TO_FINALIZE",
            "failure_code": "EVIDENCE_GAP",
        }
    )
    renderers.render_engineering_result({"status": "failed", "answer": "Try again."})

    assert warnings == ["I couldn't complete this safely with the available evidence."]
    assert errors == ["The engineering analysis could not be completed."]
    assert all("INSUFFICIENT_EVIDENCE_TO_FINALIZE" not in value for context, value in markdown if context is None)
    assert all("EVIDENCE_GAP" not in value for context, value in markdown if context is None)
    details = [value for context, value in markdown if context == "Execution details"]
    assert "**Reason code:** INSUFFICIENT_EVIDENCE_TO_FINALIZE" in details
    assert "**Failure code:** EVIDENCE_GAP" in details
