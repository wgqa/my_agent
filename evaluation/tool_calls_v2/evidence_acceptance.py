"""Frozen A/B/C/D regression, additional-case acceptance and D stability runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .author_acceptance import NEW_CASES, NEW_PROTOCOL
from .evidence_experiment import execute
from .manifest import REPO_ROOT
from .schema import digest, load_cases, validate_case

VERSION = "engineering_evidence_acceptance_v1"


def frozen_cases():
    protocol = json.loads(NEW_PROTOCOL.read_text(encoding="utf-8"))
    known = load_cases()
    new = [json.loads(line) for line in NEW_CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    for case in new:
        validate_case(case)
    if (len(known) != 72 or len(new) != 24 or digest(known) != protocol["known_sha256"]
            or digest(new) != protocol["new_sha256"]
            or len({c["id"] for c in known + new}) != 96
            or len({c["query"] for c in known + new}) != 96):
        raise ValueError("Frozen evaluation matrix changed")
    return known, new, protocol


def select_phase(phase):
    known, new, protocol = frozen_cases()
    if phase == "regression":
        cases, groups = known, ["A", "B", "C", "D"]
    elif phase == "new":
        cases, groups = new, ["A", "B", "C", "D"]
    elif phase in {"stability-2", "stability-3"}:
        by_id = {c["id"]: c for c in known + new}
        cases = [by_id[key] for key in protocol["stability_ids"]]
        groups = ["D"]
    else:
        raise ValueError("Unknown formal phase")
    return cases, groups, {"phase": phase, "protocol_sha256": hashlib.sha256(NEW_PROTOCOL.read_bytes()).hexdigest(),
        "known_sha256": protocol["known_sha256"], "new_sha256": protocol["new_sha256"],
        "sealed_holdout": False, "reviewer_type": "developer_assistant"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("regression", "new", "stability-2", "stability-3"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--preflight", action="store_true", help="Actual Gold tools, zero models; synthetic terminal only")
    parser.add_argument("--knowledge-source", type=Path)
    args = parser.parse_args(argv)
    if args.live and args.preflight:
        raise ValueError("Preflight cannot call models")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.run_id):
        raise ValueError("Invalid run ID")
    cases, groups, identity = select_phase(args.phase)
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    output = REPO_ROOT / "data/runtime/evidence_experiments" / args.run_id
    summary = execute(cases=cases, groups=groups, run_id=args.run_id, output=output,
        source_cache=REPO_ROOT / "data/runtime/tool_call_v2/source_cache", corpus_root=args.knowledge_source,
        live=args.live, experiment_version=VERSION,
        scope="72 historical regression and 24 newly authored cases, reported separately; no business tuning during runs",
        protocol_identity=identity)
    if args.preflight:
        from core.knowledge_library import KnowledgeLibrary
        from .observer import Recorder
        from .product_runtime import build_evaluation_registry
        from .reporting import write_json
        from .runner import run_gold_proof
        from .scorer import score_case
        library = KnowledgeLibrary(output / "state/knowledge.sqlite3")
        scores = []
        for case in cases:
            recorder = Recorder(case["id"], fault=case["fault"])
            registry = build_evaluation_registry(output / "state/projects" / case["project"], library.retrieval_port)
            run_gold_proof(case, registry, recorder)
            scores.append({"case_id": case["id"], "score": score_case(case, recorder.events, mode="gold_proof"),
                           "events": recorder.events})
        proof = {"schema_version": "evidence_acceptance_reachability_v1", "model_calls": 0,
            "synthetic_terminal": True, "cases": len(cases),
            "pass": sum(s["score"]["verdict"] == "PASS" for s in scores), "scores": scores}
        write_json(output / "gold_reachability.json", proof)
        print(json.dumps({k: v for k, v in proof.items() if k != "scores"}), flush=True)
        return 0 if proof["pass"] == proof["cases"] else 2
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 2 if summary["status"] == "interrupted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
