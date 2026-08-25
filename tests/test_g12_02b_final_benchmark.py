"""Deterministic checks for the frozen 16-case G12 benchmark."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.gate12.candidate_contract import CandidateContractError, candidate_sha256, load_json, load_jsonl
from evaluation.gate12.final_contract import (
    FINAL_CASE_MAPPING,
    FINAL_CASE_STATUS,
    REJECTED_CANDIDATE_REASONS,
    REVIEW_BASELINE_COMMIT,
    build_final_manifest,
    candidate_semantic_payload,
    final_case_sha256,
    final_semantic_payload,
    validate_final_benchmark,
    validate_final_manifest,
    validate_reviewer_selection,
)


GATE12_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "gate12"
POOL_PATH = GATE12_DIR / "candidate_pool_v1.jsonl"
REGISTRY_PATH = GATE12_DIR / "repositories_v1.json"
CANDIDATE_MANIFEST_PATH = GATE12_DIR / "candidate_pool_manifest_v1.json"
FINAL_PATH = GATE12_DIR / "final_benchmark_v1.jsonl"
FINAL_MANIFEST_PATH = GATE12_DIR / "final_benchmark_manifest_v1.json"
SELECTION_PATH = GATE12_DIR / "reviewer_selection_v1.json"


def _bundle() -> tuple[list[dict], list[dict], dict, dict, dict, dict]:
    candidates = load_jsonl(POOL_PATH)
    cases = load_jsonl(FINAL_PATH)
    repositories = load_json(REGISTRY_PATH)["repositories"]
    candidate_manifest = load_json(CANDIDATE_MANIFEST_PATH)
    final_manifest = load_json(FINAL_MANIFEST_PATH)
    selection = load_json(SELECTION_PATH)
    return candidates, cases, repositories, candidate_manifest, final_manifest, selection


def _validate(cases: list[dict] | None = None) -> dict:
    candidates, stored_cases, repositories, candidate_manifest, _, selection = _bundle()
    return validate_final_benchmark(
        stored_cases if cases is None else cases,
        candidates,
        repositories,
        candidate_manifest,
        selection,
    )


def test_exact_reviewer_selection_mapping_and_rejections_are_frozen():
    _, cases, _, candidate_manifest, _, selection = _bundle()

    validate_reviewer_selection(
        selection,
        candidate_pool_sha256=candidate_manifest["candidate_pool_sha256"],
        repository_manifest_sha256=candidate_manifest["repository_manifest_sha256"],
    )

    assert selection["review_baseline_commit"] == REVIEW_BASELINE_COMMIT
    assert [(case["case_id"], case["source_candidate_id"]) for case in cases] == list(FINAL_CASE_MAPPING)
    assert selection["selected_candidate_ids"] == [candidate_id for _, candidate_id in FINAL_CASE_MAPPING]
    assert selection["rejected_candidate_ids"] == list(REJECTED_CANDIDATE_REASONS)
    assert "g12c009" not in selection["selected_candidate_ids"]
    assert "g12c024" not in selection["selected_candidate_ids"]


def test_final_cases_preserve_source_semantics_and_candidate_sha_binding():
    candidates, cases, _, candidate_manifest, _, _ = _bundle()
    sources = {candidate["candidate_id"]: candidate for candidate in candidates}

    for case in cases:
        source = sources[case["source_candidate_id"]]
        assert case["case_status"] == FINAL_CASE_STATUS
        assert final_semantic_payload(case) == candidate_semantic_payload(source)
        assert case["source_candidate_sha256"] == candidate_manifest["candidate_sha256"][source["candidate_id"]]
        assert case["source_candidate_sha256"] == candidate_sha256(source)


def test_final_distribution_and_structural_diagnostics_are_real_not_quota_filled():
    report = _validate()

    assert report["family_distribution"] == {
        "Theory <-> Code": 4,
        "Change Impact <-> Test": 4,
        "Diagnosis / Config": 4,
        "Docs <-> Code": 4,
    }
    assert report["repository_distribution"] == {"my_agent": 8, "pydantic_ai": 8}
    assert set(report["family_repository_distribution"].values()) == {2}
    assert report["structural_diagnostics"]["unseen_change_test_case_ids"] == ["g12q007"]
    assert report["structural_diagnostics"]["cross_file_diagnosis_case_ids"] == [
        "g12q009", "g12q010", "g12q011"
    ]
    assert report["structural_diagnostics"]["docs_label_distribution"] == {"CONSISTENT": 4}


def test_semantic_mutation_or_rejected_candidate_breaks_final_contract():
    _, cases, _, _, _, _ = _bundle()
    mutated = deepcopy(cases)
    mutated[0]["difficulty"] = "hard" if mutated[0]["difficulty"] != "hard" else "medium"

    with pytest.raises(CandidateContractError, match="semantic payload"):
        _validate(mutated)

    rejected = deepcopy(cases)
    rejected[0]["source_candidate_id"] = "g12c009"
    with pytest.raises(CandidateContractError, match="mapping drift"):
        _validate(rejected)


def test_source_candidate_sha_and_absolute_path_leaks_are_rejected():
    _, cases, _, _, _, _ = _bundle()
    sha_drift = deepcopy(cases)
    sha_drift[0]["source_candidate_sha256"] = "0" * 64

    with pytest.raises(CandidateContractError, match="SHA mismatch"):
        _validate(sha_drift)

    local_path = deepcopy(cases)
    local_path[0]["question"] = "C:\\local\\evaluator"
    with pytest.raises(CandidateContractError, match="absolute local path"):
        _validate(local_path)


def test_final_question_cannot_copy_a_gold_obligation_even_when_source_matches():
    candidates, cases, repositories, candidate_manifest, _, selection = _bundle()
    source = deepcopy(next(candidate for candidate in candidates if candidate["candidate_id"] == "g12c002"))
    source["question"] += source["gold_obligations"][0]["claim"]
    candidates = [source if candidate["candidate_id"] == source["candidate_id"] else candidate for candidate in candidates]
    cases = deepcopy(cases)
    cases[0]["question"] = source["question"]
    source_sha = candidate_sha256(source)
    cases[0]["source_candidate_sha256"] = source_sha
    candidate_manifest = deepcopy(candidate_manifest)
    candidate_manifest["candidate_sha256"][source["candidate_id"]] = source_sha

    with pytest.raises(CandidateContractError, match="Gold obligation"):
        validate_final_benchmark(cases, candidates, repositories, candidate_manifest, selection)


def test_final_cases_retain_change_temporal_contract_fields():
    _, cases, _, _, _, _ = _bundle()
    changes = [case for case in cases if case["task_family"] == "Change Impact <-> Test"]

    assert len(changes) == 4
    assert all(case["base_ref"] == f"{case['head_ref']}^" for case in changes)
    assert all(
        {"project_change", "project_test"}.issubset(
            {proof["kind"] for proof in case["source_proofs"]}
        )
        for case in changes
    )
    assert [case["case_id"] for case in changes if not case["accepted_test_in_change_set"]] == ["g12q007"]


def test_manifest_is_canonical_deterministic_and_binds_all_final_case_identities():
    candidates, cases, repositories, candidate_manifest, manifest, selection = _bundle()

    validate_final_benchmark(cases, candidates, repositories, candidate_manifest, selection)
    validate_final_manifest(
        manifest,
        cases,
        final_benchmark_path=FINAL_PATH,
        reviewer_selection_path=SELECTION_PATH,
        candidate_manifest=candidate_manifest,
        repository_manifest_path=REGISTRY_PATH,
    )
    assert manifest == build_final_manifest(
        cases,
        final_benchmark_path=FINAL_PATH,
        reviewer_selection_path=SELECTION_PATH,
        candidate_manifest=candidate_manifest,
        repository_manifest_path=REGISTRY_PATH,
    )
    assert manifest["final_case_sha256"] == {
        case["case_id"]: final_case_sha256(case) for case in cases
    }


def test_manifest_rejects_mutated_final_case_identity():
    _, cases, _, candidate_manifest, manifest, _ = _bundle()
    mutated = deepcopy(cases)
    mutated[0]["difficulty"] = "hard" if mutated[0]["difficulty"] != "hard" else "medium"

    with pytest.raises(CandidateContractError, match="identity mismatch"):
        validate_final_manifest(
            manifest,
            mutated,
            final_benchmark_path=FINAL_PATH,
            reviewer_selection_path=SELECTION_PATH,
            candidate_manifest=candidate_manifest,
            repository_manifest_path=REGISTRY_PATH,
        )
