"""Run the frozen G12 Baseline A through two operator-started Engineering APIs.

The runner is evaluator-only. It neither starts APIs nor configures provider
credentials; it validates two already-bound public endpoints and sends each
frozen case exactly one payload containing only ``question``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
if str(EVALUATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_ROOT))

from evaluation.gate12.baseline_contract import (
    BaselineContractError,
    GATE12_DATASET_FREEZE_ID,
    InfrastructureFailure,
    PRODUCT_BASELINE_COMMIT,
    add_case_contract_flags,
    build_manual_review_entry,
    build_request_payload,
    derive_api_urls,
    load_frozen_final_dataset,
    normalize_case_result,
    route_case,
    sanitize_for_artifact,
    summarize_structural_metrics,
    validate_api_preflight,
    validate_baseline_artifact_safety,
    validate_distinct_roots,
    validate_product_baseline_attestation,
    validate_run_id,
)
from evaluation.gate12.candidate_contract import CandidateContractError
from scripts.validate_g12_candidate_pool import run_validation as run_candidate_pool_validation


GATE12_DIR = EVALUATOR_ROOT / "evaluation" / "gate12"
WORKFLOW_ID = "g12-baseline-a-v1"
DEFAULT_OUTPUT_ROOT = EVALUATOR_ROOT.parent / "rag数据集" / "benchmark_work" / "gate12" / "baseline_runs"


@dataclass(frozen=True)
class HttpReply:
    """A minimal injectable HTTP result for formal execution and offline tests."""

    status_code: int
    payload: object


HttpClient = Callable[[str, str, Mapping[str, Any] | None], HttpReply]


def urllib_http_client(method: str, url: str, payload: Mapping[str, Any] | None) -> HttpReply:
    """Perform one bounded HTTP request without capturing raw provider traffic."""

    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise InfrastructureFailure("endpoint returned invalid JSON") from exc
            return HttpReply(status_code=response.status, payload=parsed)
    except urllib.error.HTTPError as exc:
        return HttpReply(status_code=exc.code, payload=None)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise InfrastructureFailure("evaluator transport connection or timeout failure") from exc


def _get_json(client: HttpClient, url: str) -> Mapping[str, Any]:
    reply = client("GET", url, None)
    if reply.status_code != 200:
        raise InfrastructureFailure("endpoint preflight returned non-200 HTTP")
    if not isinstance(reply.payload, Mapping):
        raise InfrastructureFailure("endpoint preflight returned invalid response schema")
    return reply.payload


def _post_agent_case(client: HttpClient, url: str, case: Mapping[str, Any]) -> dict[str, Any]:
    reply = client("POST", url, build_request_payload(case))
    if reply.status_code != 200:
        raise InfrastructureFailure("engineering query returned non-200 HTTP")
    if not isinstance(reply.payload, dict):
        raise InfrastructureFailure("engineering query returned invalid response schema")
    return reply.payload


def _validate_output_root(output_root: str | Path, evaluator_root: Path) -> Path:
    root = Path(output_root).resolve()
    if root.exists() and not root.is_dir():
        raise BaselineContractError("output_root must be a directory path")
    try:
        root.relative_to(evaluator_root)
    except ValueError:
        return root
    raise BaselineContractError("output_root must be outside the tracked evaluator checkout")


def run_preflight(
    *,
    client: HttpClient,
    evaluator_git_root: str | Path,
    evaluator_commit: str,
    product_baseline_commit: str,
    my_agent_root: str | Path,
    pydantic_ai_root: str | Path,
    corpus_root: str | Path,
    my_agent_url: str,
    pydantic_ai_url: str,
) -> dict[str, Any]:
    """Complete all local and public preflight checks before case requests."""

    roots = validate_distinct_roots(
        evaluator_git_root, my_agent_root, pydantic_ai_root, corpus_root
    )
    dataset = load_frozen_final_dataset(GATE12_DIR)
    product = validate_product_baseline_attestation(
        evaluator_git_root=roots["evaluator"],
        evaluator_commit=evaluator_commit,
        product_baseline_commit=product_baseline_commit,
    )
    try:
        project_validation = run_candidate_pool_validation(
            my_agent_root=roots["my_agent"],
            pydantic_ai_root=roots["pydantic_ai"],
            corpus_root=roots["knowledge_corpus"],
        )
    except (CandidateContractError, OSError, subprocess.CalledProcessError) as exc:  # type: ignore[name-defined]
        raise BaselineContractError("frozen project checkout validation failed") from exc
    api_preflight = {
        "my_agent": validate_api_preflight(
            get_json=lambda url: _get_json(client, url),
            query_url=my_agent_url,
            project_root=roots["my_agent"],
        ),
        "pydantic_ai": validate_api_preflight(
            get_json=lambda url: _get_json(client, url),
            query_url=pydantic_ai_url,
            project_root=roots["pydantic_ai"],
        ),
    }
    return {
        "roots": roots,
        "dataset": dataset,
        "product": product,
        "project_validation": project_validation,
        "api_preflight": api_preflight,
    }


def _public_project_validation(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        project_id: details["checkout"]
        for project_id, details in report["projects"].items()
    }


def _build_manifest(
    *,
    run_id: str,
    label: str,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    dataset = preflight["dataset"]
    identity = dataset["identity"]
    product = preflight["product"]
    api_preflight = preflight["api_preflight"]
    return {
        "schema_version": "g12_baseline_a_manifest_v1",
        "workflow": WORKFLOW_ID,
        "run_id": run_id,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_classification": "VALID AGENT OUTCOMES / MANUAL GOLD PENDING",
        "baseline_definition": {
            "name": "Baseline A",
            "production_engineering_v2": True,
            "finalization_guard": "NOT IMPLEMENTED",
            "prompt_modified": False,
            "task_family_hint_injected": False,
            "gold_metadata_injected": False,
            "request_payload_fields": ["question"],
        },
        "frozen_dataset": identity,
        "case_ids": [case["case_id"] for case in dataset["cases"]],
        "case_source_candidates": {
            case["case_id"]: {
                "source_candidate_id": case["source_candidate_id"],
                "source_candidate_sha256": case["source_candidate_sha256"],
            }
            for case in dataset["cases"]
        },
        "evaluator": {
            "commit": product["evaluator_commit"],
            "commit_attestation": product["evaluator_commit_attestation"],
        },
        "product_baseline": {
            "commit": product["product_baseline_commit"],
            "source_paths": product["product_source_paths"],
            "source_diff_clean": product["product_source_diff_clean"],
            **product["product_identity"],
        },
        "project_checkouts": {
            project_id: {
                "project_checkout_commit": details["head"],
                "checkout_attestation": "locally_verified_exact_checkout",
                "runtime_binding_attestation": api_preflight[project_id]["runtime_binding_attestation"],
                "public_project_identity": api_preflight[project_id]["public_project_identity"],
                "query_endpoint": api_preflight[project_id]["endpoints"]["query"],
            }
            for project_id, details in _public_project_validation(preflight["project_validation"]).items()
        },
        "engineering_knowledge": api_preflight["my_agent"]["knowledge"],
        "api_preflight": {
            project_id: {
                "capabilities": details["capabilities"],
                "knowledge": details["knowledge"],
                "public_project_identity": details["public_project_identity"],
            }
            for project_id, details in api_preflight.items()
        },
        "manual_only_metrics": {
            "task_success": "NOT AUTO SCORED",
            "evidence_coverage": "NOT AUTO SCORED",
            "evidence_correctness": "NOT AUTO SCORED",
            "claim_grounding": "NOT AUTO SCORED",
            "remediation_correctness": "NOT AUTO SCORED",
            "docs_semantic_label_correctness": "NOT AUTO SCORED",
        },
        "absolute_paths_in_artifact": False,
        "raw_provider_responses_recorded": False,
        "private_cot_recorded": False,
        "full_prompt_recorded": False,
    }


def _write_report(
    path: Path, manifest: Mapping[str, Any], cases: list[Mapping[str, Any]], metrics: Mapping[str, Any]
) -> None:
    lines = [
        "# G12 Baseline A Evaluation Run",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- classification: `{manifest['run_classification']}`",
        f"- dataset freeze: `{manifest['frozen_dataset']['gate12_dataset_freeze_id']}`",
        f"- evaluator commit: `{manifest['evaluator']['commit']}`",
        f"- product baseline: `{manifest['product_baseline']['commit']}`",
        "- requests contain only the frozen case question; no task-family or Gold metadata is sent.",
        "- structural metrics are automatic; semantic answer quality remains Manual Gold work.",
        "",
        "## Metrics",
        "",
        "```json",
        json.dumps(metrics, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Cases",
        "",
    ]
    for case in cases:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- family/project: `{case['task_family']}` / `{case['project_id']}`",
                f"- status: `{case['status']}`",
                f"- reason/failure: `{case['reason_code']}` / `{case['failure_code']}`",
                f"- evidence sufficient/premature: `{case['evidence_sufficient']}` / `{case['premature_finalization']}`",
                f"- provider calls/repair: `{case['provider_call_count']}` / `{case['repair_attempted']}` / `{case['repair_succeeded']}`",
                f"- tool sequence: `{' -> '.join(case['tool_sequence']) or '(none)'}`",
                f"- structural layers: `{', '.join(case['structural_failure_layers']) or '(none)'}`",
                "",
                "#### Final answer",
                "",
                case["answer"] or "(no final answer)",
                "",
                "#### Public evidence",
                "",
                "```json",
                json.dumps(case["public_evidence"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_invalid_diagnostic(
    *, output: Path, run_id: str, case_id: str, completed_cases: int, message: str, roots: list[Path]
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    diagnostic = sanitize_for_artifact(
        {
            "schema_version": "g12_baseline_a_infrastructure_failure_v1",
            "run_id": run_id,
            "run_classification": "INVALID / INFRASTRUCTURE FAILURE",
            "failure_stage": "case_request",
            "case_id": case_id,
            "completed_case_count": completed_cases,
            "diagnostic_code": "HTTP_OR_RESPONSE_SCHEMA_FAILURE",
            "diagnostic_message": message,
            "baseline_conclusion": "NOT PRODUCED",
            "manual_gold": "NOT PRODUCED",
        },
        roots,
    )
    (output / "infrastructure_failure.json").write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validate_baseline_artifact_safety(output, roots)


def execute_baseline_a(
    *,
    client: HttpClient,
    my_agent_url: str,
    pydantic_ai_url: str,
    evaluator_git_root: str | Path,
    evaluator_commit: str,
    product_baseline_commit: str = PRODUCT_BASELINE_COMMIT,
    my_agent_root: str | Path,
    pydantic_ai_root: str | Path,
    corpus_root: str | Path,
    output_root: str | Path,
    run_id: str,
    label: str = "g12-baseline-a",
) -> Path:
    """Execute one complete Baseline A run after all preflight checks pass."""

    run_id = validate_run_id(run_id)
    preflight = run_preflight(
        client=client,
        evaluator_git_root=evaluator_git_root,
        evaluator_commit=evaluator_commit,
        product_baseline_commit=product_baseline_commit,
        my_agent_root=my_agent_root,
        pydantic_ai_root=pydantic_ai_root,
        corpus_root=corpus_root,
        my_agent_url=my_agent_url,
        pydantic_ai_url=pydantic_ai_url,
    )
    roots = list(preflight["roots"].values())
    output_base = _validate_output_root(output_root, preflight["roots"]["evaluator"])
    output = output_base / run_id
    if output.exists():
        raise FileExistsError("Baseline output run already exists")
    normalized_cases: list[dict[str, Any]] = []
    try:
        for case in preflight["dataset"]["cases"]:
            query_url = route_case(
                case, my_agent_url=my_agent_url, pydantic_ai_url=pydantic_ai_url
            )
            started = time.perf_counter()
            response = _post_agent_case(client, query_url, case)
            normalized = normalize_case_result(
                case,
                response,
                latency_ms=(time.perf_counter() - started) * 1000,
                roots=roots,
            )
            normalized_cases.append(add_case_contract_flags(normalized, case))
    except InfrastructureFailure as exc:
        _write_invalid_diagnostic(
            output=output,
            run_id=run_id,
            case_id=case["case_id"],
            completed_cases=len(normalized_cases),
            message=str(exc),
            roots=roots,
        )
        raise
    manifest = sanitize_for_artifact(
        _build_manifest(run_id=run_id, label=label, preflight=preflight), roots
    )
    metrics = summarize_structural_metrics(normalized_cases)
    manual_review = [
        build_manual_review_entry(case, result)
        for case, result in zip(preflight["dataset"]["cases"], normalized_cases, strict=True)
    ]
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "case_results.jsonl").open("w", encoding="utf-8") as handle:
        for result in normalized_cases:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    (output / "summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "manual_review_template.jsonl").open("w", encoding="utf-8") as handle:
        for entry in manual_review:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    validate_baseline_artifact_safety(output, roots)
    _write_report(output / "run_report.md", manifest, normalized_cases, metrics)
    validate_baseline_artifact_safety(output, roots)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen G12 Baseline A evaluator.")
    parser.add_argument("--my-agent-url", required=True)
    parser.add_argument("--pydantic-ai-url", required=True)
    parser.add_argument("--evaluator-git-root", required=True)
    parser.add_argument("--evaluator-commit", required=True)
    parser.add_argument("--product-baseline-commit", default=PRODUCT_BASELINE_COMMIT)
    parser.add_argument("--my-agent-root", required=True)
    parser.add_argument("--pydantic-ai-root", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--label", default="g12-baseline-a")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = execute_baseline_a(
            client=urllib_http_client,
            my_agent_url=args.my_agent_url,
            pydantic_ai_url=args.pydantic_ai_url,
            evaluator_git_root=args.evaluator_git_root,
            evaluator_commit=args.evaluator_commit,
            product_baseline_commit=args.product_baseline_commit,
            my_agent_root=args.my_agent_root,
            pydantic_ai_root=args.pydantic_ai_root,
            corpus_root=args.corpus_root,
            output_root=args.output_root,
            run_id=args.run_id,
            label=args.label,
        )
    except (BaselineContractError, InfrastructureFailure, FileExistsError) as exc:
        print(f"G12 Baseline A: INVALID / INFRASTRUCTURE FAILURE: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(output), "run_status": "VALID / MANUAL GOLD PENDING"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
