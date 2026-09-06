"""Independent ARCH-INTEGRATION-14A full Dev candidate runner.

This evaluation-only runner executes the frozen 18-case Dev split once against
the kind-aware Unified Engineering candidate.  It reuses the existing worker,
automatic metrics, corpus verifier, and safe artifact boundary.  System A,
Holdout, retries, semantic review, and historical result directories are not
execution paths here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
)
from evaluation.integration_v7.candidate_runner import _verify_candidate_corpus
from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
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
    _automatic_score,
    _git_head,
    _tracked_clean,
    _write_json,
    _write_jsonl,
    aggregate_metrics,
    safe_artifact,
)
from evaluation.integration_v7.runner_worker import (
    UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR,
)


RUNNER_SCHEMA_VERSION = "integration_v7_end_to_end_candidate_runner_v1"
CANDIDATE_RUNTIME_COMMIT = "6d7e58f1e8c1f2bdaab091c453855b6eee53036b"
CANDIDATE_SYSTEM_LABEL = "B_kind_aware_recovery_candidate"
WORKER_SYSTEM = "B"
RUNTIME_VARIANT = "unified_kind_aware_recovery_candidate"
DECISION_PROMPT_PROFILE_SELECTOR = UNIFIED_KIND_AWARE_DECISION_PROMPT_SELECTOR
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_6d7e58f_v1"
)
PROTECTED_RESULT_DIRS = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_e374_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_0abdb_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_d001_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_6cd1_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_diag_12d_1a26428_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_verify_13b_6d7e58f_v1",
)
ARTIFACT_KIND_VALUES = ("any", "project_code", "project_doc")


@dataclass(frozen=True)
class EndToEndCandidateRunConfig:
    corpus_checkout: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_dev_only(split: str) -> None:
    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-INTEGRATION-14A is Dev-only; Holdout execution is denied"
        )


def _assert_independent_output(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    if any(
        resolved == protected.resolve() or protected.resolve() in resolved.parents
        for protected in PROTECTED_RESULT_DIRS
    ):
        raise RunnerPreflightError("14A output must not overwrite a historical result")
    if resolved.exists() and any(resolved.iterdir()):
        raise RunnerPreflightError("14A output is not empty; rerun denied")


def build_end_to_end_run_plan(
    cases: list[Mapping[str, Any]], split: str = DEV_SPLIT
) -> list[dict[str, Any]]:
    assert_dev_only(split)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise ProtocolViolation("14A requires exactly 18 Dev cases")
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case_order, case in enumerate(cases, 1):
        case_id = case.get("case_id")
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("14A run plan contains a non-Dev case")
        if not isinstance(case_id, str) or case_id in seen:
            raise ProtocolViolation("14A run plan contains duplicate case IDs")
        seen.add(case_id)
        plan.append(
            {
                "run_order": case_order,
                "case_order": case_order,
                "case_id": case_id,
                "system": CANDIDATE_SYSTEM_LABEL,
                "worker_system": WORKER_SYSTEM,
                "runtime_variant": RUNTIME_VARIANT,
                "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
                "decision_prompt_profile": (
                    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version
                ),
                "decision_prompt_sha256": (
                    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256
                ),
            }
        )
    if len(plan) != 18 or len(seen) != 18:
        raise ProtocolViolation("14A run plan must contain 18 unique Dev cases")
    return plan


def build_end_to_end_worker_job(
    case: Mapping[str, Any],
    *,
    plan_item: Mapping[str, Any],
    candidate_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    if plan_item.get("system") != CANDIDATE_SYSTEM_LABEL:
        raise ProtocolViolation("14A job must use the candidate identity")
    if plan_item.get("worker_system") != WORKER_SYSTEM:
        raise ProtocolViolation("14A worker must use System B")
    if plan_item.get("decision_prompt_profile_selector") != DECISION_PROMPT_PROFILE_SELECTOR:
        raise ProtocolViolation("14A job must select the kind-aware profile")
    return {
        "worker_schema_version": WORKER_SCHEMA_VERSION,
        "system": WORKER_SYSTEM,
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


def validate_end_to_end_identities(
    *,
    candidate_head: str,
    target_head: str,
    corpus_head: str,
    protocol_sha: str,
    dev_sha: str,
    prompt_version: str,
    prompt_sha256: str,
    provider: str,
    model: str,
) -> None:
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("14A candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("14A target project SHA mismatch")
    if corpus_head != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("14A corpus SHA mismatch")
    if protocol_sha != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("14A protocol SHA mismatch")
    if dev_sha != "fb756df4ebd688312c695b4a212d9ccf66b59eef92dec648e63d99a83a4343a9":
        raise RunnerPreflightError("14A Dev SHA mismatch")
    if prompt_version != ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version:
        raise RunnerPreflightError("14A prompt profile version mismatch")
    if prompt_sha256 != ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256:
        raise RunnerPreflightError("14A prompt profile SHA mismatch")
    if provider != FROZEN_PROVIDER or model != FROZEN_MODEL:
        raise RunnerPreflightError("14A provider/model drift from frozen DeepSeek")


def _invoke_end_to_end_worker(
    job: Mapping[str, Any], candidate_root: Path, timeout: float
) -> dict[str, Any]:
    """Invoke exactly one worker; an infrastructure failure is not retried."""

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
    if not isinstance(payload, dict) or payload.get("worker_schema_version") != WORKER_SCHEMA_VERSION:
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_output_invalid",
        }
    return payload


def _safe_raw_record(
    case: Mapping[str, Any], plan_item: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    result = payload.get("result")
    result = result if isinstance(result, Mapping) else {}
    requirement = payload.get("requirement_state")
    requirement = requirement if isinstance(requirement, Mapping) else {}
    evidence = result.get("evidence")
    evidence = evidence if isinstance(evidence, list) else []
    activity = payload.get("activity")
    activity = activity if isinstance(activity, list) else []
    record = {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": CANDIDATE_SYSTEM_LABEL,
        "worker_system": WORKER_SYSTEM,
        "runtime_variant": RUNTIME_VARIANT,
        "candidate_runtime_commit": CANDIDATE_RUNTIME_COMMIT,
        "run_order": plan_item["run_order"],
        "run_validity": payload.get("execution_validity", "INVALID"),
        "infrastructure_code": payload.get("infrastructure_code"),
        "missing_evidence_groups": requirement.get("missing_evidence_groups", []),
        "final": {
            "status": result.get("status"),
            "reason_code": result.get("reason_code"),
            "failure_code": result.get("failure_code"),
            "evidence_kinds": sorted(
                {
                    item.get("kind")
                    for item in evidence
                    if isinstance(item, Mapping) and isinstance(item.get("kind"), str)
                }
            ),
        },
        "activity": activity[:64],
        "tool_sequence": payload.get("tool_sequence", []),
        "tool_calls": result.get("tool_calls_used", 0),
        "iterations": result.get("iterations_used", 0),
    }
    sanitized = safe_artifact(record)
    if not isinstance(sanitized, dict):  # pragma: no cover
        raise RunnerPreflightError("14A raw record is not a safe mapping")
    return sanitized


def _descriptive_counts(raw_runs: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(
        {
            "code_search_calls": 0,
            "code_search_with_project_code": 0,
            "code_search_with_project_doc": 0,
            "code_search_with_any": 0,
            "code_search_without_artifact_kind": 0,
            "project_code_evidence_cases": 0,
            "project_doc_evidence_cases": 0,
            "project_test_evidence_cases": 0,
            "project_change_evidence_cases": 0,
            "completed_cases": 0,
            "refused_cases": 0,
            "failed_cases": 0,
            "invalid_cases": 0,
        }
    )
    for run in raw_runs:
        for event in run.get("activity", []):
            if not isinstance(event, Mapping):
                continue
            if event.get("tool_name") != "code_search" or event.get("state") != "started":
                continue
            counts["code_search_calls"] += 1
            target = event.get("target")
            kind = target.get("artifact_kind") if isinstance(target, Mapping) else None
            if kind in ARTIFACT_KIND_VALUES:
                counts[f"code_search_with_{kind}"] += 1
            else:
                counts["code_search_without_artifact_kind"] += 1

        evidence_kinds = set((run.get("final") or {}).get("evidence_kinds", []))
        for kind, field in (
            ("project_code", "project_code_evidence_cases"),
            ("project_doc", "project_doc_evidence_cases"),
            ("project_test", "project_test_evidence_cases"),
            ("project_change", "project_change_evidence_cases"),
        ):
            if kind in evidence_kinds:
                counts[field] += 1
        if run.get("run_validity") != "VALID":
            counts["invalid_cases"] += 1
        elif (run.get("final") or {}).get("status") == "completed":
            counts["completed_cases"] += 1
        elif (run.get("final") or {}).get("status") == "refused":
            counts["refused_cases"] += 1
        else:
            counts["failed_cases"] += 1
    return dict(counts)


def build_end_to_end_summary(
    raw_runs: list[Mapping[str, Any]], scores: list[Mapping[str, Any]]
) -> dict[str, Any]:
    families = sorted({run["task_family"] for run in raw_runs})
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "scope": "Integration Dev only / kind-aware Unified candidate / automatic metrics only",
        "run_counts": {
            "expected": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "observed": len(raw_runs),
            "valid": sum(run.get("run_validity") == "VALID" for run in raw_runs),
            "invalid": sum(run.get("run_validity") != "VALID" for run in raw_runs),
        },
        "descriptive_counts": _descriptive_counts(raw_runs),
        "descriptive_counts_by_task_family": {
            family: _descriptive_counts(
                [run for run in raw_runs if run.get("task_family") == family]
            )
            for family in families
        },
        "automatic_metrics": aggregate_metrics(scores),
        "manual_scoring": "NOT_DONE",
        "system_a": "NOT_RUN",
        "holdout": "NOT_RUN / DENY",
    }


def _candidate_manifest(
    protocol: Mapping[str, Any],
    config: EndToEndCandidateRunConfig,
    plan: list[Mapping[str, Any]],
    raw_runs: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-integration-14a-dev-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "COMPLETE" if len(raw_runs) == EXPECTED_CASE_COUNTS[DEV_SPLIT] else "INVALID",
        "execution_scope": "Integration Dev only / one attempt per frozen case",
        "split": DEV_SPLIT,
        "provider": {"name": config.provider, "model": config.model},
        "candidate_runtime": {
            "source_commit": CANDIDATE_RUNTIME_COMMIT,
            "system_identity": CANDIDATE_SYSTEM_LABEL,
            "worker_system": WORKER_SYSTEM,
            "runtime_variant": RUNTIME_VARIANT,
            "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
            "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
            "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
        },
        "target_project": {
            "repository": TARGET_REPOSITORY,
            "project_id": TARGET_PROJECT_ID,
            "source_sha": TARGET_PROJECT_COMMIT,
        },
        "corpus_identity": {
            "repository": CORPUS_REPOSITORY,
            "source_commit": CORPUS_SOURCE_COMMIT,
        },
        "protocol": {
            "version": protocol["protocol_version"],
            "sha256": protocol["protocol_sha256"],
        },
        "dataset": {
            "split": DEV_SPLIT,
            "case_count": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "sha256": protocol["datasets"][DEV_SPLIT]["sha256"],
        },
        "case_ids": [item["case_id"] for item in plan],
        "expected_runs": EXPECTED_CASE_COUNTS[DEV_SPLIT],
        "observed_runs": len(raw_runs),
        "valid_runs": sum(run.get("run_validity") == "VALID" for run in raw_runs),
        "invalid_runs": sum(run.get("run_validity") != "VALID" for run in raw_runs),
        "retry_policy": "NO_RETRY",
        "system_a": "NOT_RUN",
        "holdout": "NOT_RUN / DENY",
        "manual_scoring": "NOT_DONE",
        "artifact_files": [
            "run_manifest.json",
            "raw_runs.jsonl",
            "automatic_scores.jsonl",
            "summary.json",
        ],
        "protected_result_directories": [
            str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            for path in PROTECTED_RESULT_DIRS
        ],
    }


def _preflight(
    config: EndToEndCandidateRunConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert_dev_only(config.split)
    _assert_independent_output(config.output_dir)
    if config.provider != FROZEN_PROVIDER or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("14A provider/model drift from frozen DeepSeek")
    protocol = validate_protocol_manifest(MANIFEST_PATH)
    if protocol["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("14A protocol SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError(f"missing_environment: {config.api_key_env}")
    cases = load_cases(DEV_DATASET_PATH)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise RunnerPreflightError("14A Dev case count mismatch")
    return protocol, cases


@contextmanager
def _isolated_checkouts(repo_root: Path) -> Iterator[dict[str, Path]]:
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".arch_integration_14a_", dir=str(repo_root.parent))
    )
    paths = {
        "candidate": temporary_root / "candidate",
        "target": temporary_root / "target",
    }
    revisions = {"candidate": CANDIDATE_RUNTIME_COMMIT, "target": TARGET_PROJECT_COMMIT}
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
                raise RunnerPreflightError("14A isolated checkout creation failed")
            added.append(paths[name])
        _tracked_clean(paths["candidate"], "14A candidate")
        _tracked_clean(paths["target"], "14A target")
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


def run_end_to_end_candidate(
    config: EndToEndCandidateRunConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Run exactly the frozen 18-case Dev plan once, without A or Holdout."""

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=repo_root / ".env", override=False)
    protocol, cases = _preflight(config)
    plan = build_end_to_end_run_plan(cases, config.split)
    case_by_id = {case["case_id"]: case for case in cases}
    corpus = config.corpus_checkout.resolve()
    raw_runs: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []

    with _isolated_checkouts(repo_root) as checkouts:
        validate_end_to_end_identities(
            candidate_head=_git_head(checkouts["candidate"]),
            target_head=_git_head(checkouts["target"]),
            corpus_head=_git_head(corpus),
            protocol_sha=protocol["protocol_sha256"],
            dev_sha=protocol["datasets"][DEV_SPLIT]["sha256"],
            prompt_version=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
            prompt_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
            provider=config.provider,
            model=config.model,
        )
        corpus_identity = _verify_candidate_corpus(corpus, checkouts["candidate"])
        corpus_root = corpus / protocol["corpus_identity"]["path"]
        for item in plan:
            case = case_by_id[item["case_id"]]
            job = build_end_to_end_worker_job(
                case,
                plan_item=item,
                candidate_root=checkouts["candidate"],
                target_root=checkouts["target"],
                corpus_root=corpus_root,
            )
            payload = _invoke_end_to_end_worker(
                job, checkouts["candidate"], config.worker_timeout_seconds
            )
            if payload.get("execution_validity") == "VALID" and payload.get(
                "infrastructure_code"
            ):
                payload = dict(payload)
                payload["execution_validity"] = "INVALID"
            raw_runs.append(_safe_raw_record(case, item, payload))
            scores.append(
                {
                    "case_id": case["case_id"],
                    "task_family": case["task_family"],
                    "system": CANDIDATE_SYSTEM_LABEL,
                    "run_order": item["run_order"],
                    "run_validity": payload.get("execution_validity", "INVALID"),
                    "automatic_metrics": (
                        _automatic_score(case, WORKER_SYSTEM, payload)
                        if payload.get("execution_validity") == "VALID"
                        else {}
                    ),
                }
            )

    output = config.output_dir
    _write_json(
        output / "run_manifest.json",
        {**_candidate_manifest(protocol, config, plan, raw_runs), "corpus_identity": {
            "repository": CORPUS_REPOSITORY,
            "source_commit": CORPUS_SOURCE_COMMIT,
            **corpus_identity,
        }},
    )
    _write_jsonl(output / "raw_runs.jsonl", raw_runs)
    _write_jsonl(output / "automatic_scores.jsonl", scores)
    _write_json(output / "summary.json", build_end_to_end_summary(raw_runs, scores))
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the ARCH-INTEGRATION-14A full Dev candidate evaluation"
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    try:
        output = run_end_to_end_candidate(
            EndToEndCandidateRunConfig(
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
