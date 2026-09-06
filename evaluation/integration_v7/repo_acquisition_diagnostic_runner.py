"""Three-case ARCH-INTEGRATION-12D repository-acquisition diagnostic.

This deliberately small harness executes only v7d003, v7d012, and v7d014
against the frozen Integration-v7 Dev contract.  Each case is attempted once
with the current Unified-v1 product assembly.  The persisted artifact contains
only bounded product-safe Activity and a minimal final-state projection.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
from evaluation.integration_v7.candidate_runner import _verify_candidate_corpus
from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
    DEV_DATASET_PATH,
    DEV_SPLIT,
    MANIFEST_PATH,
    TARGET_PROJECT_COMMIT,
    TARGET_PROJECT_ID,
    HoldoutExecutionDenied,
    ProtocolViolation,
    load_cases,
    validate_protocol_manifest,
)
from evaluation.integration_v7.runner import (
    CORPUS_REPOSITORY,
    FROZEN_MODEL,
    FROZEN_PROTOCOL_SHA,
    FROZEN_PROVIDER,
    REPO_ROOT,
    TARGET_REPOSITORY,
    WORKER_SCHEMA_VERSION,
    RunnerPreflightError,
    _git_head,
    _tracked_clean,
    _write_json,
    _write_jsonl,
    safe_artifact,
)
from evaluation.integration_v7.runner_worker import UNIFIED_DECISION_PROMPT_SELECTOR


DIAGNOSTIC_RUNNER_SCHEMA_VERSION = (
    "integration_v7_repo_acquisition_diagnostic_runner_v1"
)
CANDIDATE_RUNTIME_COMMIT = "1a26428d64c724cad42b8ed331b9fdef65d1e9d7"
CANDIDATE_SYSTEM = "B"
RUNTIME_VARIANT = "repo_acquisition_diagnostic_12d"
DECISION_PROMPT_PROFILE_SELECTOR = UNIFIED_DECISION_PROMPT_SELECTOR
DIAGNOSTIC_CASE_IDS = ("v7d003", "v7d012", "v7d014")
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_diag_12d_1a26428_v1"
)
PROTECTED_RESULT_DIRS = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_e374_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_0abdb_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_d001_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_6cd1_v1",
)


@dataclass(frozen=True)
class RepoAcquisitionDiagnosticConfig:
    """Explicit inputs for the single, three-case diagnostic work unit."""

    corpus_checkout: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_diagnostic_scope(split: str) -> None:
    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-INTEGRATION-12D is Dev-only; Holdout execution is denied"
        )


def _assert_independent_output(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    if any(
        resolved == protected.resolve() or protected.resolve() in resolved.parents
        for protected in PROTECTED_RESULT_DIRS
    ):
        raise RunnerPreflightError("12D output must not overwrite an earlier result")
    if resolved.exists() and any(resolved.iterdir()):
        raise RunnerPreflightError("12D diagnostic output is not empty; rerun denied")


def validate_diagnostic_checkouts(
    candidate_root: Path,
    target_root: Path,
    *,
    candidate_head: str,
    target_head: str,
) -> None:
    if candidate_root.resolve() == target_root.resolve():
        raise RunnerPreflightError("12D candidate and target checkouts must be separate")
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("12D candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("12D target project SHA mismatch")


def build_diagnostic_run_plan(
    cases: list[Mapping[str, Any]], split: str = DEV_SPLIT
) -> list[dict[str, Any]]:
    """Select exactly the three frozen Dev cases in fixed diagnostic order."""

    assert_diagnostic_scope(split)
    by_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for case_order, case in enumerate(cases, 1):
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in by_id:
            raise ProtocolViolation("12D source dataset contains an invalid case ID")
        by_id[case_id] = (case_order, case)

    if any(case_id not in by_id for case_id in DIAGNOSTIC_CASE_IDS):
        raise ProtocolViolation("12D frozen diagnostic case is missing")

    plan: list[dict[str, Any]] = []
    for run_order, case_id in enumerate(DIAGNOSTIC_CASE_IDS, 1):
        case_order, case = by_id[case_id]
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("12D run plan contains a non-Dev case")
        plan.append(
            {
                "run_order": run_order,
                "case_order": case_order,
                "case_id": case_id,
                "system": CANDIDATE_SYSTEM,
                "runtime_variant": RUNTIME_VARIANT,
                "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
                "decision_prompt_profile": (
                    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version
                ),
                "decision_prompt_sha256": (
                    ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256
                ),
            }
        )
    if tuple(item["case_id"] for item in plan) != DIAGNOSTIC_CASE_IDS:
        raise ProtocolViolation("12D run plan must contain exactly three fixed cases")
    return plan


def build_diagnostic_worker_job(
    case: Mapping[str, Any],
    *,
    plan_item: Mapping[str, Any],
    candidate_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    if plan_item.get("case_id") not in DIAGNOSTIC_CASE_IDS:
        raise ProtocolViolation("12D worker received a case outside diagnostic scope")
    if plan_item.get("system") != CANDIDATE_SYSTEM:
        raise ProtocolViolation("12D worker must use System B")
    if (
        plan_item.get("decision_prompt_profile_selector")
        != DECISION_PROMPT_PROFILE_SELECTOR
    ):
        raise ProtocolViolation("12D worker must explicitly select Unified-v1")
    return {
        "worker_schema_version": WORKER_SCHEMA_VERSION,
        "system": CANDIDATE_SYSTEM,
        "run_order": plan_item["run_order"],
        "case_order": plan_item["case_order"],
        "case": dict(case),
        "system_root": str(candidate_root),
        "target_root": str(target_root),
        "corpus_root": str(corpus_root),
        "question": case["question"],
        "conversation_context": case.get("conversation_context", []),
        "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
    }


def _diagnostic_raw_record(
    case: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist only the Activity and final fields needed by this diagnosis."""

    result = payload.get("result")
    if not isinstance(result, Mapping):
        result = {}
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    evidence_kinds = sorted(
        {
            item.get("kind")
            for item in evidence
            if isinstance(item, Mapping) and isinstance(item.get("kind"), str)
        }
    )
    activity = payload.get("activity")
    if not isinstance(activity, list):
        activity = []
    record = {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": CANDIDATE_SYSTEM,
        "runtime_variant": RUNTIME_VARIANT,
        "candidate_runtime_commit": CANDIDATE_RUNTIME_COMMIT,
        "run_order": plan_item["run_order"],
        "run_validity": payload.get("execution_validity", "INVALID"),
        "infrastructure_code": payload.get("infrastructure_code"),
        "final": {
            "status": result.get("status"),
            "reason_code": result.get("reason_code"),
            "failure_code": result.get("failure_code"),
            "evidence_kinds": evidence_kinds,
        },
        "activity": activity[:64],
    }
    sanitized = safe_artifact(record)
    if not isinstance(sanitized, dict):  # pragma: no cover - structural guard
        raise RunnerPreflightError("12D safe raw record is invalid")
    return sanitized


def _invoke_diagnostic_worker(
    job: Mapping[str, Any], candidate_root: Path, timeout: float
) -> dict[str, Any]:
    """Invoke one worker once. Infrastructure failures are not retried."""

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(candidate_root)
    worker = candidate_root / "evaluation" / "integration_v7" / "runner_worker.py"
    try:
        completed = subprocess.run(
            [sys.executable, str(worker)],
            cwd=candidate_root,
            input=json.dumps(job, ensure_ascii=False, separators=(",", ":")),
            capture_output=True,
            text=True,
            env=environment,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "process_timeout",
        }
    except (OSError, subprocess.SubprocessError):
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_process_failure",
        }
    if completed.returncode != 0:
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_process_failure",
        }
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_output_invalid",
        }
    if (
        not isinstance(payload, dict)
        or payload.get("worker_schema_version") != WORKER_SCHEMA_VERSION
    ):
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_output_invalid",
        }
    return payload


@contextmanager
def _isolated_diagnostic_checkouts(repo_root: Path) -> Iterator[dict[str, Path]]:
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".arch_integration_12d_", dir=str(repo_root.parent))
    )
    paths = {
        "candidate": temporary_root / "runtime_candidate",
        "target": temporary_root / "target_project",
    }
    revisions = {
        "candidate": CANDIDATE_RUNTIME_COMMIT,
        "target": TARGET_PROJECT_COMMIT,
    }
    added: list[Path] = []
    try:
        for name, revision in revisions.items():
            completed = subprocess.run(
                ["git", "worktree", "add", "--detach", str(paths[name]), revision],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if completed.returncode != 0:
                raise RunnerPreflightError("12D isolated checkout creation failed")
            added.append(paths[name])
        validate_diagnostic_checkouts(
            paths["candidate"],
            paths["target"],
            candidate_head=_git_head(paths["candidate"]),
            target_head=_git_head(paths["target"]),
        )
        _tracked_clean(paths["candidate"], "12D candidate")
        _tracked_clean(paths["target"], "12D target")
        yield paths
    finally:
        for path in reversed(added):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        shutil.rmtree(temporary_root, ignore_errors=True)


def _preflight(
    config: RepoAcquisitionDiagnosticConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert_diagnostic_scope(config.split)
    _assert_independent_output(config.output_dir)
    if config.provider != "deepseek" or config.provider != FROZEN_PROVIDER:
        raise RunnerPreflightError("12D provider must be frozen DeepSeek")
    if config.model != "deepseek-chat" or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("12D model must be frozen deepseek-chat")
    manifest = validate_protocol_manifest(MANIFEST_PATH)
    if manifest["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("12D protocol SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError("missing_environment: DEEPSEEK_API_KEY")
    cases = load_cases(DEV_DATASET_PATH)
    return manifest, cases


def build_diagnostic_manifest(
    *,
    protocol: Mapping[str, Any],
    config: RepoAcquisitionDiagnosticConfig,
    plan: list[Mapping[str, Any]],
    raw_runs: list[Mapping[str, Any]],
    corpus_identity: Mapping[str, Any],
    timestamp: str = "",
) -> dict[str, Any]:
    run_timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": DIAGNOSTIC_RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-integration-12d-repo-acquisition-{run_timestamp}",
        "status": "COMPLETE" if len(raw_runs) == len(DIAGNOSTIC_CASE_IDS) else "INVALID",
        "execution_scope": "three frozen Integration Dev cases / diagnostic only",
        "split": DEV_SPLIT,
        "case_ids": list(DIAGNOSTIC_CASE_IDS),
        "provider": {"name": config.provider, "model": config.model},
        "candidate_runtime": {
            "source_commit": CANDIDATE_RUNTIME_COMMIT,
            "system": CANDIDATE_SYSTEM,
            "runtime_variant": RUNTIME_VARIANT,
            "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
            "decision_prompt_profile": (
                ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version
            ),
            "decision_prompt_sha256": (
                ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256
            ),
        },
        "target_project": {
            "repository": TARGET_REPOSITORY,
            "project_id": TARGET_PROJECT_ID,
            "source_sha": TARGET_PROJECT_COMMIT,
        },
        "corpus_identity": {
            "repository": CORPUS_REPOSITORY,
            "source_commit": CORPUS_SOURCE_COMMIT,
            **dict(corpus_identity),
        },
        "protocol": {
            "version": protocol["protocol_version"],
            "sha256": protocol["protocol_sha256"],
        },
        "dataset": {
            "split": DEV_SPLIT,
            "sha256": protocol["datasets"][DEV_SPLIT]["sha256"],
        },
        "run_plan": [dict(item) for item in plan],
        "expected_runs": len(DIAGNOSTIC_CASE_IDS),
        "observed_runs": len(raw_runs),
        "valid_runs": sum(run.get("run_validity") == "VALID" for run in raw_runs),
        "invalid_runs": sum(run.get("run_validity") != "VALID" for run in raw_runs),
        "retry_policy": "NO_RETRY",
        "system_a": "NOT_RUN",
        "holdout": "NOT_RUN / DENY",
        "artifact_files": ["run_manifest.json", "raw_runs.jsonl", "summary.json"],
    }


def _diagnostic_summary(raw_runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": DIAGNOSTIC_RUNNER_SCHEMA_VERSION,
        "scope": "safe Activity and final state only; no semantic scoring",
        "run_counts": {
            "expected": len(DIAGNOSTIC_CASE_IDS),
            "observed": len(raw_runs),
            "valid": sum(run.get("run_validity") == "VALID" for run in raw_runs),
            "invalid": sum(run.get("run_validity") != "VALID" for run in raw_runs),
        },
        "cases": [
            {
                "case_id": run["case_id"],
                "run_validity": run["run_validity"],
                "infrastructure_code": run.get("infrastructure_code"),
                "final": run["final"],
            }
            for run in raw_runs
        ],
        "manual_scoring": "NOT_DONE",
        "system_a": "NOT_RUN",
        "holdout": "NOT_RUN / DENY",
    }


def run_repo_acquisition_diagnostic(
    config: RepoAcquisitionDiagnosticConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Execute each fixed diagnostic case exactly once, with no retry path."""

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=repo_root / ".env", override=False)
    protocol, cases = _preflight(config)
    plan = build_diagnostic_run_plan(cases, config.split)
    case_by_id = {case["case_id"]: case for case in cases}
    corpus = config.corpus_checkout.resolve()
    raw_runs: list[dict[str, Any]] = []

    with _isolated_diagnostic_checkouts(repo_root) as checkouts:
        if _git_head(corpus) != CORPUS_SOURCE_COMMIT:
            raise RunnerPreflightError("12D knowledge corpus SHA mismatch")
        corpus_identity = _verify_candidate_corpus(corpus, checkouts["candidate"])
        knowledge_root = corpus / protocol["corpus_identity"]["path"]
        for item in plan:
            case = case_by_id[item["case_id"]]
            job = build_diagnostic_worker_job(
                case,
                plan_item=item,
                candidate_root=checkouts["candidate"],
                target_root=checkouts["target"],
                corpus_root=knowledge_root,
            )
            payload = _invoke_diagnostic_worker(
                job, checkouts["candidate"], config.worker_timeout_seconds
            )
            if payload.get("execution_validity") == "VALID" and payload.get(
                "infrastructure_code"
            ):
                payload = dict(payload)
                payload["execution_validity"] = "INVALID"
            raw_runs.append(_diagnostic_raw_record(case, item, payload))

    run_manifest = build_diagnostic_manifest(
        protocol=protocol,
        config=config,
        plan=plan,
        raw_runs=raw_runs,
        corpus_identity=corpus_identity,
    )
    output = config.output_dir
    _write_json(output / "run_manifest.json", run_manifest)
    _write_jsonl(output / "raw_runs.jsonl", raw_runs)
    _write_json(output / "summary.json", _diagnostic_summary(raw_runs))
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the three-case ARCH-INTEGRATION-12D DeepSeek diagnostic"
    )
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    try:
        output = run_repo_acquisition_diagnostic(
            RepoAcquisitionDiagnosticConfig(
                corpus_checkout=Path(args.corpus_root),
                output_dir=Path(args.output_dir),
                split=args.split,
            )
        )
    except (RunnerPreflightError, HoldoutExecutionDenied, ProtocolViolation):
        return 2
    print(output.name)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
