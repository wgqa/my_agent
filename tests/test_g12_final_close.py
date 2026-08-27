from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE12_DIR = REPO_ROOT / "evaluation" / "gate12"
CLOSURE_PATH = GATE12_DIR / "gate12_final_close_v1.json"
ASSESSMENT_PATH = GATE12_DIR / "system_c_final_assessment_v1.json"
BASELINE_MANUAL_PATH = GATE12_DIR / "baseline_a_manual_review_v1.jsonl"
BASELINE_MANIFEST_PATH = GATE12_DIR / "baseline_a_manual_review_manifest_v1.json"
SYSTEM_C_MANUAL_PATH = GATE12_DIR / "system_c_manual_review_v1.jsonl"
SYSTEM_C_SUMMARY_PATH = GATE12_DIR / "system_c_manual_review_summary_v1.json"
BENCHMARK_MANIFEST_PATH = GATE12_DIR / "final_benchmark_manifest_v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_gate12_final_closure_identity_and_status_are_frozen():
    closure = _load_json(CLOSURE_PATH)

    assert closure["schema_version"] == "gate12_final_close_v1"
    assert closure["gate12_status"] == "CLOSED / FROZEN"
    assert closure["core_agent_system"] == "COMPLETE"
    assert closure["final_gate12_baseline"] == (
        "299632e6d78c1a0fb83f32c7dea7be70cc53e9fd"
    )
    assert closure["dataset"] == "gate12-v1-630fc8b527c2"
    assert closure["benchmark_sha"] == (
        "630fc8b527c22d3e7afc4f4288788524f5dfb52f5ed6ade13ec050abc35f215f"
    )
    assert closure["baseline_a_run"] == "g12-baseline-a-formal-20260825-195305"
    assert closure["system_c_run"] == "g12-system-c-formal-manual-20260826-203236"
    assert closure["system_c_product"] == "65ee45eb52c45e95d2871aa9060416dabcd3d759"
    assert closure["acceptance_contract_sha"] == (
        "5a9d190dcb585a29097fac206c14aa0f31c27d178d8fe0cae8d72b1b8c17bb8f"
    )
    assert closure["system_c_final_assessment_commit"] == closure["final_gate12_baseline"]


def test_gate12_final_closure_accepts_negative_result_without_automatic_repair():
    closure = _load_json(CLOSURE_PATH)

    assert closure["system_c_final_classification"] == "VALID / FAIL"
    assert closure["no_further_system_c_rerun"] is True
    assert closure["negative_result_accepted"] is True
    assert closure["no_benchmark_aware_router_patch"] is True
    assert closure["automatic_gate_13_opened"] is False
    assert closure["closure_policy"] == {
        "current_core_agent_project_phase_complete": True,
        "no_automatic_next_generation_repair": True,
        "no_automatic_gate_13": True,
        "future_enhancement_examples": [
            "Evidence Planning 2.0",
            "semantic requirement routing",
            "Graph-based planning",
            "multi-agent",
            "GraphRAG",
        ],
        "future_enhancement_boundary": (
            "A future phase is independent enhancement work, not an attempt to repair "
            "or select a better G12 result."
        ),
    }


def test_gate12_final_closure_binds_valid_assessment_and_manual_gold_identities():
    closure = _load_json(CLOSURE_PATH)
    assessment = _load_json(ASSESSMENT_PATH)
    baseline_manifest = _load_json(BASELINE_MANIFEST_PATH)
    system_c_summary = _load_json(SYSTEM_C_SUMMARY_PATH)

    assert assessment["final_classification"] == "VALID / FAIL"
    assert assessment["rerun_policy"]["no_further_system_c_rerun"] is True
    assert closure["system_c_final_classification"] == assessment["final_classification"]

    baseline_identity = closure["manual_gold_identities"]["baseline_a"]
    assert baseline_identity == {
        "file": "baseline_a_manual_review_v1.jsonl",
        "sha256": "2162ab579a56369b4f6bc5665e1d0e62493a1b729e7a2e1d1dc8bb5366f92758",
        "manifest_file": "baseline_a_manual_review_manifest_v1.json",
        "run_id": "g12-baseline-a-formal-20260825-195305",
    }
    assert hashlib.sha256(BASELINE_MANUAL_PATH.read_bytes()).hexdigest() == baseline_identity["sha256"]
    assert baseline_manifest["manual_review_sha256"] == baseline_identity["sha256"]
    assert baseline_manifest["run_id"] == baseline_identity["run_id"]

    system_c_identity = closure["manual_gold_identities"]["system_c"]
    assert system_c_identity == {
        "file": "system_c_manual_review_v1.jsonl",
        "sha256": "6ac8edaaa2cee86f4fafea2a152a77b02c048839c62ac7bd1115cdeb87bc4b67",
        "summary_file": "system_c_manual_review_summary_v1.json",
        "run_id": "g12-system-c-formal-manual-20260826-203236",
    }
    assert hashlib.sha256(SYSTEM_C_MANUAL_PATH.read_bytes()).hexdigest() == system_c_identity["sha256"]
    assert system_c_summary["run_id"] == system_c_identity["run_id"]
    assert system_c_summary["gate12_dataset_freeze_id"] == closure["dataset"]


def test_gate12_final_closure_freezes_final_capability_metrics():
    closure = _load_json(CLOSURE_PATH)
    benchmark_manifest = _load_json(BENCHMARK_MANIFEST_PATH)
    assessment = _load_json(ASSESSMENT_PATH)
    baseline_manifest = _load_json(BASELINE_MANIFEST_PATH)
    system_c_summary = _load_json(SYSTEM_C_SUMMARY_PATH)
    conclusions = closure["final_capability_conclusions"]

    assert benchmark_manifest["gate12_dataset_freeze_id"] == closure["dataset"]
    assert benchmark_manifest["final_benchmark_jsonl_sha256"] == closure["benchmark_sha"]
    assert conclusions["baseline_a"] == {
        "task_success": {"PASS": 2, "PARTIAL": 8, "FAIL": 6},
        "evidence_sufficiency": "2/16",
        "premature_finalization": "12/16",
        "claim_grounding": {"PASS": 1, "PARTIAL": 8, "FAIL": 7},
    }
    assert conclusions["system_c"] == {
        "task_success": {"PASS": 2, "PARTIAL": 7, "FAIL": 7},
        "evidence_sufficiency": "2/16",
        "premature_finalization": "9/16",
        "claim_grounding": {"PASS": 1, "PARTIAL": 5, "FAIL": 10},
    }
    assert conclusions["baseline_a"]["task_success"] == baseline_manifest["full_task_success"]
    assert conclusions["baseline_a"]["claim_grounding"] == baseline_manifest["claim_grounding"]
    assert conclusions["system_c"]["task_success"] == system_c_summary["task_success"]
    assert conclusions["system_c"]["claim_grounding"] == system_c_summary["claim_grounding"]
    assert conclusions["baseline_a"]["evidence_sufficiency"] == (
        f"{assessment['baseline_a']['automatic']['evidence_sufficiency_cases']}/16"
    )
    assert conclusions["baseline_a"]["premature_finalization"] == (
        f"{assessment['baseline_a']['automatic']['premature_finalization_cases']}/16"
    )
    assert conclusions["system_c"]["evidence_sufficiency"] == (
        f"{assessment['system_c']['automatic']['evidence_sufficiency_cases']}/16"
    )
    assert conclusions["system_c"]["premature_finalization"] == (
        f"{assessment['system_c']['automatic']['premature_finalization_cases']}/16"
    )
    assert "mixed task capability" in conclusions["engineering_conclusion"]
    assert conclusions["closure_conclusion"] == (
        "因此 Gate 12 接受 negative result 并冻结，不进行 benchmark-aware Router patch 或结果选择式 rerun。"
    )


def test_gate12_final_closure_preserves_provider_incident_and_reproducibility_boundary():
    closure = _load_json(CLOSURE_PATH)

    assert closure["provider_incident_provenance"] == {
        "early_invalid_system_c_runs": [
            {
                "run_id": "g12-system-c-formal-20260826-173039",
                "classification": "INVALID / PROVIDER-PLANE FAILURE",
            },
            {
                "run_id": "g12-system-c-formal-r1-20260826-191531",
                "classification": "INVALID / PROVIDER-PLANE FAILURE",
            },
        ],
        "underlying_error": "APIConnectionError",
        "manual_powershell_equivalent_api_health": "PASS",
        "final_manual_process_16_case_formal": "VALID",
        "environment_note": (
            "Agent-managed execution environment showed reproducible APIConnectionError, "
            "while manually launched equivalent API processes succeeded."
        ),
    }
    assert closure["reproducibility_lesson"]["future_real_network_provider_or_long_formal_execution"] == (
        "operator runs from a normal local shell"
    )
