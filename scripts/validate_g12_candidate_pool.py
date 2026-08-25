"""Validate the G12-02A draft pool against real isolated project checkouts.

The command is evaluator-only.  It does not call an LLM, modify either target
checkout, or serialize local roots into tracked artifacts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from api.project_workspace import resolve_engineering_project
from core.engineering_knowledge import build_verified_engineering_knowledge
from core.tool_agent.tools.code_search import CodeSearchHandler
from core.tool_agent.tools.git_change import ChangedFilesHandler, GitDiffHandler
from core.tool_agent.tools.read_project_context import ReadProjectContextHandler
from core.tool_agent.tools.test_discovery import FindTestsHandler
from evaluation.gate12.candidate_contract import (
    CandidateContractError,
    load_json,
    load_jsonl,
    validate_candidate_sources,
    validate_manifest,
    validate_pool,
    validate_repository_checkout,
)


GATE12_DIR = EVALUATOR_ROOT / "evaluation" / "gate12"
REPOSITORY_REGISTRY_PATH = GATE12_DIR / "repositories_v1.json"
CANDIDATE_POOL_PATH = GATE12_DIR / "candidate_pool_v1.jsonl"
CANDIDATE_MANIFEST_PATH = GATE12_DIR / "candidate_pool_manifest_v1.json"
MY_AGENT_FORBIDDEN_PATHS = (
    "scripts/run_g11_02*",
    "scripts/run_g11_03*",
    "scripts/run_g11_04*",
    "scripts/run_g11_05*",
    "tests/test_g11_02*",
    "tests/test_g11_03*",
    "tests/test_g11_04*",
    "tests/test_g11_05*",
    "docs/design/g12-engineering-evaluation-2.0.md",
    "docs/study-notes/113-Engineering-Evaluation-2.0与Evidence-Sufficiency.md",
    "evaluation/gate12/",
)
SMOKE_CONFIG = {
    "my_agent": {"query": "EngineeringAgentFacade", "context_path": "api/app.py", "context_line": 16},
    "pydantic_ai": {
        "query": "class AbstractAgent",
        "context_path": "pydantic_ai_slim/pydantic_ai/agent/abstract.py",
        "context_line": 346,
    },
}


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return completed.stdout.strip()


def _tracked_count(root: Path, *pathspecs: str) -> int:
    args = ["ls-files"]
    if pathspecs:
        args.extend(("--", *pathspecs))
    output = _git(root, *args)
    return 0 if not output else len(output.splitlines())


def _assert_required_tree(root: Path, project: dict[str, Any]) -> None:
    for relative in project["required_tree"]:
        if not (root / relative).exists():
            raise CandidateContractError(f"required source tree is missing: {project['project_id']}")


def _assert_declared_counts(root: Path, project: dict[str, Any]) -> dict[str, int]:
    counts = {
        "tracked_file_count": _tracked_count(root),
        "python_source_file_count": _tracked_count(root, "*.py"),
        "doc_file_count": _tracked_count(root, "docs/*", "docs/**/*"),
        "test_file_count": _tracked_count(root, "tests/*", "tests/**/*"),
    }
    expected = {key: project[key] for key in counts}
    if counts != expected:
        raise CandidateContractError(f"repository tracked-file counts drift: {project['project_id']}")
    return counts


def _assert_my_agent_isolated(root: Path) -> None:
    unexpected: list[str] = []
    for pattern in MY_AGENT_FORBIDDEN_PATHS:
        output = _git(root, "ls-files", "--", pattern)
        if output:
            unexpected.extend(output.splitlines())
    if unexpected:
        raise CandidateContractError("my_agent target contains evaluator/G11 leakage")


def _tool_smoke(project_id: str, root: Path) -> dict[str, Any]:
    config = SMOKE_CONFIG[project_id]
    code_matches = CodeSearchHandler(root).execute({"query": config["query"]})["matches"]
    if not code_matches:
        raise CandidateContractError(f"code_search smoke returned no match: {project_id}")
    context = ReadProjectContextHandler(root).execute(
        {"path": config["context_path"], "line": config["context_line"], "context_lines": 3}
    )
    if not context["lines"]:
        raise CandidateContractError(f"read_project_context smoke returned no lines: {project_id}")
    head = _git(root, "rev-parse", "HEAD")
    changed = ChangedFilesHandler(root).execute(
        {"mode": "commit_range", "base_ref": f"{head}^", "head_ref": head}
    )
    if not changed["changes"]:
        raise CandidateContractError(f"changed_files smoke returned no paths: {project_id}")
    diff_path = changed["changes"][0]["path"]
    diff = GitDiffHandler(root).execute(
        {"mode": "commit_range", "base_ref": f"{head}^", "head_ref": head, "path": diff_path}
    )
    if not diff["diff"]:
        raise CandidateContractError(f"git_diff smoke returned no diff: {project_id}")
    discovered = FindTestsHandler(root).execute({"path": config["context_path"]})
    binding = resolve_engineering_project(EVALUATOR_ROOT, configured_root=str(root))
    public_binding = {"project_name": binding.project_name, "source": binding.source}
    if str(root) in json.dumps(public_binding, ensure_ascii=False):
        raise CandidateContractError(f"project binding leaks local root: {project_id}")
    return {
        "code_search_matches": len(code_matches),
        "context_path": context["path"],
        "changed_files_returned": changed["returned_count"],
        "git_diff_bounded": len(diff["diff"]) <= 12000 and len(diff["diff"].splitlines()) <= 240,
        "find_tests_candidates": discovered["returned_count"],
        "project_binding": public_binding,
    }


def _validate_knowledge_probes(candidates: list[dict[str, Any]], corpus_root: Path) -> dict[str, Any]:
    backend = build_verified_engineering_knowledge(corpus_root, repo_root=EVALUATOR_ROOT)
    theory = [candidate for candidate in candidates if candidate["task_family"] == "Theory <-> Code"]
    for candidate in theory:
        returned = [
            document.source_name
            for document in backend.retrieval_port.search(candidate["knowledge_probe_query"], "bm25", 5)
        ]
        expected = candidate["knowledge_probe_proof"]["returned_sources"]
        if returned != expected:
            raise CandidateContractError(f"knowledge probe result drift: {candidate['candidate_id']}")
        if not set(candidate["knowledge_gold_sources"]).issubset(returned):
            raise CandidateContractError(f"knowledge Gold source not returned: {candidate['candidate_id']}")
    return {"candidate_count": len(theory), "identity": backend.identity.to_dict()}


def run_validation(
    *, my_agent_root: Path, pydantic_ai_root: Path, corpus_root: Path
) -> dict[str, Any]:
    registry_document = load_json(REPOSITORY_REGISTRY_PATH)
    repositories = registry_document.get("repositories")
    if not isinstance(repositories, dict):
        raise CandidateContractError("repository registry has no repositories map")
    candidates = load_jsonl(CANDIDATE_POOL_PATH)
    manifest = load_json(CANDIDATE_MANIFEST_PATH)
    validate_pool(candidates, repositories)
    validate_manifest(manifest, candidates, REPOSITORY_REGISTRY_PATH, CANDIDATE_POOL_PATH)
    roots = {"my_agent": my_agent_root, "pydantic_ai": pydantic_ai_root}
    project_report: dict[str, Any] = {}
    for project_id, root in roots.items():
        project = repositories[project_id]
        checkout = validate_repository_checkout(project_id, root, repositories)
        _assert_required_tree(root, project)
        counts = _assert_declared_counts(root, project)
        if project_id == "my_agent":
            _assert_my_agent_isolated(root)
        project_report[project_id] = {
            "checkout": checkout,
            "counts": counts,
            "tool_viability": _tool_smoke(project_id, root),
        }
    validate_candidate_sources(candidates, roots)
    knowledge = _validate_knowledge_probes(candidates, corpus_root)
    return {
        "schema_version": "g12_candidate_pool_validation_v1",
        "status": "PASS",
        "projects": project_report,
        "knowledge": knowledge,
        "candidate_count": len(candidates),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate G12-02A draft candidates against isolated repositories.")
    parser.add_argument("--my-agent-root", type=Path, required=True)
    parser.add_argument("--pydantic-ai-root", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_validation(
            my_agent_root=args.my_agent_root,
            pydantic_ai_root=args.pydantic_ai_root,
            corpus_root=args.corpus_root,
        )
    except (CandidateContractError, OSError, subprocess.CalledProcessError) as exc:
        print(f"G12 candidate pool validation: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
