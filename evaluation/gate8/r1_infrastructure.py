"""Gate8 R1 clean-corpus provenance and safe result helpers.

This module is evaluation-only.  It deliberately keeps corpus provenance and
source sanitization outside the production retrieval/API path until the API
source contract is repaired in a separate task.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from evaluation.experiment_corpus import ExperimentCorpus

EXPECTED_CASE_COUNT = 6
R1_CASE_SCHEMA_VERSION = "gate8_context_case_r1"
R1_RESULT_SCHEMA_VERSION = "gate8_context_result_r1"
R1_REPORT_SCHEMA_VERSION = "gate8_context_report_r1"
EXPECTED_REPOSITORY = "wgqa/agent_data"
EXPECTED_COMMIT = "179f18e812ad63c36c5569de8e86c5ff9a931cb5"
EXPECTED_CORPUS_PATH = "agent_ai_v1/02_corpus_candidate"
EXPECTED_CORPUS_ID = "870e5864df67"
EXPECTED_FILE_COUNT = 37
_LOCAL_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\"'\r\n]+")
_UNSAFE_COMPONENT_RE = re.compile(r"(?i)(?:test|temp|rag_test|upload|appdata)")


class R1PreflightError(ValueError):
    """The clean-corpus/index gate cannot prove a valid experiment."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _reference_entries(repo_root: Path) -> list[dict[str, Any]]:
    manifests = sorted(repo_root.glob("experiments/*/*/index_manifest.json"))
    for manifest_path in manifests:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = data.get("corpus_entries")
        if data.get("corpus_id") == EXPECTED_CORPUS_ID and isinstance(entries, list):
            return entries
    raise R1PreflightError("frozen corpus reference entries are unavailable")


def _git_head(path: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def assert_expected_identity(
    *,
    repository: str,
    commit: str,
    path: str,
    corpus_id: str,
    file_count: int,
) -> None:
    actual = (repository, commit, path, corpus_id, file_count)
    expected = (
        EXPECTED_REPOSITORY,
        EXPECTED_COMMIT,
        EXPECTED_CORPUS_PATH,
        EXPECTED_CORPUS_ID,
        EXPECTED_FILE_COUNT,
    )
    if actual != expected:
        raise R1PreflightError(
            "frozen corpus identity mismatch: "
            f"actual={actual!r} expected={expected!r}"
        )


def build_corpus_provenance(corpus_root: str | Path, *, repo_root: str | Path) -> dict[str, Any]:
    """Verify the pinned corpus bytes and return only safe provenance data."""

    root = Path(corpus_root).resolve()
    if not root.is_dir():
        raise R1PreflightError("frozen corpus directory is missing")
    entries = _reference_entries(Path(repo_root).resolve())
    if len(entries) != EXPECTED_FILE_COUNT:
        raise R1PreflightError("frozen reference entry count mismatch")
    relative_paths = [entry.get("relative_path") for entry in entries]
    if not all(isinstance(item, str) and item for item in relative_paths):
        raise R1PreflightError("frozen reference path is invalid")

    corpus = ExperimentCorpus.build(root, relative_paths)
    actual_paths = sorted(
        item.relative_path
        for item in corpus.entries
    )
    expected_paths = sorted(relative_paths)
    all_files = sorted(
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    )
    if len(all_files) != EXPECTED_FILE_COUNT or all_files != expected_paths:
        raise R1PreflightError(
            "corpus contains extra/missing files; clean Gate8 corpus requires exactly 37"
        )
    unsafe = [path for path in all_files if _UNSAFE_COMPONENT_RE.search(path)]
    if unsafe:
        raise R1PreflightError("corpus contains test/temp/upload material")
    if corpus.corpus_id != EXPECTED_CORPUS_ID:
        raise R1PreflightError(
            f"corpus_id mismatch: actual={corpus.corpus_id} expected={EXPECTED_CORPUS_ID}"
        )

    head = _git_head(root)
    if head is not None and head != EXPECTED_COMMIT:
        raise R1PreflightError(
            f"corpus checkout HEAD mismatch: actual={head} expected={EXPECTED_COMMIT}"
        )
    # The supplied benchmark checkout is a materialized public-corpus directory,
    # not necessarily a git worktree.  The lock + byte identity is still checked;
    # when a .git directory exists, HEAD is checked as an additional assertion.
    commit_verification = "git_head_and_locked_bytes" if head else "locked_bytes_git_checkout_unavailable"
    return {
        "repository": EXPECTED_REPOSITORY,
        "commit": EXPECTED_COMMIT,
        "path": EXPECTED_CORPUS_PATH,
        "corpus_id": corpus.corpus_id,
        "file_count": len(corpus.entries),
        "relative_paths": actual_paths,
        "commit_verification": commit_verification,
    }


def _source_map(relative_paths: Sequence[str]) -> dict[str, str]:
    by_basename: dict[str, str] = {}
    for relative in relative_paths:
        basename = PurePosixPath(relative).name
        if basename in by_basename and by_basename[basename] != relative:
            raise R1PreflightError(f"duplicate corpus basename: {basename}")
        by_basename[basename] = relative
    return by_basename


def _safe_source_identity(raw: object, source_map: Mapping[str, str]) -> tuple[str, bool]:
    value = str(raw or "")
    normalized = value.replace("\\", "/")
    exposed = bool(PureWindowsPath(value).is_absolute() or PurePosixPath(normalized).is_absolute())
    lower = normalized.lower()
    for relative in source_map.values():
        rel_lower = relative.lower()
        if lower == rel_lower or lower.endswith("/" + rel_lower):
            return relative, exposed
    basename = PurePosixPath(normalized).name
    if basename in source_map:
        return source_map[basename], exposed
    if not value:
        return "unresolved_source/empty", exposed
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]
    return f"unresolved_source/{digest}", exposed


def sanitize_artifact_text(value: object) -> str:
    """Remove local filesystem identities from user/provider text."""

    text = str(value or "")
    text = _LOCAL_PATH_RE.sub("[LOCAL_PATH_REDACTED]", text)
    text = re.sub(r"(?i)(?:appdata|temp|temporary)[^\s\"']*", "[LOCAL_PATH_REDACTED]", text)
    return text


def safe_sources(
    data: Mapping[str, Any], source_map: Mapping[str, str]
) -> tuple[list[dict[str, Any]], bool]:
    sources = data.get("sources", [])
    if type(sources) is not list:
        raise R1PreflightError("provider sources is not a list")
    result: list[dict[str, Any]] = []
    absolute_exposed = False
    for item in sources:
        if type(item) is not dict:
            continue
        safe_source, exposed = _safe_source_identity(item.get("source"), source_map)
        absolute_exposed = absolute_exposed or exposed
        result.append({
            key: item.get(key)
            for key in ("citation_id", "chunk_id", "document_id", "score", "rank")
            if key in item
        } | {"source": safe_source})
    return result, absolute_exposed


def validate_index_source_identities(
    raw_sources: Sequence[object], source_map: Mapping[str, str]
) -> dict[str, Any]:
    """Validate a Chroma index without returning raw source paths."""

    safe: list[str] = []
    for raw in raw_sources:
        identity, _ = _safe_source_identity(raw, source_map)
        if identity.startswith("unresolved_source/"):
            raise R1PreflightError("index contains a source outside the frozen corpus")
        if _UNSAFE_COMPONENT_RE.search(identity):
            raise R1PreflightError("index contains test/temp/upload source")
        safe.append(identity)
    unique = sorted(set(safe))
    if len(unique) != EXPECTED_FILE_COUNT:
        raise R1PreflightError(
            f"isolated index source count mismatch: actual={len(unique)} expected={EXPECTED_FILE_COUNT}"
        )
    return {"source_count": len(unique), "source_identities": unique}


def preflight_clean_index(
    index_path: str | Path, provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify an isolated Chroma index contains only the frozen 37-doc corpus."""

    path = Path(index_path).resolve()
    if not path.is_dir():
        raise R1PreflightError("isolated Gate8 vector store is missing")
    repo_root = Path(__file__).resolve().parents[2]
    forbidden = (repo_root / "data" / "vector_store").resolve()
    if path == forbidden or forbidden in path.parents:
        raise R1PreflightError("contaminated current data/vector_store cannot be used")
    try:
        from chromadb import PersistentClient

        collection = PersistentClient(path=str(path)).get_collection("documents")
        data = collection.get(include=["metadatas"])
    except Exception as exc:
        raise R1PreflightError("isolated index cannot be opened") from exc
    metadata = data.get("metadatas") or []
    raw_sources = [item.get("source") for item in metadata if isinstance(item, dict)]
    source_map = _source_map(provenance["relative_paths"])
    source_proof = validate_index_source_identities(raw_sources, source_map)
    document_ids = {
        item.get("document_id")
        for item in metadata
        if isinstance(item, dict) and item.get("document_id")
    }
    if len(document_ids) != EXPECTED_FILE_COUNT:
        raise R1PreflightError(
            f"isolated index document count mismatch: actual={len(document_ids)} expected={EXPECTED_FILE_COUNT}"
        )
    return {
        "isolated": True,
        "index_id": f"gate8-clean-{EXPECTED_CORPUS_ID}",
        "corpus_id": provenance["corpus_id"],
        "file_count": provenance["file_count"],
        "vector_store_count": len(data.get("ids") or []),
        "document_count": len(document_ids),
        **source_proof,
    }


def load_r1_cases(path: str | Path, provenance: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    required = {
        "schema_version", "case_id", "case_type", "turn1", "turn2", "topic",
        "answer_terms", "min_answer_terms", "forbidden_topic_terms",
        "turn1_source_paths",
    }
    allowed_types = {
        "pronoun_reference", "plural_reference", "previous_concept_reference",
        "previous_answer_reference", "short_elliptical_followup", "topic_switch_control",
    }
    source_paths = set(provenance["relative_paths"])
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid R1 case JSON at line {line_number}") from exc
        if type(item) is not dict or set(item) != required:
            raise ValueError(f"R1 case at line {line_number} fields mismatch")
        if item["schema_version"] != R1_CASE_SCHEMA_VERSION:
            raise ValueError(f"R1 case {item.get('case_id')} schema mismatch")
        if item["case_type"] not in allowed_types:
            raise ValueError(f"R1 case {item.get('case_id')} type invalid")
        for field in ("case_id", "turn1", "turn2", "topic"):
            if type(item[field]) is not str or not item[field].strip():
                raise ValueError(f"R1 case {item.get('case_id')} field {field} invalid")
        if item["case_type"] == "topic_switch_control" and item["turn1"] == item["turn2"]:
            raise ValueError("topic switch case must switch topics")
        if (
            type(item["answer_terms"]) is not list or not item["answer_terms"]
            or not all(type(term) is str and term.strip() for term in item["answer_terms"])
        ):
            raise ValueError(f"R1 case {item.get('case_id')} answer_terms invalid")
        if (
            type(item["forbidden_topic_terms"]) is not list
            or not all(type(term) is str and term.strip() for term in item["forbidden_topic_terms"])
        ):
            raise ValueError(f"R1 case {item.get('case_id')} forbidden terms invalid")
        if (
            type(item["min_answer_terms"]) is not int
            or isinstance(item["min_answer_terms"], bool)
            or not 1 <= item["min_answer_terms"] <= len(item["answer_terms"])
        ):
            raise ValueError(f"R1 case {item.get('case_id')} min_answer_terms invalid")
        if (
            type(item["turn1_source_paths"]) is not list
            or not item["turn1_source_paths"]
            or not all(path in source_paths for path in item["turn1_source_paths"])
        ):
            raise ValueError(f"R1 case {item.get('case_id')} source coverage invalid")
        cases.append(item)
    if len(cases) != EXPECTED_CASE_COUNT:
        raise ValueError("R1 requires exactly 6 cases")
    if len({item["case_id"] for item in cases}) != EXPECTED_CASE_COUNT:
        raise ValueError("R1 case_id values must be unique")
    if {item["case_type"] for item in cases} != allowed_types:
        raise ValueError("R1 must cover all six context case types")
    return cases


def safe_provider_summary(
    data: Mapping[str, Any], latency_ms: float, source_map: Mapping[str, str]
) -> tuple[dict[str, Any], bool]:
    from evaluation.gate8.run_conversation_context_check import _context_trace

    sources, exposed = safe_sources(data, source_map)
    planner = data.get("planner") if type(data.get("planner")) is dict else {}
    plan = planner.get("plan") if type(planner.get("plan")) is dict else {}
    route = data.get("route") if type(data.get("route")) is dict else {}
    verification = data.get("verification") if type(data.get("verification")) is dict else {}
    return {
        "status": data.get("status"),
        "answer": sanitize_artifact_text(data.get("answer")),
        "sources": sources,
        "planner": {"action": plan.get("action"), "query_type": plan.get("query_type")},
        "route": {
            key: route.get(key)
            for key in ("route", "retrieval_strategy", "reason_code", "query_count")
            if key in route
        },
        "verification": {
            key: verification.get(key)
            for key in ("status", "can_generate", "reason_code", "evidence_count", "coverage_complete")
            if key in verification
        },
        "warning_count": len(data.get("warnings", [])) if isinstance(data.get("warnings"), list) else 0,
        "latency_ms": round(latency_ms, 2),
        "context": _context_trace(data),
    }, exposed


def turn1_is_valid(case: Mapping[str, Any], data: Mapping[str, Any], summary: Mapping[str, Any]) -> bool:
    if data.get("status") != "completed":
        return False
    if not isinstance(data.get("answer"), str) or not data["answer"].strip():
        return False
    available = {item.get("source") for item in summary.get("sources", [])}
    return bool(available.intersection(case["turn1_source_paths"]))
