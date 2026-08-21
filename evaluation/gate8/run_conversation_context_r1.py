"""G8-CONTEXT-02-R1 clean-corpus, validity-gated provider A/B runner."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from evaluation.gate8.r1_infrastructure import (
    EXPECTED_CASE_COUNT,
    R1_REPORT_SCHEMA_VERSION,
    R1_RESULT_SCHEMA_VERSION,
    build_corpus_provenance,
    load_r1_cases,
    preflight_clean_index,
    safe_provider_summary,
    sanitize_artifact_text,
    turn1_is_valid,
)
from evaluation.gate8.run_conversation_context_check import _judge


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class R1RunBlocked(RuntimeError):
    """The provider/API could not perform a valid formal run."""


def _request_json(session: Any, base_url: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    try:
        response = session.post(
            f"{base_url.rstrip('/')}/agent/query", json=payload, timeout=180.0
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise R1RunBlocked("http_transport_unavailable") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if response.status_code in (502, 503, 504):
        raise R1RunBlocked("agent_runtime_unavailable")
    if response.status_code != 200:
        raise R1RunBlocked("agent_endpoint_contract_error")
    try:
        data = response.json()
    except ValueError as exc:
        raise R1RunBlocked("agent_response_not_json") from exc
    if type(data) is not dict:
        raise R1RunBlocked("agent_response_not_object")
    return data, elapsed_ms


def _record_base(case: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": R1_RESULT_SCHEMA_VERSION,
        "case_id": case["case_id"],
        "case_type": case["case_type"],
        "turn1": case["turn1"],
        "turn2": case["turn2"],
        "corpus_id": provenance["corpus_id"],
        "execution_status": "NOT_RUN",
        "turn1_valid": False,
        "turn1_result": None,
        "no_history": None,
        "with_history": None,
        "judgement": None,
        "ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API": False,
    }


def run_r1_check(
    cases: Sequence[Mapping[str, Any]],
    *,
    base_url: str,
    provenance: Mapping[str, Any],
    index_proof: Mapping[str, Any],
    session: Any = requests,
) -> list[dict[str, Any]]:
    """Run six Turn1 requests first, then exactly one A/B pair per valid case."""

    source_map = {Path(path).name: path for path in provenance["relative_paths"]}
    records = [_record_base(case, provenance) for case in cases]
    turn1_data: list[tuple[dict[str, Any], float] | None] = [None] * len(cases)
    validity_failed = False
    try:
        for index, case in enumerate(cases):
            data, latency = _request_json(
                session, base_url, {"question": case["turn1"], "top_k": 5}
            )
            summary, exposed = safe_provider_summary(data, latency, source_map)
            records[index]["turn1_result"] = {
                "status": data.get("status"),
                "answer": sanitize_artifact_text(data.get("answer")),
                "sources": summary["sources"],
                "latency_ms": summary["latency_ms"],
            }
            records[index]["turn1_valid"] = turn1_is_valid(case, data, summary)
            records[index]["ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API"] = exposed
            turn1_data[index] = (data, latency)
            if not records[index]["turn1_valid"]:
                validity_failed = True
                records[index]["execution_status"] = "INVALID_CASE"
        if validity_failed:
            for index, record in enumerate(records):
                if record["execution_status"] == "NOT_RUN":
                    record["execution_status"] = "VALIDITY_GATE_BLOCKED"
            return records

        for index, case in enumerate(cases):
            first = turn1_data[index]
            assert first is not None
            turn1_response = first[0]
            turn1_answer = turn1_response.get("answer")
            no_data, no_latency = _request_json(
                session, base_url, {"question": case["turn2"], "top_k": 5}
            )
            with_data, with_latency = _request_json(
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
            no_summary, no_exposed = safe_provider_summary(no_data, no_latency, source_map)
            with_summary, with_exposed = safe_provider_summary(with_data, with_latency, source_map)
            record = records[index]
            record["execution_status"] = "COMPLETED"
            record["no_history"] = no_summary
            record["with_history"] = with_summary
            record["judgement"] = {
                "no_history": _judge(case, no_summary),
                "with_history": _judge(case, with_summary),
            }
            record["ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API"] = bool(
                record["ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API"] or no_exposed or with_exposed
            )
    except R1RunBlocked as exc:
        for record in records:
            if record["execution_status"] == "NOT_RUN":
                record["execution_status"] = "BLOCKED"
                record["blocked_reason"] = str(exc)
    return records


def _comparison(item: Mapping[str, Any]) -> str:
    rank = {"FAIL": 0, "PARTIAL": 1, "PASS": 2}
    if not item.get("judgement"):
        return "not_scored"
    a = rank[item["judgement"]["no_history"]["status"]]
    b = rank[item["judgement"]["with_history"]["status"]]
    return "improved" if b > a else "regressed" if b < a else "equal"


def build_report(
    results: Sequence[Mapping[str, Any]],
    *,
    provenance: Mapping[str, Any],
    index_proof: Mapping[str, Any],
    base_url: str,
) -> str:
    lines = [
        "# G8 Context v1 R1 Clean-Corpus Capability Check",
        "",
        f"- schema: `{R1_REPORT_SCHEMA_VERSION}`",
        f"- endpoint: `{base_url.rstrip('/')}/agent/query`",
        "- formal request design: 6 Turn1 + 6 A no-history + 6 B with-history = 18 requests",
        "- sealed holdout: untouched / not read",
        "",
        "## Corpus Identity",
        "",
        f"- repository: `{provenance['repository']}`",
        f"- commit: `{provenance['commit']}`",
        f"- path: `{provenance['path']}`",
        f"- corpus_id: `{provenance['corpus_id']}`",
        f"- file_count: `{provenance['file_count']}`",
        f"- commit verification: `{provenance['commit_verification']}`",
        "",
        "## Clean-Index Proof",
        "",
        f"- isolated: `{index_proof.get('isolated')}`",
        f"- index_id: `{index_proof.get('index_id')}`",
        f"- vector_store_count: `{index_proof.get('vector_store_count')}`",
        f"- document_count: `{index_proof.get('document_count')}`",
        f"- source_count: `{index_proof.get('source_count')}`",
        "- contamination preflight: `passed`",
        "",
        "## Cases and Turn1 Validity",
        "",
        "| Case | Type | Turn1 | A | B | Comparison | Resolver used/fallback |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in results:
        turn1 = "VALID" if item.get("turn1_valid") else "INVALID"
        if item.get("judgement"):
            a = item["judgement"]["no_history"]["status"]
            b = item["judgement"]["with_history"]["status"]
            context = item["with_history"]["context"]
            resolver = f"{context.get('resolver_used')}/{context.get('resolver_fallback')}"
        else:
            a = b = "NOT_SCORED"
            resolver = "n/a"
        lines.append(
            f"| `{item['case_id']}` | `{item['case_type']}` | `{turn1}` | `{a}` | `{b}` | "
            f"`{_comparison(item)}` | `{resolver}` |"
        )
    completed = [item for item in results if item.get("execution_status") == "COMPLETED"]
    lines.extend(["", "## A/B Metrics", ""])
    if completed:
        a_counts = Counter(item["judgement"]["no_history"]["status"] for item in completed)
        b_counts = Counter(item["judgement"]["with_history"]["status"] for item in completed)
        comparisons = Counter(_comparison(item) for item in completed)
        latencies = [
            item["no_history"]["latency_ms"] for item in completed
        ] + [item["with_history"]["latency_ms"] for item in completed]
        resolver_used = sum(item["with_history"]["context"].get("resolver_used") is True for item in completed)
        resolver_fallback = sum(item["with_history"]["context"].get("resolver_fallback") is True for item in completed)
        lines.extend([
            f"- no-history: PASS `{a_counts['PASS']}` / PARTIAL `{a_counts['PARTIAL']}` / FAIL `{a_counts['FAIL']}`",
            f"- with-history: PASS `{b_counts['PASS']}` / PARTIAL `{b_counts['PARTIAL']}` / FAIL `{b_counts['FAIL']}`",
            f"- improved/equal/regressed: `{comparisons['improved']}/{comparisons['equal']}/{comparisons['regressed']}`",
            f"- resolver used: `{resolver_used}/{len(completed)}`",
            f"- resolver fallback: `{resolver_fallback}/{len(completed)}`",
            f"- average A/B latency: `{sum(latencies) / len(latencies):.2f} ms`",
            f"- average tool calls: `not exposed by Agent Runtime response; request count is {len(completed) * 3}`",
        ])
    else:
        lines.append("- no valid completed A/B run; metrics are not scored")
    switch = next((item for item in results if item["case_type"] == "topic_switch_control"), None)
    lines.extend(["", "## Topic Switch", ""])
    if switch and switch.get("judgement"):
        lines.append(
            f"`{switch['case_id']}`: A `{switch['judgement']['no_history']['status']}`, "
            f"B `{switch['judgement']['with_history']['status']}`, "
            f"safety `{switch['judgement']['with_history']['topic_switch_safety']}`."
        )
    else:
        lines.append("Topic switch was not scored because the validity gate did not complete.")
    absolute_exposed = any(item.get("ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API") for item in results)
    lines.extend([
        "",
        "## Source Safety",
        "",
        f"- `ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API = {str(absolute_exposed).lower()}`",
        "- result serialization keeps corpus-relative source identities only; raw local paths are not retained",
        "",
        "## Decision",
        "",
    ])
    if len(completed) != EXPECTED_CASE_COUNT:
        decision = "mixed"
        lines.append("`mixed`: the clean-corpus/provider run did not complete all six valid cases; no capability score is claimed.")
    else:
        comparisons = Counter(_comparison(item) for item in completed)
        if comparisons["improved"] >= 4 and comparisons["regressed"] == 0:
            decision = "validated"
        elif comparisons["improved"] == 0 and comparisons["regressed"] == 0:
            decision = "negative"
        else:
            decision = "mixed"
        lines.append(
            f"`{decision}`: clean-corpus R1 completed with six valid cases; this is the observed result of this fixed check."
        )
    return "\n".join(lines) + "\n"


def write_artifacts(
    results: Sequence[Mapping[str, Any]],
    *,
    results_path: str | Path,
    report_path: str | Path,
    provenance: Mapping[str, Any],
    index_proof: Mapping[str, Any],
    base_url: str,
) -> None:
    result_file = Path(results_path)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(
        "\n".join(_canonical_json(item) for item in results) + "\n", encoding="utf-8"
    )
    Path(report_path).write_text(
        build_report(results, provenance=provenance, index_proof=index_proof, base_url=base_url),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("RAG_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--index-path", required=True)
    parser.add_argument("--cases", default=str(Path(__file__).with_name("conversation_context_cases_r1.jsonl")))
    parser.add_argument("--results", default=str(Path(__file__).parent / "results" / "context_v1_r1_results.jsonl"))
    parser.add_argument("--report", default=str(Path(__file__).parent / "results" / "context_v1_r1_report.md"))
    parser.add_argument("--clean-index-manifest", default=str(Path(__file__).parent / "results" / "context_v1_r1_clean_index_manifest.json"))
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    provenance = build_corpus_provenance(args.corpus_root, repo_root=repo_root)
    index_proof = preflight_clean_index(args.index_path, provenance)
    cases = load_r1_cases(args.cases, provenance)
    Path(args.clean_index_manifest).write_text(
        _canonical_json({"schema_version": "gate8_clean_index_proof_v1", **index_proof, "corpus": provenance}) + "\n",
        encoding="utf-8",
    )
    results = run_r1_check(
        cases,
        base_url=args.base_url,
        provenance=provenance,
        index_proof=index_proof,
    )
    write_artifacts(
        results,
        results_path=args.results,
        report_path=args.report,
        provenance=provenance,
        index_proof=index_proof,
        base_url=args.base_url,
    )
    print(json.dumps({"run_id": uuid.uuid4().hex[:12], "case_count": len(results), "results": args.results, "report": args.report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
