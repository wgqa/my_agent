"""Deterministic provenance contract for the frozen G12 final benchmark.

The final benchmark is evaluator metadata.  It derives each final case from a
reviewed candidate without changing the candidate's semantic payload.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.gate12.candidate_contract import (
    ABSOLUTE_PATH_RE,
    CANDIDATE_STATUS,
    SCHEMA_VERSION as CANDIDATE_SCHEMA_VERSION,
    CandidateContractError,
    TASK_FAMILIES,
    candidate_sha256,
    canonical_json,
    file_sha256,
    validate_candidate,
    validate_pool,
)


FINAL_CASE_SCHEMA_VERSION = "g12_final_case_v1"
FINAL_MANIFEST_SCHEMA_VERSION = "g12_final_benchmark_manifest_v1"
REVIEWER_SELECTION_SCHEMA_VERSION = "g12_reviewer_selection_v1"
FINAL_CASE_STATUS = "FROZEN / REVIEWER ACCEPTED"
REVIEW_BASELINE_COMMIT = "58c52bd5d4ee443426398b067f848e3ca7684288"

FINAL_CASE_MAPPING = (
    ("g12q001", "g12c002"),
    ("g12q002", "g12c003"),
    ("g12q003", "g12c004"),
    ("g12q004", "g12c006"),
    ("g12q005", "g12c007"),
    ("g12q006", "g12c008"),
    ("g12q007", "g12c010"),
    ("g12q008", "g12c011"),
    ("g12q009", "g12c014"),
    ("g12q010", "g12c015"),
    ("g12q011", "g12c017"),
    ("g12q012", "g12c018"),
    ("g12q013", "g12c020"),
    ("g12q014", "g12c021"),
    ("g12q015", "g12c022"),
    ("g12q016", "g12c023"),
)
REJECTED_CANDIDATE_REASONS = {
    "g12c001": "lower discriminative value",
    "g12c005": "cross-framework analogy less direct",
    "g12c009": "historical provenance now valid, but overlaps prior G11 budget-control development topic",
    "g12c012": "valid but lower priority / less central Engineering-Agent surface",
    "g12c013": "generator-failure overlap and weaker differentiation",
    "g12c016": "valid but lower-priority diagnostic surface",
    "g12c019": "broader long-term-memory wording adds avoidable semantic scope",
    "g12c024": "consistency-label ambiguity; distributed ownership is evidence insufficiency, not inconsistency",
}

_CANDIDATE_BOOKKEEPING_FIELDS = frozenset({"schema_version", "candidate_id", "candidate_status"})
_FINAL_BOOKKEEPING_FIELDS = frozenset(
    {"schema_version", "case_id", "source_candidate_id", "source_candidate_sha256", "case_status"}
)
_EXPECTED_FAMILY_DISTRIBUTION = {
    "Theory <-> Code": 4,
    "Change Impact <-> Test": 4,
    "Diagnosis / Config": 4,
    "Docs <-> Code": 4,
}
_EXPECTED_REPOSITORY_DISTRIBUTION = {"my_agent": 8, "pydantic_ai": 8}
_EXPECTED_FAMILY_REPOSITORY_DISTRIBUTION = {
    f"{family}/{project_id}": 2
    for family in TASK_FAMILIES
    for project_id in ("my_agent", "pydantic_ai")
}


def candidate_semantic_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return the candidate fields that must survive final-dataset freezing."""

    return {key: value for key, value in candidate.items() if key not in _CANDIDATE_BOOKKEEPING_FIELDS}


def final_semantic_payload(case: Mapping[str, Any]) -> dict[str, Any]:
    """Return final-case fields that originate verbatim from the candidate."""

    return {key: value for key, value in case.items() if key not in _FINAL_BOOKKEEPING_FIELDS}


def final_case_sha256(case: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(case).encode("utf-8")).hexdigest()


def canonical_jsonl(cases: Iterable[Mapping[str, Any]]) -> str:
    return "".join(f"{canonical_json(case)}\n" for case in cases)


def make_final_case(
    candidate: Mapping[str, Any], *, case_id: str, source_candidate_sha256: str
) -> dict[str, Any]:
    case = {
        "schema_version": FINAL_CASE_SCHEMA_VERSION,
        "case_id": case_id,
        "source_candidate_id": candidate["candidate_id"],
        "source_candidate_sha256": source_candidate_sha256,
        "case_status": FINAL_CASE_STATUS,
    }
    case.update(candidate_semantic_payload(candidate))
    return case


def build_final_cases(
    candidates: Iterable[Mapping[str, Any]], candidate_sha256_map: Mapping[str, str]
) -> list[dict[str, Any]]:
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    return [
        make_final_case(
            candidates_by_id[source_candidate_id],
            case_id=case_id,
            source_candidate_sha256=candidate_sha256_map[source_candidate_id],
        )
        for case_id, source_candidate_id in FINAL_CASE_MAPPING
    ]


def build_reviewer_selection(
    *, candidate_pool_sha256: str, repository_manifest_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": REVIEWER_SELECTION_SCHEMA_VERSION,
        "review_baseline_commit": REVIEW_BASELINE_COMMIT,
        "source_candidate_pool_sha256": candidate_pool_sha256,
        "repository_manifest_sha256": repository_manifest_sha256,
        "selected_candidate_ids": [source_candidate_id for _, source_candidate_id in FINAL_CASE_MAPPING],
        "rejected_candidate_ids": list(REJECTED_CANDIDATE_REASONS),
        "rejected_decisions": [
            {
                "candidate_id": candidate_id,
                "case_status": "NOT SELECTED",
                "reason": reason,
            }
            for candidate_id, reason in REJECTED_CANDIDATE_REASONS.items()
        ],
        "final_case_mapping": [
            {"case_id": case_id, "source_candidate_id": source_candidate_id}
            for case_id, source_candidate_id in FINAL_CASE_MAPPING
        ],
        "selection_performed_before_real_provider_formal": True,
    }


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = ", ".join(sorted(expected - actual))
        unexpected = ", ".join(sorted(actual - expected))
        detail = "; ".join(part for part in (f"missing: {missing}" if missing else "", f"unexpected: {unexpected}" if unexpected else "") if part)
        raise CandidateContractError(f"{label} fields drift ({detail})")


def _validate_no_absolute_values(value: object, label: str) -> None:
    if isinstance(value, str):
        if ABSOLUTE_PATH_RE.search(value):
            raise CandidateContractError(f"{label} contains an absolute local path")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_absolute_values(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_no_absolute_values(item, f"{label}.{key}")


def _validate_question_leakage(candidate: Mapping[str, Any]) -> None:
    question = candidate["question"].lower()
    if "required_evidence_groups" in question or "gold obligation" in question or "gold label" in question:
        raise CandidateContractError("final question leaks evaluator-only metadata")
    if candidate.get("gold_consistency_label", "").lower() in question and candidate.get("gold_consistency_label"):
        raise CandidateContractError("final question leaks Gold label")
    for obligation in candidate["gold_obligations"]:
        claim = obligation["claim"].strip().lower()
        if claim and claim in question:
            raise CandidateContractError("final question copies a Gold obligation")


def _candidate_from_final(case: Mapping[str, Any]) -> dict[str, Any]:
    candidate = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": case["source_candidate_id"],
        "candidate_status": CANDIDATE_STATUS,
    }
    candidate.update(final_semantic_payload(case))
    return candidate


def _structural_diagnostics(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    case_list = list(cases)
    unseen_change_case_ids = [
        case["case_id"]
        for case in case_list
        if case["task_family"] == "Change Impact <-> Test" and not case["accepted_test_in_change_set"]
    ]
    cross_file_diagnosis_ids = [
        case["case_id"]
        for case in case_list
        if case["task_family"] == "Diagnosis / Config" and case["requires_cross_file"]
    ]
    docs_labels = Counter(
        case["gold_consistency_label"]
        for case in case_list
        if case["task_family"] == "Docs <-> Code"
    )
    return {
        "unseen_change_test_cases": len(unseen_change_case_ids),
        "unseen_change_test_case_ids": unseen_change_case_ids,
        "cross_file_diagnosis_cases": len(cross_file_diagnosis_ids),
        "cross_file_diagnosis_case_ids": cross_file_diagnosis_ids,
        "docs_label_distribution": dict(sorted(docs_labels.items())),
        "docs_label_limitation": (
            "No naturally accepted OUTDATED, INCOMPLETE, or PARTIALLY CONSISTENT Docs case; "
            "label distribution follows reviewed evidence and is not quota-balanced."
        ),
    }


def _distribution(cases: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    case_list = list(cases)
    family = Counter(case["task_family"] for case in case_list)
    project = Counter(case["project_id"] for case in case_list)
    family_project = Counter(
        f"{case['task_family']}/{case['project_id']}" for case in case_list
    )
    return {
        "family_distribution": dict(sorted(family.items())),
        "repository_distribution": dict(sorted(project.items())),
        "family_repository_distribution": dict(sorted(family_project.items())),
    }


def validate_reviewer_selection(
    selection: Mapping[str, Any], *, candidate_pool_sha256: str, repository_manifest_sha256: str
) -> None:
    _require_exact_keys(
        selection,
        {
            "schema_version", "review_baseline_commit", "source_candidate_pool_sha256",
            "repository_manifest_sha256", "selected_candidate_ids", "rejected_candidate_ids",
            "rejected_decisions", "final_case_mapping", "selection_performed_before_real_provider_formal",
        },
        "reviewer selection",
    )
    _validate_no_absolute_values(selection, "reviewer selection")
    if selection["schema_version"] != REVIEWER_SELECTION_SCHEMA_VERSION:
        raise CandidateContractError("reviewer selection schema drift")
    if selection["review_baseline_commit"] != REVIEW_BASELINE_COMMIT:
        raise CandidateContractError("reviewer selection baseline drift")
    if selection["source_candidate_pool_sha256"] != candidate_pool_sha256:
        raise CandidateContractError("reviewer selection candidate pool identity mismatch")
    if selection["repository_manifest_sha256"] != repository_manifest_sha256:
        raise CandidateContractError("reviewer selection repository identity mismatch")
    if selection["selected_candidate_ids"] != [candidate_id for _, candidate_id in FINAL_CASE_MAPPING]:
        raise CandidateContractError("reviewer selection selected candidates drift")
    if selection["rejected_candidate_ids"] != list(REJECTED_CANDIDATE_REASONS):
        raise CandidateContractError("reviewer selection rejected candidates drift")
    expected_decisions = [
        {"candidate_id": candidate_id, "case_status": "NOT SELECTED", "reason": reason}
        for candidate_id, reason in REJECTED_CANDIDATE_REASONS.items()
    ]
    if selection["rejected_decisions"] != expected_decisions:
        raise CandidateContractError("reviewer rejection reasons drift")
    expected_mapping = [
        {"case_id": case_id, "source_candidate_id": candidate_id}
        for case_id, candidate_id in FINAL_CASE_MAPPING
    ]
    if selection["final_case_mapping"] != expected_mapping:
        raise CandidateContractError("reviewer final mapping drift")
    if selection["selection_performed_before_real_provider_formal"] is not True:
        raise CandidateContractError("reviewer selection must precede Formal")


def validate_final_benchmark(
    cases: list[Mapping[str, Any]],
    candidates: list[Mapping[str, Any]],
    repositories: Mapping[str, Mapping[str, Any]],
    candidate_manifest: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate final identities, source binding, semantic equality, and shape."""

    validate_pool(candidates, repositories)
    candidate_hashes = candidate_manifest.get("candidate_sha256")
    if not isinstance(candidate_hashes, dict):
        raise CandidateContractError("candidate manifest has no candidate identity map")
    validate_reviewer_selection(
        selection,
        candidate_pool_sha256=candidate_manifest.get("candidate_pool_sha256", ""),
        repository_manifest_sha256=candidate_manifest.get("repository_manifest_sha256", ""),
    )
    if len(cases) != len(FINAL_CASE_MAPPING):
        raise CandidateContractError("final benchmark must contain exactly 16 cases")
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    expected_final_keys: set[str] | None = None

    for case, (expected_case_id, source_candidate_id) in zip(cases, FINAL_CASE_MAPPING, strict=True):
        _validate_no_absolute_values(case, "final case")
        if case.get("schema_version") != FINAL_CASE_SCHEMA_VERSION:
            raise CandidateContractError("final case schema drift")
        if case.get("case_id") != expected_case_id:
            raise CandidateContractError("final case identity or order drift")
        if case.get("source_candidate_id") != source_candidate_id:
            raise CandidateContractError("final source candidate mapping drift")
        source = candidates_by_id.get(source_candidate_id)
        if source is None:
            raise CandidateContractError("final case references an unknown candidate")
        source_sha = candidate_hashes.get(source_candidate_id)
        if source_sha != candidate_sha256(source):
            raise CandidateContractError("candidate manifest source identity mismatch")
        if case.get("source_candidate_sha256") != source_sha:
            raise CandidateContractError("final case source candidate SHA mismatch")
        if case.get("case_status") != FINAL_CASE_STATUS:
            raise CandidateContractError("final case must be reviewer accepted and frozen")
        expected_keys = set(candidate_semantic_payload(source)) | set(_FINAL_BOOKKEEPING_FIELDS)
        if expected_final_keys is None:
            expected_final_keys = expected_keys
        _require_exact_keys(case, expected_keys, "final case")
        if final_semantic_payload(case) != candidate_semantic_payload(source):
            raise CandidateContractError("final semantic payload differs from source candidate")
        reconstructed_candidate = _candidate_from_final(case)
        validate_candidate(reconstructed_candidate, repositories)
        _validate_question_leakage(reconstructed_candidate)

    source_ids = [case["source_candidate_id"] for case in cases]
    if set(source_ids) & set(REJECTED_CANDIDATE_REASONS):
        raise CandidateContractError("rejected candidate cannot appear in final benchmark")
    distributions = _distribution(cases)
    if distributions["family_distribution"] != _EXPECTED_FAMILY_DISTRIBUTION:
        raise CandidateContractError("final family distribution drift")
    if distributions["repository_distribution"] != _EXPECTED_REPOSITORY_DISTRIBUTION:
        raise CandidateContractError("final repository distribution drift")
    if distributions["family_repository_distribution"] != _EXPECTED_FAMILY_REPOSITORY_DISTRIBUTION:
        raise CandidateContractError("final family/repository distribution drift")
    diagnostics = _structural_diagnostics(cases)
    if diagnostics["unseen_change_test_case_ids"] != ["g12q007"]:
        raise CandidateContractError("final unseen change-test diagnostic drift")
    if diagnostics["cross_file_diagnosis_case_ids"] != ["g12q009", "g12q010", "g12q011"]:
        raise CandidateContractError("final cross-file diagnosis diagnostic drift")
    if diagnostics["docs_label_distribution"] != {"CONSISTENT": 4}:
        raise CandidateContractError("final Docs label distribution drift")
    return {**distributions, "structural_diagnostics": diagnostics}


def build_final_manifest(
    cases: list[Mapping[str, Any]],
    *, final_benchmark_path: Path, reviewer_selection_path: Path,
    candidate_manifest: Mapping[str, Any], repository_manifest_path: Path,
) -> dict[str, Any]:
    distribution = _distribution(cases)
    final_benchmark_sha256 = file_sha256(final_benchmark_path)
    return {
        "schema_version": FINAL_MANIFEST_SCHEMA_VERSION,
        "dataset_status": FINAL_CASE_STATUS,
        "gate12_dataset_freeze_id": f"gate12-v1-{final_benchmark_sha256[:12]}",
        "case_count": len(cases),
        "final_case_sha256": {case["case_id"]: final_case_sha256(case) for case in cases},
        "final_benchmark_jsonl_sha256": final_benchmark_sha256,
        "reviewer_selection_sha256": file_sha256(reviewer_selection_path),
        "candidate_pool_sha256": candidate_manifest["candidate_pool_sha256"],
        "repository_manifest_sha256": file_sha256(repository_manifest_path),
        **distribution,
        "structural_diagnostics": _structural_diagnostics(cases),
        "selection_performed_before_real_provider_formal": True,
    }


def validate_final_manifest(
    manifest: Mapping[str, Any],
    cases: list[Mapping[str, Any]],
    *, final_benchmark_path: Path, reviewer_selection_path: Path,
    candidate_manifest: Mapping[str, Any], repository_manifest_path: Path,
) -> None:
    _require_exact_keys(
        manifest,
        {
            "schema_version", "dataset_status", "gate12_dataset_freeze_id", "case_count",
            "final_case_sha256", "final_benchmark_jsonl_sha256", "reviewer_selection_sha256",
            "candidate_pool_sha256", "repository_manifest_sha256", "family_distribution",
            "repository_distribution", "family_repository_distribution", "structural_diagnostics",
            "selection_performed_before_real_provider_formal",
        },
        "final manifest",
    )
    _validate_no_absolute_values(manifest, "final manifest")
    if manifest["schema_version"] != FINAL_MANIFEST_SCHEMA_VERSION:
        raise CandidateContractError("final manifest schema drift")
    expected = build_final_manifest(
        cases,
        final_benchmark_path=final_benchmark_path,
        reviewer_selection_path=reviewer_selection_path,
        candidate_manifest=candidate_manifest,
        repository_manifest_path=repository_manifest_path,
    )
    if dict(manifest) != expected:
        raise CandidateContractError("final manifest deterministic identity mismatch")
    try:
        content = final_benchmark_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateContractError("final benchmark JSONL is unreadable") from exc
    if content != canonical_jsonl(cases):
        raise CandidateContractError("final benchmark JSONL is not canonical")


__all__ = [
    "FINAL_CASE_MAPPING", "FINAL_CASE_SCHEMA_VERSION", "FINAL_CASE_STATUS",
    "FINAL_MANIFEST_SCHEMA_VERSION", "REJECTED_CANDIDATE_REASONS", "REVIEW_BASELINE_COMMIT",
    "REVIEWER_SELECTION_SCHEMA_VERSION", "build_final_cases", "build_final_manifest",
    "build_reviewer_selection", "candidate_semantic_payload", "canonical_jsonl", "final_case_sha256",
    "final_semantic_payload", "validate_final_benchmark", "validate_final_manifest",
    "validate_reviewer_selection",
]
