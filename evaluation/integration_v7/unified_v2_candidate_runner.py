"""Independent ARCH-INTEGRATION-11B Dev harness for Unified-v2 candidate.

This module prepares and, only when explicitly invoked with the frozen
provider credentials, executes one isolated 18-case Integration Dev run for
the Unified-v2 grounding/recovery candidate.  It never runs System A or
Holdout, and it never writes any earlier Dev or candidate result directory.
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

from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE
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
from evaluation.integration_v7.candidate_runner import _verify_candidate_corpus
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROVIDER,
    FROZEN_PROTOCOL_SHA,
    REPO_ROOT,
    WORKER_PATH,
    WORKER_SCHEMA_VERSION,
    _automatic_score,
    _git_head,
    _raw_record,
    _tracked_clean,
    _write_json,
    _write_jsonl,
    aggregate_metrics,
    safe_artifact,
    RunnerPreflightError,
)


CANDIDATE_RUNNER_SCHEMA_VERSION = "integration_v7_unified_v2_candidate_dev_runner_v1"
CANDIDATE_RUNTIME_COMMIT = "d0013abd9f0cbdf50b72b330f18b5a94ca368815"
CANDIDATE_RUNTIME_LABEL = "unified_v2_grounding_recovery_candidate"
CANDIDATE_SYSTEM_LABEL = "B_triple_prime"
DECISION_PROMPT_PROFILE_SELECTOR = "engineering_agent_decision_prompt_unified_v2"
LEGACY_DEV_RESULTS_DIR = REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1"
PREVIOUS_CANDIDATE_RESULTS_DIRS = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_e374_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_0abdb_v1",
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_d001_v1"
)


@dataclass(frozen=True)
class UnifiedV2CandidateRunConfig:
    corpus_checkout: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_unified_v2_candidate_scope(split: str) -> None:
    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-INTEGRATION-11B is Dev-only; Holdout execution is denied"
        )


def _assert_independent_output(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    protected = (LEGACY_DEV_RESULTS_DIR.resolve(),) + tuple(
        path.resolve() for path in PREVIOUS_CANDIDATE_RESULTS_DIRS
    )
    if any(
        resolved == protected_path or protected_path in resolved.parents
        for protected_path in protected
    ):
        raise RunnerPreflightError(
            "11B output must not overwrite dev_v1 or earlier candidate results"
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise RunnerPreflightError("11B candidate output is not empty; rerun denied")


def validate_unified_v2_candidate_checkouts(
    candidate_root: Path,
    target_root: Path,
    *,
    candidate_head: str,
    target_head: str,
) -> None:
    if candidate_root.resolve() == target_root.resolve():
        raise RunnerPreflightError("11B candidate and target checkouts must be separate")
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("11B candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("11B target project SHA mismatch")


def validate_unified_v2_candidate_identities(
    *,
    candidate_head: str,
    target_head: str,
    corpus_head: str,
    protocol_sha: str,
    prompt_profile_version: str,
    prompt_profile_sha256: str,
) -> None:
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("11B candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("11B target project SHA mismatch")
    if corpus_head != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("11B knowledge corpus SHA mismatch")
    if protocol_sha != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("11B protocol SHA mismatch")
    if prompt_profile_version != ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version:
        raise RunnerPreflightError("11B decision prompt profile version mismatch")
    if prompt_profile_sha256 != ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256:
        raise RunnerPreflightError("11B decision prompt profile SHA mismatch")


def build_unified_v2_candidate_run_plan(
    cases: list[Mapping[str, Any]], split: str = DEV_SPLIT
) -> list[dict[str, Any]]:
    """Build exactly one Unified-v2 candidate run for every Dev case."""

    assert_unified_v2_candidate_scope(split)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise ProtocolViolation("ARCH-INTEGRATION-11B requires exactly 18 Dev cases")
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case_order, case in enumerate(cases, 1):
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("11B run plan contains a non-Dev case")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen:
            raise ProtocolViolation("11B run plan contains duplicate case IDs")
        seen.add(case_id)
        plan.append(
            {
                "run_order": case_order,
                "case_order": case_order,
                "case_id": case_id,
                "system": CANDIDATE_SYSTEM_LABEL,
                "worker_system": "B",
                "runtime_variant": CANDIDATE_RUNTIME_LABEL,
                "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
                "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version,
                "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256,
            }
        )
    if len(plan) != EXPECTED_CASE_COUNTS[DEV_SPLIT] or len(seen) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise ProtocolViolation("11B run plan must contain 18 unique Dev cases")
    return plan


def build_unified_v2_candidate_worker_job(
    case: Mapping[str, Any],
    *,
    plan_item: Mapping[str, Any],
    candidate_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    if plan_item.get("system") != CANDIDATE_SYSTEM_LABEL:
        raise ProtocolViolation("11B worker job must use B_triple_prime identity")
    if plan_item.get("worker_system") != "B":
        raise ProtocolViolation("11B worker must use the Unified B execution path")
    if plan_item.get("decision_prompt_profile_selector") != DECISION_PROMPT_PROFILE_SELECTOR:
        raise ProtocolViolation("11B worker must explicitly select Unified-v2")
    if plan_item.get("decision_prompt_profile") != ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version:
        raise ProtocolViolation("11B worker profile version mismatch")
    return {
        "worker_schema_version": WORKER_SCHEMA_VERSION,
        "system": "B",
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


def _candidate_metadata() -> dict[str, Any]:
    return {
        "candidate_runtime_commit": CANDIDATE_RUNTIME_COMMIT,
        "runtime_variant": CANDIDATE_RUNTIME_LABEL,
        "system_identity": CANDIDATE_SYSTEM_LABEL,
        "target_project_commit": TARGET_PROJECT_COMMIT,
        "corpus_source_commit": CORPUS_SOURCE_COMMIT,
        "protocol_sha256": FROZEN_PROTOCOL_SHA,
        "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
        "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version,
        "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256,
    }


def _candidate_raw_record(
    case: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _raw_record(case, plan_item, payload)
    raw.update(_candidate_metadata())
    return raw


def _candidate_score_record(
    case: Mapping[str, Any],
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    score: dict[str, Any] = {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": CANDIDATE_SYSTEM_LABEL,
        "run_order": raw["run_order"],
        "run_validity": raw["run_validity"],
        "automatic_metrics": {},
        **_candidate_metadata(),
    }
    if raw["run_validity"] == "VALID":
        score["automatic_metrics"] = _automatic_score(case, "B", payload)
    return score


def build_unified_v2_candidate_summary(
    raw_runs: list[Mapping[str, Any]], scores: list[Mapping[str, Any]]
) -> dict[str, Any]:
    families = sorted({run["task_family"] for run in raw_runs})
    valid = [score for score in scores if score.get("run_validity") == "VALID"]
    return {
        "schema_version": CANDIDATE_RUNNER_SCHEMA_VERSION,
        "execution_scope": "Integration Dev only / Unified-v2 candidate B_triple_prime / automatic metrics only",
        "candidate_identity": _candidate_metadata(),
        "run_counts": {
            "expected_candidate_runs": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "observed_candidate_runs": len(raw_runs),
            "valid_candidate_runs": len(valid),
            "infrastructure_invalid_candidate_runs": len(raw_runs) - len(valid),
        },
        "overall": aggregate_metrics(scores),
        "by_task_family": {
            family: aggregate_metrics(
                score for score in scores if score.get("task_family") == family
            )
            for family in families
        },
        "manual_scoring": "NOT_DONE",
        "holdout": "NOT_RUN / DENY",
    }


def _invoke_unified_v2_candidate_worker(
    job: Mapping[str, Any], candidate_root: Path, timeout: float
) -> dict[str, Any]:
    """Invoke the current selector-aware harness worker with candidate imports first."""

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(candidate_root)
    try:
        completed = subprocess.run(
            [sys.executable, str(WORKER_PATH)],
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


def _preflight(
    config: UnifiedV2CandidateRunConfig, repo_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert_unified_v2_candidate_scope(config.split)
    _assert_independent_output(config.output_dir)
    if config.provider != FROZEN_PROVIDER or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("11B provider/model drift from frozen DeepSeek contract")
    manifest = validate_protocol_manifest(MANIFEST_PATH)
    if manifest["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("11B protocol SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError(f"missing_environment: {config.api_key_env}")
    cases = load_cases(DEV_DATASET_PATH)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise RunnerPreflightError("11B Dev case count mismatch")
    return manifest, cases


@contextmanager
def _isolated_unified_v2_candidate_checkouts(
    repo_root: Path,
) -> Iterator[dict[str, Path]]:
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".arch_eval_11b_candidate_", dir=str(repo_root.parent))
    )
    paths = {
        "candidate": temporary_root / "runtime_candidate",
        "target": temporary_root / "target_project",
    }
    revisions = {"candidate": CANDIDATE_RUNTIME_COMMIT, "target": TARGET_PROJECT_COMMIT}
    added: list[Path] = []
    try:
        for name, revision in revisions.items():
            completed = subprocess.run(
                ["git", "worktree", "add", "--detach", str(paths[name]), revision],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode != 0:
                raise RunnerPreflightError("11B isolated checkout creation failed")
            added.append(paths[name])
        validate_unified_v2_candidate_checkouts(
            paths["candidate"],
            paths["target"],
            candidate_head=_git_head(paths["candidate"]),
            target_head=_git_head(paths["target"]),
        )
        _tracked_clean(paths["candidate"], "11B candidate")
        _tracked_clean(paths["target"], "11B target")
        yield paths
    finally:
        for path in reversed(added):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        shutil.rmtree(temporary_root, ignore_errors=True)


def build_unified_v2_candidate_manifest(
    *,
    manifest: Mapping[str, Any],
    config: UnifiedV2CandidateRunConfig,
    plan: list[Mapping[str, Any]],
    raw_runs: list[Mapping[str, Any]],
    corpus_identity: Mapping[str, Any],
    timestamp: str = "",
) -> dict[str, Any]:
    run_timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": CANDIDATE_RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-integration-11b-dev-candidate-d001-{run_timestamp}",
        "status": "COMPLETE" if len(raw_runs) == EXPECTED_CASE_COUNTS[DEV_SPLIT] else "INVALID",
        "execution_scope": "Integration Dev only / Unified-v2 candidate B_triple_prime",
        "split": DEV_SPLIT,
        "provider": {"name": config.provider, "model": config.model},
        "candidate_runtime": {
            "label": CANDIDATE_RUNTIME_LABEL,
            "system_identity": CANDIDATE_SYSTEM_LABEL,
            "source_commit": CANDIDATE_RUNTIME_COMMIT,
            "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
            "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version,
            "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256,
            "worker_system_path": "B unified runtime execution path",
        },
        "frozen_system_identity_preserved": {
            "system_a_08b": "not executed",
            "system_b_08b": "not executed as frozen B; candidate only",
            "candidate_b_double_prime_10b": "not executed or overwritten",
            "candidate_b_prime_09b": "not executed or overwritten",
        },
        "target_project": {
            "repository": "wgqa/my_agent",
            "project_id": TARGET_PROJECT_ID,
            "source_sha": TARGET_PROJECT_COMMIT,
        },
        "corpus_identity": {
            "repository": "wgqa/agent_data",
            "source_commit": CORPUS_SOURCE_COMMIT,
            **dict(corpus_identity),
        },
        "protocol": {
            "version": manifest["protocol_version"],
            "sha256": manifest["protocol_sha256"],
        },
        "dataset": {
            "split": DEV_SPLIT,
            "case_count": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "sha256": manifest["datasets"][DEV_SPLIT]["sha256"],
        },
        "run_plan": [dict(item) for item in plan],
        "expected_candidate_runs": EXPECTED_CASE_COUNTS[DEV_SPLIT],
        "observed_candidate_runs": len(raw_runs),
        "infrastructure_invalid_count": sum(
            run.get("run_validity") != "VALID" for run in raw_runs
        ),
        "automatic_metrics_only": True,
        "manual_scoring": "NOT_DONE",
        "holdout": "NOT_RUN / DENY",
        "protected_result_directories": [
            "evaluation/integration_v7/results/dev_v1",
            "evaluation/integration_v7/results/dev_candidate_e374_v1",
            "evaluation/integration_v7/results/dev_candidate_0abdb_v1",
        ],
        "artifact_files": [
            "run_manifest.json",
            "raw_runs.jsonl",
            "automatic_scores.jsonl",
            "summary.json",
        ],
    }


def run_unified_v2_candidate_dev(
    config: UnifiedV2CandidateRunConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Execute exactly one 18-case Unified-v2 Dev plan, with no retries."""

    manifest, cases = _preflight(config, repo_root)
    plan = build_unified_v2_candidate_run_plan(cases, config.split)
    corpus = config.corpus_checkout.resolve()
    raw_runs: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    case_by_id = {case["case_id"]: case for case in cases}

    with _isolated_unified_v2_candidate_checkouts(repo_root) as checkouts:
        validate_unified_v2_candidate_identities(
            candidate_head=_git_head(checkouts["candidate"]),
            target_head=_git_head(checkouts["target"]),
            corpus_head=_git_head(corpus),
            protocol_sha=manifest["protocol_sha256"],
            prompt_profile_version=ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.version,
            prompt_profile_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_V2_PROFILE.sha256,
        )
        corpus_identity = _verify_candidate_corpus(corpus, checkouts["candidate"])
        knowledge_root = corpus / manifest["corpus_identity"]["path"]
        for item in plan:
            case = case_by_id[item["case_id"]]
            job = build_unified_v2_candidate_worker_job(
                case,
                plan_item=item,
                candidate_root=checkouts["candidate"],
                target_root=checkouts["target"],
                corpus_root=knowledge_root,
            )
            # One provider invocation per case.  Invalid outcomes are recorded
            # and never retried to manufacture the expected run count.
            payload = _invoke_unified_v2_candidate_worker(
                job,
                checkouts["candidate"],
                config.worker_timeout_seconds,
            )
            if payload.get("execution_validity") == "VALID" and payload.get(
                "infrastructure_code"
            ):
                payload = dict(payload)
                payload["execution_validity"] = "INVALID"
            raw = _candidate_raw_record(case, item, payload)
            scores.append(_candidate_score_record(case, raw, payload))
            raw_runs.append(raw)

    run_manifest = build_unified_v2_candidate_manifest(
        manifest=manifest,
        config=config,
        plan=plan,
        raw_runs=raw_runs,
        corpus_identity=corpus_identity,
    )
    output = config.output_dir
    _write_json(output / "run_manifest.json", run_manifest)
    _write_jsonl(output / "raw_runs.jsonl", raw_runs)
    _write_jsonl(output / "automatic_scores.jsonl", scores)
    _write_json(output / "summary.json", build_unified_v2_candidate_summary(raw_runs, scores))
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run independent ARCH-INTEGRATION-11B Unified-v2 candidate Dev"
    )
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    try:
        output = run_unified_v2_candidate_dev(
            UnifiedV2CandidateRunConfig(
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
