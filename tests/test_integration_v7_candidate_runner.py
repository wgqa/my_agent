"""Provider-free contract tests for ARCH-INTEGRATION-09B."""

from pathlib import Path

import pytest

from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    HoldoutExecutionDenied,
    TARGET_PROJECT_COMMIT,
    load_cases,
    validate_protocol_manifest,
)
from evaluation.integration_v7.candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_RUNTIME_LABEL,
    CANDIDATE_SYSTEM_LABEL,
    DEFAULT_OUTPUT_DIR,
    LEGACY_DEV_RESULTS_DIR,
    CandidateRunConfig,
    RunnerPreflightError,
    _assert_independent_output,
    build_candidate_manifest,
    build_candidate_run_plan,
    build_candidate_summary,
    build_candidate_worker_job,
    safe_artifact,
    assert_candidate_run_scope,
    validate_candidate_checkout_separation,
    validate_candidate_identities,
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


def test_candidate_and_target_checkouts_are_separate_and_frozen():
    candidate = Path("candidate")
    target = Path("target")
    validate_candidate_checkout_separation(
        candidate,
        target,
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
    )
    with pytest.raises(RunnerPreflightError):
        validate_candidate_checkout_separation(
            candidate,
            candidate,
            candidate_head=CANDIDATE_RUNTIME_COMMIT,
            target_head=TARGET_PROJECT_COMMIT,
        )


def test_candidate_plan_is_dev_only_and_exactly_one_run_per_case():
    cases = _cases()
    plan = build_candidate_run_plan(cases)
    assert len(plan) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert [item["run_order"] for item in plan] == list(range(1, 19))
    assert [item["case_id"] for item in plan] == [case["case_id"] for case in cases]
    assert {item["system"] for item in plan} == {CANDIDATE_SYSTEM_LABEL}
    assert {item["worker_system"] for item in plan} == {"B"}
    with pytest.raises(HoldoutExecutionDenied):
        assert_candidate_run_scope(HOLDOUT_SPLIT)
    with pytest.raises(HoldoutExecutionDenied):
        build_candidate_run_plan(cases, HOLDOUT_SPLIT)


def test_candidate_worker_preserves_b_context_and_candidate_target_roots():
    case = {
        "case_id": "v7d004",
        "split": DEV_SPLIT,
        "task_family": "context_followup",
        "question": "What is the current implementation?",
        "conversation_context": [{"role": "user", "content": "Earlier context"}],
    }
    plan_cases = [case] + [
        item for item in _cases(18) if item["case_id"] != case["case_id"]
    ]
    item = build_candidate_run_plan(plan_cases, DEV_SPLIT)[0]
    job = build_candidate_worker_job(
        case,
        plan_item=item,
        candidate_root=Path("candidate"),
        target_root=Path("target"),
        corpus_root=Path("corpus"),
    )
    assert job["system"] == "B"
    assert job["system_root"] == "candidate"
    assert job["target_root"] == "target"
    assert job["conversation_context"] == case["conversation_context"]


def test_candidate_artifacts_are_safe_and_old_dev_output_is_protected(tmp_path):
    safe = safe_artifact(
        {
            "answer": r"see C:\private\repo and sk-123456789012345",
            "nested": ["/home/user/private", "https://api.deepseek.com/v1"],
        }
    )
    serialized = repr(safe)
    assert "C:\\private" not in serialized
    assert "/home/user/private" not in serialized
    assert "sk-123456789012345" not in serialized
    with pytest.raises(RunnerPreflightError):
        safe_artifact({"raw_provider_response": "must not be stored"})

    candidate_output = tmp_path / "dev_candidate_e374_v1"
    _assert_independent_output(candidate_output)
    assert not candidate_output.exists()
    with pytest.raises(RunnerPreflightError):
        _assert_independent_output(LEGACY_DEV_RESULTS_DIR)
    assert DEFAULT_OUTPUT_DIR.resolve() != LEGACY_DEV_RESULTS_DIR.resolve()


def test_candidate_identity_is_explicit_and_candidate_summary_has_no_pairwise_or_manual_score():
    validate_candidate_identities(
        candidate_head=CANDIDATE_RUNTIME_COMMIT,
        target_head=TARGET_PROJECT_COMMIT,
        corpus_head="179f18e812ad63c36c5569de8e86c5ff9a931cb5",
        protocol_sha="281dba7b098535fd508971bfdd98d53ae188c8efa204b5c1fa929c3a40d6a40d",
    )
    raw = [
        {
            "case_id": "v7d001",
            "task_family": "knowledge_only",
            "run_validity": "INVALID",
        }
    ]
    summary = build_candidate_summary(raw, [{"run_validity": "INVALID"}])
    assert summary["candidate_identity"]["candidate_runtime_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert summary["candidate_identity"]["runtime_variant"] == CANDIDATE_RUNTIME_LABEL
    assert "automatic_pairwise" not in summary
    assert summary["manual_scoring"] == "NOT_DONE"
    assert summary["holdout"] == "NOT_RUN / DENY"


def test_candidate_manifest_records_all_execution_identities(tmp_path):
    protocol = validate_protocol_manifest()
    plan = build_candidate_run_plan(_cases())
    manifest = build_candidate_manifest(
        manifest=protocol,
        config=CandidateRunConfig(
            corpus_checkout=Path("corpus"), output_dir=tmp_path / "candidate"
        ),
        plan=plan,
        raw_runs=[],
        corpus_identity={
            "corpus_id": "870e5864df67",
            "file_count": 37,
            "chunk_count": 215,
            "retrieval_strategy": "bm25",
            "manifest_experiment_id": "dbc497c796d5",
            "verified": True,
        },
        timestamp="20260901T000000Z",
    )
    assert manifest["candidate_runtime"]["source_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert manifest["candidate_runtime"]["system_identity"] == CANDIDATE_SYSTEM_LABEL
    assert manifest["target_project"]["source_sha"] == TARGET_PROJECT_COMMIT
    assert manifest["corpus_identity"]["source_commit"] == "179f18e812ad63c36c5569de8e86c5ff9a931cb5"
    assert manifest["corpus_identity"]["corpus_id"] == "870e5864df67"
    assert manifest["protocol"]["sha256"] == "281dba7b098535fd508971bfdd98d53ae188c8efa204b5c1fa929c3a40d6a40d"
    assert manifest["split"] == DEV_SPLIT
    assert manifest["expected_candidate_runs"] == 18
    assert manifest["holdout"] == "NOT_RUN / DENY"


def test_current_dev_dataset_is_not_holdout_and_remains_18_cases():
    cases = load_cases(DEV_DATASET_PATH)
    assert len(cases) == 18
    assert all(case["split"] == DEV_SPLIT for case in cases)
