"""Deterministic, provider-free contract tests for ARCH-EVAL-08A."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from evaluation.integration_v7 import (
    DEV_SPLIT,
    CORPUS_SOURCE_COMMIT,
    EXPECTED_CASE_COUNTS,
    EXPECTED_FAMILY_COUNTS,
    HOLDOUT_SPLIT,
    HoldoutExecutionDenied,
    ProtocolViolation,
    assert_execution_allowed,
    canonical_jsonl_sha256,
    compute_premature_finalization,
    compute_refusal_correctness,
    compute_required_evidence_coverage,
    compute_task_completion,
    compute_tool_coverage,
    load_gold_proof_audit,
    load_cases,
    load_protocol_manifest,
    validate_corpus_identity,
    validate_knowledge_source_proofs,
    validate_gold_proof_audit,
    validate_protocol_manifest,
    validate_project_source_proofs,
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
    _computed_protocol_sha256,
    validate_case,
    required_tools_for_system,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_system_local_tool_contract_keeps_planned_knowledge_fair() -> None:
    manifest = validate_protocol_manifest()
    a_tools = manifest["systems"]["A"]["toolset"]["effective_dynamic_registry"]["names"]
    b_tools = manifest["systems"]["B"]["toolset"]["effective_dynamic_registry"]["names"]
    assert "knowledge_search" in a_tools
    assert "knowledge_search" not in b_tools
    knowledge_case = load_cases(DEV_DATASET_PATH)[0]
    assert knowledge_case["task_family"] == "knowledge_only"
    assert required_tools_for_system(knowledge_case, "A") == ["knowledge_search"]
    assert required_tools_for_system(knowledge_case, "B") == []
    assert knowledge_case["required_tools"] == []
    assert compute_tool_coverage(knowledge_case, "B", []) == 1.0
    assert compute_tool_coverage(knowledge_case, "A", []) == 0.0


def test_tool_obligation_mapping_is_architecture_local_for_mixed_case() -> None:
    case = next(case for case in load_cases(DEV_DATASET_PATH) if case["case_id"] == "v7d005")
    assert case["required_tools"] == ["code_search"]
    assert case["required_tools_by_system"] == {
        "A": ["knowledge_search", "code_search"],
        "B": ["code_search"],
    }
    assert compute_tool_coverage(case, "B", ["code_search"]) == 1.0


def test_automatic_metrics_use_runtime_state_and_evidence_groups_only() -> None:
    answerable = load_cases(DEV_DATASET_PATH)[2]
    assert compute_task_completion(answerable, {"status": "completed"}) is True
    mutated_gold = copy.deepcopy(answerable)
    mutated_gold["gold_obligations"][0]["claim"] = "intentionally not used by automatic completion"
    assert compute_task_completion(mutated_gold, {"status": "completed"}) is True

    grouped = next(case for case in load_cases(DEV_DATASET_PATH) if case["case_id"] == "v7d009")
    assert compute_required_evidence_coverage(grouped, [True, False]) == 0.5
    assert compute_premature_finalization(
        grouped,
        {"finalized": True, "required_evidence_satisfied": False, "typed_requirement_satisfied": True},
    ) is True
    assert compute_premature_finalization(grouped, {"finalized": True}) is False

    refusal = next(case for case in load_cases(DEV_DATASET_PATH) if case["case_id"] == "v7d017")
    assert compute_refusal_correctness(refusal, {"status": "refused"}) is True
    assert compute_refusal_correctness(refusal, {"status": "completed"}) is False


def _init_git_fixture(root: Path, relative_path: str, content: str) -> str:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "protocol@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Protocol Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_project_source_proof_validator_rejects_missing_anchor_wrong_source_and_escape(tmp_path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    commit = _init_git_fixture(checkout, "README.md", "first\nsecond\n")
    case = {"case_id": "fixture", "source_proofs": [{"kind": "project_doc", "relative_path": "README.md", "anchor": "line:2", "source_excerpt": "second", "bounded_proof": "second", "obligation_ids": ["O1"]}]}
    validate_project_source_proofs(checkout, expected_commit=commit, cases=[case])

    missing = copy.deepcopy(case)
    missing["source_proofs"][0]["anchor"] = "line:99"
    with pytest.raises(ProtocolViolation, match="anchor"):
        validate_project_source_proofs(checkout, expected_commit=commit, cases=[missing])
    with pytest.raises(ProtocolViolation, match="SHA"):
        validate_project_source_proofs(checkout, expected_commit="0" * 40, cases=[case])

    escaped = copy.deepcopy(case)
    escaped["source_proofs"][0]["relative_path"] = "../outside.md"
    with pytest.raises(ProtocolViolation, match="repo-relative|escapes"):
        validate_project_source_proofs(checkout, expected_commit=commit, cases=[escaped])


def test_knowledge_source_proof_validator_uses_frozen_fixture_commit(tmp_path) -> None:
    checkout = tmp_path / "corpus"
    checkout.mkdir()
    commit = _init_git_fixture(
        checkout,
        "agent_ai_v1/02_corpus_candidate/fixture.md",
        "corpus anchor\n",
    )
    case = {"case_id": "fixture", "source_proofs": [{"kind": "knowledge", "relative_path": "fixture.md", "anchor": "line:1", "source_excerpt": "corpus anchor", "bounded_proof": "corpus anchor", "obligation_ids": ["O1"]}]}
    validate_knowledge_source_proofs(checkout, expected_commit=commit, cases=[case])

    missing = copy.deepcopy(case)
    missing["source_proofs"][0]["anchor"] = "missing text"
    with pytest.raises(ProtocolViolation, match="anchor"):
        validate_knowledge_source_proofs(checkout, expected_commit=commit, cases=[missing])
    with pytest.raises(ProtocolViolation, match="SHA"):
        validate_knowledge_source_proofs(checkout, expected_commit=CORPUS_SOURCE_COMMIT, cases=[case])


def test_v7d012_project_proofs_are_visible_at_target_sha() -> None:
    case = next(case for case in load_cases(DEV_DATASET_PATH) if case["case_id"] == "v7d012")
    for proof in case["source_proofs"]:
        if not proof["kind"].startswith("project_"):
            continue
        shown = subprocess.run(
            ["git", "show", f"{SYSTEM_B_COMMIT}:{proof['relative_path']}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8")
        assert proof["anchor"].startswith("line:")
        line_number = int(proof["anchor"].removeprefix("line:"))
        assert shown.splitlines()[line_number - 1].strip()


def test_r2_dataset_and_protocol_hashes_are_self_consistent() -> None:
    manifest = validate_protocol_manifest()
    assert manifest["datasets"][DEV_SPLIT]["sha256"] == canonical_jsonl_sha256(DEV_DATASET_PATH)
    assert manifest["datasets"][HOLDOUT_SPLIT]["sha256"] == canonical_jsonl_sha256(HOLDOUT_DATASET_PATH)
    assert manifest["protocol_sha256"] == _computed_protocol_sha256(manifest)
    assert manifest["supersedes_protocol_sha256"] == "534c0a69c817125c23cf2b1d75d60df1c3cd65dacf13844ee4b654206e313d31"


def test_r2_source_excerpt_must_be_exact_and_at_the_declared_anchor(tmp_path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    commit = _init_git_fixture(checkout, "README.md", "first\nsecond\n")
    case = {
        "case_id": "fixture",
        "source_proofs": [
            {
                "kind": "project_doc",
                "relative_path": "README.md",
                "anchor": "line:2",
                "source_excerpt": "second",
                "bounded_proof": "second",
                "obligation_ids": ["O1"],
            }
        ],
    }
    validate_project_source_proofs(checkout, expected_commit=commit, cases=[case])

    missing = copy.deepcopy(case)
    missing["source_proofs"][0].pop("source_excerpt")
    with pytest.raises(ProtocolViolation, match="source_excerpt"):
        validate_project_source_proofs(checkout, expected_commit=commit, cases=[missing])

    unrelated = copy.deepcopy(case)
    unrelated["source_proofs"][0]["source_excerpt"] = "first"
    with pytest.raises(ProtocolViolation, match="located at its line anchor"):
        validate_project_source_proofs(checkout, expected_commit=commit, cases=[unrelated])

    mismatched = copy.deepcopy(case)
    mismatched["source_proofs"][0]["source_excerpt"] = "not in source"
    with pytest.raises(ProtocolViolation, match="does not exist"):
        validate_project_source_proofs(checkout, expected_commit=commit, cases=[mismatched])


def test_r2_project_change_proof_requires_path_membership_in_declared_diff(tmp_path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    base = _init_git_fixture(checkout, "README.md", "first\n")
    (checkout / "other.py").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "other.py"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=checkout, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    case = {
        "case_id": "fixture",
        "base_ref": base,
        "head_ref": head,
        "accepted_test_paths": ["tests/test_fixture.py"],
        "source_proofs": [
            {
                "kind": "project_change",
                "relative_path": "README.md",
                "anchor": "line:1",
                "source_excerpt": "first",
                "bounded_proof": "README changed",
                "obligation_ids": ["O1"],
            }
        ],
    }
    with pytest.raises(ProtocolViolation, match="not present in git diff"):
        validate_project_source_proofs(checkout, expected_commit=head, cases=[case])


def test_r2_project_test_proof_requires_accepted_path_and_head_source(tmp_path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    base = _init_git_fixture(checkout, "tests/test_fixture.py", "assert True\n")
    case = {
        "case_id": "fixture",
        "base_ref": base,
        "head_ref": base,
        "accepted_test_paths": ["tests/other_test.py"],
        "source_proofs": [
            {
                "kind": "project_test",
                "relative_path": "tests/test_fixture.py",
                "anchor": "line:1",
                "source_excerpt": "assert True",
                "bounded_proof": "actual assertion",
                "obligation_ids": ["O1"],
            }
        ],
    }
    with pytest.raises(ProtocolViolation, match="accepted_test_paths"):
        validate_project_source_proofs(checkout, expected_commit=base, cases=[case])

    case["accepted_test_paths"] = ["tests/test_fixture.py"]
    (checkout / "tests/test_fixture.py").unlink()
    subprocess.run(["git", "rm", "-q", "tests/test_fixture.py"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "remove test"], cwd=checkout, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    case["head_ref"] = head
    with pytest.raises(ProtocolViolation, match="source file is missing"):
        validate_project_source_proofs(checkout, expected_commit=head, cases=[case])


def test_r2_duplicate_required_evidence_groups_are_rejected() -> None:
    case = copy.deepcopy(load_cases(DEV_DATASET_PATH)[0])
    case["required_evidence_groups"] = [["knowledge"], ["knowledge"]]
    with pytest.raises(ProtocolViolation, match="duplicate group"):
        validate_case(case)


def test_r2_every_gold_obligation_has_an_accepted_audit_record() -> None:
    cases = load_cases(DEV_DATASET_PATH) + load_cases(HOLDOUT_DATASET_PATH)
    records = load_gold_proof_audit()
    assert len(records) == 56
    assert {record["review_decision"] for record in records} == {"ACCEPT"}
    validate_gold_proof_audit(cases=cases)

    expected = {
        (
            case["case_id"],
            proof["obligation_ids"][0],
            proof["kind"],
            proof["relative_path"],
            proof["anchor"],
        ): proof["source_excerpt"]
        for case in cases
        for proof in case["source_proofs"]
    }
    actual = {
        (
            record["case_id"],
            record["obligation_id"],
            record["proof_kind"],
            record["relative_path"],
            record["anchor"],
        ): record["source_excerpt"]
        for record in records
    }
    assert actual.keys() == expected.keys()
    for record in records:
        proof = next(
            proof
            for case in cases
            if case["case_id"] == record["case_id"]
            for proof in case["source_proofs"]
            if proof["kind"] == record["proof_kind"]
            and proof["relative_path"] == record["relative_path"]
            and proof["anchor"] == record["anchor"]
        )
        assert record["source_excerpt"] == proof["source_excerpt"]


def test_r2_frozen_project_corpus_and_holdout_boundaries_remain_unchanged() -> None:
    manifest = validate_protocol_manifest()
    assert manifest["target_project_commit"] == TARGET_PROJECT_COMMIT == SYSTEM_B_COMMIT
    assert manifest["corpus_identity"]["source_commit"] == CORPUS_SOURCE_COMMIT
    assert manifest["holdout_execution"]["default"] == "DENY"
    assert manifest["systems"]["A"]["toolset"]["names"] == [
        "calculator", "changed_files", "code_search", "find_tests", "git_diff",
        "knowledge_search", "read_project_context",
    ]
    assert manifest["systems"]["B"]["toolset"]["effective_dynamic_registry"]["names"] == [
        "calculator", "changed_files", "code_search", "find_tests", "git_diff",
        "read_project_context",
    ]
