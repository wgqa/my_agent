"""Deterministic contract checks for the G12-02A draft candidate pool."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.gate12.candidate_contract import (
    CandidateContractError,
    FAMILY_EVIDENCE_GROUPS,
    candidate_sha256,
    load_json,
    load_jsonl,
    validate_candidate,
    validate_manifest,
    validate_pool,
)


GATE12_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "gate12"
POOL_PATH = GATE12_DIR / "candidate_pool_v1.jsonl"
REGISTRY_PATH = GATE12_DIR / "repositories_v1.json"
MANIFEST_PATH = GATE12_DIR / "candidate_pool_manifest_v1.json"


def _pool() -> list[dict]:
    return load_jsonl(POOL_PATH)


def _repositories() -> dict:
    return load_json(REGISTRY_PATH)["repositories"]


def _candidate(candidate_id: str) -> dict:
    return next(candidate for candidate in _pool() if candidate["candidate_id"] == candidate_id)


def test_pool_schema_distribution_and_draft_identity_are_frozen():
    candidates = _pool()

    validate_pool(candidates, _repositories())

    assert [candidate["candidate_id"] for candidate in candidates] == [
        f"g12c{index:03d}" for index in range(1, 25)
    ]
    assert sum(candidate["task_family"] == "Theory <-> Code" for candidate in candidates) == 6
    assert sum(candidate["task_family"] == "Change Impact <-> Test" for candidate in candidates) == 6
    assert sum(candidate["task_family"] == "Diagnosis / Config" for candidate in candidates) == 6
    assert sum(candidate["task_family"] == "Docs <-> Code" for candidate in candidates) == 6
    assert sum(candidate["project_id"] == "my_agent" for candidate in candidates) == 12
    assert sum(candidate["project_id"] == "pydantic_ai" for candidate in candidates) == 12
    assert all(candidate["candidate_status"] == "DRAFT / REVIEW REQUIRED" for candidate in candidates)


def test_every_candidate_uses_the_exact_family_evidence_contract():
    for candidate in _pool():
        assert candidate["required_evidence_groups"] == FAMILY_EVIDENCE_GROUPS[candidate["task_family"]]


def test_manifest_binds_canonical_candidate_and_file_identity():
    candidates = _pool()
    manifest = load_json(MANIFEST_PATH)

    validate_manifest(manifest, candidates, REGISTRY_PATH, POOL_PATH)
    assert manifest["candidate_sha256"] == {
        candidate["candidate_id"]: candidate_sha256(candidate) for candidate in candidates
    }


def test_question_rejects_gold_path_leakage():
    candidate = deepcopy(_candidate("g12c007"))
    candidate["question"] += f" 请读取 {candidate['gold_source_paths'][0]}。"

    with pytest.raises(CandidateContractError, match="leaks Gold"):
        validate_candidate(candidate, _repositories())


def test_family_contract_drift_is_rejected():
    candidate = deepcopy(_candidate("g12c019"))
    candidate["required_evidence_groups"] = [["project_doc"]]

    with pytest.raises(CandidateContractError, match="contract drift"):
        validate_candidate(candidate, _repositories())


def test_cross_file_candidate_requires_two_distinct_code_paths():
    candidate = deepcopy(_candidate("g12c013"))
    candidate["min_distinct_project_code_paths"] = 1

    with pytest.raises(CandidateContractError, match="cross-file"):
        validate_candidate(candidate, _repositories())


def test_change_candidate_invariants_and_unseen_test_count_are_enforced():
    candidates = _pool()
    changes = [candidate for candidate in candidates if candidate["task_family"] == "Change Impact <-> Test"]

    assert sum(not candidate["accepted_test_in_change_set"] for candidate in changes) == 2
    invalid = deepcopy(_candidate("g12c010"))
    invalid["accepted_test_in_change_set"] = True
    with pytest.raises(CandidateContractError, match="does not match"):
        validate_candidate(invalid, _repositories())


def test_instruction_source_and_absolute_path_are_rejected():
    instruction_candidate = deepcopy(_candidate("g12c022"))
    instruction_candidate["gold_source_paths"][0] = "docs/AGENTS.md"
    with pytest.raises(CandidateContractError, match="instruction file"):
        validate_candidate(instruction_candidate, _repositories())

    absolute_candidate = deepcopy(_candidate("g12c018"))
    absolute_candidate["independence_note"] = "C:/private/evaluator"
    with pytest.raises(CandidateContractError, match="absolute"):
        validate_candidate(absolute_candidate, _repositories())


def test_repository_identity_mismatch_is_rejected():
    candidate = deepcopy(_candidate("g12c004"))
    candidate["project_source_commit"] = "0" * 40

    with pytest.raises(CandidateContractError, match="does not match"):
        validate_candidate(candidate, _repositories())


def test_candidate_field_mutation_breaks_manifest_identity():
    candidates = _pool()
    mutated = deepcopy(candidates)
    mutated[0]["difficulty"] = "hard"

    with pytest.raises(CandidateContractError, match="identity mismatch"):
        validate_manifest(load_json(MANIFEST_PATH), mutated, REGISTRY_PATH, POOL_PATH)


def test_diagnosis_cross_file_distribution_is_frozen():
    diagnosis = [candidate for candidate in _pool() if candidate["task_family"] == "Diagnosis / Config"]

    assert sum(candidate["requires_cross_file"] for candidate in diagnosis) == 4
