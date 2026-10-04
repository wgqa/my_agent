"""Provider-free audit of both development rounds and their frozen boundaries."""

from collections import Counter
import hashlib
import json
from pathlib import Path

from api.schemas import EngineeringQueryResponse
from core.tool_agent.source_excerpt import project_context_snippet

ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit_phase(folder, *, current):
    manifest = read(folder / "manifest.json")
    groups = ["input_sha256", "helper_sha256", "protected_sha256", "prior_archive_sha256"]
    if current:
        groups += ["production_sha256", "test_sha256"]
    for group in groups:
        for name, expected in manifest[group].items():
            assert sha(REPO / name) == expected, f"Frozen file changed: {name}"
    catalog = read(folder / "catalog.json")["cases"]
    rows = [json.loads(line) for line in (folder / "raw/live_results.jsonl").read_text(encoding="utf-8").splitlines()]
    reviews = read(folder / "manual_review.json")["reviews"]
    expected_pairs = {(case["id"], arm) for case in catalog for arm in ("baseline", "candidate")}
    assert len(rows) == len(expected_pairs) == 16
    assert {(row["id"], row["arm"]) for row in rows} == expected_pairs
    assert len(reviews) == 16 and {(r["id"], r["arm"]) for r in reviews} == expected_pairs
    assert sum(row["path"].endswith("/stream/v2") for row in rows) == 8
    repairs = []
    for row in rows:
        assert row["transport_ok"]
        response = row["public_response"]
        EngineeringQueryResponse.model_validate(response)
        assert response["iterations_used"] <= 5 and response["tool_calls_used"] <= 4 and response["tool_errors_used"] <= 2
        identity = manifest["identities"][row["arm"]]
        observations = row["observations"]
        planner = [o for o in observations if o["stage"] == "planner"]
        assert len(planner) == 1
        metadata = planner[0]["call_metadata"]
        assert metadata["prompt_version"] == manifest["planner"]["version"]
        assert metadata["prompt_sha256"] == manifest["planner"]["sha256"] and metadata["call_count"] == 1
        decisions = [o for o in observations if o["stage"] == "decision_metadata"]
        assert len(decisions) == response["iterations_used"]
        for decision in decisions:
            metadata = decision["metadata"]
            assert metadata["prompt_version"] == identity["decision_prompt_version"]
            assert metadata["prompt_sha256"] == identity["decision_prompt_sha256"]
            assert metadata["toolset_sha256"] == identity["effective_toolset_sha256"]
            assert metadata["call_count"] in {1, 2}
            if metadata["repair_attempted"]:
                repairs.append({"id": row["id"], "arm": row["arm"],
                                "category": metadata["initial_parse_category"],
                                "succeeded": metadata["repair_succeeded"],
                                "initial_finish_reason": metadata["initial_finish_reason"]})
        requirements = [o for o in observations if o["stage"] == "requirement_identity"]
        assert requirements and all(o["router_version"] == identity["router_version"] for o in requirements)
        if row["id"] in {"R06", "T02", "T03", "T04"} and identity["code_search_version"] == "code_search_v7":
            assert all(o["profile"] == "PROJECT_TEST_V1" and o["groups"] == [["project_test"]] for o in requirements)
        tools = [o for o in observations if o["stage"] == "tool_result"]
        assert len(tools) == response["tool_calls_used"]
        assert all(o["status"] == "ok" for o in tools)
        for evidence in response["evidence"]:
            if evidence["kind"] not in {"project_code", "project_doc", "project_test"}:
                continue
            reads = [o["result"] for o in tools if o["tool"] == "read_project_context" and o["result"]["path"] == evidence["path"]
                     and o["result"]["start_line"] == evidence["start_line"] and o["result"]["end_line"] == evidence["end_line"]]
            assert reads and any(project_context_snippet(r) == evidence["snippet"] for r in reads)
        if row["id"] == "T04":
            assert response["status"] == "refused" and response["answer"] is None
            assert not any(e["kind"] == "project_test" for e in response["evidence"])
            assert all(not (o["result"] or {}).get("matches") for o in tools)
        if row["id"] in {"K01", "C02"}:
            assert response["status"] == "completed" and response["evidence"] == []
            assert next(o for o in observations if o["stage"] == "retrieval")["retrieval_call_count"] == 0
        if row["id"] == "C02":
            assert response["answer"] == "1073"
            assert len(tools) == 1 and tools[0]["tool"] == "calculator" and tools[0]["result"]["value"] == 1073
        if row["id"] == "K01":
            assert not tools
    summary = {"requests": len(rows), "repairs": repairs, "arms": {}}
    for arm in ("baseline", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        metadata = [o["call_metadata"] if o["stage"] == "planner" else o["metadata"] for row in selected for o in row["observations"]
                    if o["stage"] in {"planner", "decision_metadata"}]
        summary["arms"][arm] = {
            "status_counts": dict(Counter(row["public_response"]["status"] for row in selected)),
            "review_counts": dict(Counter(r["grade"] for r in reviews if r["arm"] == arm)),
            "provider_calls": sum(m["call_count"] for m in metadata),
            "input_tokens": sum(m.get("input_tokens") or 0 for m in metadata),
            "output_tokens": sum(m.get("output_tokens") or 0 for m in metadata),
            "tool_calls": sum(row["public_response"]["tool_calls_used"] for row in selected),
        }
    return summary


def main():
    frozen = read(ARCHIVE / "phase1_integrity.json")["files_sha256"]
    for name, expected in frozen.items():
        assert sha(ARCHIVE / name) == expected, f"Phase 1 archive changed: {name}"
    first = audit_phase(ARCHIVE, current=False)
    followup = audit_phase(ARCHIVE / "definition_policy_followup", current=True)
    for name, expected in read(ARCHIVE / "definition_policy_followup/manifest.json")["production_sha256"].items():
        assert sha(ARCHIVE / "definition_policy_followup/candidate" / name) == expected
    if (ARCHIVE / "final_integrity.json").exists():
        for name, expected in read(ARCHIVE / "final_integrity.json")["files_sha256"].items():
            assert sha(REPO / name) == expected, f"Final artifact changed: {name}"
    outcome = {"phase1": first, "definition_policy_followup": followup,
               "total_requests": first["requests"] + followup["requests"],
               "total_provider_calls": sum(arm["provider_calls"] for phase in (first, followup) for arm in phase["arms"].values()),
               "independent_formal_acceptance": False, "source_test_execution_performed": False,
               "all_frozen_boundaries_verified": True}
    output = ARCHIVE / "outcome.json"
    serialized = json.dumps(outcome, ensure_ascii=False, indent=2) + "\n"
    if output.exists():
        assert output.read_text(encoding="utf-8") == serialized
    else:
        output.write_text(serialized, encoding="utf-8")
    print(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    main()
