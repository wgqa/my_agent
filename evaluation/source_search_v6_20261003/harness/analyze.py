"""Offline audit of a completed paired run; never calls a provider."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ARCHIVE = Path(__file__).resolve().parents[1]
REPO = ARCHIVE.parents[1]
sys.path.insert(0, str(REPO))
from evaluation.integration_v7.runner import safe_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.input_dir / "live_results.jsonl").read_text(encoding="utf-8").splitlines()]
    catalog = json.loads((ARCHIVE / "catalog.json").read_text(encoding="utf-8"))
    review = json.loads((ARCHIVE / "review.json").read_text(encoding="utf-8"))
    assert len(rows) == 16
    assert Counter((r["id"], r["arm"]) for r in rows) == Counter((c["id"], arm) for c in catalog["cases"] for arm in ("v5", "v6"))
    assert all(r["transport_ok"] for r in rows)
    assert all(r["public_response"]["iterations_used"] <= 5 and r["public_response"]["tool_calls_used"] <= 4 and r["public_response"]["tool_errors_used"] <= 2 for r in rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "live_results.jsonl"
    assert not target.exists(), "Never overwrite a prior audit export"
    target.write_text("".join(json.dumps(safe_artifact(r), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    summary = {"requests": 16, "transport_valid": 16, "within_budget": 16,
               "stream_v2_validated_requests": sum("stream_event_types" in r for r in rows),
               "independent_formal_acceptance": False, "reviewer": review["reviewer"], "arms": {}, "pairs": []}
    for arm in ("v5", "v6"):
        subset = [r for r in rows if r["arm"] == arm]
        stage_metadata = {stage: [o.get("call_metadata" if stage == "planner" else "metadata") for r in subset for o in r["observations"] if o["stage"] == stage] for stage in ("planner", "decision_metadata")}
        metadata = [m for group in stage_metadata.values() for m in group if m]
        assert all(m["provider"] == "deepseek" and m["model"] == "deepseek-chat" for m in metadata)
        assert all(not o["resolver_used"] for r in subset for o in r["observations"] if o["stage"] == "context")
        searches = [o for r in subset for o in r["observations"] if o["stage"] == "source_search"]
        summary["arms"][arm] = {
            "terminal_status": dict(Counter(r["public_response"]["status"] for r in subset)),
            "iterations": sum(r["public_response"]["iterations_used"] for r in subset),
            "tool_calls": sum(r["public_response"]["tool_calls_used"] for r in subset),
            "tool_errors": sum(r["public_response"]["tool_errors_used"] for r in subset),
            "search_calls": len(searches), "scope_calls": sum("scope" in o["arguments"] for o in searches),
            "truncated_true_calls": sum((o["result"] or {}).get("truncated") is True for o in searches),
            "gold_source_read_requests": sum(any(o["stage"] == "source_read" and (o["result"] or {}).get("path") == next(c["gold_path"] for c in catalog["cases"] if c["id"] == r["id"]) for o in r["observations"]) for r in subset),
            "provider_calls": sum(m["call_count"] for m in metadata),
            "planner_calls": sum(m["call_count"] for m in stage_metadata["planner"] if m),
            "decision_calls": sum(m["call_count"] for m in stage_metadata["decision_metadata"] if m),
            "repair_attempts": sum(m.get("repair_attempted", False) for m in metadata),
            "input_tokens": sum(m["input_tokens"] for m in metadata),
            "output_tokens": sum(m["output_tokens"] for m in metadata),
            "query_seconds": round(sum(r["elapsed_seconds"] for r in subset), 3),
            "identity": {stage: {key: sorted({m[key] for m in group if m and key in m}) for key in ("provider", "model", "prompt_version", "prompt_sha256", "toolset_sha256")} for stage, group in stage_metadata.items()},
            "asked_behavior": dict(Counter(c[arm]["asked_behavior"] for c in review["cases"])),
            "whole_answer": dict(Counter(c[arm]["whole_answer"] for c in review["cases"])),
        }
    for case in catalog["cases"]:
        pair = {arm: next(r for r in rows if r["id"] == case["id"] and r["arm"] == arm) for arm in ("v5", "v6")}
        chains = {arm: [{"tool": o["tool"], "arguments": o["arguments"]} for o in pair[arm]["observations"] if o["stage"] == "tool"] for arm in pair}
        effective_chains = {}
        for arm, chain in chains.items():
            effective_chains[arm] = []
            for call in chain:
                arguments = dict(call["arguments"])
                if call["tool"] == "read_project_context" and arguments.get("mode") == "window":
                    arguments.pop("mode")  # The current reader's omitted default.
                effective_chains[arm].append({"tool": call["tool"], "arguments": arguments})
        spans = {arm: [{k: o["result"].get(k) for k in ("path", "start_line", "end_line", "definition")} for o in pair[arm]["observations"] if o["stage"] == "source_read" and o["result"]] for arm in pair}
        summary["pairs"].append({"id": case["id"], "same_tool_arguments": chains["v5"] == chains["v6"], "same_effective_tool_arguments": effective_chains["v5"] == effective_chains["v6"], "same_read_spans": spans["v5"] == spans["v6"], "tool_chain": chains, "read_spans": spans})
    summary["decision"] = "NOT_PROMOTED: scope never used; acquisition and tool usage unchanged; no demonstrated answer-quality gain"
    summary["total_provider_calls"] = sum(a["provider_calls"] for a in summary["arms"].values())
    summary["export_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (args.output_dir / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k != "pairs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
