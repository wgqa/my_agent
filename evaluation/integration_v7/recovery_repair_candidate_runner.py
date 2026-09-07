"""Dev-only runner for the 16A recovery-repair candidate observation.

This module is deliberately distinct from the historical 10B-era
``recovery_candidate_runner`` (schema
``integration_v7_recovery_candidate_dev_runner_v1``): that historical harness
keeps its own frozen candidate identity and is not an execution path here.

The current checkout supplies the evaluation worker, the semantic-artifact
contract, and the repair-observability projection.  The isolated candidate
checkout at the 16A commit supplies Product ``core`` imports.  This is a new
Product-candidate evaluation run: it is not a 15B rerun and not a repair of
historical artifacts, and it never loads 15B results as execution input.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from core.tool_agent.decision_prompt import (
    ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE,
    ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256,
    ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION,
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
from evaluation.integration_v7.end_to_end_candidate_runner import (
    DECISION_PROMPT_PROFILE_SELECTOR,
    WORKER_SYSTEM,
    _descriptive_counts,
    _safe_raw_record,
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
from evaluation.integration_v7.semantic_evaluation_artifact import (
    SEMANTIC_EVALUATION_ARTIFACT_VERSION,
    project_semantic_evaluation_artifact,
)


RUNNER_SCHEMA_VERSION = "integration_v7_recovery_candidate_runner_v1"
CANDIDATE_RUNTIME_COMMIT = "09c92746cea2699cb544e999c2b6feda88e43969"
CANDIDATE_SYSTEM_LABEL = "B_kind_aware_recovery_repair_candidate"
RUNTIME_VARIANT = "unified_kind_aware_recovery_repair_candidate"
RECOVERY_REPAIR_PROMPT_VERSION = ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION
FROZEN_RECOVERY_REPAIR_PROMPT_SHA256 = (
    "b4890280e4ec8fa76e31865698c24b751356350c20b1d32f05cd9720124e1013"
)
EXPECTED_DEV_DATASET_SHA = "fb756df4ebd688312c695b4a212d9ccf66b59eef92dec648e63d99a83a4343a9"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_semantic_16b_09c9274_v1"
)
PROTECTED_RESULT_DIRS = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_e374_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_0abdb_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_d001_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_6cd1_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_diag_12d_1a26428_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_verify_13b_6d7e58f_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_6d7e58f_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_semantic_15b_6d7e58f_v1",
)
ARTIFACT_FILES = (
    "run_manifest.json",
    "diagnostic_runs.jsonl",
    "semantic_runs.jsonl",
    "automatic_scores.jsonl",
    "summary.json",
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_REPAIR_PARSE_CATEGORIES = frozenset(
    {
        "EMPTY_OUTPUT",
        "OUTPUT_TRUNCATED",
        "INVALID_JSON",
        "DUPLICATE_KEY",
        "ACTION_SCHEMA_INVALID",
        "UNKNOWN_TOOL",
        "ARGUMENTS_SCHEMA_INVALID",
    }
)
_IDENTITY_FIELD_OVERRIDES = (
    ("system", CANDIDATE_SYSTEM_LABEL),
    ("worker_system", WORKER_SYSTEM),
    ("runtime_variant", RUNTIME_VARIANT),
    ("candidate_runtime_commit", CANDIDATE_RUNTIME_COMMIT),
)


@dataclass(frozen=True)
class RecoveryRepairCandidateRunConfig:
    """Explicit inputs for exactly one 16B Dev observation run."""

    corpus_checkout: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_dev_only(split: str) -> None:
    """Deny Holdout and all non-Dev scopes before any worker launch."""

    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-INTEGRATION-16B is Dev-only; Holdout execution is denied"
        )


def _assert_independent_output(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    if any(
        resolved == protected.resolve() or protected.resolve() in resolved.parents
        for protected in PROTECTED_RESULT_DIRS
    ):
        raise RunnerPreflightError("16B output must not overwrite a historical result")
    if resolved.exists() and any(resolved.iterdir()):
        raise RunnerPreflightError("16B output is not empty; rerun denied")


def build_recovery_run_plan(
    cases: list[Mapping[str, Any]], split: str = DEV_SPLIT
) -> list[dict[str, Any]]:
    """Build one System-B candidate invocation for every frozen Dev case."""

    assert_dev_only(split)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise ProtocolViolation("16B requires exactly 18 Dev cases")
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case_order, case in enumerate(cases, 1):
        case_id = case.get("case_id")
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("16B run plan contains a non-Dev case")
        if not isinstance(case_id, str) or case_id in seen:
            raise ProtocolViolation("16B run plan contains duplicate case IDs")
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
        raise ProtocolViolation("16B run plan must contain 18 unique Dev cases")
    return plan


def build_recovery_worker_job(
    case: Mapping[str, Any],
    *,
    plan_item: Mapping[str, Any],
    candidate_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    """Bind the current harness worker to candidate Product imports only."""

    if plan_item.get("system") != CANDIDATE_SYSTEM_LABEL:
        raise ProtocolViolation("16B job must use the fixed candidate identity")
    if plan_item.get("worker_system") != WORKER_SYSTEM:
        raise ProtocolViolation("16B worker must use System B")
    if plan_item.get("decision_prompt_profile_selector") != DECISION_PROMPT_PROFILE_SELECTOR:
        raise ProtocolViolation("16B job must select the kind-aware prompt profile")
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


def validate_recovery_identities(
    *,
    candidate_head: str,
    target_head: str,
    corpus_head: str,
    protocol_sha: str,
    dev_sha: str,
    prompt_version: str,
    prompt_sha256: str,
    recovery_repair_prompt_version: str,
    recovery_repair_prompt_sha256: str,
    provider: str,
    model: str,
    harness_head: str,
) -> None:
    """Fail closed on every frozen identity except the new harness commit."""

    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("16B candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("16B target project SHA mismatch")
    if corpus_head != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("16B corpus SHA mismatch")
    if protocol_sha != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("16B protocol SHA mismatch")
    if dev_sha != EXPECTED_DEV_DATASET_SHA:
        raise RunnerPreflightError("16B Dev dataset SHA mismatch")
    if prompt_version != ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version:
        raise RunnerPreflightError("16B prompt profile version mismatch")
    if prompt_sha256 != ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256:
        raise RunnerPreflightError("16B prompt profile SHA mismatch")
    if recovery_repair_prompt_version != RECOVERY_REPAIR_PROMPT_VERSION:
        raise RunnerPreflightError("16B recovery repair prompt version mismatch")
    if recovery_repair_prompt_sha256 != FROZEN_RECOVERY_REPAIR_PROMPT_SHA256:
        raise RunnerPreflightError("16B recovery repair prompt SHA mismatch")
    if provider != FROZEN_PROVIDER or model != FROZEN_MODEL:
        raise RunnerPreflightError("16B provider/model drift from frozen DeepSeek")
    if type(harness_head) is not str or _SHA40_RE.fullmatch(harness_head) is None:
        raise RunnerPreflightError("16B evaluation harness SHA is invalid")


def validate_checkout_separation(
    candidate_root: Path,
    target_root: Path,
    *,
    candidate_head: str,
    target_head: str,
) -> None:
    if candidate_root.resolve() == target_root.resolve():
        raise RunnerPreflightError("candidate and target checkouts must be separate")
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("target project SHA mismatch")


def project_decision_repair_observability(
    trace: Sequence[Any] | None, *, run_validity: str
) -> dict[str, Any]:
    """Project bounded decision-repair facts from the worker's safe trace.

    INVALID runs keep only a not-applicable marker: a worker_process_failure is
    never reported as "zero recovery repairs".  VALID runs fail closed on any
    missing or malformed decision-repair fact instead of silently writing 0.
    """

    if run_validity != "VALID":
        return {"availability": "NOT_APPLICABLE_INVALID_RUN"}
    if not isinstance(trace, list):
        raise RunnerPreflightError("VALID payload lacks a safe worker trace")
    decision_count = 0
    provider_calls_total = 0
    recovery_attempts = 0
    recovery_successes = 0
    parse_attempts = 0
    parse_successes = 0
    recovery_attempt_iterations: list[int] = []
    recovery_success_iterations: list[int] = []
    for event in trace:
        if not isinstance(event, Mapping):
            raise RunnerPreflightError("VALID worker trace contains a non-mapping event")
        if event.get("event_type") != "decision_completed":
            continue
        decision_count += 1
        iteration = event.get("iteration")
        if type(iteration) is not int or isinstance(iteration, bool) or iteration < 1:
            raise RunnerPreflightError("decision event lacks a safe iteration")
        call_count = event.get("provider_call_count")
        if type(call_count) is not int or call_count not in (1, 2):
            raise RunnerPreflightError(
                "decision event lacks a safe provider_call_count (1 or 2)"
            )
        attempted = event.get("repair_attempted")
        succeeded = event.get("repair_succeeded")
        if type(attempted) is not bool or type(succeeded) is not bool:
            raise RunnerPreflightError(
                "decision event lacks strict bool repair metadata"
            )
        if succeeded and not attempted:
            raise RunnerPreflightError(
                "repair_succeeded=True requires repair_attempted=True"
            )
        if attempted and call_count != 2:
            raise RunnerPreflightError(
                "repair_attempted=True requires provider_call_count=2"
            )
        category = event.get("parse_failure_category")
        if category is not None and (
            type(category) is not str or category not in _REPAIR_PARSE_CATEGORIES
        ):
            raise RunnerPreflightError("parse_failure_category is not a safe parse enum")
        provider_calls_total += call_count
        if not attempted:
            continue
        if category is not None:
            parse_attempts += 1
            if succeeded:
                parse_successes += 1
        else:
            recovery_attempts += 1
            recovery_attempt_iterations.append(iteration)
            if succeeded:
                recovery_successes += 1
                recovery_success_iterations.append(iteration)
    if decision_count == 0:
        raise RunnerPreflightError("VALID payload contains no decision_completed fact")
    return {
        "availability": "AVAILABLE",
        "decision_count": decision_count,
        "provider_calls_total": provider_calls_total,
        "recovery_repair_attempts": recovery_attempts,
        "recovery_repair_successes": recovery_successes,
        "parse_repair_attempts": parse_attempts,
        "parse_repair_successes": parse_successes,
        "recovery_repair_attempt_iterations": recovery_attempt_iterations,
        "recovery_repair_success_iterations": recovery_success_iterations,
    }


def _safe_diagnostic_record(
    case: Mapping[str, Any], plan_item: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Reuse the accepted safe projection, then stamp 16B identity and repair facts.

    The 14A helper freezes its own candidate identity fields, so they are
    re-stamped to the 16B candidate before the repair observability block is
    appended; the final record is re-sanitized as one bounded artifact.
    """

    record = _safe_raw_record(case, plan_item, payload)
    for key, value in _IDENTITY_FIELD_OVERRIDES:
        if key not in record:
            raise RunnerPreflightError("safe diagnostic record lost an identity field")
        record[key] = value
    result = payload.get("result")
    trace = result.get("trace") if isinstance(result, Mapping) else None
    record["decision_repair_observability"] = project_decision_repair_observability(
        trace,
        run_validity=payload.get("execution_validity", "INVALID"),
    )
    sanitized = safe_artifact(record)
    if not isinstance(sanitized, dict):  # pragma: no cover
        raise RunnerPreflightError("16B diagnostic record is not a safe mapping")
    return sanitized


def _semantic_run_record(
    case: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Delegate schema and safety validation to the accepted 15A projector."""

    return project_semantic_evaluation_artifact(
        frozen_case=case,
        worker_payload=payload,
    ).to_dict()


def _automatic_score_record(
    case: Mapping[str, Any], plan_item: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    validity = payload.get("execution_validity", "INVALID")
    return {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": CANDIDATE_SYSTEM_LABEL,
        "run_order": plan_item["run_order"],
        "run_validity": validity,
        "automatic_metrics": (
            _automatic_score(case, WORKER_SYSTEM, payload) if validity == "VALID" else {}
        ),
    }


def _aggregate_repair_observability(
    diagnostic_runs: list[Mapping[str, Any]]
) -> dict[str, Any]:
    available = [
        run
        for run in diagnostic_runs
        if isinstance(
            run.get("decision_repair_observability"), Mapping
        )
        and run["decision_repair_observability"].get("availability") == "AVAILABLE"
    ]
    recovery_attempted = 0
    recovery_successful = 0
    parse_attempted = 0
    parse_successful = 0
    provider_calls_total = 0
    cases_with_attempt: list[str] = []
    cases_with_success: list[str] = []
    for run in available:
        observability = run["decision_repair_observability"]
        recovery_attempted += observability["recovery_repair_attempts"]
        recovery_successful += observability["recovery_repair_successes"]
        parse_attempted += observability["parse_repair_attempts"]
        parse_successful += observability["parse_repair_successes"]
        provider_calls_total += observability["provider_calls_total"]
        if observability["recovery_repair_attempts"]:
            cases_with_attempt.append(run["case_id"])
        if observability["recovery_repair_successes"]:
            cases_with_success.append(run["case_id"])
    return {
        "available_valid_cases": len(available),
        "cases_with_recovery_repair_attempt": cases_with_attempt,
        "cases_with_recovery_repair_success": cases_with_success,
        "recovery_repair_attempted_decisions": recovery_attempted,
        "recovery_repair_successful_decisions": recovery_successful,
        "recovery_repair_failed_decisions": recovery_attempted - recovery_successful,
        "parse_repair_attempted_decisions": parse_attempted,
        "parse_repair_successful_decisions": parse_successful,
        "provider_calls_total": provider_calls_total,
    }


def build_recovery_summary(
    diagnostic_runs: list[Mapping[str, Any]],
    semantic_runs: list[Mapping[str, Any]],
    automatic_scores: list[Mapping[str, Any]],
) -> dict[str, Any]:
    terminal_counts = Counter(
        row["final"]["status"]
        for row in semantic_runs
        if row.get("run_validity") == "VALID"
        and isinstance(row.get("final"), Mapping)
        and row["final"].get("status") in {"completed", "refused", "failed"}
    )
    families = sorted({run["task_family"] for run in diagnostic_runs})
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "scope": "Integration Dev only / recovery-repair candidate observation",
        "run_counts": {
            "expected": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "observed": len(diagnostic_runs),
            "valid": sum(run.get("run_validity") == "VALID" for run in diagnostic_runs),
            "invalid": sum(run.get("run_validity") != "VALID" for run in diagnostic_runs),
        },
        "semantic_artifact_counts": {
            "available": sum(
                row.get("semantic_evaluation_availability") == "AVAILABLE"
                for row in semantic_runs
            ),
            "not_applicable_invalid": sum(
                row.get("semantic_evaluation_availability")
                == "NOT_APPLICABLE_INVALID_RUN"
                for row in semantic_runs
            ),
        },
        "terminal_counts": {
            "completed": terminal_counts["completed"],
            "refused": terminal_counts["refused"],
            "failed": terminal_counts["failed"],
        },
        "descriptive_counts": _descriptive_counts(diagnostic_runs),
        "descriptive_counts_by_task_family": {
            family: _descriptive_counts(
                [run for run in diagnostic_runs if run.get("task_family") == family]
            )
            for family in families
        },
        "recovery_repair_observability": _aggregate_repair_observability(
            diagnostic_runs
        ),
        "automatic_metrics": aggregate_metrics(automatic_scores),
        "semantic_scoring": "NOT_DONE",
        "manual_scoring": "NOT_DONE",
        "system_a": "NOT_RUN",
        "holdout": "NOT_RUN / DENY",
    }


def build_recovery_manifest(
    *,
    protocol: Mapping[str, Any],
    config: RecoveryRepairCandidateRunConfig,
    plan: list[Mapping[str, Any]],
    diagnostic_runs: list[Mapping[str, Any]],
    harness_head: str,
    corpus_identity: Mapping[str, Any],
    timestamp: str = "",
) -> dict[str, Any]:
    """Record candidate, main prompt, repair mechanism, and harness identities."""

    run_timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    valid_runs = sum(run.get("run_validity") == "VALID" for run in diagnostic_runs)
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-integration-16b-dev-recovery-repair-{run_timestamp}",
        "status": (
            "COMPLETE"
            if len(diagnostic_runs) == EXPECTED_CASE_COUNTS[DEV_SPLIT]
            else "INVALID"
        ),
        "execution_scope": "Integration Dev only / one attempt per frozen case",
        "split": DEV_SPLIT,
        "provider": {"name": config.provider, "model": config.model},
        "candidate_runtime": {
            "source_commit": CANDIDATE_RUNTIME_COMMIT,
            "system_identity": CANDIDATE_SYSTEM_LABEL,
            "worker_system": WORKER_SYSTEM,
            "runtime_variant": RUNTIME_VARIANT,
            "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
            "decision_prompt_profile": (
                ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version
            ),
            "decision_prompt_sha256": (
                ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256
            ),
            "recovery_action_repair": {
                "enabled": True,
                "prompt_version": RECOVERY_REPAIR_PROMPT_VERSION,
                "prompt_sha256": FROZEN_RECOVERY_REPAIR_PROMPT_SHA256,
            },
        },
        "evaluation_harness": {
            "source_commit": harness_head,
            "runner_schema_version": RUNNER_SCHEMA_VERSION,
            "semantic_artifact_schema_version": SEMANTIC_EVALUATION_ARTIFACT_VERSION,
            "worker_schema_version": WORKER_SCHEMA_VERSION,
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
            "case_count": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "sha256": protocol["datasets"][DEV_SPLIT]["sha256"],
        },
        "case_ids": [item["case_id"] for item in plan],
        "expected_runs": EXPECTED_CASE_COUNTS[DEV_SPLIT],
        "observed_runs": len(diagnostic_runs),
        "valid_runs": valid_runs,
        "invalid_runs": len(diagnostic_runs) - valid_runs,
        "retry_policy": "NO_RETRY",
        "semantic_scoring": "NOT_DONE",
        "manual_scoring": "NOT_DONE",
        "system_a": "NOT_RUN",
        "holdout": "NOT_RUN / DENY",
        "relationship_to_15b": (
            "NEW_PRODUCT_CANDIDATE_EVALUATION_RUN_NOT_15B_RERUN_NOT_HISTORICAL_REPAIR"
        ),
        "artifact_files": list(ARTIFACT_FILES),
        "protected_result_directories": [
            str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            for path in PROTECTED_RESULT_DIRS
        ],
    }


def _preflight(
    config: RecoveryRepairCandidateRunConfig, repo_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    assert_dev_only(config.split)
    _assert_independent_output(config.output_dir)
    _tracked_clean(repo_root, "16B evaluation harness")
    harness_head = _git_head(repo_root)
    if config.provider != FROZEN_PROVIDER or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("16B provider/model drift from frozen DeepSeek")
    protocol = validate_protocol_manifest(MANIFEST_PATH)
    if protocol["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("16B protocol SHA mismatch")
    if protocol["datasets"][DEV_SPLIT]["sha256"] != EXPECTED_DEV_DATASET_SHA:
        raise RunnerPreflightError("16B Dev dataset SHA mismatch")
    if ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256 != FROZEN_RECOVERY_REPAIR_PROMPT_SHA256:
        raise RunnerPreflightError("16B recovery repair prompt SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError(f"missing_environment: {config.api_key_env}")
    cases = load_cases(DEV_DATASET_PATH)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise RunnerPreflightError("16B Dev case count mismatch")
    return protocol, cases, harness_head


@contextmanager
def _isolated_checkouts(repo_root: Path) -> Iterator[dict[str, Path]]:
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".arch_integration_16b_", dir=str(repo_root.parent))
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
                raise RunnerPreflightError("16B isolated checkout creation failed")
            added.append(paths[name])
        validate_checkout_separation(
            paths["candidate"],
            paths["target"],
            candidate_head=_git_head(paths["candidate"]),
            target_head=_git_head(paths["target"]),
        )
        _tracked_clean(paths["candidate"], "16B candidate")
        _tracked_clean(paths["target"], "16B target")
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


def _current_harness_worker_path(harness_root: Path) -> Path:
    return harness_root / "evaluation" / "integration_v7" / "runner_worker.py"


def _invoke_current_harness_worker(
    job: Mapping[str, Any],
    *,
    harness_root: Path,
    candidate_root: Path,
    timeout: float,
) -> dict[str, Any]:
    """Invoke the current worker once while it imports Product from candidate."""

    worker_path = _current_harness_worker_path(harness_root)
    if not worker_path.is_file():
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_process_failure",
        }
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(candidate_root)
    try:
        completed = subprocess.run(
            [sys.executable, str(worker_path)],
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


def _normalized_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep infrastructure-invalid records invalid without retrying them."""

    if payload.get("execution_validity") == "VALID" and payload.get(
        "infrastructure_code"
    ):
        normalized = dict(payload)
        normalized["execution_validity"] = "INVALID"
        return normalized
    return payload


def _write_result_package(
    output_dir: Path,
    *,
    manifest: Mapping[str, Any],
    diagnostic_runs: list[Mapping[str, Any]],
    semantic_runs: list[Mapping[str, Any]],
    automatic_scores: list[Mapping[str, Any]],
) -> None:
    """Write exactly the five safe 16B files; no scoring artifacts exist yet."""

    _write_json(output_dir / "run_manifest.json", manifest)
    _write_jsonl(output_dir / "diagnostic_runs.jsonl", diagnostic_runs)
    _write_jsonl(output_dir / "semantic_runs.jsonl", semantic_runs)
    _write_jsonl(output_dir / "automatic_scores.jsonl", automatic_scores)
    _write_json(
        output_dir / "summary.json",
        build_recovery_summary(diagnostic_runs, semantic_runs, automatic_scores),
    )


def run_recovery_repair_candidate_dev(
    config: RecoveryRepairCandidateRunConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Run the frozen 18-case plan once, without A, Holdout, or retries."""

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=repo_root / ".env", override=False)
    protocol, cases, harness_head = _preflight(config, repo_root)
    plan = build_recovery_run_plan(cases, config.split)
    case_by_id = {case["case_id"]: case for case in cases}
    corpus = config.corpus_checkout.resolve()
    diagnostic_runs: list[dict[str, Any]] = []
    semantic_runs: list[dict[str, Any]] = []
    automatic_scores: list[dict[str, Any]] = []

    with _isolated_checkouts(repo_root) as checkouts:
        validate_recovery_identities(
            candidate_head=_git_head(checkouts["candidate"]),
            target_head=_git_head(checkouts["target"]),
            corpus_head=_git_head(corpus),
            protocol_sha=protocol["protocol_sha256"],
            dev_sha=protocol["datasets"][DEV_SPLIT]["sha256"],
            prompt_version=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.version,
            prompt_sha256=ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE.sha256,
            recovery_repair_prompt_version=ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_VERSION,
            recovery_repair_prompt_sha256=ENGINEERING_RECOVERY_ACTION_REPAIR_PROMPT_SHA256,
            provider=config.provider,
            model=config.model,
            harness_head=harness_head,
        )
        corpus_identity = _verify_candidate_corpus(corpus, checkouts["candidate"])
        corpus_root = corpus / protocol["corpus_identity"]["path"]
        for item in plan:
            case = case_by_id[item["case_id"]]
            job = build_recovery_worker_job(
                case,
                plan_item=item,
                candidate_root=checkouts["candidate"],
                target_root=checkouts["target"],
                corpus_root=corpus_root,
            )
            payload = _normalized_payload(
                _invoke_current_harness_worker(
                    job,
                    harness_root=repo_root,
                    candidate_root=checkouts["candidate"],
                    timeout=config.worker_timeout_seconds,
                )
            )
            diagnostic_runs.append(_safe_diagnostic_record(case, item, payload))
            semantic_runs.append(_semantic_run_record(case, payload))
            automatic_scores.append(_automatic_score_record(case, item, payload))

    manifest = build_recovery_manifest(
        protocol=protocol,
        config=config,
        plan=plan,
        diagnostic_runs=diagnostic_runs,
        harness_head=harness_head,
        corpus_identity=corpus_identity,
    )
    _write_result_package(
        config.output_dir,
        manifest=manifest,
        diagnostic_runs=diagnostic_runs,
        semantic_runs=semantic_runs,
        automatic_scores=automatic_scores,
    )
    return config.output_dir


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Prepare and run the ARCH-INTEGRATION-16B recovery-repair Dev candidate"
        )
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    try:
        output = run_recovery_repair_candidate_dev(
            RecoveryRepairCandidateRunConfig(
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


__all__ = [
    "ARTIFACT_FILES",
    "CANDIDATE_RUNTIME_COMMIT",
    "CANDIDATE_SYSTEM_LABEL",
    "DEFAULT_OUTPUT_DIR",
    "EXPECTED_DEV_DATASET_SHA",
    "FROZEN_RECOVERY_REPAIR_PROMPT_SHA256",
    "PROTECTED_RESULT_DIRS",
    "RECOVERY_REPAIR_PROMPT_VERSION",
    "RUNNER_SCHEMA_VERSION",
    "RUNTIME_VARIANT",
    "RecoveryRepairCandidateRunConfig",
    "assert_dev_only",
    "build_recovery_manifest",
    "build_recovery_run_plan",
    "build_recovery_summary",
    "build_recovery_worker_job",
    "project_decision_repair_observability",
    "run_recovery_repair_candidate_dev",
    "validate_checkout_separation",
    "validate_recovery_identities",
]
