"""G5-APP-04: Streamlit 渲染辅助。

只做展示，不做 HTTP。所有字段一律 `.get()` 防御式读取——UI 只能展示 API
返回的事实，绝不推断 CoT / 展示 Prompt / 制造"模型思考过程"。
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st


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
    render = mapping.get(status, st.info)
    render(f"Status: **{status}**")


# ══════════════════════════════════════════════════════════════
# Basic RAG
# ══════════════════════════════════════════════════════════════

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
    """Render the complete Basic RAG result in the current Streamlit run."""
    st.markdown(result.get("answer", ""))
    render_basic_sources(result.get("sources") or [])


# ══════════════════════════════════════════════════════════════
# Agentic RAG
# ══════════════════════════════════════════════════════════════

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

    subqueries = plan.get("subqueries") or []
    if subqueries:
        st.markdown("**Subqueries**")
        for i, sq in enumerate(subqueries, start=1):
            subquery_id = sq.get("id") or f"sq{i}"
            st.markdown(f"**{subquery_id}**  —  {sq.get('query', '—')}")
            if sq.get("evidence_target") is not None:
                st.markdown(f"Evidence target: {sq['evidence_target']}")


def render_agent_route(route: dict) -> None:
    st.markdown("#### Adaptive Route")
    _kv("Route", route.get("route", "—"))
    _kv("Retrieval Strategy", route.get("retrieval_strategy", "—"))
    st.caption("Planner 原因 vs Router 策略原因 分开展示：")
    _kv("Planner reason_code", route.get("reason_code", "—"))
    _kv("Router strategy_reason_code", route.get("strategy_reason_code", "—"))
    if route.get("router_policy_version") is not None:
        _kv("Router Policy Version", route["router_policy_version"])
    queries = route.get("queries")
    if queries:
        _kv("Queries", ", ".join(str(q) for q in queries))


def render_agent_verification(verification: dict) -> None:
    st.markdown("#### Verification")
    _kv("Status", verification.get("status", "—"))
    _kv("Reason Code", verification.get("reason_code", "—"))
    _kv("Can Generate", verification.get("can_generate", "—"))
    _kv("Coverage Complete", verification.get("coverage_complete", "—"))
    _kv("Evidence Count", verification.get("evidence_count", "—"))
    if verification.get("upgrade_attempted") is not None:
        _kv("Upgrade Attempted", verification["upgrade_attempted"])
    if verification.get("upgrade_used") is not None:
        _kv("Upgrade Used", verification["upgrade_used"])
    for label, key in (
        ("Required", "required_query_ids"),
        ("Covered", "covered_query_ids"),
        ("Missing", "missing_query_ids"),
    ):
        ids = verification.get(key)
        if ids:
            st.markdown(f"**{label}:** {', '.join(str(i) for i in ids)}")


def render_agent_sources(sources: list) -> None:
    if not sources:
        return
    st.subheader("Evidence / Sources")
    for src in sources:
        citation = src.get("citation_id", "?")
        source = src.get("source", "?")
        query_id = src.get("query_id")
        rank = src.get("rank")
        score = format_score(src.get("score"))
        content = src.get("content", "")
        header = f"[{citation}] {source}"
        meta = []
        if query_id is not None:
            meta.append(f"query_id: {query_id}")
        if rank is not None:
            meta.append(f"rank: {rank}")
        meta.append(f"score: {score}")
        with st.expander(f"{header}  ·  {' · '.join(meta)}"):
            st.text(content or "（无内容）")
            chunk_id = src.get("chunk_id")
            doc_id = src.get("document_id")
            if chunk_id or doc_id:
                st.caption(f"chunk_id: {chunk_id or '—'}  |  document_id: {doc_id or '—'}")


def render_agent_trace(trace: list) -> None:
    if not trace:
        return
    with st.expander("▶ Execution Trace"):
        for event in trace:
            event_type = event.get("event_type", "?")
            summary = event.get("summary")
            if summary:
                st.markdown(f"**{event_type}**  —  {summary}")
            else:
                st.markdown(f"**{event_type}**")


def render_agent_result(result: dict) -> None:
    _status_ui(result.get("status", "?"))
    run_id = result.get("run_id")
    if run_id:
        _kv("Run ID", run_id)
    answer = result.get("answer")
    if answer:
        st.markdown("#### Answer")
        st.markdown(answer)
    if result.get("error_code") is not None:
        _kv("Error Code", result["error_code"])
    warnings = result.get("warnings")
    if warnings:
        _kv("Warnings", "; ".join(str(w) for w in warnings))

    planner = result.get("planner")
    if planner:
        render_agent_planner(planner)
    route = result.get("route")
    if route:
        render_agent_route(route)
    verification = result.get("verification")
    if verification:
        render_agent_verification(verification)
    render_agent_sources(result.get("sources") or [])
    render_agent_trace(result.get("trace") or [])


# ══════════════════════════════════════════════════════════════
# Structured Tool Agent
# ══════════════════════════════════════════════════════════════

def render_tool_counters(result: dict) -> None:
    cols = st.columns(3)
    cols[0].metric("Iterations", result.get("iterations_used", 0))
    cols[1].metric("Tool Calls", result.get("tool_calls_used", 0))
    cols[2].metric("Tool Errors", result.get("tool_errors_used", 0))


def render_tool_trace(trace: list) -> None:
    if not trace:
        return
    with st.expander("▶ Tool Execution Trace"):
        for event in trace:
            event_type = event.get("event_type", "?")
            iteration = event.get("iteration")
            action_type = event.get("action_type")
            tool_name = event.get("tool_name")
            tool_status = event.get("tool_status")
            error_code = event.get("error_code")

            heading = f"Iteration {iteration}" if iteration is not None else event_type
            st.markdown(f"**{heading}**  ·  `{event_type}`")

            if action_type:
                st.markdown(f"Decision: action_type = `{action_type}`")
            if tool_name:
                st.markdown(f"Decision: tool_name = `{tool_name}`")
            if tool_status:
                st.markdown(f"Tool Result: status = `{tool_status}`")
            if error_code is not None:
                st.markdown(f"Error Code: `{error_code}`")


def render_tool_result(result: dict) -> None:
    _status_ui(result.get("status", "?"))
    render_tool_counters(result)
    if result.get("reason_code") is not None:
        _kv("Reason Code", result["reason_code"])
    if result.get("failure_code") is not None:
        _kv("Failure Code", result["failure_code"])
    answer = result.get("answer")
    if answer:
        st.markdown("#### Answer")
        st.markdown(answer)
    render_tool_trace(result.get("trace") or [])
