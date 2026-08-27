"""Safe, layered Streamlit rendering for the Chat-first UI.

Answer and evidence are the default presentation. Runtime metadata remains
available in a collapsed execution-details section and is sourced only from
the public API response.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from ui.streaming import EngineeringStreamState


EVIDENCE_KIND_LABELS = {
    "knowledge": "KNOWLEDGE",
    "project_code": "CODE",
    "project_doc": "DOC",
    "project_change": "CHANGE",
    "project_test": "TEST",
}

STATUS_MESSAGES = {
    "refused": "I couldn't complete this safely with the available evidence.",
    "deferred": "This analysis needs another pass before it can be completed.",
    "failed": "The engineering analysis could not be completed.",
}


def format_score(score: Optional[float]) -> str:
    if score is None:
        return "N/A"
    try:
        return f"{score:.3f}"
    except (TypeError, ValueError):
        return "N/A"


def _status_ui(status: str) -> None:
    mapping = {
        "completed": st.success,
        "refused": st.warning,
        "deferred": st.warning,
        "failed": st.error,
    }
    message = STATUS_MESSAGES.get(status, "The request did not complete.")
    mapping.get(status, st.info)(message)


def _render_answer(answer: Any) -> None:
    if isinstance(answer, str) and answer.strip():
        st.markdown(answer)
    else:
        st.caption("No answer returned")


def render_basic_sources(sources: list) -> None:
    if not sources:
        return
    st.subheader("Sources")
    for i, src in enumerate(sources, start=1):
        source = src.get("source", "?")
        score = format_score(src.get("score"))
        content = src.get("content", "")
        with st.expander(f"[{i}] {source}  (score: {score})"):
            st.text(content or "（无内容）")


def render_basic_result(result: dict) -> None:
    _render_answer(result.get("answer"))
    render_basic_sources(result.get("sources") or [])


def _kv(key: str, value: Any, label: Optional[str] = None) -> None:
    st.markdown(f"**{label or key}:** {value}")


def render_agent_planner(planner: dict) -> None:
    st.markdown("#### Planner")
    plan = planner.get("plan") or {}
    _kv("Plan ID", plan.get("plan_id", "—"))
    _kv("Query Type", plan.get("query_type", "—"))
    _kv("Action", plan.get("action", "—"))
    _kv("Retrieval Required", plan.get("retrieval_required", "—"))
    _kv("Reason Code", plan.get("reason_code", "—"))
    _kv("Fallback Used", planner.get("fallback_used", "—"))
    if planner.get("failure_code") is not None:
        _kv("Failure Code", planner["failure_code"])
    for i, subquery in enumerate(plan.get("subqueries") or [], start=1):
        subquery_id = subquery.get("id") or f"sq{i}"
        st.markdown(f"**{subquery_id}**  —  {subquery.get('query', '—')}")
        if subquery.get("evidence_target") is not None:
            st.markdown(f"Evidence target: {subquery['evidence_target']}")


def render_agent_route(route: dict) -> None:
    st.markdown("#### Adaptive Route")
    _kv("Route", route.get("route", "—"))
    _kv("Retrieval Strategy", route.get("retrieval_strategy", "—"))
    _kv("Planner reason_code", route.get("reason_code", "—"))
    _kv("Router strategy_reason_code", route.get("strategy_reason_code", "—"))
    if route.get("router_policy_version") is not None:
        _kv("Router Policy Version", route["router_policy_version"])
    queries = route.get("queries")
    if queries:
        _kv("Queries", ", ".join(str(q) for q in queries))


def render_agent_verification(verification: dict) -> None:
    st.markdown("#### Verification")
    for label, key in (
        ("Status", "status"),
        ("Reason Code", "reason_code"),
        ("Can Generate", "can_generate"),
        ("Coverage Complete", "coverage_complete"),
        ("Evidence Count", "evidence_count"),
        ("Upgrade Attempted", "upgrade_attempted"),
        ("Upgrade Used", "upgrade_used"),
    ):
        if key in verification:
            _kv(label, verification.get(key, "—"))
    for label, key in (("Required", "required_query_ids"), ("Covered", "covered_query_ids"), ("Missing", "missing_query_ids")):
        ids = verification.get(key)
        if ids:
            st.markdown(f"**{label}:** {', '.join(str(i) for i in ids)}")


def _render_agent_sources_body(sources: list) -> None:
    for src in sources:
        citation = src.get("citation_id", "?")
        source = src.get("source", "?")
        meta = []
        if src.get("query_id") is not None:
            meta.append(f"query {src['query_id']}")
        if src.get("rank") is not None:
            meta.append(f"rank {src['rank']}")
        meta.append(f"score {format_score(src.get('score'))}")
        st.markdown(f"**[{citation}] {source}** · {' · '.join(meta)}")
        st.text(src.get("content", "") or "（无内容）")
        chunk_id = src.get("chunk_id")
        doc_id = src.get("document_id")
        if chunk_id or doc_id:
            st.caption(f"chunk_id: {chunk_id or '—'} · document_id: {doc_id or '—'}")


def render_agent_sources(sources: list, *, collapsed: bool = False) -> None:
    if not sources:
        return
    if collapsed:
        with st.expander(f"Sources / Evidence ({len(sources)})", expanded=False):
            _render_agent_sources_body(sources)
    else:
        st.subheader("Evidence / Sources")
        _render_agent_sources_body(sources)


def _render_agent_trace_body(trace: list) -> None:
    for event in trace:
        event_type = event.get("event_type", "?")
        summary = event.get("summary")
        st.markdown(f"**{event_type}**" + (f" · {summary}" if summary else ""))


def render_agent_trace(trace: list, *, collapsed: bool = True) -> None:
    if not trace:
        return
    if collapsed:
        with st.expander("▶ Execution Trace", expanded=False):
            _render_agent_trace_body(trace)
    else:
        st.markdown("#### Execution Trace")
        _render_agent_trace_body(trace)


def _agent_has_details(result: dict) -> bool:
    return (
        any(result.get(key) for key in ("planner", "route", "verification", "trace", "warnings", "error_code"))
        or result.get("status") not in (None, "completed")
    )


def render_agent_result(result: dict) -> None:
    if result.get("status") not in (None, "completed"):
        _status_ui(result.get("status", "?"))
    _render_answer(result.get("answer"))
    render_agent_sources(result.get("sources") or [], collapsed=True)
    with st.expander("▶ View execution details", expanded=False):
        if result.get("planner"):
            render_agent_planner(result["planner"])
        if result.get("route"):
            render_agent_route(result["route"])
        if result.get("verification"):
            render_agent_verification(result["verification"])
        if result.get("warnings"):
            _kv("Warnings", "; ".join(str(item) for item in result["warnings"]))
        if result.get("error_code") is not None:
            _kv("Error Code", result["error_code"])
        render_agent_trace(result.get("trace") or [], collapsed=False)
        if not _agent_has_details(result):
            st.caption("No additional execution details")


def _render_tool_evidence_body(evidence: list) -> None:
    for item in evidence:
        evidence_id = item.get("evidence_id", "?")
        kind_label = EVIDENCE_KIND_LABELS.get(item.get("kind"), "EVIDENCE")
        path = item.get("path", "?")
        start_line = item.get("start_line", "?")
        end_line = item.get("end_line", "?")
        st.markdown(f"**{evidence_id} · {kind_label}**")
        st.caption(f"{path} · lines {start_line}-{end_line}")
        st.text(item.get("snippet", ""))


def _render_engineering_evidence_body(evidence: list) -> None:
    for item in evidence:
        evidence_id = item.get("evidence_id", "?")
        kind = item.get("kind")
        kind_label = EVIDENCE_KIND_LABELS.get(kind, "EVIDENCE")
        source = item.get("source_name") or item.get("path") or "Unknown source"
        st.markdown(f"**{evidence_id} · {kind_label}**")
        if kind == "knowledge":
            rank = item.get("rank")
            score = format_score(item.get("score"))
            metadata = [source]
            if rank is not None:
                metadata.append(f"rank {rank}")
            metadata.append(f"score {score}")
            st.caption(" · ".join(metadata))
        else:
            start_line = item.get("start_line", "?")
            end_line = item.get("end_line", "?")
            st.caption(f"{source} · lines {start_line}-{end_line}")
        st.text(item.get("snippet", "") or "(No snippet returned)")


def render_engineering_evidence(evidence: list) -> None:
    if not evidence:
        st.caption("No evidence was returned.")
        return
    with st.expander(f"Evidence ({len(evidence)})", expanded=False):
        _render_engineering_evidence_body(evidence)


def render_tool_evidence(evidence: list) -> None:
    if not evidence:
        return
    st.subheader("Evidence")
    _render_tool_evidence_body(evidence)


def _render_tool_trace_body(trace: list) -> None:
    for event in trace:
        event_type = event.get("event_type", "?")
        heading = f"Iteration {event.get('iteration')}" if event.get("iteration") is not None else event_type
        st.markdown(f"**{heading}** · `{event_type}`")
        if event.get("action_type"):
            st.markdown(f"Action: `{event['action_type']}`")
        if event.get("tool_name"):
            st.markdown(f"Tool: `{event['tool_name']}`")
        if event.get("tool_status"):
            st.markdown(f"Tool status: `{event['tool_status']}`")
        if event.get("error_code") is not None:
            st.markdown(f"Error code: `{event['error_code']}`")


def render_tool_trace(trace: list, *, collapsed: bool = True) -> None:
    if not trace:
        return
    if collapsed:
        with st.expander("▶ Tool Execution Trace", expanded=False):
            _render_tool_trace_body(trace)
    else:
        st.markdown("#### Tool Execution Trace")
        _render_tool_trace_body(trace)


def render_tool_result(result: dict) -> None:
    if result.get("status") not in (None, "completed"):
        _status_ui(result.get("status", "?"))
    _render_answer(result.get("answer"))
    evidence = result.get("evidence") or []
    if evidence:
        with st.expander(f"Engineering Evidence ({len(evidence)})", expanded=False):
            _render_tool_evidence_body(evidence)
    with st.expander("▶ View execution details", expanded=False):
        cols = st.columns(3)
        cols[0].metric("Iterations", result.get("iterations_used", 0))
        cols[1].metric("Tool Calls", result.get("tool_calls_used", 0))
        cols[2].metric("Tool Errors", result.get("tool_errors_used", 0))
        if result.get("reason_code") is not None:
            _kv("Reason Code", result["reason_code"])
        if result.get("failure_code") is not None:
            _kv("Failure Code", result["failure_code"])
        render_tool_trace(result.get("trace") or [], collapsed=False)


def render_engineering_result(result: dict) -> None:
    """Render the public Engineering Agent response in a chat-friendly layout."""
    status = result.get("status")
    if status not in (None, "completed"):
        _status_ui(status)
    _render_answer(result.get("answer"))
    render_engineering_evidence(result.get("evidence") or [])

    with st.expander("Execution details", expanded=False):
        cols = st.columns(3)
        cols[0].metric("Iterations", result.get("iterations_used", 0))
        cols[1].metric("Tool calls", result.get("tool_calls_used", 0))
        cols[2].metric("Tool errors", result.get("tool_errors_used", 0))
        if status is not None:
            _kv("Status", status)
        if result.get("reason_code") is not None:
            _kv("Reason code", result["reason_code"])
        if result.get("failure_code") is not None:
            _kv("Failure code", result["failure_code"])
        render_tool_trace(result.get("trace") or [], collapsed=False)


def render_engineering_stream_status(
    container,
    state: EngineeringStreamState,
    *,
    final: bool = False,
) -> None:
    """Render only the safe, user-facing progress summary for an SSE run."""

    lines = ["✓ 分析任务" if state.analysis_started else "● 正在分析任务"]
    icons = {
        "running": "●",
        "complete": "✓",
        "error": "!",
        "blocked": "↻",
    }
    lines.extend(
        f"{icons.get(step.state, '●')} {step.label}" for step in state.steps
    )
    if state.evidence:
        lines.append(f"Evidence · {len(state.evidence)}")
    if state.error_code:
        lines.append("! 分析过程中发生了服务错误，请重试。")
    elif final:
        lines.append("✓ 分析完成")

    text = "\n".join(lines)
    renderer = getattr(container, "markdown", None)
    if callable(renderer):
        renderer(text)
    else:
        st.markdown(text)
