"""Check recorded evidence/budgets and summarize the explicit source review.

Content correctness comes from manual_review.json, never from completed status,
keyword presence, citation validity or transport success. No provider calls.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

from core.tool_agent.source_excerpt import project_context_snippet
from core.tool_agent.source_excerpt import MAX_LINE_LENGTH

ARCHIVE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    review = json.loads((ARCHIVE / "manual_review.json").read_text(encoding="utf-8"))
    summary = {"independent_acceptance": False, "phases": {}, "requests": 0,
               "planner_calls": 0, "decision_calls": 0, "input_tokens": 0,
               "output_tokens": 0, "successful_reads_checked": 0}
    for phase, expected in review["phases"].items():
        path = ARCHIVE / "raw" / phase / "live_results.jsonl"
        if digest(path) != expected["results_sha256"]:
            raise ValueError("Recorded results changed: " + phase)
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        manifest = json.loads(path.with_name("run_manifest.json").read_text(encoding="utf-8"))
        scores = {item["id"]: item for item in expected["reviews"]}
        if {r["id"] for r in records} != set(scores) or len(records) != len(scores):
            raise ValueError("Missing or duplicate results/reviews: " + phase)
        metadata_seen = Counter()
        reads = 0
        for row in records:
            result = row["public_response"]
            if not row["transport_ok"] or result["iterations_used"] > 5 or result["tool_calls_used"] > 4 or result["tool_errors_used"] > 2:
                raise ValueError("Transport or budget violation: " + row["id"])
            observations = row["observations"]
            if any(o["stage"] == "context" and (o["resolver_used"] or o["received_count"] != 0) for o in observations):
                raise ValueError("Unexpected history/Resolver cost")
            successful = [o["result"] for o in observations if o["stage"] == "tool_result" and o["tool"] == "read_project_context" and o["status"] == "ok"]
            for content in successful:
                source = ARCHIVE / "source_snapshots" / row["project"] / content["path"]
                identity = manifest["projects"][row["project"]]
                expected_hash = identity["readme_sha256"] if content["path"] == "README.md" else identity["source_sha256"][content["path"]]
                if digest(source) != expected_hash:
                    raise ValueError("Source snapshot differs from recorded input")
                lines = source.read_text(encoding="utf-8").splitlines()
                actual_excerpt = "\n".join(line[:MAX_LINE_LENGTH] for line in lines[content["start_line"] - 1:content["end_line"]])
                if actual_excerpt != project_context_snippet(content):
                    raise ValueError("Reader excerpt differs from fixed source")
                snippets = [e for e in result["evidence"] if e.get("path") == content["path"] and e.get("start_line") == content["start_line"] and e.get("end_line") == content["end_line"]]
                if not snippets or any(e["snippet"] != project_context_snippet(content) for e in snippets):
                    raise ValueError("Public source differs from Reader: " + row["id"])
                reads += 1
            for observation in observations:
                if observation["stage"] == "planner":
                    metadata = observation.get("call_metadata")
                    kind = "planner"
                elif observation["stage"] == "decision_metadata":
                    metadata = observation.get("metadata")
                    kind = "decision"
                else:
                    continue
                if metadata is None:
                    raise ValueError("Missing provider metadata: " + row["id"])
                calls = metadata["call_count"]
                metadata_seen[kind] += calls
                summary[kind + "_calls"] += calls
                for key in ("input_tokens", "output_tokens"):
                    if metadata[key] is None:
                        raise ValueError("Missing reported token usage")
                    summary[key] += metadata[key]
            summary["requests"] += 1
        summary["successful_reads_checked"] += reads
        summary["phases"][phase] = {
            "requests": len(records), "scores": dict(Counter(s["score"] for s in scores.values())),
            "statuses": dict(Counter(r["public_response"]["status"] for r in records)),
            "provider_calls": dict(metadata_seen), "successful_reads_checked": reads,
            "median_elapsed_seconds": statistics.median(r["elapsed_seconds"] for r in records),
        }
    summary["all_provider_calls"] = summary["planner_calls"] + summary["decision_calls"]
    summary["token_scope"] = "Provider-reported Planner and Decision usage, including recorded parse repair. No history/Resolver calls in this set. Not money, billing receipt, load testing or an independent evaluation."
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
