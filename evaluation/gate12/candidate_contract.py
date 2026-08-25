"""Deterministic validation for the draft G12 candidate pool.

This module belongs to evaluator infrastructure.  It describes draft-case
metadata and deliberately does not participate in product Runtime behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "g12_candidate_v1"
CANDIDATE_STATUS = "DRAFT / REVIEW REQUIRED"
TASK_FAMILIES = (
    "Theory <-> Code",
    "Change Impact <-> Test",
    "Diagnosis / Config",
    "Docs <-> Code",
)
FAMILY_EVIDENCE_GROUPS = {
    "Theory <-> Code": [["knowledge"], ["project_code", "project_doc"]],
    "Change Impact <-> Test": [["project_change"], ["project_test"]],
    "Diagnosis / Config": [["project_code"]],
    "Docs <-> Code": [["project_doc"], ["project_code"]],
}
PROJECT_IDS = ("my_agent", "pydantic_ai")
CHANGE_REQUIRED_TOOLS = ("changed_files", "git_diff", "read_project_context")
INSTRUCTION_PATH_PARTS = frozenset({".agents", ".claude", ".gemini"})
INSTRUCTION_FILENAMES = frozenset({"agents.md", "claude.md", "skill.md"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ABSOLUTE_PATH_RE = re.compile(r"(?:^[A-Za-z]:[\\/]|^/|^\\\\|(?<![A-Za-z0-9_])[A-Za-z]:[\\/])")


class CandidateContractError(ValueError):
    """Raised when draft evaluator metadata violates the frozen contract."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidate_sha256(candidate: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(candidate).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"invalid JSON: {path.name}") from exc
    if not isinstance(loaded, dict):
        raise CandidateContractError(f"JSON root must be an object: {path.name}")
    return loaded


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CandidateContractError(f"candidate pool is unreadable: {path.name}") from exc
    candidates: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            raise CandidateContractError(f"blank JSONL line {line_number}")
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CandidateContractError(f"invalid JSONL line {line_number}") from exc
        if not isinstance(item, dict):
            raise CandidateContractError(f"JSONL line {line_number} must be an object")
        candidates.append(item)
    return candidates


def _require_exact_keys(value: Mapping[str, Any], required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(value))
    if missing:
        raise CandidateContractError(f"{label} missing fields: {', '.join(missing)}")


def _relative_path(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\\" in value:
        raise CandidateContractError(f"{label} must be a non-empty POSIX relative path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in ("", ".", "..") for part in posix.parts)
        or ABSOLUTE_PATH_RE.search(value)
    ):
        raise CandidateContractError(f"{label} must not be absolute or traversing")
    return posix.as_posix()


def _is_instruction_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        any(part.lower() in INSTRUCTION_PATH_PARTS for part in parsed.parts)
        or parsed.name.lower() in INSTRUCTION_FILENAMES
    )


def _validate_no_absolute_values(value: object, label: str = "candidate") -> None:
    if isinstance(value, str):
        if ABSOLUTE_PATH_RE.search(value):
            raise CandidateContractError(f"{label} contains an absolute local path")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_absolute_values(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_no_absolute_values(item, f"{label}.{key}")


def _obligation_ids(candidate: Mapping[str, Any]) -> set[str]:
    obligations = candidate.get("gold_obligations")
    if not isinstance(obligations, list) or not obligations:
        raise CandidateContractError("gold_obligations must be a non-empty list")
    ids: set[str] = set()
    for obligation in obligations:
        if not isinstance(obligation, dict):
            raise CandidateContractError("gold obligation must be an object")
        identifier = obligation.get("id")
        claim = obligation.get("claim")
        if type(identifier) is not str or not identifier or type(claim) is not str or not claim:
            raise CandidateContractError("gold obligation needs id and claim")
        if identifier in ids:
            raise CandidateContractError("gold obligation ids must be unique")
        ids.add(identifier)
    return ids


def _question_leaks_gold(candidate: Mapping[str, Any]) -> bool:
    question = candidate["question"].lower()
    disallowed: list[str] = []
    disallowed.extend(candidate.get("gold_source_paths", []))
    disallowed.extend(candidate.get("accepted_test_paths", []))
    for proof in candidate.get("source_proofs", []):
        if isinstance(proof, dict) and proof.get("kind") != "knowledge":
            disallowed.append(proof.get("relative_path", ""))
    for token in disallowed:
        if type(token) is str and token and token.lower() in question:
            return True
    for obligation in candidate.get("gold_obligations", []):
        if isinstance(obligation, dict) and obligation.get("id", "").lower() in question:
            return True
    return any(label in question for label in ("答案是", "gold label", "gold obligation"))


def _validate_proofs(candidate: Mapping[str, Any]) -> None:
    obligation_ids = _obligation_ids(candidate)
    proofs = candidate.get("source_proofs")
    if not isinstance(proofs, list) or not proofs:
        raise CandidateContractError("source_proofs must be a non-empty list")
    covered: set[str] = set()
    for proof in proofs:
        if not isinstance(proof, dict):
            raise CandidateContractError("source proof must be an object")
        _require_exact_keys(proof, ("kind", "relative_path", "anchor", "obligation_ids"), "source proof")
        if proof["kind"] not in {"knowledge", "project_code", "project_doc", "project_change", "project_test"}:
            raise CandidateContractError("source proof has unknown kind")
        path = _relative_path(proof["relative_path"], "source proof path")
        if _is_instruction_path(path):
            raise CandidateContractError("instruction file cannot be a Gold source")
        if type(proof["anchor"]) is not str or not proof["anchor"].strip():
            raise CandidateContractError("source proof needs a non-empty anchor")
        proof_ids = proof["obligation_ids"]
        if not isinstance(proof_ids, list) or not proof_ids or any(type(item) is not str for item in proof_ids):
            raise CandidateContractError("source proof needs obligation ids")
        unknown = set(proof_ids) - obligation_ids
        if unknown:
            raise CandidateContractError("source proof references unknown obligation")
        covered.update(proof_ids)
    if covered != obligation_ids:
        raise CandidateContractError("every Gold obligation needs a source proof")


def validate_candidate(candidate: Mapping[str, Any], repositories: Mapping[str, Mapping[str, Any]]) -> None:
    required = (
        "schema_version", "candidate_id", "task_family", "project_id", "project_source_commit",
        "question", "requires_cross_file", "required_evidence_groups",
        "min_distinct_project_code_paths", "gold_obligations", "gold_source_paths",
        "source_proofs", "required_tools", "forbidden_tools", "difficulty",
        "independence_note", "candidate_status",
    )
    _require_exact_keys(candidate, required, "candidate")
    _validate_no_absolute_values(candidate)
    if candidate["schema_version"] != SCHEMA_VERSION:
        raise CandidateContractError("schema version drift")
    candidate_id = candidate["candidate_id"]
    if type(candidate_id) is not str or not re.fullmatch(r"g12c\d{3}", candidate_id):
        raise CandidateContractError("candidate id must match g12cNNN")
    family = candidate["task_family"]
    if family not in TASK_FAMILIES:
        raise CandidateContractError("unknown task family")
    project_id = candidate["project_id"]
    if project_id not in PROJECT_IDS or project_id not in repositories:
        raise CandidateContractError("candidate project is not registered")
    if candidate["project_source_commit"] != repositories[project_id].get("project_source_commit"):
        raise CandidateContractError("candidate project commit does not match repository registry")
    if not isinstance(candidate["question"], str) or not candidate["question"].strip():
        raise CandidateContractError("question must be non-empty")
    if _question_leaks_gold(candidate):
        raise CandidateContractError("question leaks Gold-only metadata")
    if candidate["required_evidence_groups"] != FAMILY_EVIDENCE_GROUPS[family]:
        raise CandidateContractError("family evidence contract drift")
    if type(candidate["requires_cross_file"]) is not bool:
        raise CandidateContractError("requires_cross_file must be bool")
    min_paths = candidate["min_distinct_project_code_paths"]
    if type(min_paths) is not int or min_paths < 1:
        raise CandidateContractError("min distinct project code paths must be >= 1")
    if candidate["requires_cross_file"] and min_paths < 2:
        raise CandidateContractError("cross-file candidate needs two distinct code paths")
    if not candidate["requires_cross_file"] and min_paths != 1:
        raise CandidateContractError("single-file candidate must use minimum one code path")
    source_paths = candidate["gold_source_paths"]
    if not isinstance(source_paths, list) or not source_paths:
        raise CandidateContractError("gold_source_paths must be non-empty")
    normalized_paths = [_relative_path(path, "gold source path") for path in source_paths]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise CandidateContractError("gold source paths must be unique")
    if any(_is_instruction_path(path) for path in normalized_paths):
        raise CandidateContractError("instruction file cannot be a Gold source")
    if candidate["requires_cross_file"]:
        code_paths = {
            proof["relative_path"]
            for proof in candidate["source_proofs"]
            if isinstance(proof, dict) and proof.get("kind") == "project_code"
        }
        if len(code_paths) < 2:
            raise CandidateContractError("cross-file candidate needs two code proof paths")
    if not isinstance(candidate["required_tools"], list) or not candidate["required_tools"]:
        raise CandidateContractError("required_tools must be non-empty")
    if not isinstance(candidate["forbidden_tools"], list):
        raise CandidateContractError("forbidden_tools must be a list")
    if set(candidate["required_tools"]) & set(candidate["forbidden_tools"]):
        raise CandidateContractError("a Tool cannot be both required and forbidden")
    if candidate["candidate_status"] != CANDIDATE_STATUS:
        raise CandidateContractError("candidate status must remain draft")
    _validate_proofs(candidate)
    if family == "Change Impact <-> Test":
        _validate_change_candidate(candidate)
    elif family == "Theory <-> Code":
        _validate_theory_candidate(candidate)
    elif family == "Docs <-> Code":
        if candidate.get("gold_consistency_label") not in {
            "CONSISTENT", "OUTDATED", "INCOMPLETE", "PARTIALLY CONSISTENT"
        }:
            raise CandidateContractError("docs candidate needs a valid draft consistency label")


def _validate_change_candidate(candidate: Mapping[str, Any]) -> None:
    _require_exact_keys(
        candidate,
        ("base_ref", "head_ref", "changed_paths", "accepted_test_paths", "accepted_test_in_change_set"),
        "change candidate",
    )
    head_ref = candidate["head_ref"]
    base_ref = candidate["base_ref"]
    if type(head_ref) is not str or not GIT_SHA_RE.fullmatch(head_ref):
        raise CandidateContractError("change head_ref must be a full SHA")
    if base_ref != f"{head_ref}^":
        raise CandidateContractError("change base_ref must be <head>^")
    changed_paths = candidate["changed_paths"]
    test_paths = candidate["accepted_test_paths"]
    if not isinstance(changed_paths, list) or not changed_paths:
        raise CandidateContractError("change candidate needs changed paths")
    if not isinstance(test_paths, list) or not test_paths:
        raise CandidateContractError("change candidate needs accepted tests")
    normalized_changed = {_relative_path(path, "changed path") for path in changed_paths}
    normalized_tests = {_relative_path(path, "accepted test path") for path in test_paths}
    if not any(path.endswith((".py", ".ts", ".js", ".java", ".go", ".rs")) for path in normalized_changed):
        raise CandidateContractError("change candidate needs an implementation path")
    if any("test" not in PurePosixPath(path).name.lower() and "tests" not in PurePosixPath(path).parts for path in normalized_tests):
        raise CandidateContractError("accepted test path does not look like a test")
    actual = bool(normalized_changed & normalized_tests)
    if candidate["accepted_test_in_change_set"] is not actual:
        raise CandidateContractError("accepted_test_in_change_set does not match changed paths")
    if not set(CHANGE_REQUIRED_TOOLS).issubset(candidate["required_tools"]):
        raise CandidateContractError("change candidate omits required change/test Tools")
    proofs = candidate["source_proofs"]
    if not any(proof["kind"] == "project_change" for proof in proofs):
        raise CandidateContractError("change candidate needs project_change proof")
    if not any(proof["kind"] == "project_test" for proof in proofs):
        raise CandidateContractError("change candidate needs project_test proof")
    if any(
        proof["kind"] == "project_test" and proof["relative_path"] not in normalized_tests
        for proof in proofs
    ):
        raise CandidateContractError("project_test proof must use an accepted test path")


def _validate_theory_candidate(candidate: Mapping[str, Any]) -> None:
    _require_exact_keys(
        candidate,
        ("knowledge_probe_query", "knowledge_gold_sources", "knowledge_probe_proof"),
        "theory candidate",
    )
    if type(candidate["knowledge_probe_query"]) is not str or not candidate["knowledge_probe_query"].strip():
        raise CandidateContractError("theory candidate needs a knowledge probe query")
    sources = candidate["knowledge_gold_sources"]
    if not isinstance(sources, list) or not sources:
        raise CandidateContractError("theory candidate needs knowledge sources")
    for source in sources:
        _relative_path(source, "knowledge source")
    proof = candidate["knowledge_probe_proof"]
    if not isinstance(proof, dict) or proof.get("corpus_id") != "870e5864df67":
        raise CandidateContractError("theory candidate needs frozen corpus proof")
    if proof.get("manifest_experiment_id") != "dbc497c796d5" or proof.get("retrieval_strategy") != "bm25":
        raise CandidateContractError("theory candidate has wrong knowledge identity")
    returned = proof.get("returned_sources")
    if not isinstance(returned, list) or not set(sources).issubset(set(returned)):
        raise CandidateContractError("knowledge probe proof does not return Gold source")


def validate_pool(candidates: list[Mapping[str, Any]], repositories: Mapping[str, Mapping[str, Any]]) -> None:
    if len(candidates) != 24:
        raise CandidateContractError("candidate pool must contain exactly 24 entries")
    for candidate in candidates:
        validate_candidate(candidate, repositories)
    ids = [candidate["candidate_id"] for candidate in candidates]
    expected_ids = [f"g12c{index:03d}" for index in range(1, 25)]
    if sorted(ids) != expected_ids:
        raise CandidateContractError("candidate ids must be g12c001 through g12c024")
    questions = [candidate["question"] for candidate in candidates]
    if len(set(questions)) != len(questions):
        raise CandidateContractError("candidate questions must be unique")
    families = Counter(candidate["task_family"] for candidate in candidates)
    if families != Counter({family: 6 for family in TASK_FAMILIES}):
        raise CandidateContractError("pool must contain six candidates per family")
    projects = Counter(candidate["project_id"] for candidate in candidates)
    if projects != Counter({project_id: 12 for project_id in PROJECT_IDS}):
        raise CandidateContractError("pool must contain twelve candidates per repository")
    family_project = Counter((candidate["task_family"], candidate["project_id"]) for candidate in candidates)
    expected_pairs = Counter((family, project_id) for family in TASK_FAMILIES for project_id in PROJECT_IDS)
    if set(family_project) != set(expected_pairs) or any(count != 3 for count in family_project.values()):
        raise CandidateContractError("each family/repository pair needs three candidates")
    change_candidates = [candidate for candidate in candidates if candidate["task_family"] == "Change Impact <-> Test"]
    if sum(not candidate["accepted_test_in_change_set"] for candidate in change_candidates) < 2:
        raise CandidateContractError("at least two change candidates need unseen accepted tests")
    diagnosis_candidates = [candidate for candidate in candidates if candidate["task_family"] == "Diagnosis / Config"]
    if sum(candidate["requires_cross_file"] for candidate in diagnosis_candidates) < 4:
        raise CandidateContractError("at least four diagnosis candidates must be cross-file")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _read_git_file(root: Path, commit: str, relative_path: str) -> str:
    try:
        return _git(root, "show", f"{commit}:{relative_path}")
    except subprocess.CalledProcessError as exc:
        raise CandidateContractError(f"source path is absent at pinned commit: {relative_path}") from exc


def validate_repository_checkout(
    project_id: str,
    root: Path,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    if project_id not in registry:
        raise CandidateContractError(f"unregistered project checkout: {project_id}")
    project = registry[project_id]
    resolved = root.resolve()
    if not resolved.is_dir():
        raise CandidateContractError(f"project root is not a directory: {project_id}")
    try:
        head = _git(resolved, "rev-parse", "HEAD")
        status = _git(resolved, "status", "--porcelain")
        shallow = _git(resolved, "rev-parse", "--is-shallow-repository")
        origin = _git(resolved, "remote", "get-url", "origin")
    except subprocess.CalledProcessError as exc:
        raise CandidateContractError(f"Git checkout validation failed: {project_id}") from exc
    if head != project["project_source_commit"]:
        raise CandidateContractError(f"project HEAD mismatch: {project_id}")
    if status:
        raise CandidateContractError(f"project checkout is tracked-dirty: {project_id}")
    if shallow != "false":
        raise CandidateContractError(f"project checkout is shallow: {project_id}")
    if origin != project["origin_url"]:
        raise CandidateContractError(f"project origin mismatch: {project_id}")
    return {"head": head, "tracked_clean": True, "is_shallow": False, "origin_verified": True}


def validate_candidate_sources(
    candidates: Iterable[Mapping[str, Any]], roots: Mapping[str, Path]
) -> None:
    for candidate in candidates:
        root = roots[candidate["project_id"]].resolve()
        commit = candidate["project_source_commit"]
        is_change_candidate = candidate["task_family"] == "Change Impact <-> Test"
        changed: set[str] = set()
        head_ref = ""
        actual_base = ""
        accepted_tests: set[str] = set()

        if is_change_candidate:
            head_ref = candidate["head_ref"]
            try:
                actual_base = _git(root, "rev-parse", f"{head_ref}^")
            except subprocess.CalledProcessError as exc:
                raise CandidateContractError(
                    f"change base is invalid: {candidate['candidate_id']}"
                ) from exc
            if candidate["base_ref"] != f"{head_ref}^" or not actual_base:
                raise CandidateContractError(f"change base is invalid: {candidate['candidate_id']}")
            changed = set(_git(root, "diff", "--name-only", actual_base, head_ref).splitlines())
            declared = set(candidate["changed_paths"])
            if declared != changed:
                raise CandidateContractError(
                    f"declared changed_paths differ from real diff: {candidate['candidate_id']}"
                )
            accepted_tests = set(candidate["accepted_test_paths"])
            actual = bool(changed & accepted_tests)
            if actual != candidate["accepted_test_in_change_set"]:
                raise CandidateContractError(
                    f"real accepted-test change-set truth mismatch: {candidate['candidate_id']}"
                )
            for test_path in accepted_tests:
                try:
                    _read_git_file(root, head_ref, test_path)
                except CandidateContractError as exc:
                    raise CandidateContractError(
                        f"accepted test is absent at change head: {candidate['candidate_id']}: {test_path}"
                    ) from exc

        for proof in candidate["source_proofs"]:
            if proof["kind"] == "knowledge":
                continue
            path = proof["relative_path"]
            if is_change_candidate and proof["kind"] == "project_change":
                if path not in changed:
                    raise CandidateContractError(
                        f"change proof path is absent from real diff: {candidate['candidate_id']}: {path}"
                    )
                content = _git(root, "diff", actual_base, head_ref, "--", path)
                if proof["anchor"] not in content:
                    raise CandidateContractError(
                        f"change proof anchor not found in real diff for {candidate['candidate_id']}: {path}"
                    )
                continue
            if is_change_candidate and proof["kind"] == "project_test":
                if path not in accepted_tests:
                    raise CandidateContractError(
                        f"project_test proof is not an accepted test: {candidate['candidate_id']}: {path}"
                    )
                content = _read_git_file(root, head_ref, path)
                if proof["anchor"] not in content:
                    raise CandidateContractError(
                        f"project_test proof anchor not found at change head for {candidate['candidate_id']}: {path}"
                    )
                continue
            content = _read_git_file(root, commit, path)
            if proof["anchor"] not in content:
                raise CandidateContractError(
                    f"source proof anchor not found for {candidate['candidate_id']}: {proof['relative_path']}"
                )


def validate_manifest(
    manifest: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]], repository_manifest_path: Path, pool_path: Path
) -> None:
    candidate_list = list(candidates)
    expected_map = {candidate["candidate_id"]: candidate_sha256(candidate) for candidate in candidate_list}
    if manifest.get("candidate_sha256") != expected_map:
        raise CandidateContractError("candidate manifest identity mismatch")
    if manifest.get("candidate_pool_sha256") != file_sha256(pool_path):
        raise CandidateContractError("candidate JSONL manifest identity mismatch")
    if manifest.get("repository_manifest_sha256") != file_sha256(repository_manifest_path):
        raise CandidateContractError("repository manifest identity mismatch")
    if manifest.get("case_count") != 24:
        raise CandidateContractError("candidate manifest count mismatch")


__all__ = [
    "CANDIDATE_STATUS", "CandidateContractError", "CHANGE_REQUIRED_TOOLS",
    "FAMILY_EVIDENCE_GROUPS", "PROJECT_IDS", "SCHEMA_VERSION", "TASK_FAMILIES",
    "candidate_sha256", "canonical_json", "file_sha256", "load_json", "load_jsonl",
    "validate_candidate", "validate_candidate_sources", "validate_manifest", "validate_pool",
    "validate_repository_checkout",
]
