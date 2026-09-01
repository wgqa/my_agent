"""Provider-free contract tests for the ARCH-EVAL-08B runner."""

from pathlib import Path

import pytest

from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    EXPECTED_FAMILY_COUNTS,
    HOLDOUT_SPLIT,
    HOLDOUT_DATASET_PATH,
    HoldoutExecutionDenied,
    SYSTEM_A_COMMIT,
    SYSTEM_B_COMMIT,
    CORPUS_SOURCE_COMMIT,
    TARGET_PROJECT_COMMIT,
    load_cases,
    load_gold_proof_audit,
    validate_case_gold_coherence,
    validate_gold_proof_audit,
    validate_protocol_manifest,
)
from evaluation.integration_v7.runner import (
    FROZEN_PROTOCOL_SHA,
    RunnerPreflightError,
    aggregate_metrics,
    assert_run_scope,
    build_run_plan,
    build_summary,
    build_worker_job,
    safe_artifact,
    validate_frozen_identities,
)


def _cases(count: int = 18) -> list[dict]:
    return [
        {
            "case_id": f"v7d{index:03d}",
            "split": DEV_SPLIT,
            "task_family": "knowledge_only",
            "question": f"question {index}",
            "conversation_context": [],
        }
        for index in range(1, count + 1)
    ]


def _identity_kwargs() -> dict:
    return {
        "system_heads": {"A": SYSTEM_A_COMMIT, "B": SYSTEM_B_COMMIT},
        "target_head": TARGET_PROJECT_COMMIT,
        "corpus_head": CORPUS_SOURCE_COMMIT,
        "protocol_sha": FROZEN_PROTOCOL_SHA,
    }


def test_runner_is_dev_only_and_holdout_is_denied():
    assert_run_scope(DEV_SPLIT)
    with pytest.raises(HoldoutExecutionDenied):
        assert_run_scope(HOLDOUT_SPLIT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("system_heads", {"A": "bad", "B": SYSTEM_B_COMMIT}),
        ("target_head", "bad"),
        ("corpus_head", "bad"),
        ("protocol_sha", "bad"),
    ],
)
def test_frozen_identity_mismatch_is_rejected(field, value):
    kwargs = _identity_kwargs()
    kwargs[field] = value
    with pytest.raises(RunnerPreflightError):
        validate_frozen_identities(**kwargs)


def test_run_order_alternates_by_case_parity():
    plan = build_run_plan(_cases())
    assert len(plan) == 36
    assert [item["run_order"] for item in plan] == list(range(1, 37))
    assert [(plan[2 * i]["system"], plan[2 * i + 1]["system"]) for i in range(18)] == [
        ("A", "B") if index % 2 else ("B", "A")
        for index in range(1, 19)
    ]


def test_safe_serialization_redacts_paths_and_secrets_and_rejects_raw_fields():
    result = safe_artifact(
        {
            "answer": r"see C:\private\repo and sk-123456789012345",
            "nested": ["/home/user/private", "https://api.deepseek.com/v1"],
        }
    )
    serialized = repr(result)
    assert "C:\\private" not in serialized
    assert "/home/user/private" not in serialized
    assert "sk-123456789012345" not in serialized
    assert "https://api.deepseek.com/v1" in serialized
    with pytest.raises(RunnerPreflightError):
        safe_artifact({"raw_provider_response": "must not be stored"})


def test_metric_aggregation_excludes_invalid_runs_and_averages_numeric_values():
    aggregate = aggregate_metrics(
        [
            {"run_validity": "VALID", "automatic_metrics": {"score": 1, "flag": True}},
            {"run_validity": "VALID", "automatic_metrics": {"score": 0.5, "flag": False}},
            {"run_validity": "INVALID", "automatic_metrics": {"score": 0}},
        ]
    )
    assert aggregate["valid_runs"] == 2
    assert aggregate["invalid_runs_excluded"] == 1
    assert aggregate["metrics"]["score"] == {"n": 2, "mean": 0.75}
    assert aggregate["metrics"]["flag"] == {"n": 2, "mean": 0.5}


def test_ab_context_contract_differs_without_running_a_provider():
    case = {
        "case_id": "v7d004",
        "split": DEV_SPLIT,
        "task_family": "context_followup",
        "question": "What is the current implementation?",
        "conversation_context": [{"role": "user", "content": "Earlier context"}],
    }
    common = {
        "run_order": 1,
        "case_order": 1,
        "system_root": Path("system"),
        "target_root": Path("target"),
        "corpus_root": Path("corpus"),
    }
    a_job = build_worker_job(case, system="A", **common)
    b_job = build_worker_job(case, system="B", **common)
    assert a_job["conversation_context"] == []
    assert b_job["conversation_context"] == case["conversation_context"]


def test_summary_exposes_overall_family_system_and_automatic_pairwise_views():
    raw = [
        {"case_id": "v7d001", "task_family": "knowledge_only", "system": "A"},
        {"case_id": "v7d001", "task_family": "knowledge_only", "system": "B"},
    ]
    scores = [
        {
            "case_id": "v7d001",
            "task_family": "knowledge_only",
            "system": "A",
            "run_validity": "VALID",
            "automatic_metrics": {"task_completion": True},
        },
        {
            "case_id": "v7d001",
            "task_family": "knowledge_only",
            "system": "B",
            "run_validity": "VALID",
            "automatic_metrics": {"task_completion": False},
        },
    ]
    summary = build_summary(raw, scores)
    assert set(summary["by_system"]) == {"A", "B"}
    assert "knowledge_only" in summary["by_task_family"]
    assert summary["automatic_pairwise"]["task_completion"]["counts"]["A better"] == 1
    assert summary["holdout"] == "NOT_RUN"


def test_worker_job_rejects_unknown_system():
    with pytest.raises(ValueError):
        build_worker_job(
            _cases(1)[0],
            system="C",
            run_order=1,
            case_order=1,
            system_root=Path("system"),
            target_root=Path("target"),
            corpus_root=Path("corpus"),
        )


def test_frozen_r3_cases_have_current_coherence_and_matrix_contract():
    dev = load_cases(DEV_DATASET_PATH)
    holdout = load_cases(HOLDOUT_DATASET_PATH)
    assert len(dev) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert len(holdout) == EXPECTED_CASE_COUNTS[HOLDOUT_SPLIT] == 9
    assert validate_protocol_manifest()["family_counts"] == EXPECTED_FAMILY_COUNTS
    for case_id in ("v7d008", "v7d010", "v7d014", "v7h007"):
        validate_case_gold_coherence(
            next(case for case in dev + holdout if case["case_id"] == case_id)
        )


def test_distinct_code_path_gold_contract_passes_for_v7d014_and_v7h007():
    cases = load_cases(DEV_DATASET_PATH) + load_cases(HOLDOUT_DATASET_PATH)
    for case_id in ("v7d014", "v7h007"):
        case = next(case for case in cases if case["case_id"] == case_id)
        code_paths = {
            proof["relative_path"]
            for proof in case["source_proofs"]
            if proof["kind"] == "project_code"
        }
        assert len(code_paths) >= case["min_distinct_project_code_paths"]


def test_r2_gold_provenance_validator_remains_unchanged_and_provider_free():
    cases = load_cases(DEV_DATASET_PATH) + load_cases(HOLDOUT_DATASET_PATH)
    records = load_gold_proof_audit()
    assert len(records) == 61
    validate_gold_proof_audit(cases=cases)
