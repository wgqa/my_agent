"""Provider-free integrity checks and descriptive paired-run summary."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parents[1]
DIRECT = {"C02", "C03", "K01", "N01"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    integrity_path = ARCHIVE / "final_integrity.json"
    if integrity_path.exists():
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        for name, expected in integrity["file_sha256"].items():
            assert sha(REPO / name) == expected, f"Final retained input changed: {name}"
    manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    initial = json.loads((ARCHIVE / "initial_manifest.json").read_text(encoding="utf-8"))
    for group in ("input_sha256", "production_sha256", "protected_sha256", "helper_sha256"):
        for name, expected in manifest[group].items():
            assert sha(REPO / name) == expected, f"Frozen input changed: {name}"
    for name, expected in initial["prior_archives_sha256"].items():
        assert sha(REPO / name) == expected, f"Prior archive changed: {name}"
    ci = re.findall(r"tests/test_[\w]+\.py", (REPO / ".github/workflows/ci.yml").read_text())
    blocks = re.findall(r"```bash\n(.*?)```", (REPO / "docs/release2_local_runbook.md").read_text(encoding="utf-8"), re.S)
    ci_blocks = [block for block in blocks if "tests/test_api.py" in block]
    assert len(ci_blocks) == 1
    runbook = re.findall(r"tests/test_[\w]+\.py", ci_blocks[0])
    assert ci == runbook and len(ci) == len(set(ci)) == 37
    raw = ARCHIVE / "raw/paired/live_results.jsonl"
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    catalog = json.loads((ARCHIVE / "catalog.json").read_text(encoding="utf-8"))
    assert len(rows) == catalog["max_live_requests"] == 16
    assert Counter((r["id"], r["arm"]) for r in rows) == Counter(
        (c["id"], arm) for c in catalog["cases"] for arm in ("baseline", "candidate")
    )
    summary = {}
    for arm in ("baseline", "candidate"):
        group = [r for r in rows if r["arm"] == arm]
        direct = [r for r in group if r["id"] in DIRECT]
        planners = [o for r in group for o in r["observations"] if o["stage"] == "planner"]
        decisions = [o for r in group for o in r["observations"] if o["stage"] == "decision_metadata"]
        metas = [o["call_metadata"] for o in planners] + [o["metadata"] for o in decisions]
        assert all(r["transport_ok"] for r in group)
        assert all(p["call_metadata"]["prompt_version"] == manifest[arm + "_prompt"]["version"]
                   and p["call_metadata"]["prompt_sha256"] == manifest[arm + "_prompt"]["sha256"]
                   and p["call_metadata"]["call_count"] == 1 for p in planners)
        assert all(d["metadata"]["prompt_sha256"] == manifest["unchanged_decision_prompt_sha256"]
                   and d["metadata"]["toolset_sha256"] == "30846e05d9fbead31244a262d3b6bf1d6429fcdc5528316428810e5dd6c189ab"
                   for d in decisions)
        for row in group:
            response = row["public_response"]
            assert response["iterations_used"] <= 5
            assert response["tool_calls_used"] <= 4
            assert response["tool_errors_used"] == 0
        for row in direct:
            planner = next(o for o in row["observations"] if o["stage"] == "planner")
            verification = [o for o in row["observations"] if o["stage"] == "verification"][-1]
            if arm == "baseline":
                assert planner["failure_code"] == "PLAN_INVALID_SCHEMA"
                assert row["public_response"]["status"] == "refused"
                assert "ANSWER_EVIDENCE_REFERENCE_MISSING" in verification["insufficiency_reasons"]
            else:
                assert not planner["fallback_used"] and planner["plan"]["action"] == "no_retrieval"
                assert row["public_response"]["status"] == "completed"
                assert row["public_response"]["evidence"] == []
                assert verification["binding_status"] == "NOT_REQUIRED"
        summary[arm] = {
            "status_counts": dict(Counter(r["public_response"]["status"] for r in group)),
            "planner_fallbacks": sum(p["fallback_used"] for p in planners),
            "direct_completed": sum(r["public_response"]["status"] == "completed" for r in direct),
            "actual_provider_calls": sum(m["call_count"] for m in metas),
            "input_tokens": sum(m.get("input_tokens") or 0 for m in metas),
            "output_tokens": sum(m.get("output_tokens") or 0 for m in metas),
            "tool_calls": sum(r["public_response"]["tool_calls_used"] for r in group),
            "stream_v2_requests": sum(r["path"].endswith("/v2") for r in group),
        }
    review = json.loads((ARCHIVE / "manual_review.json").read_text(encoding="utf-8"))
    for arm in ("baseline", "candidate"):
        summary[arm]["asked_behavior_grades"] = dict(Counter(c[arm][0] for c in review["cases"]))
        summary[arm]["whole_answer_grades"] = dict(Counter(c[arm][1] for c in review["cases"]))
    for case_id in ("C02", "C03"):
        row = next(r for r in rows if r["arm"] == "candidate" and r["id"] == case_id)
        expected = "1073" if case_id == "C02" else "294"
        assert row["public_response"]["answer"] == expected
        tool = next(o for o in row["observations"] if o["stage"] == "tool_result")
        assert tool["tool"] == "calculator" and tool["status"] == "ok"
        assert tool["result"]["value"] == int(expected)
    for arm in ("baseline", "candidate"):
        missing = next(r for r in rows if r["arm"] == arm and r["id"] == "D03")
        assert missing["public_response"]["status"] == "refused"
        assert missing["public_response"]["answer"] is None
    result = {
        "raw_sha256": sha(raw), "requests": len(rows), "summary": summary,
        "actual_provider_calls": sum(s["actual_provider_calls"] for s in summary.values()),
        "protected_files_unchanged": len(manifest["protected_sha256"]),
        "prior_archive_files_unchanged": len(initial["prior_archives_sha256"]),
        "ci_modules": len(ci), "new_provider_calls_from_analysis": 0,
        "independent_formal_acceptance": False,
        "limitations": ["One paired round; known development failures; no holdout.",
                        "R02 candidate answer has a semantic regression despite identical tool chain.",
                        "C01 candidate has valid citations but incomplete semantic support; baseline parse failure has unknown exact format cause."],
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    print(payload)


if __name__ == "__main__":
    main()
