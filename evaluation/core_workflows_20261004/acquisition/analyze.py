"""Verify recorded multi-region sources/identities and explicit claim reviews.

No provider calls. Whole-answer scores remain human-style source review data,
separate from transport success, completed status and source-text fidelity.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path

from core.tool_agent.source_excerpt import MAX_LINE_LENGTH, project_context_fragments, project_context_snippet
from core.tool_agent.tools.source_navigation import python_symbols

ARCHIVE = Path(__file__).resolve().parent
SOURCES = ARCHIVE.parent/"source_snapshots"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    review = json.loads((ARCHIVE/"manual_review.json").read_text(encoding="utf-8"))
    summary = {"independent_acceptance": False, "requests": 0, "planner_calls": 0,
        "decision_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "source_regions_checked": 0, "qualified_definitions_checked": 0,
        "persisted_conversations_checked": 0, "phases": {}}
    for phase, expected in review["phases"].items():
        raw = ARCHIVE/"raw"/phase/"live_results.jsonl"
        assert digest(raw)==expected["results_sha256"]
        manifest = json.loads(raw.with_name("run_manifest.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
        scores = {item["id"]:item for item in expected["reviews"]}
        assert len(scores)==len(rows) and set(scores)=={row["id"] for row in rows}
        counts = Counter()
        for row in rows:
            output = row["public_response"]
            assert row["transport_ok"] and output["iterations_used"]<=5 and output["tool_calls_used"]<=4 and output["tool_errors_used"]<=2
            if "conversations/" in row["path"]:
                assert row["persistence_ok"]
                summary["persisted_conversations_checked"] += 1
            for event in row["observations"]:
                if event["stage"]=="context":
                    assert not event["resolver_used"] and event["received_count"]==0
                if event["stage"]=="tool_result" and event["tool"]=="read_project_context" and event["status"]=="ok":
                    result = event["result"]
                    source = SOURCES/row["project"]/result["path"]
                    identity = manifest["projects"][row["project"]]
                    expected_hash = identity["readme_sha256"] if result["path"]=="README.md" else identity["source_sha256"][result["path"]]
                    assert digest(source)==expected_hash
                    lines = source.read_text(encoding="utf-8").splitlines()
                    for fragment in project_context_fragments(result):
                        actual = "\n".join(line[:MAX_LINE_LENGTH] for line in lines[fragment["start_line"]-1:fragment["end_line"]])
                        assert actual==project_context_snippet(fragment)
                        public = [item for item in output["evidence"] if item.get("path")==result["path"] and item.get("start_line")==fragment["start_line"] and item.get("end_line")==fragment["end_line"]]
                        assert public and all(item["snippet"]==actual for item in public)
                        summary["source_regions_checked"] += 1
                    if source.suffix==".py":
                        spans, error = python_symbols(lines)
                        assert error is None
                        definitions = [span.to_dict() for span in spans]
                        for target in result["targets"]:
                            if target["definition"] is not None:
                                assert target["definition"] in definitions
                                summary["qualified_definitions_checked"] += 1
                if event["stage"] not in {"planner","decision_metadata"}:
                    continue
                kind = "planner" if event["stage"]=="planner" else "decision"
                metadata = event["call_metadata"] if kind=="planner" else event["metadata"]
                assert metadata is not None
                counts[kind] += metadata["call_count"]
                summary[kind+"_calls"] += metadata["call_count"]
                for key in ["input_tokens","output_tokens"]:
                    assert metadata[key] is not None
                    summary[key] += metadata[key]
            summary["requests"] += 1
        summary["phases"][phase] = {"requests":len(rows),
            "whole_answer_scores":dict(Counter(scores[row["id"]]["score"] for row in rows)),
            "core_scores":dict(Counter(scores[row["id"]]["score"] for row in rows if not scores[row["id"]]["boundary_control"])),
            "boundary_scores":dict(Counter(scores[row["id"]]["score"] for row in rows if scores[row["id"]]["boundary_control"])),
            "provider_calls":dict(counts)}
    summary["all_provider_calls"] = summary["planner_calls"]+summary["decision_calls"]
    summary["limits"] = "Development has same questions as historical baseline, one run each. Confirmation/entry inputs differ and are not fair A/B or independent success rates. Reported tokens are usage, not money/billing/load-test evidence."
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
