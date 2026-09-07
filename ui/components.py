"""Pure presentation helpers for the product shell.

These functions model the UI without touching Streamlit so the 18A
productization tests can run without a DOM. ``app.py``/``renderers.py`` turn
the models below into actual widgets.
"""

from __future__ import annotations

import html
from typing import Any, Iterable


# Ordered kind list: 5 canonical engineering evidence kinds.
EVIDENCE_KIND_ORDER = (
    "project_code",
    "knowledge",
    "project_doc",
    "project_change",
    "project_test",
)

EVIDENCE_KIND_LABELS = {
    "knowledge": "KNOWLEDGE",
    "project_code": "CODE",
    "project_doc": "DOC",
    "project_change": "CHANGE",
    "project_test": "TEST",
}

# Starter cards for the empty state. Clicking never bypasses the standard
# chat path — the text is sent as the user's first question.
STARTER_PROMPTS = (
    ("Trace a configuration value to runtime behavior", "Trace a config value to how the runtime behaves at launch"),
    ("Explain how Planner → Retrieval → Verifier works", "Explain the Planner → Retrieval → Verifier pipeline"),
    ("Analyze a code change and recommend regression tests", "Analyze this code change and suggest regression tests"),
    ("Compare documentation with the current implementation", "Compare the docs with the current implementation"),
)


def group_evidence_by_kind(evidence: Iterable[dict]) -> dict[str, list[dict]]:
    """Group evidence preserving API order within each canonical kind."""

    grouped: dict[str, list[dict]] = {kind: [] for kind in EVIDENCE_KIND_ORDER}
    for item in evidence or []:
        kind = item.get("kind")
        if kind in EVIDENCE_KIND_ORDER:
            grouped[kind].append(item)
        else:
            grouped.setdefault(kind, [item])
    return {key: value for key, value in grouped.items() if value}


def evidence_summary(evidence: Iterable[dict]) -> dict[str, int]:
    """Return a {kind: count} mapping for the compact summary chips."""

    grouped = group_evidence_by_kind(evidence)
    return {kind: len(items) for kind, items in grouped.items()}


def evidence_kind_label(kind: Any) -> str:
    return EVIDENCE_KIND_LABELS.get(kind, "EVIDENCE")


def evidence_meta_text(item: dict) -> str:
    """Location metadata line that never reveals local absolute paths."""

    if item.get("kind") == "knowledge":
        meta = [item.get("source_name") or "unknown source"]
        if item.get("rank") is not None:
            meta.append(f"rank {item['rank']}")
        score = item.get("score")
        meta.append("score {0:.3f}".format(score) if isinstance(score, (int, float)) else "score N/A")
        return " · ".join(meta)
    source = item.get("path") or "Unknown source"
    return f"{source} · lines {item.get('start_line', '?')}-{item.get('end_line', '?')}"


def evidence_card_html(item: dict) -> str:
    """Build the escaped HTML for one evidence card."""

    evidence_id = html.escape(str(item.get("evidence_id", "?")))
    kind_label = html.escape(evidence_kind_label(item.get("kind")))
    meta = html.escape(evidence_meta_text(item))
    snippet = item.get("snippet")
    body = (
        f'<div class="evidence-card">'
        f'<div class="evidence-card-head">'
        f'<span class="evidence-id">[{evidence_id}]</span>'
        f'<span class="evidence-kind">{kind_label}</span>'
        f"</div>"
        f'<div class="evidence-meta">{meta}</div>'
    )
    if isinstance(snippet, str) and snippet.strip():
        body += f'<div class="evidence-snippet">{html.escape(snippet)}</div>'
    body += "</div>"
    return body


def evidence_summary_html(summary: dict[str, int]) -> str:
    chips = "".join(
        f'<span class="evidence-chip">{html.escape(evidence_kind_label(kind))} {count}</span>'
        for kind, count in summary.items()
    )
    return f'<div class="evidence-summary">{chips}</div>'


def activity_icon(step_state: str) -> tuple[str, str]:
    """Return (icon, css_class) for a timeline entry."""

    icons = {
        "running": ("●", "activity-running"),
        "complete": ("✓", "activity-complete"),
        "blocked": ("↻", "activity-blocked"),
        "error": ("✗", "activity-error"),
        "muted": ("·", "activity-muted"),
    }
    return icons.get(step_state, icons["running"])


def activity_timeline_html(state) -> str:
    """Render the reducer state as a sequence of escaped HTML lines."""

    lines: list[str] = []
    if getattr(state, "analysis_started", False):
        icon, cls = activity_icon("complete")
        lines.append(
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>Analyzing request</div>'
        )
    else:
        icon, cls = activity_icon("running")
        lines.append(
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>Analyzing request</div>'
        )
    for step in getattr(state, "steps", ()):
        icon, cls = activity_icon(step.state)
        label = html.escape(step.label)
        lines.append(
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>{label}</div>'
        )
    evidence_count = len(getattr(state, "evidence", ()))
    if evidence_count:
        icon, cls = activity_icon("muted")
        lines.append(
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>Evidence · {evidence_count}</div>'
        )
    if getattr(state, "error_code", None):
        icon, cls = activity_icon("error")
        lines.append(
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>Run failed</div>'
        )
    return "\n".join(lines)


def workspace_status_model(
    project: dict | None,
    api_available: bool,
    knowledge: dict | None,
) -> list[dict[str, str]]:
    """Compact public workspace rows for the sidebar."""

    rows: list[dict[str, str]] = []
    if isinstance(project, dict) and isinstance(project.get("project_name"), str):
        rows.append({"label": "Project", "value": project["project_name"], "state": "ok"})
    else:
        rows.append({"label": "Project", "value": "unavailable", "state": "off"})

    if api_available:
        rows.append({"label": "API", "value": "connected", "state": "ok"})
    else:
        rows.append({"label": "API", "value": "unavailable", "state": "off"})

    if isinstance(knowledge, dict):
        if knowledge.get("ready") is True and knowledge.get("verified") is True:
            rows.append(
                {
                    "label": "Knowledge",
                    "value": f"verified · {knowledge.get('file_count', '?')} files",
                    "state": "ok",
                }
            )
        elif knowledge.get("ready") is True:
            rows.append({"label": "Knowledge", "value": "ready, not verified", "state": "warn"})
        else:
            rows.append({"label": "Knowledge", "value": "unavailable", "state": "off"})
    else:
        rows.append({"label": "Knowledge", "value": "unavailable", "state": "off"})
    return rows


def execution_summary(result: dict) -> list[tuple[str, Any]]:
    """Public execution facts for the collapsed details section."""

    pairs: list[tuple[str, Any]] = [
        ("Iterations", result.get("iterations_used", 0)),
        ("Tool calls", result.get("tool_calls_used", 0)),
        ("Tool errors", result.get("tool_errors_used", 0)),
    ]
    if result.get("status") is not None:
        pairs.append(("Status", result["status"]))
    if result.get("reason_code") is not None:
        pairs.append(("Reason code", result["reason_code"]))
    if result.get("failure_code") is not None:
        pairs.append(("Failure code", result["failure_code"]))
    return pairs


def status_banner_kind(status: Any) -> str:
    """Classify a public status into a banner variant (refused ≠ failed ≠ deferred)."""

    if status == "refused":
        return "banner-refused"
    if status == "failed":
        return "banner-failed"
    return "banner-deferred"


__all__ = [
    "EVIDENCE_KIND_LABELS",
    "EVIDENCE_KIND_ORDER",
    "STARTER_PROMPTS",
    "activity_icon",
    "activity_timeline_html",
    "evidence_card_html",
    "evidence_kind_label",
    "evidence_meta_text",
    "evidence_summary",
    "evidence_summary_html",
    "execution_summary",
    "group_evidence_by_kind",
    "status_banner_kind",
    "workspace_status_model",
]
