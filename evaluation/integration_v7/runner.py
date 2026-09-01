"""ARCH-EVAL-08B real Dev A/B runner.

This module is an evaluation harness only.  It creates isolated Git
checkouts for the frozen System A and System B commits, binds both runs to
the same frozen target project and corpus, and serializes only safe public
results.  Holdout is deliberately denied by default and is not an input to
the execution path.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from evaluation.integration_v7.case_contract import (
    CORPUS_SOURCE_COMMIT,
    DEV_DATASET_PATH,
    DEV_SPLIT,
    EXPECTED_CASE_COUNTS,
    HOLDOUT_SPLIT,
    MANIFEST_PATH,
    SYSTEM_A_COMMIT,
    SYSTEM_B_COMMIT,
    TARGET_PROJECT_COMMIT,
    TARGET_PROJECT_ID,
    HoldoutExecutionDenied,
    ProtocolViolation,
    compute_premature_finalization,
    compute_refusal_correctness,
    compute_required_evidence_coverage,
    compute_task_completion,
    compute_tool_coverage,
    load_cases,
    load_protocol_manifest,
    validate_protocol_manifest,
)


RUNNER_SCHEMA_VERSION = "integration_v7_real_dev_runner_v1"
WORKER_SCHEMA_VERSION = "integration_v7_real_dev_worker_v1"
BASELINE_COMMIT = "155ee71a2a39efb74a524232c97699e773f65655"
FROZEN_PROTOCOL_SHA = "281dba7b098535fd508971bfdd98d53ae188c8efa204b5c1fa929c3a40d6a40d"
FROZEN_PROVIDER = "deepseek"
FROZEN_MODEL = "deepseek-chat"
CORPUS_REPOSITORY = "wgqa/agent_data"
TARGET_REPOSITORY = "wgqa/my_agent"
WORKER_PATH = Path(__file__).with_name("runner_worker.py")
REPO_ROOT = Path(__file__).resolve().parents[2]

_PROVIDER_FAILURE_CODES = frozenset(
    {
        "ACTION_PROVIDER_ERROR",
        "ACTION_TIMEOUT",
        "PLANNER_PROVIDER_ERROR",
        "PLANNER_TIMEOUT",
    }
)
_FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "cot",
        "full_prompt",
        "private_cot",
        "private_reasoning",
        "raw_model_output",
        "raw_provider_response",
        "system_prompt",
        "traceback",
    }
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/][^\s\"']+|(?:^|[\s(])/(?:Users|home|tmp|mnt|workspace|var)/[^\s\"']+)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,})"
)

_PAIRWISE_METRICS = (
    "task_completion",
    "required_evidence_coverage",
    "tool_coverage",
    "premature_finalization",
    "refusal_correctness",
    "context_resolution_correct",
    "knowledge_source_hit_at_5",
    "subquery_coverage",
    "retrieval_call_count",
    "tool_calls",
    "llm_calls_total",
    "latency_e2e_ms",
)
_HIGHER_IS_BETTER = frozenset(
    {
        "task_completion",
        "required_evidence_coverage",
        "tool_coverage",
        "refusal_correctness",
        "context_resolution_correct",
        "knowledge_source_hit_at_5",
        "subquery_coverage",
    }
)


class RunnerPreflightError(RuntimeError):
    """A safe, non-provider preflight failure that must prevent all runs."""


@dataclass(frozen=True)
class RunConfig:
    """Explicit execution inputs; no Holdout mode is accepted by this runner."""

    corpus_checkout: Path
    output_dir: Path = REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1"
    split: str = DEV_SPLIT
    provider: str = FROZEN_PROVIDER
    model: str = FROZEN_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    worker_timeout_seconds: float = 180.0


def assert_run_scope(split: str) -> None:
    if split != DEV_SPLIT:
        raise HoldoutExecutionDenied(
            "ARCH-EVAL-08B is Dev-only; Holdout execution is denied"
        )


def _git_output(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunnerPreflightError("git preflight failed") from exc
    if completed.returncode != 0:
        raise RunnerPreflightError("git preflight returned a non-zero status")
    return completed.stdout.strip()


def _git_head(root: Path) -> str:
    return _git_output(root, "rev-parse", "--verify", "HEAD")


def _tracked_clean(root: Path, label: str) -> None:
    status = _git_output(root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise RunnerPreflightError(f"{label} checkout has tracked changes")


def validate_frozen_identities(
    *,
    system_heads: Mapping[str, str],
    target_head: str,
    corpus_head: str,
    protocol_sha: str,
) -> None:
    """Fail closed before a provider call if any frozen identity drifts."""

    if dict(system_heads) != {"A": SYSTEM_A_COMMIT, "B": SYSTEM_B_COMMIT}:
        raise RunnerPreflightError("system source SHA mismatch")
    if target_head != TARGET_PROJECT_COMMIT:
        raise RunnerPreflightError("target project SHA mismatch")
    if corpus_head != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("knowledge corpus SHA mismatch")
    if protocol_sha != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("protocol SHA mismatch")


def build_run_plan(cases: list[Mapping[str, Any]], split: str = DEV_SPLIT) -> list[dict[str, Any]]:
    """Expand frozen Dev case order into exactly 36 alternating system-runs."""

    assert_run_scope(split)
    expected_count = EXPECTED_CASE_COUNTS[DEV_SPLIT]
    if len(cases) != expected_count:
        raise ProtocolViolation("ARCH-EVAL-08B requires exactly 18 Dev cases")
    plan: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases, 1):
        if case.get("split") != DEV_SPLIT:
            raise ProtocolViolation("ARCH-EVAL-08B run plan contains a non-Dev case")
        systems = ("A", "B") if case_index % 2 else ("B", "A")
        for system in systems:
            plan.append(
                {
                    "run_order": len(plan) + 1,
                    "case_order": case_index,
                    "case_id": case["case_id"],
                    "system": system,
                }
            )
    return plan


def build_worker_job(
    case: Mapping[str, Any],
    *,
    system: str,
    run_order: int,
    case_order: int,
    system_root: Path,
    target_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    if system not in {"A", "B"}:
        raise ValueError("system must be A or B")
    context = case.get("conversation_context", []) if system == "B" else []
    return {
        "worker_schema_version": WORKER_SCHEMA_VERSION,
        "system": system,
        "run_order": run_order,
        "case_order": case_order,
        "case": dict(case),
        "system_root": str(system_root),
        "target_root": str(target_root),
        "corpus_root": str(corpus_root),
        "question": case["question"],
        "conversation_context": context,
    }


def _redact_text(value: str) -> str:
    value = _ABSOLUTE_PATH_RE.sub("<REDACTED_PATH>", value)
    return _SECRET_VALUE_RE.sub("<REDACTED_SECRET>", value)


def safe_artifact(value: Any) -> Any:
    """Redact incidental path/secret text and reject sensitive field names."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is str and key.casefold() in _FORBIDDEN_ARTIFACT_KEYS:
                raise RunnerPreflightError("artifact contains a forbidden sensitive field")
            result[key] = safe_artifact(item)
        return result
    if isinstance(value, list):
        return [safe_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [safe_artifact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        safe_artifact(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    safe_artifact(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
    os.replace(temporary, path)


def aggregate_metrics(scores: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate only automatic metrics; None and invalid runs are excluded."""

    values: dict[str, list[float]] = defaultdict(list)
    valid_count = 0
    invalid_count = 0
    for score in scores:
        if score.get("run_validity") != "VALID":
            invalid_count += 1
            continue
        valid_count += 1
        for name, value in score.get("automatic_metrics", {}).items():
            if type(value) is bool:
                values[name].append(float(value))
            elif type(value) in (int, float) and not isinstance(value, bool):
                values[name].append(float(value))
    return {
        "valid_runs": valid_count,
        "invalid_runs_excluded": invalid_count,
        "metrics": {
            name: {
                "n": len(items),
                "mean": sum(items) / len(items) if items else None,
            }
            for name, items in sorted(values.items())
        },
    }


def _pairwise_summary(scores: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for score in scores:
        if score.get("run_validity") == "VALID":
            by_case[score["case_id"]][score["system"]] = score
    result: dict[str, Any] = {}
    for metric in _PAIRWISE_METRICS:
        pairs = []
        for case_id, systems in sorted(by_case.items()):
            if "A" not in systems or "B" not in systems:
                continue
            a = systems["A"]["automatic_metrics"].get(metric)
            b = systems["B"]["automatic_metrics"].get(metric)
            if not isinstance(a, (bool, int, float)):
                continue
            if not isinstance(b, (bool, int, float)):
                continue
            if a is None or b is None:
                continue
            a_value = float(a)
            b_value = float(b)
            if a_value == b_value:
                winner = "equal"
            elif metric in _HIGHER_IS_BETTER:
                winner = "A better" if a_value > b_value else "B better"
            else:
                winner = "A better" if a_value < b_value else "B better"
            pairs.append({"case_id": case_id, "A": a_value, "B": b_value, "winner": winner})
        counts = {label: sum(item["winner"] == label for item in pairs) for label in ("A better", "B better", "equal")}
        result[metric] = {"pairs": pairs, "counts": counts}
    return result


def build_summary(raw_runs: list[Mapping[str, Any]], scores: list[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [score for score in scores if score.get("run_validity") == "VALID"]
    families = sorted({run["task_family"] for run in raw_runs})
    systems = {"A", "B"}
    return {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "execution_scope": "Integration Dev only / automatic metrics only",
        "run_counts": {
            "expected_system_runs": 36,
            "observed_system_runs": len(raw_runs),
            "valid_system_runs": len(valid),
            "infrastructure_invalid_system_runs": len(raw_runs) - len(valid),
        },
        "overall": aggregate_metrics(scores),
        "by_task_family": {
            family: aggregate_metrics(
                score for score in scores if score.get("task_family") == family
            )
            for family in families
        },
        "by_system": {
            system: aggregate_metrics(
                score for score in scores if score.get("system") == system
            )
            for system in sorted(systems)
        },
        "automatic_pairwise": _pairwise_summary(scores),
        "manual_scoring": "NOT_DONE",
        "holdout": "NOT_RUN",
    }


@contextmanager
def _isolated_checkouts(repo_root: Path) -> Iterator[dict[str, Path]]:
    temporary_root = Path(tempfile.mkdtemp(prefix=".arch_eval_08b_", dir=str(repo_root.parent)))
    paths = {
        "A": temporary_root / "system_a",
        "B": temporary_root / "system_b",
        "target": temporary_root / "target_project",
    }
    revisions = {"A": SYSTEM_A_COMMIT, "B": SYSTEM_B_COMMIT, "target": TARGET_PROJECT_COMMIT}
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
                raise RunnerPreflightError("isolated system checkout creation failed")
            added.append(paths[name])
        for name, revision in revisions.items():
            if _git_head(paths[name]) != revision:
                raise RunnerPreflightError(f"{name} checkout SHA mismatch")
            _tracked_clean(paths[name], name)
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


def _verify_corpus(corpus_checkout: Path, system_roots: Mapping[str, Path]) -> dict[str, Any]:
    if not corpus_checkout.is_dir():
        raise RunnerPreflightError("knowledge corpus checkout is unavailable")
    if _git_head(corpus_checkout) != CORPUS_SOURCE_COMMIT:
        raise RunnerPreflightError("knowledge corpus SHA mismatch")
    _tracked_clean(corpus_checkout, "knowledge corpus")
    protocol = load_protocol_manifest()
    candidate_root = corpus_checkout / protocol["corpus_identity"]["path"]
    if not candidate_root.is_dir():
        raise RunnerPreflightError("knowledge corpus candidate root is unavailable")
    identities = []
    for system in ("A", "B"):
        probe = (
            "import json, sys; "
            "from core.engineering_knowledge import build_verified_engineering_knowledge; "
            "backend = build_verified_engineering_knowledge(sys.argv[1], repo_root=sys.argv[2]); "
            "print(json.dumps({'identity': backend.identity.to_dict(), 'bm25_doc_count': backend.bm25_doc_count}, separators=(',', ':')))"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(system_roots[system])
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    probe,
                    str(candidate_root),
                    str(system_roots[system]),
                ],
                cwd=system_roots[system],
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
            probe_result = json.loads(completed.stdout)
            identity = probe_result["identity"]
            bm25_doc_count = probe_result["bm25_doc_count"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise RunnerPreflightError("knowledge backend identity output invalid") from exc
        if identity != {
            "corpus_id": "870e5864df67",
            "file_count": 37,
            "chunk_count": 215,
            "retrieval_strategy": "bm25",
            "manifest_experiment_id": "dbc497c796d5",
            "verified": True,
        } or bm25_doc_count != 215:
            raise RunnerPreflightError("knowledge corpus identity mismatch")
        identities.append(identity)
    if identities[0] != identities[1]:
        raise RunnerPreflightError("A/B corpus identities differ")
    return identities[0]


def _preflight(config: RunConfig, repo_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assert_run_scope(config.split)
    if config.provider != FROZEN_PROVIDER or config.model != FROZEN_MODEL:
        raise RunnerPreflightError("provider/model drift from frozen DeepSeek contract")
    manifest = validate_protocol_manifest(MANIFEST_PATH)
    if manifest["protocol_sha256"] != FROZEN_PROTOCOL_SHA:
        raise RunnerPreflightError("protocol SHA mismatch")
    if not os.getenv(config.api_key_env):
        raise RunnerPreflightError("missing_environment: DEEPSEEK_API_KEY")
    cases = load_cases(DEV_DATASET_PATH)
    if len(cases) != EXPECTED_CASE_COUNTS[DEV_SPLIT]:
        raise RunnerPreflightError("Dev case count mismatch")
    if manifest["datasets"][DEV_SPLIT]["sha256"] != "fb756df4ebd688312c695b4a212d9ccf66b59eef92dec648e63d99a83a4343a9":
        raise RunnerPreflightError("Dev dataset SHA mismatch")
    return manifest, cases


def _invoke_worker(job: Mapping[str, Any], system_root: Path, timeout: float) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(system_root)
    try:
        completed = subprocess.run(
            [sys.executable, str(WORKER_PATH)],
            cwd=system_root,
            input=json.dumps(job, ensure_ascii=False, separators=(",", ":")),
            capture_output=True,
            text=True,
            env=environment,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"worker_schema_version": WORKER_SCHEMA_VERSION, "execution_validity": "INVALID", "infrastructure_code": "process_timeout"}
    except (OSError, subprocess.SubprocessError):
        return {"worker_schema_version": WORKER_SCHEMA_VERSION, "execution_validity": "INVALID", "infrastructure_code": "worker_process_failure"}
    if completed.returncode != 0:
        return {"worker_schema_version": WORKER_SCHEMA_VERSION, "execution_validity": "INVALID", "infrastructure_code": "worker_process_failure"}
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return {"worker_schema_version": WORKER_SCHEMA_VERSION, "execution_validity": "INVALID", "infrastructure_code": "worker_output_invalid"}
    if not isinstance(payload, dict) or payload.get("worker_schema_version") != WORKER_SCHEMA_VERSION:
        return {"worker_schema_version": WORKER_SCHEMA_VERSION, "execution_validity": "INVALID", "infrastructure_code": "worker_output_invalid"}
    return payload


def _automatic_score(case: Mapping[str, Any], system: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    evidence = result.get("evidence") or []
    evidence_kinds = {item.get("kind") for item in evidence if isinstance(item, Mapping)}
    groups = case["required_evidence_groups"]
    satisfied_groups = [any(kind in evidence_kinds for kind in group) for group in groups]
    requirement_state = payload.get("requirement_state") or {}
    automatic = {
        "task_completion": compute_task_completion(case, {"status": result.get("status")}),
        "required_evidence_coverage": compute_required_evidence_coverage(case, satisfied_groups),
        "tool_coverage": compute_tool_coverage(case, system, list(dict.fromkeys(payload.get("tool_sequence") or []))),
        "premature_finalization": compute_premature_finalization(
            case,
            {
                "finalized": result.get("status") == "completed",
                "required_evidence_satisfied": bool(requirement_state.get("satisfied")),
                "typed_requirement_satisfied": bool(payload.get("requirement_contract_match")),
            },
        ),
        "refusal_correctness": compute_refusal_correctness(case, {"status": result.get("status")}),
        "context_resolution_correct": (payload.get("context") or {}).get("resolution_correct"),
        "knowledge_source_hit_at_5": (payload.get("retrieval") or {}).get("knowledge_source_hit_at_5"),
        "retrieval_call_count": (payload.get("retrieval") or {}).get("retrieval_call_count", 0),
        "subquery_coverage": (payload.get("retrieval") or {}).get("subquery_coverage"),
        "hybrid_rescue_attempted": (payload.get("retrieval") or {}).get("hybrid_rescue_attempted", False),
        "hybrid_rescue_used": (payload.get("retrieval") or {}).get("hybrid_rescue_used", False),
        "merged_evidence_count": (payload.get("retrieval") or {}).get("merged_evidence_count", 0),
        "tool_calls": result.get("tool_calls_used", 0),
        "llm_calls_context": payload.get("llm_calls_context", 0),
        "llm_calls_planner": payload.get("llm_calls_planner", 0),
        "llm_calls_toolagent_decision": payload.get("llm_calls_toolagent_decision", 0),
        "llm_calls_repair": payload.get("llm_calls_repair", 0),
        "llm_calls_total": payload.get("llm_calls_total", 0),
        "latency_e2e_ms": (payload.get("timing") or {}).get("latency_e2e_ms", 0.0),
        "latency_context_ms": (payload.get("timing") or {}).get("latency_context_ms", 0.0),
        "latency_planner_ms": (payload.get("timing") or {}).get("latency_planner_ms", 0.0),
        "latency_retrieval_ms": (payload.get("timing") or {}).get("latency_retrieval_ms", 0.0),
        "latency_toolagent_ms": (payload.get("timing") or {}).get("latency_toolagent_ms", 0.0),
        "latency_verifier_ms": (payload.get("timing") or {}).get("latency_verifier_ms", 0.0),
        "latency_finalization_ms": (payload.get("timing") or {}).get("latency_finalization_ms", 0.0),
        "token_cost": "UNAVAILABLE",
    }
    return automatic


def _raw_record(case: Mapping[str, Any], plan_item: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    return {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": plan_item["system"],
        "run_order": plan_item["run_order"],
        "case_order": plan_item["case_order"],
        "run_validity": payload.get("execution_validity", "INVALID"),
        "infrastructure_code": payload.get("infrastructure_code"),
        "status": result.get("status"),
        "answer": result.get("answer"),
        "reason_code": result.get("reason_code"),
        "failure_code": result.get("failure_code"),
        "evidence": result.get("evidence", []),
        "evidence_kinds": sorted({item.get("kind") for item in result.get("evidence", []) if isinstance(item, Mapping) and item.get("kind")}),
        "tool_sequence": payload.get("tool_sequence", []),
        "tool_calls": result.get("tool_calls_used", 0),
        "iterations": result.get("iterations_used", 0),
        "tool_errors": result.get("tool_errors_used", 0),
        "retrieval": payload.get("retrieval", {}),
        "llm_calls": {
            "context": payload.get("llm_calls_context", 0),
            "planner": payload.get("llm_calls_planner", 0),
            "toolagent_decision": payload.get("llm_calls_toolagent_decision", 0),
            "repair": payload.get("llm_calls_repair", 0),
            "total": payload.get("llm_calls_total", 0),
        },
        "timing": payload.get("timing", {}),
        "token_usage": payload.get("token_usage", "UNAVAILABLE"),
        "context": payload.get("context", {}),
        "planner": payload.get("planner", {}),
    }


def _score_record(case: Mapping[str, Any], raw: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    score = {
        "case_id": case["case_id"],
        "task_family": case["task_family"],
        "system": raw["system"],
        "run_order": raw["run_order"],
        "run_validity": raw["run_validity"],
        "automatic_metrics": {},
    }
    if raw["run_validity"] == "VALID":
        score["automatic_metrics"] = _automatic_score(case, raw["system"], payload)
    return score


def _manual_template(case: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "system": raw["system"],
        "answer": raw.get("answer"),
        "evidence": raw.get("evidence", []),
        "gold_obligations": case["gold_obligations"],
        "source_proofs": case["source_proofs"],
        "task_success": "REVIEW_PENDING",
        "evidence_correctness": "REVIEW_PENDING",
        "grounding": "REVIEW_PENDING",
        "answer_obligation": "REVIEW_PENDING",
        "unsupported_claim": "REVIEW_PENDING",
        "citation_validity": "REVIEW_PENDING",
        "review_notes": "",
    }


def run_dev(config: RunConfig, *, repo_root: Path = REPO_ROOT) -> Path:
    """Run exactly one frozen 18-case Dev A/B execution."""

    manifest, cases = _preflight(config, repo_root)
    plan = build_run_plan(cases, config.split)
    corpus = config.corpus_checkout.resolve()
    raw_runs: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    with _isolated_checkouts(repo_root) as checkouts:
        validate_frozen_identities(
            system_heads={name: _git_head(checkouts[name]) for name in ("A", "B")},
            target_head=_git_head(checkouts["target"]),
            corpus_head=_git_head(corpus),
            protocol_sha=manifest["protocol_sha256"],
        )
        corpus_identity = _verify_corpus(corpus, checkouts)
        candidate_root = corpus / manifest["corpus_identity"]["path"]
        for item in plan:
            case = next(case for case in cases if case["case_id"] == item["case_id"])
            job = build_worker_job(
                case,
                system=item["system"],
                run_order=item["run_order"],
                case_order=item["case_order"],
                system_root=checkouts[item["system"]],
                target_root=checkouts["target"],
                corpus_root=candidate_root,
            )
            payload = _invoke_worker(job, checkouts[item["system"]], config.worker_timeout_seconds)
            if payload.get("execution_validity") == "VALID":
                provider_failure = payload.get("infrastructure_code")
                if provider_failure:
                    payload = dict(payload)
                    payload["execution_validity"] = "INVALID"
            raw = _raw_record(case, item, payload)
            score = _score_record(case, raw, payload)
            raw_runs.append(raw)
            scores.append(score)
            manual.append(_manual_template(case, raw))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_manifest = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "run_id": f"arch-eval-08b-dev-{timestamp}",
        "status": "COMPLETE" if len(raw_runs) == 36 else "INVALID",
        "split": DEV_SPLIT,
        "provider": {"name": config.provider, "model": config.model},
        "runner_baseline": BASELINE_COMMIT,
        "protocol": {"version": manifest["protocol_version"], "sha256": manifest["protocol_sha256"]},
        "system_identity": {"A": SYSTEM_A_COMMIT, "B": SYSTEM_B_COMMIT},
        "target_project": {"repository": TARGET_REPOSITORY, "project_id": TARGET_PROJECT_ID, "source_sha": TARGET_PROJECT_COMMIT},
        "corpus_identity": {"repository": CORPUS_REPOSITORY, "source_commit": CORPUS_SOURCE_COMMIT, **corpus_identity},
        "order_contract": manifest["run_order"],
        "context_contract": {"A": "current_question_only", "B": "frozen_conversation_context"},
        "expected_system_runs": 36,
        "observed_system_runs": len(raw_runs),
        "infrastructure_invalid_count": sum(run["run_validity"] != "VALID" for run in raw_runs),
        "manual_scoring": "NOT_DONE",
        "holdout": "NOT_RUN / DENY",
        "artifact_files": ["run_manifest.json", "raw_runs.jsonl", "automatic_scores.jsonl", "summary.json", "manual_review_template.jsonl"],
    }
    output = config.output_dir
    _write_json(output / "run_manifest.json", run_manifest)
    _write_jsonl(output / "raw_runs.jsonl", raw_runs)
    _write_jsonl(output / "automatic_scores.jsonl", scores)
    _write_json(output / "summary.json", build_summary(raw_runs, scores))
    _write_jsonl(output / "manual_review_template.jsonl", manual)
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run frozen ARCH-EVAL-08B Dev A/B")
    parser.add_argument("--split", default=DEV_SPLIT)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "evaluation" / "integration_v7" / "results" / "dev_v1"))
    args = parser.parse_args(argv)
    try:
        output = run_dev(
            RunConfig(corpus_checkout=Path(args.corpus_root), output_dir=Path(args.output_dir), split=args.split)
        )
    except (RunnerPreflightError, HoldoutExecutionDenied, ProtocolViolation):
        return 2
    print(output.name)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
