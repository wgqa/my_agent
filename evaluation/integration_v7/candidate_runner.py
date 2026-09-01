"""Independent ARCH-INTEGRATION-09B Dev runner for the repaired candidate.

This harness executes only the repaired Unified Engineering Runtime candidate
(System B') against the frozen Integration Dev set.  It deliberately does not
reuse the frozen 08B A/B run plan or its result directory.  The worker still
uses the existing System B execution path because B' is a candidate checkout
of that same unified runtime contract; all emitted artifacts label the
candidate identity explicitly and never present it as frozen System B.

The module is an evaluation harness only.  It does not modify production
runtime code, datasets, Gold, protocol assets, or the frozen 08B results.
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

from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    MANIFEST_PATH,
    TARGET_PROJECT_COMMIT,
    TARGET_PROJECT_ID,
    HoldoutExecutionDenied,
    ProtocolViolation,
    load_cases,
    load_protocol_manifest,
    validate_protocol_manifest,
)
from evaluation.integration_v7.runner import (
    FROZEN_MODEL,
    FROZEN_PROVIDER,
    FROZEN_PROTOCOL_SHA,
    REPO_ROOT,
    RunnerPreflightError,
    WORKER_SCHEMA_VERSION,
    _automatic_score,
    _git_head,
    _raw_record,
    _tracked_clean,
    _write_json,
    _write_jsonl,
    aggregate_metrics,
    safe_artifact,
)


CANDIDATE_RUNNER_SCHEMA_VERSION = "integration_v7_candidate_dev_runner_v1"
CANDIDATE_RUNTIME_COMMIT = "e374e151f0396468c06334bc2d78d7bb75381c61"
CANDIDATE_RUNTIME_LABEL = "repaired_candidate_b_prime"
CANDIDATE_SYSTEM_LABEL = "B_prime"
LEGACY_DEV_RESULTS_DIR = REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_candidate_e374_v1"
EXPECTED_DEV_DATASET_SHA = "fb756df4ebd688312c695b4a212d9ccf66b59eef92dec648e63d99a83a4343a9"


@dataclass(frozen=True)
class CandidateRunConfig:
    """Explicit inputs for one, and only one, candidate Dev execution."""

    corpus_checkout: Path
    output_dir: Path = DEFAULT_OUTPUT_DIR
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_candidate_run_scope(split: str) -> None:
    """Deny Holdout and every non-Dev scope before any provider work."""

    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-INTEGRATION-09B is Dev-only; Holdout execution is denied"
        )


def validate_candidate_checkout_separation(
    candidate_root: Path,
    target_root: Path,
    *,
    candidate_head: str,
    target_head: str,
) -> None:
    """Require distinct source and target checkouts with exact frozen SHAs."""

    if candidate_root.resolve() == target_root.resolve():
        raise RunnerPreflightError("candidate and target checkouts must be separate")
    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("target project SHA mismatch")


def validate_candidate_identities(
    *,
    candidate_head: str,
    target_head: str,
    corpus_head: str,
    protocol_sha: str,
) -> None:
    """Fail closed if the candidate, target, corpus, or protocol drifts."""

    if candidate_head != CANDIDATE_RUNTIME_COMMIT:
        raise RunnerPreflightError("candidate runtime SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("target project SHA mismatch")
    if corpus_head != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("knowledge corpus SHA mismatch")
    if protocol_sha != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("protocol SHA mismatch")


def _assert_independent_output(output_dir: Path) -> None:
    """Protect the frozen 08B directory and fail closed on rerun artifacts."""

    resolved = output_dir.resolve()
    legacy = LEGACY_DEV_RESULTS_DIR.resolve()
    if resolved == legacy or legacy in resolved.parents:
        raise RunnerPreflightError("candidate output must not be inside frozen dev_v1")
    if resolved.exists() and any(resolved.iterdir()):
        raise RunnerPreflightError("candidate output directory is not empty; rerun denied")


def build_candidate_run_plan(
    cases: list[Mapping[str, Any]], split: str = DEV_SPLIT
) -> list[dict[str, Any]]:
    """Build exactly one repaired candidate run for each of 18 Dev cases."""

    assert_candidate_run_scope(split)
    expected_count = EXPECTED_CASE_COUNTS[DEV_SPLIT]
    if len(cases) != expected_count:
        raise ProtocolViolation("ARCH-INTEGRATION-09B requires exactly 18 Dev cases")
    plan: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for case_order, case in enumerate(cases, 1):
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("candidate run plan contains a non-Dev case")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in seen_case_ids:
            raise ProtocolViolation("candidate run plan contains duplicate case IDs")
        seen_case_ids.add(case_id)
        plan.append(
            {
                "run_order": case_order,
                "case_order": case_order,
                "case_id": case_id,
                "system": CANDIDATE_SYSTEM_LABEL,
                "worker_system": "B",
                "runtime_variant": CANDIDATE_RUNTIME_LABEL,
            }
        )
    if len(plan) != 18 or {item["case_id"] for item in plan} != seen_case_ids:
        raise ProtocolViolation("candidate run plan must contain 18 unique Dev cases")
    return plan


def build_candidate_worker_job(
    case: Mapping[str, Any],
    *,
    plan_item: Mapping[str, Any],
    candidate_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    """Adapt the existing B worker to a candidate-labelled, single-run job."""

    if plan_item.get("system") != CANDIDATE_SYSTEM_LABEL:
        raise ProtocolViolation("candidate worker job must use B' system label")
    if plan_item.get("worker_system") != "B":
        raise ProtocolViolation("candidate worker must use the unified B execution path")
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
    }


def _candidate_metadata() -> dict[str, Any]:
    return {
        "candidate_runtime_commit": CANDIDATE_RUNTIME_COMMIT,
        "runtime_variant": CANDIDATE_RUNTIME_LABEL,
        "system_identity": CANDIDATE_SYSTEM_LABEL,
        "target_project_commit": TARGET_PROJECT_COMMIT,
        "corpus_source_commit": CORPUS_SOURCE_COMMIT,
        "protocol_sha256": FROZEN_PROTOCOL_SHA,
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
        # Case contracts are frozen for systems A/B; B' deliberately reuses
        # B's disabled-knowledge_search/tool obligations for scoring.
        score["automatic_metrics"] = _automatic_score(case, "B", payload)
    return score


def build_candidate_summary(
    raw_runs: list[Mapping[str, Any]],
    scores: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize automatic metrics without pairwise or semantic scoring."""

    families = sorted({run["task_family"] for run in raw_runs})
    valid = [score for score in scores if score.get("run_validity") == "VALID"]
    return {
        "schema_version": CANDIDATE_RUNNER_SCHEMA_VERSION,
        "execution_scope": "Integration Dev only / repaired candidate System B' / automatic metrics only",
        "candidate_identity": _candidate_metadata(),
        "run_counts": {
            "expected_candidate_runs": 18,
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


def _verify_candidate_corpus(corpus_checkout: Path, candidate_root: Path) -> dict[str, Any]:
    """Verify corpus identity through the candidate's actual knowledge backend."""

    if not corpus_checkout.is_dir():
        raise RunnerPreflightError("knowledge corpus checkout is unavailable")
    if _git_head(corpus_checkout) != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("knowledge corpus SHA mismatch")
    _tracked_clean(corpus_checkout, "knowledge corpus")
    protocol = load_protocol_manifest()
    corpus_root = corpus_checkout / protocol["corpus_identity"]["path"]
    if not corpus_root.is_dir():
        raise RunnerPreflightError("knowledge corpus candidate root is unavailable")
    probe = (
        "import json, sys; "
        "from core.engineering_knowledge import build_verified_engineering_knowledge; "
        "backend = build_verified_engineering_knowledge(sys.argv[1], repo_root=sys.argv[2]); "
        "print(json.dumps({'identity': backend.identity.to_dict(), 'bm25_doc_count': backend.bm25_doc_count}, separators=(',', ':')))"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(candidate_root)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(corpus_root), str(candidate_root)],
            cwd=candidate_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerPreflightError("knowledge backend preflight failed") from exc
    if completed.returncode != 0:
        raise RunnerPreflightError("knowledge backend identity verification failed")
    try:
        result = json.loads(completed.stdout)
        identity = result["identity"]
        bm25_doc_count = result["bm25_doc_count"]
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RunnerPreflightError("knowledge backend identity output invalid") from exc
    expected = {
        "corpus_id": "870e5864df67",
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": "dbc497c796d5",
        "verified": True,
    }
    if identity != expected or bm25_doc_count != 215:
        raise RunnerPreflightError("knowledge corpus identity mismatch")
    return identity


def _invoke_candidate_worker(
    job: Mapping[str, Any], candidate_root: Path, timeout: float
) -> dict[str, Any]:
    """Invoke the worker script from the frozen candidate checkout itself."""

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


def build_candidate_manifest(
    *,
    manifest: Mapping[str, Any],
    config: CandidateRunConfig,
    plan: list[Mapping[str, Any]],
    raw_runs: list[Mapping[str, Any]],
    corpus_identity: Mapping[str, Any],
    timestamp: str = "",
) -> dict[str, Any]:
    """Build the safe candidate manifest independently of provider execution."""

    run_timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": CANDIDATE_RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-integration-09b-dev-candidate-e374-{run_timestamp}",
        "status": "COMPLETE" if len(raw_runs) == 18 else "INVALID",
        "execution_scope": "Integration Dev only / repaired candidate System B'",
        "split": DEV_SPLIT,
        "provider": {"name": config.provider, "model": config.model},
        "candidate_runtime": {
            "label": CANDIDATE_RUNTIME_LABEL,
            "system_identity": CANDIDATE_SYSTEM_LABEL,
            "source_commit": CANDIDATE_RUNTIME_COMMIT,
            "worker_system_path": "B unified runtime execution path",
        },
        "frozen_system_identity_preserved": {
            "system_a_08b": "not executed",
            "system_b_08b": "not executed as frozen B; candidate only",
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
            "case_count": 18,
            "sha256": manifest["datasets"][DEV_SPLIT]["sha256"],
        },
        "run_plan": [dict(item) for item in plan],
        "expected_candidate_runs": 18,
        "observed_candidate_runs": len(raw_runs),
        "infrastructure_invalid_count": sum(
            run.get("run_validity") != "VALID" for run in raw_runs
        ),
        "automatic_metrics_only": True,
        "manual_scoring": "NOT_DONE",
        "holdout": "NOT_RUN / DENY",
        "legacy_dev_results_preserved": "evaluation/integration_v7/results/dev_v1",
        "artifact_files": [
            "run_manifest.json",
            "raw_runs.jsonl",
            "automatic_scores.jsonl",
            "summary.json",
        ],
    }


def _preflight(
    config: CandidateRunConfig, repo_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert_candidate_run_scope(config.split)
    _assert_independent_output(config.output_dir)
    if config.provider != FROZEN_PROVIDER or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("provider/model drift from frozen DeepSeek contract")
    manifest = validate_protocol_manifest(MANIFEST_PATH)
    if manifest["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("protocol SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError(f"missing_environment: {config.api_key_env}")
    cases = load_cases(DEV_DATASET_PATH)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise RunnerPreflightError("Dev case count mismatch")
    if manifest["datasets"][DEV_SPLIT]["sha256"] != EXPECTED_DEV_DATASET_SHA:
        raise RunnerPreflightError("Dev dataset SHA mismatch")
    return manifest, cases


@contextmanager
def _isolated_candidate_checkouts(repo_root: Path) -> Iterator[dict[str, Path]]:
    """Create separate candidate and target worktrees, then remove both."""

    temporary_root = Path(
        tempfile.mkdtemp(prefix=".arch_eval_09b_candidate_", dir=str(repo_root.parent))
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
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode != 0:
                raise RunnerPreflightError("isolated candidate checkout creation failed")
            added.append(paths[name])
        validate_candidate_checkout_separation(
            paths["candidate"],
            paths["target"],
            candidate_head=_git_head(paths["candidate"]),
            target_head=_git_head(paths["target"]),
        )
        _tracked_clean(paths["candidate"], "candidate")
        _tracked_clean(paths["target"], "target")
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


def run_candidate_dev(
    config: CandidateRunConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Run the 18-case candidate Dev plan exactly once, with no retries."""

    manifest, cases = _preflight(config, repo_root)
    plan = build_candidate_run_plan(cases, config.split)
    corpus = config.corpus_checkout.resolve()
    raw_runs: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    case_by_id = {case["case_id"]: case for case in cases}

    with _isolated_candidate_checkouts(repo_root) as checkouts:
        validate_candidate_identities(
            candidate_head=_git_head(checkouts["candidate"]),
            target_head=_git_head(checkouts["target"]),
            corpus_head=_git_head(corpus),
            protocol_sha=manifest["protocol_sha256"],
        )
        corpus_identity = _verify_candidate_corpus(corpus, checkouts["candidate"])
        knowledge_root = corpus / manifest["corpus_identity"]["path"]
        for item in plan:
            case = case_by_id[item["case_id"]]
            job = build_candidate_worker_job(
                case,
                plan_item=item,
                candidate_root=checkouts["candidate"],
                target_root=checkouts["target"],
                corpus_root=knowledge_root,
            )
            # Exactly one invocation per case.  Provider and infrastructure
            # failures remain INVALID and are never retried for count parity.
            payload = _invoke_candidate_worker(
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
            score = _candidate_score_record(case, raw, payload)
            raw_runs.append(raw)
            scores.append(score)

    run_manifest = build_candidate_manifest(
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
    _write_json(output / "summary.json", build_candidate_summary(raw_runs, scores))
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run independent ARCH-INTEGRATION-09B repaired candidate Dev"
    )
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    try:
        output = run_candidate_dev(
            CandidateRunConfig(
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
