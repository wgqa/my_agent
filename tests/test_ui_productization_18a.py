"""PRODUCTIZATION-18A pure presentation-logic tests.

These cover the UI models introduced for the Engineering Agent product shell:
evidence grouping, summary chips, workspace status rows, activity timeline,
refused≠failed banner variants, and starter prompts. None touches Streamlit.
"""

from __future__ import annotations

from ui import components
from ui.streaming import EngineeringStreamState, EngineeringStreamStep


def test_evidence_grouping_preserves_canonical_kind_order():
    evidence = [
        {"kind": "project_test", "evidence_id": "T1"},
        {"kind": "knowledge", "evidence_id": "K1"},
        {"kind": "project_code", "evidence_id": "C1"},
        {"kind": "project_code", "evidence_id": "C2"},
        {"kind": "project_doc", "evidence_id": "D1"},
        {"kind": "project_change", "evidence_id": "H1"},
    ]
    summary = components.evidence_summary(evidence)
    assert summary == {
        "project_code": 2,
        "knowledge": 1,
        "project_doc": 1,
        "project_change": 1,
        "project_test": 1,
    }
    chips = components.evidence_summary_html(summary)
    for label in ("CODE", "KNOWLEDGE", "DOC", "CHANGE", "TEST"):
        assert label in chips


def test_evidence_kind_label_maps_all_public_kinds():
    assert components.EVIDENCE_KIND_LABELS == {
        "knowledge": "KNOWLEDGE",
        "project_code": "CODE",
        "project_doc": "DOC",
        "project_change": "CHANGE",
        "project_test": "TEST",
    }
    assert components.evidence_kind_label("unknown") == "EVIDENCE"


def test_evidence_meta_shows_safe_location_only_for_code():
    code_item = {
        "kind": "project_code",
        "path": "core/engine.py",
        "start_line": 10,
        "end_line": 22,
        "snippet": "x",
    }
    assert components.evidence_meta_text(code_item) == "core/engine.py · lines 10-22"
    knowledge_item = {
        "kind": "knowledge",
        "source_name": "guide.md",
        "rank": 2,
        "score": 0.8212,
        "snippet": "x",
    }
    assert components.evidence_meta_text(knowledge_item) == "guide.md · rank 2 · score 0.821"


def test_evidence_card_introduces_e_identity_and_safe_snippet_html():
    item = {
        "kind": "project_code",
        "evidence_id": "E1",
        "path": "core/engine.py",
        "start_line": 1,
        "end_line": 5,
        "snippet": "def load(): <not html>",
    }
    card = components.evidence_card_html(item)
    assert "[E1]" in card
    assert "CODE" in card
    assert "core/engine.py · lines 1-5" in card
    assert "&lt;not html&gt;" in card.replace("<not html>", "&lt;not html&gt;") or "&lt;" in card


def test_workspace_status_model_shows_public_identity_without_paths():
    rows = components.workspace_status_model(
        {"project_name": "rag-knowledge-base"},
        True,
        {"ready": True, "verified": True, "file_count": 37},
    )
    assert [row["label"] for row in rows] == ["Project", "API", "Knowledge"]
    assert rows[0]["value"] == "rag-knowledge-base"
    assert rows[1]["value"] == "connected"
    assert rows[2]["value"] == "verified · 37 files"
    assert all(isinstance(row["state"], str) for row in rows)

    unavailable = components.workspace_status_model(None, False, None)
    assert all(row["state"] == "off" for row in unavailable)


def test_activity_timeline_uses_safe_icons_and_labels():
    state = EngineeringStreamState(
        analysis_started=True,
        steps=(
            EngineeringStreamStep((1, "code_search"), "code_search", "Search project code", "complete"),
            EngineeringStreamStep((2, "__verification__"), "__verification__", "证据仍不充分，继续调查", "blocked"),
            EngineeringStreamStep((3, "git_diff"), "git_diff", "Git diff", "running"),
        ),
        evidence=({"kind": "project_code", "path": "x"},),
    )
    html_text = components.activity_timeline_html(state)
    assert "Analyzing request" in html_text
    assert "Evidence · 1" in html_text
    assert "证据仍不充分，继续调查" in html_text
    for cls in ("activity-complete", "activity-blocked", "activity-running", "activity-muted"):
        assert cls in html_text


def test_status_banner_kind_distinguishes_refused_failed_deferred():
    assert components.status_banner_kind("refused") == "banner-refused"
    assert components.status_banner_kind("failed") == "banner-failed"
    assert components.status_banner_kind("deferred") == "banner-deferred"
    assert components.status_banner_kind(None) == "banner-deferred"


def test_execution_summary_preserves_safe_public_fields():
    summary = components.execution_summary(
        {
            "status": "refused",
            "reason_code": "INSUFFICIENT_EVIDENCE",
            "failure_code": "EVIDENCE_GAP",
            "iterations_used": 2,
            "tool_calls_used": 4,
            "tool_errors_used": 0,
        }
    )
    mapping = dict(summary)
    assert mapping["Status"] == "refused"
    assert mapping["Reason code"] == "INSUFFICIENT_EVIDENCE"
    assert mapping["Failure code"] == "EVIDENCE_GAP"
    assert mapping["Iterations"] == 2
    assert mapping["Tool calls"] == 4
    assert mapping["Tool errors"] == 0


def test_starter_prompts_are_clickable_text_and_question_pairs():
    assert len(components.STARTER_PROMPTS) == 4
    for display, question in components.STARTER_PROMPTS:
        assert display and question
        assert display not in question


def test_legacy_modes_remain_grouped_in_advanced_selector():
    from ui import app

    assert app.ADVANCED_DEMO_OPTIONS == [
        "Engineering Agent",
        "Basic RAG",
        "Agentic RAG",
        "Structured Tool Agent",
    ]
    assert app.DEFAULT_MODE == "engineering"
