"""Record actual file identities and public configuration without credentials."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess

from . import EVALUATOR_VERSION
from .schema import digest, text_digest

REPO_ROOT = Path(__file__).resolve().parents[2]


def business_fingerprint(root: Path = REPO_ROOT) -> dict:
    files = {}
    for directory in ("core", "api"):
        for path in sorted((root / directory).rglob("*")):
            if path.suffix in (".py", ".html", ".js", ".css") and path.is_file():
                files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("requirements.txt", "requirements.lock", ".env"):
        if (root / name).is_file():
            # .env is an opaque integrity hash only, never its text or keys.
            files[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    return {"files": files, "sha256": digest(files)}


def evaluator_fingerprint() -> dict:
    root = Path(__file__).parent
    files = {p.relative_to(REPO_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*")
             if p.is_file() and p.suffix in (".py", ".json", ".jsonl", ".md") and "results" not in p.relative_to(root).parts}
    script = REPO_ROOT / "scripts/run_tool_call_evaluation.py"
    if script.is_file():
        files[script.relative_to(REPO_ROOT).as_posix()] = hashlib.sha256(script.read_bytes()).hexdigest()
    return {"files": files, "sha256": digest(files)}


def copy_seed_library(path: Path, *, corpus_root: Path | None = None):
    """Freeze the verified 37-document initialization source in a new managed DB.

    This measures the managed baseline, not a user's subsequently edited live
    library. The live DB is neither read nor written.
    """
    import os
    from dotenv import load_dotenv
    from core.engineering_knowledge import CORPUS_ENV_VAR, build_verified_engineering_knowledge
    from core.knowledge_library import KnowledgeLibrary
    from core.loader.base import Document

    if path.exists():
        raise ValueError("Knowledge DB must be new")
    if corpus_root is None:
        load_dotenv(REPO_ROOT / ".env")
        configured = os.getenv(CORPUS_ENV_VAR)
        if not configured:
            raise ValueError("Set --knowledge-source to the verified baseline corpus")
        corpus_root = Path(configured)
    corpus_root = corpus_root.resolve(strict=True)
    verified = build_verified_engineering_knowledge(corpus_root, repo_root=REPO_ROOT)
    seeds = []
    for name in verified.source_names:
        file = (corpus_root / name).resolve(strict=True)
        file.relative_to(corpus_root)
        seeds.append(Document(file.read_text(encoding="utf-8"), {"source_name": name}))
    return KnowledgeLibrary(path, seeds=seeds)


def library_identity(library, db_path: Path) -> dict:
    with sqlite3.connect(db_path) as connection:
        files = dict(connection.execute("SELECT name, content_hash FROM documents ORDER BY name"))
        chunks = [(name, position, text_digest(content)) for name, position, content in connection.execute(
            "SELECT d.name, c.position, c.content FROM chunks c JOIN documents d ON d.id=c.document_id ORDER BY d.name, c.position")]
    return {"identity": asdict(library.identity), "documents": files, "content_sha256": digest(files), "chunks_sha256": digest(chunks),
            "chunk_size": 512, "chunk_overlap": 64, "input_scope": "verified 37-document seeds copied to fresh managed library"}


def runtime_identity(registry) -> dict:
    from core.query_planning.prompt import (ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION, PLANNER_MAX_OUTPUT_TOKENS,
        PLANNER_MAX_RETRIES, PLANNER_TIMEOUT_SECONDS, planner_prompt_sha256)
    from core.conversation_context.resolver import (ENGINEERING_REFERENCE_PROMPT_VERSION,
        ENGINEERING_REFERENCE_PROMPT_SHA256, RESOLVER_MAX_OUTPUT_TOKENS, RESOLVER_MAX_RETRIES)
    from core.tool_agent.decision_prompt import (ENGINEERING_DECISION_PROMPT_PROJECT_OVERVIEW_PROFILE,
        DECISION_MAX_RETRIES, DECISION_TIMEOUT_SECONDS, compute_toolset_sha256, max_output_tokens_for_profile, max_parse_repairs_for_profile)
    from core.tool_agent.integration import FROZEN_TOOL_MODEL, FROZEN_TOOL_PROVIDER
    from core.tool_agent.runtime_models import ENGINEERING_RUN_DEADLINE_SECONDS

    # Match the current API factory; actual live metadata is checked against
    # these identities rather than silently accepting a changed assembly.
    profile = ENGINEERING_DECISION_PROMPT_PROJECT_OVERVIEW_PROFILE
    registered = registry.list_specs()
    enabled = [s for s in registered if s.name != "knowledge_search"]
    return {"provider": FROZEN_TOOL_PROVIDER, "model": FROZEN_TOOL_MODEL,
            "assembly": "api.app._build_engineering_project_runtime -> EngineeringAgentFacade",
            "decision": {"version": profile.version, "sha256": profile.sha256, "output_cap": max_output_tokens_for_profile(profile),
                         "max_parse_repairs": max_parse_repairs_for_profile(profile), "timeout_seconds": DECISION_TIMEOUT_SECONDS, "sdk_retries": DECISION_MAX_RETRIES},
            "planner": {"version": ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION, "sha256": planner_prompt_sha256(ENGINEERING_OVERVIEW_PLANNER_PROMPT_VERSION),
                        "output_cap": PLANNER_MAX_OUTPUT_TOKENS, "timeout_seconds": PLANNER_TIMEOUT_SECONDS, "sdk_retries": PLANNER_MAX_RETRIES},
            "context": {"version": ENGINEERING_REFERENCE_PROMPT_VERSION, "sha256": ENGINEERING_REFERENCE_PROMPT_SHA256,
                        "output_cap": RESOLVER_MAX_OUTPUT_TOKENS, "sdk_retries": RESOLVER_MAX_RETRIES,
                        "history_scope": "empty for independent single-turn tool evaluation cases"},
            "budget": {"decisions": 5, "tools": 4, "tool_errors": 2, "deadline_seconds": ENGINEERING_RUN_DEADLINE_SECONDS},
            "registered_tools": [{"name": s.name, "version": s.version, "input_schema_sha256": digest(s.input_schema), "output_schema_sha256": digest(s.output_schema)} for s in registered],
            "primary_tools": [s.name for s in enabled], "primary_toolset_sha256": compute_toolset_sha256(enabled),
            "disabled_tools": [s.name for s in registered if s.name == "knowledge_search"]}


def create_manifest(*, run_id: str, mode: str, cases: list[dict], projects: dict, library: dict, registry, timestamp: str) -> dict:
    process = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, check=True)
    return {"run_id": run_id, "evaluator_version": EVALUATOR_VERSION, "mode": mode, "model_calls_enabled": mode == "live", "created_at": timestamp,
            "python": platform.python_version(), "code_head": process.stdout.decode().strip(), "business": business_fingerprint(),
            "evaluator": evaluator_fingerprint(), "cases_sha256": digest(cases), "planned_case_ids": [c["id"] for c in cases],
            "projects": projects, "knowledge": library, "runtime": runtime_identity(registry),
            "reviewer_type": "developer_assistant", "sealed_holdout": False,
            "retries": "no evaluation-level retries; production decision parse repair retained"}
