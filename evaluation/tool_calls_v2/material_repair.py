"""Versioned material-only regression; original four-group protocol stays frozen."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from .evidence_acceptance import frozen_cases
from .evidence_experiment import execute
from .fixtures import project_identity
from .manifest import REPO_ROOT, business_fingerprint, evaluator_fingerprint
from .reporting import write_json
from .schema import digest

VERSION = "engineering_material_repair_experiment_v1"
GROUPS = {"D": ("llm", "goal_v2", "semantic_v1"), "D2": ("llm", "goal_v2", "semantic_v2")}
FOCUSED_IDS = ("dev-007", "dev-013", "dev-017", "dev-020", "dev-025", "dev-026", "dev-037", "dev-040",
               "val-005", "val-019", "val-020", "val-021", "val-110", "val-116", "val-117", "val-120", "val-123", "val-124")


def select_cases(selection):
    historical, newer, protocol = frozen_cases()
    by_id = {case["id"]: case for case in historical + newer}
    return ([by_id[key] for key in FOCUSED_IDS] if selection == "focused" else historical + newer), protocol


def _record(raw):
    from core.engineering_materials import MaterialRecord, ToolResultEvidence
    from core.engineering_requirement_contract import canonical_json
    from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence
    e = raw["evidence"]
    if e["kind"] == "knowledge":
        evidence = KnowledgeEvidence(**e)
    elif e["kind"] == "tool_result":
        evidence = ToolResultEvidence(e["evidence_id"], e["tool_name"], e["tool_version"],
            canonical_json(e["arguments"]), canonical_json(e["payload"]))
        if evidence.to_dict() != e:
            raise ValueError("structured source evidence identity changed")
    else:
        evidence = EngineeringEvidence(**e)
    return MaterialRecord(evidence, tuple(raw["source_kinds"]), raw["form"],
                          canonical_json(raw["details"]), canonical_json(raw["provenance"]))


def component_probe(source_runs, output):
    """Keep contracts/answers/IDs fixed; enrich only byte-identical Reader bodies.

    This is a deterministic support diagnosis, NOT a new model approval, task
    score, terminal outcome, or an end-to-end answer-quality evaluation.
    """
    from core.conversation_context.resolver import build_reference_query
    from core.engineering_context import EngineeringContextSnapshot
    from core.engineering_candidate_verification import material_matches_goal
    from core.engineering_material_matching import goal_material_ids
    from core.engineering_materials import MaterialLedger
    from core.engineering_requirement_contract import canonical_json, parse_requirement_output
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall
    from core.tool_agent.registry import ToolRegistry
    from core.tool_agent.tools.read_project_snapshot import READ_PROJECT_SNAPSHOT_SPEC, ReadProjectSnapshotHandler

    if output.exists():
        raise ValueError("probe output already exists; never overwrite")
    output.mkdir(parents=True)
    entries, source_identities, checked_artifacts, checked_bodies = [], [], 0, 0
    for source in source_runs:
        manifest_path = source/"manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["status"] != "finished":
            raise ValueError("source run is not complete")
        cases = [json.loads(line) for line in (source/"cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if digest(cases) != manifest["cases_sha256"]:
            raise ValueError("source case matrix changed")
        projects = {case["id"]: case["project"] for case in cases}
        roots = {name: source/"state/projects"/name for name in manifest["projects"]}
        for name, root in roots.items():
            if digest(project_identity(name, root, manifest["projects"][name]["upstream_commit"])) != digest(manifest["projects"][name]):
                raise ValueError("source fixture changed")
        source_identities.append({"run_id": manifest["run_id"], "code_head": manifest["code_head"],
            "cases_sha256": manifest["cases_sha256"], "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "runs_sha256": hashlib.sha256((source/"runs.jsonl").read_bytes()).hexdigest()})
        rows = [json.loads(line) for line in (source/"runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            if row["group"] != "D":
                continue
            path = source/row["artifact"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["artifact_sha256"]:
                raise ValueError("source artifact changed")
            checked_artifacts += 1
            audit = json.loads(path.read_text(encoding="utf-8"))["audit"]
            enriched = {}
            for raw in audit["materials"]:
                if raw["form"] != "body" or raw["provenance"].get("tool_name") != "read_project_context":
                    continue
                registry = ToolRegistry()
                registry.register(READ_PROJECT_SNAPSHOT_SPEC, ReadProjectSnapshotHandler(roots[projects[row["case_id"]]]))
                call = ToolCall.create("read_project_context", raw["provenance"]["arguments"])
                observation = ToolExecutor(registry).execute(call)
                if observation.status != "ok":
                    raise ValueError("successful frozen read could not be reproduced")
                before = {k: v for k, v in observation.result.items() if k not in {"source_snapshot", "region_objects"}}
                if digest(before) != raw["provenance"]["returned_content_sha256"]:
                    raise ValueError("Reader body or selection differs; cannot attribute to metadata")
                ledger = MaterialLedger(registry.list_specs(), binding_identity=raw["provenance"]["binding_identity"])
                ledger.observe(call, observation)
                identity = {k: v for k, v in raw["evidence"].items() if k != "evidence_id"}
                match = [m for m in ledger.records
                         if {k: v for k, v in m.evidence.to_dict().items() if k != "evidence_id"} == identity]
                if len(match) != 1:
                    raise ValueError("source fragment identity is not unique")
                enriched[raw["evidence"]["evidence_id"]] = replace(match[0],
                    evidence=replace(match[0].evidence, evidence_id=raw["evidence"]["evidence_id"]))
                checked_bodies += 1
            for index, submission in enumerate(audit["submissions"]):
                payload = submission["input"]
                request = payload["request"]
                snapshot = EngineeringContextSnapshot(request["current_request"],
                    build_reference_query(request["current_request"], request["reference_context"]),
                    (), 0, 0, 0, False, False, False, request["reference_context"])
                raw_goals = [{k: v for k, v in g.items() if k != "goal_id"} for g in payload["contract"]["goals"]]
                contract = parse_requirement_output(canonical_json({"schema_version": payload["contract"]["schema_version"],
                                                                    "goals": raw_goals}), snapshot)
                if contract.to_dict() != payload["contract"]:
                    raise ValueError("frozen contract identity changed")
                old = tuple(_record(m) for m in payload["materials"]["materials"])
                new = tuple(enriched.get(m.evidence.evidence_id, m) for m in old)
                before = {g.goal_id: [m.evidence.evidence_id for m in old if material_matches_goal(g, m)] for g in contract.goals}
                after = {g.goal_id: list(goal_material_ids(g, new)) for g in contract.goals}
                accepted = any(r["input_sha256"] == submission["input_sha256"]
                    and r["outcome"].get("result") and r["outcome"]["result"]["decision"] == "accept" for r in audit["reviews"])
                entries.append({"run_id": manifest["run_id"], "case_id": row["case_id"], "submission_index": index,
                    "artifact_sha256": row["artifact_sha256"], "input_sha256": submission["input_sha256"],
                    "original_program_decision": submission["check"]["decision"], "original_review_accept": accepted,
                    "before": before, "after": after,
                    "before_missing": [g.goal_id for g in contract.goals if g.source_kinds and not before[g.goal_id]],
                    "after_missing": [g.goal_id for g in contract.goals if g.source_kinds and not after[g.goal_id]]})
        for name, root in roots.items():
            if digest(project_identity(name, root, manifest["projects"][name]["upstream_commit"])) != digest(manifest["projects"][name]):
                raise ValueError("probe mutated source fixture")
    blocked = [e for e in entries if e["original_review_accept"] and e["original_program_decision"] == "need_material"]
    report = {"schema_version": VERSION, "mode": "fixed_contract_component_probe", "model_calls": 0,
        "scope": "support diagnosis only; original answers, reviews, task scores and terminal outcomes unchanged",
        "business": business_fingerprint(), "evaluator": evaluator_fingerprint(), "sources": source_identities,
        "checked_artifacts": checked_artifacts, "byte_identical_body_records": checked_bodies,
        "review_accept_blocked_before": len(blocked),
        "review_accept_source_gaps_resolved": sum(not e["after_missing"] for e in blocked),
        "lost_previously_supported_goals": sum(bool(e["before"][g]) and not e["after"][g] for e in entries for g in e["before"]),
        "submissions": entries}
    write_json(output/"component_probe.json", report)
    return {k: v for k, v in report.items() if k not in {"business", "evaluator", "sources", "submissions"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--component", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--selection", choices=("focused", "all-known"), default="focused")
    parser.add_argument("--knowledge-source", type=Path)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.run_id) or (args.live and args.component):
        raise ValueError("invalid run identity/mode")
    root = REPO_ROOT/"data/runtime/evidence_experiments"
    output = root/args.run_id
    if args.component:
        summary = component_probe([root/"formal_regression_20261011_v1", root/"formal_new_20261011_v1"], output)
    else:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT/".env")
        cases, protocol = select_cases(args.selection)
        summary = execute(cases=cases, groups=list(GROUPS), group_settings=GROUPS, run_id=args.run_id, output=output,
            source_cache=REPO_ROOT/"data/runtime/tool_call_v2/source_cache", corpus_root=args.knowledge_source,
            live=args.live, experiment_version=VERSION,
            scope="Known-case material repair regression only; prompts unchanged, natural contracts may differ; no blind acceptance",
            protocol_identity={"selection": args.selection, "focused_ids": list(FOCUSED_IDS),
                "known_sha256": protocol["known_sha256"], "new_sha256": protocol["new_sha256"], "sealed_holdout": False})
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 2 if summary.get("status") == "interrupted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
