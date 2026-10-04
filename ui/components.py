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

# Core workflow cards collect a concrete target before submitting a question
# through the ordinary chat path. They do not claim independent execution.
STARTER_PROMPTS = (
    ("Trace a configuration value to runtime behavior", "configuration"),
    ("Analyze a code change and recommend regression tests", "change_test"),
    ("Compare documentation with the current implementation", "docs_code"),
)


def build_core_workflow_question(workflow: str, subject: str, reference: str = "") -> str | None:
    """Require a user-supplied target; generate an ordinary bounded question."""
    subject = subject.strip()
    reference = reference.strip()
    if not subject or workflow not in {"configuration", "change_test", "docs_code"}:
        return None
    if workflow == "configuration":
        hint = f"已知相关源码位置：{reference}。" if reference else ""
        return (
            f"请在当前仓库追踪配置 {subject} 的默认值、覆盖与校验规则，以及它如何影响调用行为。"
            f"{hint}读取所需的实际默认值定义和调用点，引用源码；未取得的部分明确说明，"
            "不要把常量名当作默认数值，也不要用未读方法补全结论。"
        )
    if workflow == "change_test":
        return (
            f"变更文件已明确为当前仓库的 {subject}。请直接取得该文件的未提交 Git diff，"
            "分析行为影响，再按这个源码路径寻找关联的已有测试并读取实际测试定义；"
            "无需重新发现变更文件，也不要反复猜测改动常量名来搜索测试。"
            "指出实际读到的输入与断言如何覆盖该变更，给出基于真实测试名称的建议命令；"
            "找不到具体测试时说明缺口。只做静态分析，不执行测试，不声称已经通过。"
        )
    if not reference:
        return None
    return (
        f"请核对当前仓库文档 {subject} 与源码实现 {reference} 是否一致。"
        "读取文档和决定所问行为的实际实现，分别引用两边；逐项区分一致、冲突与未核实。"
        "只读到局部实现时不能断言整个调用链与文档矛盾。"
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


def evidence_kind_badge_html(kind: Any) -> str:
    """A small capability chip used above the landing-state hero."""

    label = evidence_kind_label(kind)
    return f'<span class="capability-chip">{html.escape(label)}</span>'


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
    """Build the escaped HTML for one evidence card header + meta.

    The snippet body is rendered separately so its raw text is never passed
    through Streamlit's markdown pre-processor.
    """

    evidence_id = html.escape(str(item.get("evidence_id", "?")))
    kind_label = html.escape(evidence_kind_label(item.get("kind")))
    meta = html.escape(evidence_meta_text(item))
    return (
        '<div class="evidence-card">'
        '<div class="evidence-card-head">'
        f'<span class="evidence-id">[{evidence_id}]</span>'
        f'<span class="evidence-kind">{kind_label}</span>'
        "</div>"
        f'<div class="evidence-meta">{meta}</div>'
        "</div>"
    )


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
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>Analyze request</div>'
        )
    else:
        icon, cls = activity_icon("running")
        lines.append(
            f'<div class="activity-line"><span class="activity-icon {cls}">{icon}</span>Analyze request</div>'
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


def execution_headline(result: dict) -> str:
    """One-line compressed execution summary.

    R1: lead with status. Iterations / tool calls / tool errors are pulled
    into a single line; errors are only surfaced when non-zero.
    """

    status = result.get("status") or "run"
    parts: list[str] = [str(status)]
    iterations = result.get("iterations_used", 0)
    if iterations:
        parts.append(f"{iterations} iteration" + ("s" if iterations != 1 else ""))
    tool_calls = result.get("tool_calls_used", 0)
    if tool_calls:
        parts.append(f"{tool_calls} tool call" + ("s" if tool_calls != 1 else ""))
    tool_errors = result.get("tool_errors_used", 0)
    if tool_errors:
        parts.append(f"{tool_errors} tool error" + ("s" if tool_errors != 1 else ""))
    return " · ".join(parts)


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
    "build_core_workflow_question",
    "activity_icon",
    "activity_timeline_html",
    "evidence_card_html",
    "evidence_kind_badge_html",
    "evidence_kind_label",
    "evidence_meta_text",
    "evidence_summary",
    "evidence_summary_html",
    "execution_headline",
    "execution_summary",
    "group_evidence_by_kind",
    "status_banner_kind",
    "workspace_status_model",
]
