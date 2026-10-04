"""Objective metrics only; semantic grades are in the separate manual review."""

import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(rows):
    metrics = {}
    for arm in ("baseline", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        responses = [row["public_response"] for row in selected]
        planner = [obs["call_metadata"] for row in selected for obs in row["observations"]
                   if obs["stage"] == "planner" and obs.get("call_metadata")]
        decision = [obs["metadata"] for row in selected for obs in row["observations"]
                    if obs["stage"] == "decision_metadata" and obs.get("metadata")]
        metrics[arm] = {
            "requests": len(selected),
            "transport_ok": sum(row["transport_ok"] for row in selected),
            "stream_v2_requests": sum(row["path"].endswith("/stream/v2") for row in selected),
            "statuses": dict(Counter(r["status"] for r in responses)),
            "iterations": sum(r["iterations_used"] for r in responses),
            "tools": sum(r["tool_calls_used"] for r in responses),
            "tool_errors": sum(r["tool_errors_used"] for r in responses),
            "budget_valid": all(r["iterations_used"] <= 5 and r["tool_calls_used"] <= 4
                                and r["tool_errors_used"] <= 2 for r in responses),
            "planner_calls": sum(m["call_count"] for m in planner),
            "decision_calls": sum(m["call_count"] for m in decision),
            "format_repairs": sum(m["repair_attempted"] for m in decision),
            "input_tokens": sum(m.get("input_tokens") or 0 for m in planner + decision),
            "output_tokens": sum(m.get("output_tokens") or 0 for m in planner + decision),
            "query_seconds": round(sum(row["elapsed_seconds"] for row in selected), 3),
            "decision_prompt_identities": sorted({(m["prompt_version"], m["prompt_sha256"]) for m in decision}),
            "toolset_identities": sorted({m["toolset_sha256"] for m in decision}),
        }
    pairs = []
    for case_id in dict.fromkeys(row["id"] for row in rows):
        pair = {row["arm"]: row for row in rows if row["id"] == case_id}
        assert set(pair) == {"baseline", "candidate"}
        item = {"id": case_id}
        chains = []
        for arm in ("baseline", "candidate"):
            row = pair[arm]
            response = row["public_response"]
            chain = [{"tool": o["tool"], "arguments": o["arguments"],
                      "span": o["span"], "status": o["status"]}
                     for o in row["observations"] if o["stage"] == "tool"]
            chains.append(chain)
            item[arm] = {
                "status": response["status"], "reason_code": response["reason_code"],
                "failure_code": response["failure_code"],
                "iterations": response["iterations_used"], "tools": response["tool_calls_used"],
                "chain": chain,
                "read_spans": [{k: o["result"].get(k) for k in ("path", "start_line", "end_line")}
                               for o in row["observations"] if o["stage"] == "source_read" and o["result"]],
            }
        item["identical_tool_chain"] = chains[0] == chains[1]
        pairs.append(item)
    return {"independent_formal_acceptance": False, "arms": metrics, "pairs": pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(s) for s in args.input.read_text(encoding="utf-8").splitlines()]
    result = summarize(rows)
    assert not args.output.exists(), "Never overwrite an existing analysis"
    args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(result["arms"], ensure_ascii=False))


if __name__ == "__main__":
    main()
