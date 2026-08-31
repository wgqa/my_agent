"""Deterministic, provider-free contract tests for ARCH-EVAL-08A."""

from __future__ import annotations

import copy
import json
import subprocess

import pytest

from evaluation.integration_v7 import (
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    EXPECTED_FAMILY_COUNTS,
    HOLDOUT_SPLIT,
    HoldoutExecutionDenied,
    ProtocolViolation,
    assert_execution_allowed,
    canonical_jsonl_sha256,
    load_cases,
    load_protocol_manifest,
    validate_corpus_identity,
    validate_protocol_manifest,
    validate_target_project_binding,
    validate_target_project_checkout,
)
from evaluation.integration_v7.case_contract import (
    DEV_DATASET_PATH,
    HOLDOUT_DATASET_PATH,
    SYSTEM_B_COMMIT,
    TARGET_PROJECT_ID,
    TARGET_PROJECT_COMMIT,
    _historical_g12_questions_and_proofs,
    _normalise_question,
    _validate_dataset_pair,
    validate_case,
)


def test_frozen_manifest_and_dataset_matrix_are_provider_free() -> None:
    manifest = validate_protocol_manifest()
    dev = load_cases(DEV_DATASET_PATH)
    holdout = load_cases(HOLDOUT_DATASET_PATH)

    assert manifest["case_count"] == sum(EXPECTED_CASE_COUNTS.values()) == 27
    assert len(dev) == EXPECTED_CASE_COUNTS[DEV_SPLIT] == 18
    assert len(holdout) == EXPECTED_CASE_COUNTS[HOLDOUT_SPLIT] == 9
    assert manifest["family_counts"] == EXPECTED_FAMILY_COUNTS
    assert manifest["target_project_commit"] == SYSTEM_B_COMMIT == TARGET_PROJECT_COMMIT
    assert "path" not in manifest["target_project"]
    assert manifest["holdout_execution"]["default"] == "DENY"


def test_all_case_ids_questions_and_proofs_are_new() -> None:
    dev = load_cases(DEV_DATASET_PATH)
    holdout = load_cases(HOLDOUT_DATASET_PATH)
    historical_questions, historical_proofs = _historical_g12_questions_and_proofs()
    cases = dev + holdout

    assert all(case["case_id"].startswith("v7") for case in cases)
    assert not {case["case_id"] for case in cases} & {f"g12q{index:03d}" for index in range(1, 17)}
    assert not {_normalise_question(case["question"]) for case in cases} & historical_questions
    proof_ids = {
        (proof["kind"], proof["relative_path"], proof["anchor"])
        for case in cases
        for proof in case["source_proofs"]
    }
    assert not proof_ids & historical_proofs


def test_case_contract_rejects_unknown_fields_and_unsafe_paths() -> None:
    case = load_cases(DEV_DATASET_PATH)[0]

    extra = copy.deepcopy(case)
    extra["unexpected"] = True
    with pytest.raises(ProtocolViolation):
        validate_case(extra)

    unsafe = copy.deepcopy(case)
    unsafe["source_proofs"][0]["relative_path"] = "../outside.md"
    with pytest.raises(ProtocolViolation):
        validate_case(unsafe)

    absolute = copy.deepcopy(case)
    absolute["source_proofs"][0]["relative_path"] = "C:/secret.md"
    with pytest.raises(ProtocolViolation):
        validate_case(absolute)


def test_case_contract_rejects_invalid_evidence_obligation_and_outcome_shapes() -> None:
    case = load_cases(DEV_DATASET_PATH)[0]

    unknown_obligation = copy.deepcopy(case)
    unknown_obligation["source_proofs"][0]["obligation_ids"] = ["O99"]
    with pytest.raises(ProtocolViolation):
        validate_case(unknown_obligation)

    refusal = copy.deepcopy(case)
    refusal["expected_outcome"] = "refusal"
    with pytest.raises(ProtocolViolation):
        validate_case(refusal)

    no_groups = copy.deepcopy(case)
    no_groups["required_evidence_groups"] = []
    with pytest.raises(ProtocolViolation):
        validate_case(no_groups)


def test_context_contract_is_bounded_and_non_context_is_clean() -> None:
    context = load_cases(DEV_DATASET_PATH)[6]
    assert context["task_family"] == "context_followup"
    assert len(context["conversation_context"]) <= 6

    too_many = copy.deepcopy(context)
    too_many["conversation_context"] = context["conversation_context"] * 3
    with pytest.raises(ProtocolViolation):
        validate_case(too_many)

    non_context = load_cases(DEV_DATASET_PATH)[0]
    non_context["current_question"] = non_context["question"]
    with pytest.raises(ProtocolViolation):
        validate_case(non_context)


def test_dataset_pair_rejects_duplicate_question_and_forbidden_change_range() -> None:
    dev = load_cases(DEV_DATASET_PATH)
    holdout = load_cases(HOLDOUT_DATASET_PATH)

    duplicate_question = copy.deepcopy(holdout)
    duplicate_question[0]["question"] = dev[0]["question"]
    with pytest.raises(ProtocolViolation):
        _validate_dataset_pair(dev, duplicate_question)

    duplicate_change_target = copy.deepcopy(holdout)
    duplicate_change_target[4]["head_ref"] = dev[8]["head_ref"]
    with pytest.raises(ProtocolViolation):
        _validate_dataset_pair(dev, duplicate_change_target)


def test_manifest_fails_closed_when_dataset_mutates(tmp_path) -> None:
    manifest = load_protocol_manifest()
    dev_text = DEV_DATASET_PATH.read_text(encoding="utf-8")
    holdout_text = HOLDOUT_DATASET_PATH.read_text(encoding="utf-8")
    manifest["datasets"][DEV_SPLIT]["file"] = "dev.jsonl"
    manifest["datasets"][HOLDOUT_SPLIT]["file"] = "holdout.jsonl"
    manifest_path = tmp_path / "manifest.json"
    (tmp_path / "dev.jsonl").write_text(dev_text.replace("语料身份与检索策略", "语料版本与检索策略", 1), encoding="utf-8")
    (tmp_path / "holdout.jsonl").write_text(holdout_text, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ProtocolViolation, match="dataset SHA mismatch|protocol manifest SHA mismatch"):
        validate_protocol_manifest(manifest_path)


def test_manifest_fails_closed_when_protocol_metadata_mutates(tmp_path) -> None:
    manifest = load_protocol_manifest()
    manifest["case_count"] = 28
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ProtocolViolation, match="protocol manifest SHA mismatch"):
        validate_protocol_manifest(path)


def test_target_binding_and_corpus_identity_fail_closed() -> None:
    manifest = load_protocol_manifest()
    binding = manifest["target_project"]
    for field, value in (("project_id", "other"), ("source_commit", "0" * 40), ("dirty", True)):
        mutated = dict(binding)
        mutated[field] = value
        with pytest.raises(ProtocolViolation):
            validate_target_project_binding(mutated)

    with pytest.raises(ProtocolViolation):
        validate_target_project_binding({**binding, "path": "C:/private/checkout"})

    with pytest.raises(ProtocolViolation):
        validate_corpus_identity({**manifest["corpus_identity"], "corpus_id": "mutated"})


def test_target_checkout_requires_existing_clean_frozen_sha(tmp_path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ProtocolViolation):
        validate_target_project_checkout(missing, expected_commit=TARGET_PROJECT_COMMIT)

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "README.md").write_text("frozen\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "protocol@example.invalid"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.name", "Protocol Test"], cwd=checkout, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=checkout, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    validate_target_project_checkout(checkout, expected_commit=commit)

    with pytest.raises(ProtocolViolation, match="SHA"):
        validate_target_project_checkout(checkout, expected_commit="0" * 40)

    (checkout / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ProtocolViolation, match="tracked-clean"):
        validate_target_project_checkout(checkout, expected_commit=commit)


def test_holdout_is_deny_by_default_and_exact_confirmation_is_required() -> None:
    with pytest.raises(HoldoutExecutionDenied):
        assert_execution_allowed(HOLDOUT_SPLIT)
    with pytest.raises(HoldoutExecutionDenied):
        assert_execution_allowed(HOLDOUT_SPLIT, confirm_frozen_candidate="wrong")

    holdout_sha = load_protocol_manifest()["datasets"][HOLDOUT_SPLIT]["sha256"]
    assert_execution_allowed(HOLDOUT_SPLIT, confirm_frozen_candidate=holdout_sha)
    assert_execution_allowed(DEV_SPLIT)


def test_dataset_hash_is_canonical_and_manifest_hashes_are_present() -> None:
    manifest = validate_protocol_manifest()
    assert len(canonical_jsonl_sha256(DEV_DATASET_PATH)) == 64
    assert len(canonical_jsonl_sha256(HOLDOUT_DATASET_PATH)) == 64
    assert len(manifest["protocol_sha256"]) == 64
    assert manifest["metric_schema"]["retrieval_calls_are_not_llm_calls"] is True
