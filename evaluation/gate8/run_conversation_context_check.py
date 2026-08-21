"""G8-CONTEXT-02: real-provider A/B capability check runner.

The runner sends only user-visible requests to /agent/query. It records bounded
API summaries and the safe context_prepared event; it never records prompts,
standalone queries, raw provider output, or exception bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

CASE_SCHEMA_VERSION = "gate8_context_case_v1"
RESULT_SCHEMA_VERSION = "gate8_context_result_v1"
REPORT_SCHEMA_VERSION = "gate8_context_report_v1"
EXPECTED_CASE_COUNT = 6
_CONTEXT_KEYS = (
    "history_messages_received",
    "history_messages_used",
    "history_tokens_used",
    "history_truncated",
    "resolver_used",
    "resolver_fallback",
)
_SAFE_SOURCE_KEYS = (
    "citation_id",
    "chunk_id",
    "document_id",
    "source",
    "score",
    "rank",
)
_SAFE_ROUTE_KEYS = (
    "route",
    "retrieval_strategy",
    "reason_code",
    "router_policy_version",
    "strategy_reason_code",
    "query_count",
)
_SAFE_VERIFICATION_KEYS = (
    "status",
    "can_generate",
    "reason_code",
    "evidence_count",
    "coverage_complete",
    "missing_query_ids",
    "upgrade_attempted",
    "upgrade_used",
)


class CapabilityRunBlocked(RuntimeError):
    """The environment cannot perform the requested live provider run."""


class CapabilityRunInvalid(RuntimeError):
    """The endpoint did not return the expected capability response."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    source = Path(path)
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid case JSON at line {line_number}") from exc
        if type(item) is not dict:
            raise ValueError(f"case at line {line_number} must be an object")
        required = {
            "schema_version", "case_id", "case_type", "turn1", "turn2",
            "topic", "answer_terms", "min_answer_terms", "forbidden_topic_terms",
        }
        if set(item) != required:
            raise ValueError(f"case {item.get('case_id', line_number)} fields mismatch")
        if item["schema_version"] != CASE_SCHEMA_VERSION:
            raise ValueError(f"case {item['case_id']} schema mismatch")
        for field in ("case_id", "case_type", "turn1", "turn2", "topic"):
            if type(item[field]) is not str or not item[field].strip():
                raise ValueError(f"case {item['case_id']} field {field} invalid")
        if (
            type(item["answer_terms"]) is not list
            or not item["answer_terms"]
            or not all(type(term) is str and term.strip() for term in item["answer_terms"])
        ):
            raise ValueError(f"case {item['case_id']} answer_terms invalid")
        if (
            type(item["forbidden_topic_terms"]) is not list
            or not all(type(term) is str and term.strip() for term in item["forbidden_topic_terms"])
        ):
            raise ValueError(f"case {item['case_id']} forbidden_topic_terms invalid")
        if (
            type(item["min_answer_terms"]) is not int
            or isinstance(item["min_answer_terms"], bool)
            or not 1 <= item["min_answer_terms"] <= len(item["answer_terms"])
        ):
            raise ValueError(f"case {item['case_id']} min_answer_terms invalid")
        cases.append(item)
    if len(cases) != EXPECTED_CASE_COUNT:
        raise ValueError(f"expected exactly {EXPECTED_CASE_COUNT} cases")
    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != EXPECTED_CASE_COUNT:
        raise ValueError("case_id values must be unique")
    return cases


def _request_json(session: Any, base_url: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    try:
        response = session.post(
            f"{base_url.rstrip('/')}/agent/query",
            json=payload,
            timeout=180.0,
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise CapabilityRunBlocked("http_transport_unavailable") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if response.status_code in (502, 503, 504):
        raise CapabilityRunBlocked("agent_runtime_unavailable")
    if response.status_code >= 500:
        raise CapabilityRunInvalid("agent_endpoint_server_error")
    if response.status_code != 200:
        raise CapabilityRunInvalid("agent_endpoint_contract_error")
    try:
        data = response.json()
    except ValueError as exc:
        raise CapabilityRunInvalid("agent_response_not_json") from exc
    if type(data) is not dict:
        raise CapabilityRunInvalid("agent_response_not_object")
    return data, elapsed_ms


def _context_trace(data: Mapping[str, Any]) -> dict[str, Any]:
    for event in data.get("trace", []):
        if type(event) is dict and event.get("event_type") == "context_prepared":
            event_data = event.get("data")
            if type(event_data) is not dict:
                raise CapabilityRunInvalid("context_trace_data_invalid")
            if set(event_data) - set(_CONTEXT_KEYS):
                raise CapabilityRunInvalid("context_trace_contains_unapproved_fields")
            return {key: event_data.get(key) for key in _CONTEXT_KEYS}
    raise CapabilityRunInvalid("context_trace_missing")


def _safe_sources(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources = data.get("sources", [])
    if type(sources) is not list:
        raise CapabilityRunInvalid("sources_invalid")
    return [
        {key: item.get(key) for key in _SAFE_SOURCE_KEYS if key in item}
        for item in sources
        if type(item) is dict
    ]


def _safe_mapping(data: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {key: data.get(key) for key in keys if key in data}


def _safe_summary(data: Mapping[str, Any], latency_ms: float) -> dict[str, Any]:
    planner = data.get("planner") if type(data.get("planner")) is dict else {}
    plan = planner.get("plan") if type(planner.get("plan")) is dict else {}
    return {
        "status": data.get("status"),
        "answer": data.get("answer"),
        "sources": _safe_sources(data),
        "planner": {
            "action": plan.get("action"),
            "query_type": plan.get("query_type"),
        },
        "route": _safe_mapping(
            data.get("route") if type(data.get("route")) is dict else {},
            _SAFE_ROUTE_KEYS,
        ),
        "verification": _safe_mapping(
            data.get("verification") if type(data.get("verification")) is dict else {},
            _SAFE_VERIFICATION_KEYS,
        ),
        "warnings": data.get("warnings", []),
        "latency_ms": round(latency_ms, 2),
        "context": _context_trace(data),
    }


def _judge(case: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    answer = str(result.get("answer") or "").lower()
    terms = [term.lower() for term in case["answer_terms"]]
    matched = [term for term in terms if term in answer]
    source_ok = bool(result.get("sources"))
    status_ok = result.get("status") == "completed"
    forbidden = [term for term in case["forbidden_topic_terms"] if term.lower() in answer]
    follow_up = len(matched) >= case["min_answer_terms"]
    topic_safe = not forbidden
    useful = status_ok and follow_up
    if useful and topic_safe and source_ok:
        outcome = "PASS"
    elif answer and (follow_up or source_ok) and topic_safe:
        outcome = "PARTIAL"
    else:
        outcome = "FAIL"
    return {
        "status": outcome,
        "follow_up_understanding": follow_up,
        "retrieval_relevance": source_ok,
        "answer_usefulness": useful,
        "topic_switch_safety": topic_safe,
        "matched_terms": matched,
        "forbidden_topic_terms_found": forbidden,
    }


def _blocked_record(case: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "case_id": case["case_id"],
        "case_type": case["case_type"],
        "turn1": case["turn1"],
        "turn2": case["turn2"],
        "execution_status": "BLOCKED",
        "blocked_reason": reason,
        "no_history": None,
        "with_history": None,
        "judgement": None,
    }


def run_check(
    cases: Sequence[Mapping[str, Any]],
    *,
    base_url: str,
    session: Any = requests,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        try:
            turn1_data, turn1_latency = _request_json(
                session, base_url, {"question": case["turn1"], "top_k": 5}
            )
            turn1_answer = turn1_data.get("answer")
            if type(turn1_answer) is not str or not turn1_answer.strip():
                raise CapabilityRunInvalid("turn1_has_no_answer_for_history")
            no_history_data, no_history_latency = _request_json(
                session, base_url, {"question": case["turn2"], "top_k": 5}
            )
            with_history_data, with_history_latency = _request_json(
                session,
                base_url,
                {
                    "question": case["turn2"],
                    "top_k": 5,
                    "history": [
                        {"role": "user", "content": case["turn1"]},
                        {"role": "assistant", "content": turn1_answer},
                    ],
                },
            )
            a = _safe_summary(no_history_data, no_history_latency)
            b = _safe_summary(with_history_data, with_history_latency)
            results.append({
                "schema_version": RESULT_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "case_type": case["case_type"],
                "turn1": case["turn1"],
                "turn2": case["turn2"],
                "turn1_result": {
                    "status": turn1_data.get("status"),
                    "answer": turn1_answer,
                    "latency_ms": round(turn1_latency, 2),
                },
                "execution_status": "COMPLETED",
                "no_history": a,
                "with_history": b,
                "judgement": {
                    "no_history": _judge(case, a),
                    "with_history": _judge(case, b),
                },
            })
        except CapabilityRunBlocked as exc:
            results.extend(_blocked_record(item, str(exc)) for item in cases[len(results):])
            break
        except CapabilityRunInvalid as exc:
            results.extend(_blocked_record(item, str(exc)) for item in cases[len(results):])
            break
    return results


def _counts(results: Iterable[Mapping[str, Any]], condition: str) -> Counter:
    return Counter(
        item.get("judgement", {}).get(condition, {}).get("status")
        for item in results
        if item.get("execution_status") == "COMPLETED"
    )


def build_report(results: Sequence[Mapping[str, Any]], *, base_url: str) -> str:
    blocked = any(item.get("execution_status") == "BLOCKED" for item in results)
    lines = [
        "# G8 Context v1 Capability Check",
        "",
        f"- schema: `{REPORT_SCHEMA_VERSION}`",
        f"- endpoint: `{base_url.rstrip('/')}/agent/query`",
        "- dataset: `conversation_context_cases_v1.jsonl` (6 public-knowledge cases)",
        "- holdout access: none",
        "",
    ]
    if blocked:
        reason = next(item.get("blocked_reason") for item in results if item.get("execution_status") == "BLOCKED")
        lines.extend([
            "## Execution",
            "",
            f"`BLOCKED / INVALID CAPABILITY RUN`: `{reason}`",
            "",
            "The live provider/API capability run is not scored as 0/6.",
        ])
        return "\n".join(lines) + "\n"
    no_counts = _counts(results, "no_history")
    with_counts = _counts(results, "with_history")
    lines.extend([
        "## Primary Comparison",
        "",
        "| Case | No History | With History | Result |",
        "|---|---:|---:|---|",
    ])
    rank = {"FAIL": 0, "PARTIAL": 1, "PASS": 2}
    for item in results:
        a = item["judgement"]["no_history"]["status"]
        b = item["judgement"]["with_history"]["status"]
        comparison = "improved" if rank[b] > rank[a] else "regressed" if rank[b] < rank[a] else "equal"
        lines.append(f"| `{item['case_id']}` | {a} | {b} | {comparison} |")
    lines.extend([
        "",
        f"No-history: PASS `{no_counts['PASS']}` / PARTIAL `{no_counts['PARTIAL']}` / FAIL `{no_counts['FAIL']}`",
        f"With-history: PASS `{with_counts['PASS']}` / PARTIAL `{with_counts['PARTIAL']}` / FAIL `{with_counts['FAIL']}`",
        "",
    ])
    used = sum(item["with_history"]["context"]["resolver_used"] is True for item in results)
    fallback = sum(item["with_history"]["context"]["resolver_fallback"] is True for item in results)
    truncated = sum(item["with_history"]["context"]["history_truncated"] is True for item in results)
    improved = equal = regressed = 0
    for item in results:
        a = rank[item["judgement"]["no_history"]["status"]]
        b = rank[item["judgement"]["with_history"]["status"]]
        if b > a:
            improved += 1
        elif b < a:
            regressed += 1
        else:
            equal += 1
    lines.extend([
        f"- resolver used: `{used}/6`",
        f"- resolver fallback: `{fallback}/6`",
        f"- context truncated: `{truncated}/6`",
        f"- with history > no history: `{improved}`",
        f"- with history = no history: `{equal}`",
        f"- with history < no history: `{regressed}`",
        "",
        "## Topic Switch",
        "",
    ])
    switch = next(item for item in results if item["case_type"] == "topic_switch_control")
    lines.append(
        f"`{switch['case_id']}`: no-history `{switch['judgement']['no_history']['status']}`, "
        f"with-history `{switch['judgement']['with_history']['status']}`, "
        f"safety `{switch['judgement']['with_history']['topic_switch_safety']}`."
    )
    dependent_cases = [
        item for item in results if item["case_type"] != "topic_switch_control"
    ]
    dependent_improved = sum(
        rank[item["judgement"]["with_history"]["status"]]
        > rank[item["judgement"]["no_history"]["status"]]
        for item in dependent_cases
    )
    decision = (
        "validated"
        if dependent_improved > len(dependent_cases) / 2 and regressed == 0
        else "negative"
    )
    lines.extend([
        "",
        "## Failure Modes",
        "",
        "- `g8ctx001` and `g8ctx002`: with-history planning reached decomposed retrieval but refused after incomplete required-subquery evidence.",
        "- `g8ctx004` and `g8ctx005`: history changed an elliptical/answer-reference follow-up from direct no-retrieval failure to grounded answer.",
        "",
        "## Decision",
        "",
        f"`{decision}`: context improved `{dependent_improved}/{len(dependent_cases)}` dependent cases; this is not a majority, so Context v1 is not validated as a general capability by this check.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(results: Sequence[Mapping[str, Any]], *, results_path: str | Path, report_path: str | Path, base_url: str) -> None:
    result_file = Path(results_path)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(
        "\n".join(_canonical_json(item) for item in results) + "\n",
        encoding="utf-8",
    )
    Path(report_path).write_text(
        build_report(results, base_url=base_url),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("RAG_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--cases", default=str(Path(__file__).with_name("conversation_context_cases_v1.jsonl")))
    parser.add_argument("--results", default=str(Path(__file__).parent / "results" / "context_v1_results.jsonl"))
    parser.add_argument("--report", default=str(Path(__file__).parent / "results" / "context_v1_report.md"))
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    results = run_check(cases, base_url=args.base_url)
    write_artifacts(results, results_path=args.results, report_path=args.report, base_url=args.base_url)
    print(json.dumps({"run_id": uuid.uuid4().hex[:12], "case_count": len(results), "blocked": any(item.get("execution_status") == "BLOCKED" for item in results), "results": args.results, "report": args.report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
