from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.gate12.baseline_contract import load_frozen_final_dataset
from evaluation.gate12.system_c_contract import load_system_c_acceptance_contract


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE12_DIR = REPO_ROOT / "evaluation" / "gate12"
MANUAL_PATH = GATE12_DIR / "system_c_manual_review_v1.jsonl"
SUMMARY_PATH = GATE12_DIR / "system_c_manual_review_summary_v1.json"
ASSESSMENT_PATH = GATE12_DIR / "system_c_final_assessment_v1.json"
NOTE_PATH = REPO_ROOT / "docs" / "study-notes" / "123-G12-System-C负结果与Finalization-Guard边界.md"

CASE_IDS = [f"g12q{number:03d}" for number in range(1, 17)]
TASK_SUCCESS_VALUES = {"PASS", "PARTIAL", "FAIL"}
COVERAGE_VALUES = {"FULL", "PARTIAL", "NONE"}
CORRECTNESS_VALUES = {"PASS", "PARTIAL", "FAIL", "NO_EVIDENCE"}
GROUNDING_VALUES = {"PASS", "PARTIAL", "FAIL"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_manual_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in MANUAL_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_system_c_manual_review_has_exact_frozen_case_set_and_enums():
    rows = _load_manual_rows()
    assert len(rows) == 16
    assert [row["case_id"] for row in rows] == CASE_IDS
    assert {row["case_id"] for row in rows} == set(CASE_IDS)

    required_keys = {
        "case_id",
        "task_family",
        "project_id",
        "full_task_success",
        "evidence_coverage",
        "evidence_correctness",
        "claim_grounding",
    }
    assert all(set(row) == required_keys for row in rows)
    assert all(row["full_task_success"] in TASK_SUCCESS_VALUES for row in rows)
    assert all(row["evidence_coverage"] in COVERAGE_VALUES for row in rows)
    assert all(row["evidence_correctness"] in CORRECTNESS_VALUES for row in rows)
    assert all(row["claim_grounding"] in GROUNDING_VALUES for row in rows)


def test_manual_aggregates_are_recomputed_from_case_rows():
    rows = _load_manual_rows()
    summary = _load_json(SUMMARY_PATH)

    task_success = Counter(row["full_task_success"] for row in rows)
    coverage = Counter(row["evidence_coverage"] for row in rows)
    correctness = Counter(row["evidence_correctness"] for row in rows)
    grounding = Counter(row["claim_grounding"] for row in rows)
    family_success: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        family_success[row["task_family"]][row["full_task_success"]] += 1

    assert dict(task_success) == summary["task_success"] == {
        "PASS": 2,
        "PARTIAL": 7,
        "FAIL": 7,
    }
    assert dict(coverage) == summary["evidence_coverage"] == {
        "FULL": 1,
        "PARTIAL": 8,
        "NONE": 7,
    }
    assert dict(correctness) == summary["evidence_correctness"] == {
        "PASS": 5,
        "PARTIAL": 4,
        "FAIL": 3,
        "NO_EVIDENCE": 4,
    }
    assert dict(grounding) == summary["claim_grounding"] == {
        "PASS": 1,
        "PARTIAL": 5,
        "FAIL": 10,
    }
    assert sum(task_success[value] for value in ("PASS", "PARTIAL")) == 9
    assert summary["partial_or_better_cases"] == 9
    assert summary["strict_full_task_success_rate"] == 2 / 16
    assert summary["partial_or_better_rate"] == 9 / 16

    expected_families = {
        "Theory <-> Code": {"PASS": 1, "PARTIAL": 3, "FAIL": 0},
        "Change Impact <-> Test": {"PASS": 1, "PARTIAL": 0, "FAIL": 3},
        "Diagnosis / Config": {"PASS": 0, "PARTIAL": 2, "FAIL": 2},
        "Docs <-> Code": {"PASS": 0, "PARTIAL": 2, "FAIL": 2},
    }
    assert {
        family: {value: counts[value] for value in ("PASS", "PARTIAL", "FAIL")}
        for family, counts in family_success.items()
    } == expected_families == summary["family_task_success"]


def test_manual_rows_match_frozen_benchmark_identity():
    dataset = load_frozen_final_dataset(GATE12_DIR)
    expected = {
        case["case_id"]: (case["task_family"], case["project_id"])
        for case in dataset["cases"]
    }
    rows = _load_manual_rows()
    assert {row["case_id"] for row in rows} == set(expected)
    assert {
        row["case_id"]: (row["task_family"], row["project_id"])
        for row in rows
    } == expected
    assert dataset["identity"]["gate12_dataset_freeze_id"] == "gate12-v1-630fc8b527c2"
    assert dataset["identity"]["final_benchmark_sha256"] == (
        "630fc8b527c22d3e7afc4f4288788524f5dfb52f5ed6ade13ec050abc35f215f"
    )


def test_final_assessment_binds_formal_artifacts_and_frozen_controls():
    assessment = _load_json(ASSESSMENT_PATH)
    summary = _load_json(SUMMARY_PATH)
    identity = assessment["run_identity"]

    assert assessment["run_validity"] == "VALID"
    assert assessment["system_c_acceptance"] == "FAIL"
    assert assessment["final_classification"] == "VALID / FAIL"
    assert identity == {
        "run_id": "g12-system-c-formal-manual-20260826-203236",
        "gate12_dataset_freeze_id": "gate12-v1-630fc8b527c2",
        "final_benchmark_sha256": "630fc8b527c22d3e7afc4f4288788524f5dfb52f5ed6ade13ec050abc35f215f",
        "acceptance_contract_sha256": "5a9d190dcb585a29097fac206c14aa0f31c27d178d8fe0cae8d72b1b8c17bb8f",
        "evaluator_commit": "c2ca9bd5c52ab1b7f9e94e869cd716be53dce0e0",
        "system_c_product_commit": "65ee45eb52c45e95d2871aa9060416dabcd3d759",
        "case_results_sha256": "630a909e5563cd2c14d9d8ea4b292f0283e934acf6e02a659265d0edfbb694d6",
        "manual_review_file": "system_c_manual_review_v1.jsonl",
    }
    assert summary["run_id"] == identity["run_id"]
    assert summary["case_results_sha256"] == identity["case_results_sha256"]
    assert summary["acceptance_contract_sha256"] == identity["acceptance_contract_sha256"]
    assert summary["system_c_product_commit"] == identity["system_c_product_commit"]
    assert all(
        len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)
        for digest in summary["source_artifact_sha256"].values()
    )
    assert summary["source_artifact_sha256"]["case_results.jsonl"] == identity["case_results_sha256"]
    assert summary["source_artifact_sha256"]["summary.json"] == (
        "3816f14e67b33daf6dd7181766b290bbd8d9dabce5948b3819543130bc802523"
    )

    controls = assessment["frozen_controls"]
    assert controls["prompt_version"] == "engineering_agent_decision_prompt_v2"
    assert controls["prompt_sha256"] == (
        "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
    )
    assert controls["repair_prompt_version"] == "engineering_action_repair_prompt_v1"
    assert controls["repair_prompt_sha256"] == (
        "958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636"
    )
    assert controls["max_output_tokens"] == 1200
    assert controls["budget"] == {
        "max_agent_iterations": 5,
        "max_tool_calls": 4,
        "max_tool_errors": 2,
    }
    assert controls["registry_size"] == 7
    assert controls["request_payload_fields"] == ["question"]
    assert controls["prompt_modified"] is False
    assert controls["gold_metadata_injected"] is False
    assert controls["task_family_hint_injected"] is False


def test_acceptance_contract_identity_and_baseline_manual_values_are_unchanged():
    assessment = _load_json(ASSESSMENT_PATH)
    contract = load_system_c_acceptance_contract()
    baseline = assessment["baseline_a"]

    assert contract["acceptance_contract_sha256"] == (
        "5a9d190dcb585a29097fac206c14aa0f31c27d178d8fe0cae8d72b1b8c17bb8f"
    )
    assert baseline["run_id"] == "g12-baseline-a-formal-20260825-195305"
    assert baseline["product_baseline_commit"] == (
        "0a1f42e8ee0320486dbd0ddc01400e1e19150501"
    )
    assert baseline["manual_gold"] == {
        "full_task_success": {"PASS": 2, "PARTIAL": 8, "FAIL": 6},
        "strict_full_task_success_rate": 0.125,
        "partial_or_better_cases": 10,
        "partial_or_better_rate": 0.625,
        "evidence_coverage": {"FULL": 1, "PARTIAL": 8, "NONE": 7},
        "evidence_correctness": {"PASS": 5, "PARTIAL": 5, "FAIL": 3, "NO_EVIDENCE": 3},
        "claim_grounding": {"PASS": 1, "PARTIAL": 8, "FAIL": 7},
    }
    assert baseline["automatic"]["provider_calls"] == 54
    assert baseline["automatic"]["tool_calls"] == 37
    assert baseline["automatic"]["iterations"] == 53


def test_system_c_automatic_metrics_and_frozen_threshold_failures_are_explicit():
    assessment = _load_json(ASSESSMENT_PATH)
    automatic = assessment["system_c"]["automatic"]
    failures = {item["metric"]: item for item in assessment["threshold_evaluation"]["hard_failures"]}
    passed = {item["metric"]: item for item in assessment["threshold_evaluation"]["passed_controls"]}

    assert automatic["case_count"] == 16
    assert automatic["completed_cases"] == 11
    assert automatic["refused_cases"] == 4
    assert automatic["failed_cases"] == 1
    assert automatic["evidence_sufficiency_cases"] == 2
    assert automatic["premature_finalization_cases"] == 9
    assert automatic["required_tool_complete_cases"] == 7
    assert automatic["provider_calls"] == 57
    assert automatic["tool_calls"] == 39
    assert automatic["iterations"] == 56
    assert automatic["forbidden_tool_calls"] == 0
    assert automatic["structured_parse_failure_cases"] == 1
    assert automatic["duplicate_tool_stops"] == 2
    assert automatic["budget_stops"] == 0
    assert automatic["family_evidence_sufficiency"] == {
        "Theory <-> Code": 2,
        "Change Impact <-> Test": 0,
        "Diagnosis / Config": 0,
        "Docs <-> Code": 0,
    }
    assert all(item["passed"] is False for item in failures.values() if item["metric"] != "Theory <-> Code evidence sufficiency")
    assert failures["Theory <-> Code evidence sufficiency"]["passed"] is True
    assert all(item["passed"] is True for item in passed.values())
    assert assessment["threshold_evaluation"]["automatic_guard_invariant"] == {
        "completed_with_insufficient_evidence": 9,
        "required": 0,
        "passed": False,
    }


def test_q004_q006_tradeoff_and_negative_result_boundaries_are_recorded():
    assessment = _load_json(ASSESSMENT_PATH)
    audit = assessment["tradeoff_audit"]
    q004 = audit["q004"]
    q006 = audit["q006"]

    assert q004["automatic_evidence_sufficiency"] is True
    assert q004["manual_full_task_success"] == "PARTIAL"
    assert q004["observed_shape"] == ["knowledge", "project_doc"]
    assert q004["missing_key_evidence"] == "pydantic_ai_slim/pydantic_ai/_agent_graph.py"
    assert q004["conclusion"] == (
        "Structural evidence sufficiency does not imply semantic evidence sufficiency."
    )
    assert q006["automatic_evidence_sufficiency"] is False
    assert q006["premature_finalization"] is True
    assert q006["manual_full_task_success"] == "PASS"
    assert q006["observed_evidence"] == ["project_change"]
    assert q006["missing_evidence"] == ["project_test"]
    assert q006["diagnosis_status"] == "POST-HOC DIAGNOSIS; NO ROUTER PATCH; NO RERUN"
    assert assessment["root_cause_summary"]["guard_boundary"].startswith(
        "The Guard can block unsupported completion"
    )
    assert assessment["rerun_policy"]["no_further_system_c_rerun"] is True
    assert assessment["early_provider_invalid_runs"] == [
        {"run_id": "g12-system-c-formal-20260826-173039", "classification": "INVALID / PROVIDER-PLANE FAILURE"},
        {"run_id": "g12-system-c-formal-r1-20260826-191531", "classification": "INVALID / PROVIDER-PLANE FAILURE"},
    ]


def test_final_assessment_has_no_absolute_paths_and_note_preserves_no_patch_boundary():
    assessment_text = ASSESSMENT_PATH.read_text(encoding="utf-8")
    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
    assert "D:\\" not in assessment_text
    assert "D:\\" not in summary_text

    note = NOTE_PATH.read_text(encoding="utf-8")
    assert "不修改 Router" in note
    assert "不对同一 benchmark 重跑" in note
    assert "Agent-managed execution environment showed reproducible APIConnectionError" in note
    assert "实验假设是 `VALID / FAIL`" in note


def test_final_assessment_artifact_is_deterministically_valid_json():
    for path in (MANUAL_PATH, SUMMARY_PATH, ASSESSMENT_PATH):
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        else:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
    assert hashlib.sha256(MANUAL_PATH.read_bytes()).hexdigest() == (
        "6ac8edaaa2cee86f4fafea2a152a77b02c048839c62ac7bd1115cdeb87bc4b67"
    )
