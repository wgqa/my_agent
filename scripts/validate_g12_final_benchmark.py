"""Validate the frozen G12 final benchmark against real isolated checkouts.

This evaluator-only command delegates repository, historical-diff, Tool, and
knowledge checks to the G12-02A validator, then validates final-dataset
selection and canonical provenance.  It never calls a provider.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from evaluation.gate12.candidate_contract import CandidateContractError, load_json, load_jsonl
from evaluation.gate12.final_contract import validate_final_benchmark, validate_final_manifest
from scripts.validate_g12_candidate_pool import run_validation as run_candidate_pool_validation


GATE12_DIR = EVALUATOR_ROOT / "evaluation" / "gate12"
REPOSITORY_REGISTRY_PATH = GATE12_DIR / "repositories_v1.json"
CANDIDATE_POOL_PATH = GATE12_DIR / "candidate_pool_v1.jsonl"
CANDIDATE_MANIFEST_PATH = GATE12_DIR / "candidate_pool_manifest_v1.json"
FINAL_BENCHMARK_PATH = GATE12_DIR / "final_benchmark_v1.jsonl"
FINAL_MANIFEST_PATH = GATE12_DIR / "final_benchmark_manifest_v1.json"
REVIEWER_SELECTION_PATH = GATE12_DIR / "reviewer_selection_v1.json"


def run_validation(
    *, my_agent_root: Path, pydantic_ai_root: Path, corpus_root: Path
) -> dict[str, Any]:
    """Return public, root-free validation output for the frozen final dataset."""

    candidate_report = run_candidate_pool_validation(
        my_agent_root=my_agent_root,
        pydantic_ai_root=pydantic_ai_root,
        corpus_root=corpus_root,
    )
    registry = load_json(REPOSITORY_REGISTRY_PATH)["repositories"]
    candidates = load_jsonl(CANDIDATE_POOL_PATH)
    candidate_manifest = load_json(CANDIDATE_MANIFEST_PATH)
    cases = load_jsonl(FINAL_BENCHMARK_PATH)
    final_manifest = load_json(FINAL_MANIFEST_PATH)
    selection = load_json(REVIEWER_SELECTION_PATH)
    final_report = validate_final_benchmark(
        cases, candidates, registry, candidate_manifest, selection
    )
    validate_final_manifest(
        final_manifest,
        cases,
        final_benchmark_path=FINAL_BENCHMARK_PATH,
        reviewer_selection_path=REVIEWER_SELECTION_PATH,
        candidate_manifest=candidate_manifest,
        repository_manifest_path=REPOSITORY_REGISTRY_PATH,
    )
    return {
        "schema_version": "g12_final_benchmark_validation_v1",
        "status": "PASS",
        "dataset_freeze_id": final_manifest["gate12_dataset_freeze_id"],
        "case_count": len(cases),
        "distribution": {
            "family": final_report["family_distribution"],
            "repository": final_report["repository_distribution"],
            "family_repository": final_report["family_repository_distribution"],
        },
        "structural_diagnostics": final_report["structural_diagnostics"],
        "repository_identities": {
            project_id: details["checkout"]
            for project_id, details in candidate_report["projects"].items()
        },
        "knowledge_identity": candidate_report["knowledge"]["identity"],
        "historical_change_validation": "PASS / delegated to candidate_contract",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the G12 frozen final benchmark against isolated repositories."
    )
    parser.add_argument("--my-agent-root", type=Path, required=True)
    parser.add_argument("--pydantic-ai-root", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_validation(
            my_agent_root=args.my_agent_root,
            pydantic_ai_root=args.pydantic_ai_root,
            corpus_root=args.corpus_root,
        )
    except (CandidateContractError, OSError, subprocess.CalledProcessError) as exc:
        print(f"G12 final benchmark validation: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
