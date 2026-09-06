"""Independent ARCH-INTEGRATION-12B Dev harness for the v5 Repo Tool candidate.

This evaluation harness prepares and, only when explicitly invoked with the
operator's provider credentials, executes one isolated 18-case Dev run.  It
uses the existing Unified-v1 decision-prompt selector and checks the candidate
checkout's live ``code_search`` contract before any worker invocation.  It
never runs System A or Holdout and never writes an earlier result directory.
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

from core.tool_agent.default_tools import CODE_SEARCH_SPEC
from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
from core.tool_agent.tools.code_search import CODE_SEARCH_VERSION
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
    FROZEN_PROVIDER,
    FROZEN_PROTOCOL_SHA,
    REPO_ROOT,
    TARGET_REPOSITORY,
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
from evaluation.integration_v7.runner_worker import UNIFIED_DECISION_PROMPT_SELECTOR


CANDIDATE_RUNNER_SCHEMA_VERSION = "integration_v7_kind_aware_candidate_dev_runner_v1"
CANDIDATE_RUNTIME_COMMIT = "6cd1d8248cb939ba2e15e883c04859fbd835a671"
CANDIDATE_RUNTIME_LABEL = "kind_aware_code_search_v5_candidate"
CANDIDATE_SYSTEM_LABEL = "B_kind_aware_candidate"
DECISION_PROMPT_PROFILE_SELECTOR = UNIFIED_DECISION_PROMPT_SELECTOR
LEGACY_DEV_RESULTS_DIR = REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1"
PREVIOUS_CANDIDATE_RESULTS_DIRS = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_e374_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_0abdb_v1",
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_d001_v1",
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_6cd1_v1"
)
EXPECTED_ARTIFACT_KIND_VALUES = ("any", "project_code", "project_doc")


@dataclass(frozen=True)
class KindAwareCandidateRunConfig:
    """Explicit inputs for one, and only one, candidate Dev execution."""

    corpus_checkout: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_kind_aware_candidate_scope(split: str) -> None:
    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-INTEGRATION-12B is Dev-only; Holdout execution is denied"
        )


def _assert_independent_output(output_dir: Path) -> None:
    """Protect all historical Dev/candidate outputs and deny reruns."""

    resolved = output_dir.resolve()
    protected = (LEGACY_DEV_RESULTS_DIR,) + PREVIOUS_CANDIDATE_RESULTS_DIRS
    if any(
        resolved == path.resolve() or path.resolve() in resolved.parents
        for path in protected
    ):
        raise RunnerPreflightError(
            "12B output must not overwrite dev_v1 or an earlier candidate result"
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise RunnerPreflightError("12B candidate output is not empty; rerun denied")


def validate_kind_aware_candidate_checkouts(
    candidate_root: Path,
    target_root: Path,
    *,
    candidate_head: str,
    target_head: str,
) -> None:
    if candidate_root.resolve() == target_root.resolve():
        raise RunnerPreflightError("12B candidate and target checkouts must be separate")
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("12B candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("12B target project SHA mismatch")


def validate_kind_aware_candidate_identities(
    *,
    candidate_head: str,
    target_head: str,
    corpus_head: str,
    protocol_sha: str,
    prompt_profile_version: str,
    prompt_profile_sha256: str,
    code_search_version: str,
    artifact_kind_optional: bool,
    artifact_kind_values: tuple[str, ...],
) -> None:
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("12B candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("12B target project SHA mismatch")
    if corpus_head != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("12B knowledge corpus SHA mismatch")
    if protocol_sha != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("12B protocol SHA mismatch")
    if prompt_profile_version != ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version:
        raise RunnerPreflightError("12B decision prompt profile version mismatch")
    if prompt_profile_sha256 != ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256:
        raise RunnerPreflightError("12B decision prompt profile SHA mismatch")
    if code_search_version != CODE_SEARCH_VERSION or code_search_version != "code_search_v5":
        raise RunnerPreflightError("12B code_search version mismatch")
    if not artifact_kind_optional:
        raise RunnerPreflightError("12B code_search artifact_kind must be optional")
    if artifact_kind_values != EXPECTED_ARTIFACT_KIND_VALUES:
        raise RunnerPreflightError("12B code_search artifact_kind schema mismatch")


def build_kind_aware_candidate_run_plan(
    cases: list[Mapping[str, Any]], split: str = DEV_SPLIT
) -> list[dict[str, Any]]:
    """Build exactly one Unified-v1 candidate run for every Dev case."""

    assert_kind_aware_candidate_scope(split)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise ProtocolViolation("ARCH-INTEGRATION-12B requires exactly 18 Dev cases")
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case_order, case in enumerate(cases, 1):
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("12B run plan contains a non-Dev case")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen:
            raise ProtocolViolation("12B run plan contains duplicate case IDs")
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
                "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
                "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
            }
        )
    if len(plan) != EXPECTED_CASE_COUNTS[DEV_SPLIT] or len(seen) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise ProtocolViolation("12B run plan must contain 18 unique Dev cases")
    return plan


def build_kind_aware_candidate_worker_job(
    case: Mapping[str, Any],
    *,
    plan_item: Mapping[str, Any],
    candidate_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    if plan_item.get("system") != CANDIDATE_SYSTEM_LABEL:
        raise ProtocolViolation("12B worker job must use B_kind_aware_candidate identity")
    if plan_item.get("worker_system") != "B":
        raise ProtocolViolation("12B worker must use the Unified B execution path")
    if plan_item.get("decision_prompt_profile_selector") != DECISION_PROMPT_PROFILE_SELECTOR:
        raise ProtocolViolation("12B worker must explicitly select Unified-v1")
    if plan_item.get("decision_prompt_profile") != ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version:
        raise ProtocolViolation("12B worker Unified-v1 profile version mismatch")
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


def _candidate_metadata(code_search_contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_runtime_commit": CANDIDATE_RUNTIME_COMMIT,
        "runtime_variant": CANDIDATE_RUNTIME_LABEL,
        "system_identity": CANDIDATE_SYSTEM_LABEL,
        "target_project_commit": TARGET_PROJECT_COMMIT,
        "corpus_source_commit": CORPUS_SOURCE_COMMIT,
        "protocol_sha256": FROZEN_PROTOCOL_SHA,
        "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
        "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
        "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
        "repo_tool_contract": dict(code_search_contract),
    }


def _candidate_raw_record(
    case: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    payload: Mapping[str, Any],
    code_search_contract: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _raw_record(case, plan_item, payload)
    raw.update(_candidate_metadata(code_search_contract))
    return raw


def _candidate_score_record(
    case: Mapping[str, Any],
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    code_search_contract: Mapping[str, Any],
) -> dict[str, Any]:
    score: dict[str, Any] = {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": CANDIDATE_SYSTEM_LABEL,
        "run_order": raw["run_order"],
        "run_validity": raw["run_validity"],
        "automatic_metrics": {},
        **_candidate_metadata(code_search_contract),
    }
    if raw["run_validity"] == "VALID":
        score["automatic_metrics"] = _automatic_score(case, "B", payload)
    return score


def build_kind_aware_candidate_summary(
    raw_runs: list[Mapping[str, Any]],
    scores: list[Mapping[str, Any]],
    code_search_contract: Mapping[str, Any],
) -> dict[str, Any]:
    families = sorted({run["task_family"] for run in raw_runs})
    valid = [score for score in scores if score.get("run_validity") == "VALID"]
    return {
        "schema_version": CANDIDATE_RUNNER_SCHEMA_VERSION,
        "execution_scope": "Integration Dev only / code_search_v5 candidate B_kind_aware_candidate / automatic metrics only",
        "candidate_identity": _candidate_metadata(code_search_contract),
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


def _probe_candidate_contract(candidate_root: Path) -> dict[str, Any]:
    """Read prompt and Repo Tool identities from the detached candidate checkout."""

    probe = """
import json
from core.tool_agent.default_tools import CODE_SEARCH_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_VERSION
from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE
from evaluation.integration_v7.runner_worker import (
    UNIFIED_DECISION_PROMPT_SELECTOR,
    _select_decision_prompt_profile,
)

profile = _select_decision_prompt_profile({
    "system": "B",
    "decision_prompt_profile_selector": UNIFIED_DECISION_PROMPT_SELECTOR,
})
artifact_kind = CODE_SEARCH_SPEC.input_schema["properties"].get("artifact_kind", {})
print(json.dumps({
    "prompt_profile": {"version": profile.version, "sha256": profile.sha256},
    "code_search": {
        "name": CODE_SEARCH_SPEC.name,
        "version": CODE_SEARCH_VERSION,
        "spec_version": CODE_SEARCH_SPEC.version,
        "artifact_kind_optional": "artifact_kind" not in CODE_SEARCH_SPEC.input_schema.get("required", []),
        "artifact_kind_values": artifact_kind.get("enum", []),
    },
}, separators=(",", ":")))
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(candidate_root)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=candidate_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerPreflightError("12B candidate contract probe failed") from exc
    if completed.returncode != 0:
        raise RunnerPreflightError("12B candidate contract probe failed")
    try:
        result = json.loads(completed.stdout)
        prompt = result["prompt_profile"]
        code_search = result["code_search"]
        if code_search["name"] != "code_search":
            raise KeyError("name")
        return {
            "prompt_profile": {
                "version": prompt["version"],
                "sha256": prompt["sha256"],
            },
            "code_search": {
                "tool": code_search["name"],
                "version": code_search["version"],
                "spec_version": code_search["spec_version"],
                "artifact_kind": {
                    "optional": code_search["artifact_kind_optional"],
                    "values": list(code_search["artifact_kind_values"]),
                },
            },
        }
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RunnerPreflightError("12B candidate contract probe output invalid") from exc


def _invoke_kind_aware_candidate_worker(
    job: Mapping[str, Any], candidate_root: Path, timeout: float
) -> dict[str, Any]:
    """Invoke exactly one candidate worker process; failures are not retried."""

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(candidate_root)
    worker_path = candidate_root / "evaluation" / "integration_v7" / "runner_worker.py"
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
    if not isinstance(payload, dict) or payload.get("worker_schema_version") != WORKER_SCHEMA_VERSION:
        return {
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_output_invalid",
        }
    return payload


def _preflight(
    config: KindAwareCandidateRunConfig, repo_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert_kind_aware_candidate_scope(config.split)
    _assert_independent_output(config.output_dir)
    if config.provider != FROZEN_PROVIDER or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("12B provider/model drift from frozen DeepSeek contract")
    manifest = validate_protocol_manifest(MANIFEST_PATH)
    if manifest["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("12B protocol SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError(f"missing_environment: {config.api_key_env}")
    cases = load_cases(DEV_DATASET_PATH)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise RunnerPreflightError("12B Dev case count mismatch")
    return manifest, cases


@contextmanager
def _isolated_kind_aware_candidate_checkouts(
    repo_root: Path,
) -> Iterator[dict[str, Path]]:
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".arch_eval_12b_candidate_", dir=str(repo_root.parent))
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
                raise RunnerPreflightError("12B isolated checkout creation failed")
            added.append(paths[name])
        validate_kind_aware_candidate_checkouts(
            paths["candidate"],
            paths["target"],
            candidate_head=_git_head(paths["candidate"]),
            target_head=_git_head(paths["target"]),
        )
        _tracked_clean(paths["candidate"], "12B candidate")
        _tracked_clean(paths["target"], "12B target")
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


def build_kind_aware_candidate_manifest(
    *,
    manifest: Mapping[str, Any],
    config: KindAwareCandidateRunConfig,
    plan: list[Mapping[str, Any]],
    raw_runs: list[Mapping[str, Any]],
    corpus_identity: Mapping[str, Any],
    code_search_contract: Mapping[str, Any],
    timestamp: str = "",
) -> dict[str, Any]:
    run_timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate_runtime = {
        "label": CANDIDATE_RUNTIME_LABEL,
        "system_identity": CANDIDATE_SYSTEM_LABEL,
        "runtime_variant": CANDIDATE_RUNTIME_LABEL,
        "source_commit": CANDIDATE_RUNTIME_COMMIT,
        "candidate_runtime_commit": CANDIDATE_RUNTIME_COMMIT,
        "decision_prompt_profile_selector": DECISION_PROMPT_PROFILE_SELECTOR,
        "decision_prompt_profile": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.version,
        "decision_prompt_sha256": ENGINEERING_DECISION_PROMPT_UNIFIED_PROFILE.sha256,
        "repo_tool_contract": dict(code_search_contract),
    }
    return {
        "schema_version": CANDIDATE_RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-integration-12b-dev-candidate-6cd1-{run_timestamp}",
        "status": "COMPLETE" if len(raw_runs) == EXPECTED_CASE_COUNTS[DEV_SPLIT] else "INVALID",
        "execution_scope": "Integration Dev only / code_search_v5 candidate B_kind_aware_candidate",
        "split": DEV_SPLIT,
        "provider": {"name": config.provider, "model": config.model},
        "candidate_runtime": candidate_runtime,
        "frozen_system_identity_preserved": {
            "system_a_08b": "not executed",
            "system_b_08b": "not executed as frozen B; 12B candidate only",
            "candidate_b_prime_09b": "not executed or overwritten",
            "candidate_b_double_prime_10b": "not executed or overwritten",
            "candidate_b_triple_prime_11b": "not executed or overwritten",
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
            "version": manifest["protocol_version"],
            "sha256": manifest["protocol_sha256"],
        },
        "dataset": {
            "split": DEV_SPLIT,
            "case_count": EXPECTED_CASE_COUNTS[DEV_SPLIT],
            "sha256": manifest["datasets"][DEV_SPLIT]["sha256"],
        },
        "repo_tool_contract": {
            "backend": "Repo Evidence Backend",
            "tool": CODE_SEARCH_SPEC.name,
            "version": code_search_contract["version"],
            "artifact_kind": code_search_contract["artifact_kind"],
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
            "evaluation/integration_v7/results/dev_candidate_d001_v1",
        ],
        "artifact_files": [
            "run_manifest.json",
            "raw_runs.jsonl",
            "automatic_scores.jsonl",
            "summary.json",
        ],
    }


def run_kind_aware_candidate_dev(
    config: KindAwareCandidateRunConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Execute exactly one 18-case Dev plan, with no retry or Holdout path."""

    manifest, cases = _preflight(config, repo_root)
    plan = build_kind_aware_candidate_run_plan(cases, config.split)
    corpus = config.corpus_checkout.resolve()
    raw_runs: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    case_by_id = {case["case_id"]: case for case in cases}

    with _isolated_kind_aware_candidate_checkouts(repo_root) as checkouts:
        candidate_contract = _probe_candidate_contract(checkouts["candidate"])
        code_search_contract = candidate_contract["code_search"]
        prompt = candidate_contract["prompt_profile"]
        artifact_kind = code_search_contract["artifact_kind"]
        validate_kind_aware_candidate_identities(
            candidate_head=_git_head(checkouts["candidate"]),
            target_head=_git_head(checkouts["target"]),
            corpus_head=_git_head(corpus),
            protocol_sha=manifest["protocol_sha256"],
            prompt_profile_version=prompt["version"],
            prompt_profile_sha256=prompt["sha256"],
            code_search_version=code_search_contract["version"],
            artifact_kind_optional=artifact_kind["optional"],
            artifact_kind_values=tuple(artifact_kind["values"]),
        )
        corpus_identity = _verify_candidate_corpus(corpus, checkouts["candidate"])
        knowledge_root = corpus / manifest["corpus_identity"]["path"]
        for item in plan:
            case = case_by_id[item["case_id"]]
            job = build_kind_aware_candidate_worker_job(
                case,
                plan_item=item,
                candidate_root=checkouts["candidate"],
                target_root=checkouts["target"],
                corpus_root=knowledge_root,
            )
            payload = _invoke_kind_aware_candidate_worker(
                job,
                checkouts["candidate"],
                config.worker_timeout_seconds,
            )
            if payload.get("execution_validity") == "VALID" and payload.get(
                "infrastructure_code"
            ):
                payload = dict(payload)
                payload["execution_validity"] = "INVALID"
            raw = _candidate_raw_record(case, item, payload, code_search_contract)
            score = _candidate_score_record(case, raw, payload, code_search_contract)
            raw_runs.append(raw)
            scores.append(score)

    run_manifest = build_kind_aware_candidate_manifest(
        manifest=manifest,
        config=config,
        plan=plan,
        raw_runs=raw_runs,
        corpus_identity=corpus_identity,
        code_search_contract=code_search_contract,
    )
    output = config.output_dir
    _write_json(output / "run_manifest.json", run_manifest)
    _write_jsonl(output / "raw_runs.jsonl", raw_runs)
    _write_jsonl(output / "automatic_scores.jsonl", scores)
    _write_json(
        output / "summary.json",
        build_kind_aware_candidate_summary(raw_runs, scores, code_search_contract),
    )
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run independent ARCH-INTEGRATION-12B code_search_v5 Dev candidate"
    )
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    try:
        output = run_kind_aware_candidate_dev(
            KindAwareCandidateRunConfig(
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
