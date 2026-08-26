"""Run the frozen G12 System C benchmark through two operator-started APIs.

The runner is evaluator-only.  It does not start an API, call a provider, or
send evaluator metadata to the product.  Each request contains only ``question``.
"""

from __future__ import annotations

import argparse
import json
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

from evaluation.gate12.baseline_contract import (  # noqa: E402
    BaselineContractError,
    InfrastructureFailure,
    build_request_payload,
    derive_api_urls,
    load_frozen_final_dataset,
    route_case,
    sanitize_for_artifact,
    validate_distinct_roots,
    validate_run_id,
)
from evaluation.gate12.system_c_contract import (  # noqa: E402
    GATE12_DIR,
    SYSTEM_C_ACCEPTANCE_CONTRACT_SHA256,
    SYSTEM_C_BASELINE_METRICS,
    SYSTEM_C_MANIFEST_SCHEMA,
    SYSTEM_C_PRODUCT_COMMIT,
    SYSTEM_C_WORKFLOW_ID,
    add_system_c_case_flags,
    build_acceptance_snapshot,
    build_system_c_manual_review_entry,
    evaluate_system_c_acceptance,
    load_system_c_acceptance_contract,
    normalize_system_c_case,
    summarize_system_c_metrics,
    validate_system_c_artifact_safety,
    validate_system_c_product_attestation,
)
from scripts.validate_g12_candidate_pool import run_validation as run_candidate_pool_validation  # noqa: E402


DEFAULT_OUTPUT_ROOT = (
    EVALUATOR_ROOT.parent / "rag数据集" / "benchmark_work" / "gate12" / "system_c_runs"
)


@dataclass(frozen=True)
class HttpReply:
    status_code: int
    payload: object


HttpClient = Callable[[str, str, Mapping[str, Any] | None], HttpReply]


def urllib_http_client(
    method: str, url: str, payload: Mapping[str, Any] | None
) -> HttpReply:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            try:
                parsed = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InfrastructureFailure("endpoint returned invalid JSON") from exc
            return HttpReply(status_code=response.status, payload=parsed)
    except urllib.error.HTTPError as exc:
        return HttpReply(status_code=exc.code, payload=None)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise InfrastructureFailure("evaluator transport connection or timeout failure") from exc


def _get_json(client: HttpClient, url: str) -> Mapping[str, Any]:
    reply = client("GET", url, None)
    if reply.status_code != 200 or not isinstance(reply.payload, Mapping):
        raise InfrastructureFailure("endpoint preflight returned invalid HTTP/schema")
    return reply.payload


def _post_case(client: HttpClient, url: str, case: Mapping[str, Any]) -> dict[str, Any]:
    reply = client("POST", url, build_request_payload(case))
    if reply.status_code != 200 or not isinstance(reply.payload, dict):
        raise InfrastructureFailure("engineering query returned invalid HTTP/schema")
    return reply.payload


def _validate_output_root(output_root: str | Path, evaluator_root: Path) -> Path:
    root = Path(output_root).resolve()
    if root.exists() and not root.is_dir():
        raise BaselineContractError("output_root must be a directory")
    try:
        root.relative_to(evaluator_root)
    except ValueError:
        return root
    raise BaselineContractError("output_root must be outside tracked evaluator checkout")


def _validate_api_preflight(
    client: HttpClient,
    query_url: str,
    project_root: Path,
    expected_project_name: str,
) -> dict[str, Any]:
    urls = derive_api_urls(query_url)
    capabilities = _get_json(client, urls["capabilities"])
    if capabilities.get("schema_version") != "capabilities_response_v1":
        raise InfrastructureFailure("capabilities response schema mismatch")
    features = capabilities.get("features")
    if not isinstance(features, Mapping) or features.get("engineering_agent") is not True:
        raise InfrastructureFailure("engineering_agent capability is unavailable")
    knowledge = _get_json(client, urls["knowledge"])
    expected_knowledge = {
        "schema_version": "engineering_knowledge_status_v1",
        "ready": True,
        "verified": True,
        "corpus_id": "870e5864df67",
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": "dbc497c796d5",
    }
    if {key: knowledge.get(key) for key in expected_knowledge} != expected_knowledge:
        raise InfrastructureFailure("Engineering Knowledge identity mismatch")
    project = _get_json(client, urls["project"])
    if project.get("source") != "configured" or project.get("project_name") != expected_project_name:
        raise InfrastructureFailure("/project does not match bound checkout identity")
    return {
        "endpoints": urls,
        "capabilities": {"schema_version": capabilities["schema_version"], "engineering_agent": True},
        "knowledge": expected_knowledge,
        "public_project_identity": {
            "project_name": expected_project_name,
            "source": "configured",
        },
        "runtime_binding_attestation": (
            "operator_started_api_with_configured_project_root; /project identity does not prove Git SHA"
        ),
    }


def run_preflight(
    *,
    client: HttpClient,
    evaluator_git_root: str | Path,
    evaluator_commit: str,
    my_agent_root: str | Path,
    pydantic_ai_root: str | Path,
    corpus_root: str | Path,
    my_agent_url: str,
    pydantic_ai_url: str,
    system_c_product_commit: str = SYSTEM_C_PRODUCT_COMMIT,
) -> dict[str, Any]:
    acceptance_contract = load_system_c_acceptance_contract()
    roots = validate_distinct_roots(
        evaluator_git_root, my_agent_root, pydantic_ai_root, corpus_root
    )
    dataset = load_frozen_final_dataset(GATE12_DIR)
    product = validate_system_c_product_attestation(
        evaluator_git_root=roots["evaluator"],
        evaluator_commit=evaluator_commit,
        system_c_product_commit=system_c_product_commit,
    )
    try:
        project_validation = run_candidate_pool_validation(
            my_agent_root=roots["my_agent"],
            pydantic_ai_root=roots["pydantic_ai"],
            corpus_root=roots["knowledge_corpus"],
        )
    except Exception as exc:
        raise BaselineContractError("frozen project checkout validation failed") from exc
    api_preflight = {
        "my_agent": _validate_api_preflight(
            client, my_agent_url, roots["my_agent"], roots["my_agent"].name
        ),
        "pydantic_ai": _validate_api_preflight(
            client, pydantic_ai_url, roots["pydantic_ai"], roots["pydantic_ai"].name
        ),
    }
    return {
        "roots": roots,
        "dataset": dataset,
        "acceptance_contract": acceptance_contract,
        "product": product,
        "project_validation": project_validation,
        "api_preflight": api_preflight,
    }


def _project_validation_by_id(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return report["projects"]


def build_system_c_manifest(
    *,
    run_id: str,
    label: str,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    dataset = preflight["dataset"]
    product = preflight["product"]
    contract = preflight["acceptance_contract"]
    project_validation = _project_validation_by_id(preflight["project_validation"])
    return {
        "schema_version": SYSTEM_C_MANIFEST_SCHEMA,
        "workflow": SYSTEM_C_WORKFLOW_ID,
        "run_id": run_id,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_status": "VALID / MANUAL GOLD PENDING",
        "final_classification": "PENDING_MANUAL_REVIEW",
        "frozen_dataset": dataset["identity"],
        "acceptance_contract": {
            "sha256": contract["acceptance_contract_sha256"],
            "schema_version": contract["schema_version"],
        },
        "baseline_comparison": {
            "baseline_run_id": contract["baseline"]["run_id"],
            "baseline_product_commit": contract["baseline"]["product_baseline_commit"],
            "baseline_metrics": dict(SYSTEM_C_BASELINE_METRICS),
            "manual_task_success_comparison": "PENDING MANUAL GOLD",
        },
        "system_c_factor": {
            "product_commit": product["system_c_product_commit"],
            "product_commit_attestation": product["system_c_product_commit_attestation"],
            "intervention": [
                "deterministic typed Evidence Requirement",
                "system-level Finalization Guard",
            ],
            "prompt_modified": False,
            "task_family_hint_injected": False,
            "gold_metadata_injected": False,
            "request_payload_fields": ["question"],
        },
        "evaluator": {
            "commit": product["evaluator_commit"],
            "commit_attestation": product["evaluator_commit_attestation"],
        },
        "product_identity": product["product_identity"],
        "product_source_attestation": {
            "source_paths": product["product_source_paths"],
            "current_product_diff_clean": product["current_product_diff_clean"],
            "allowed_intervention_paths": product["allowed_intervention_paths"],
            "observed_intervention_paths": product["observed_intervention_paths"],
            "intervention_diff_summary": product["intervention_diff_summary"],
        },
        "project_checkouts": {
            project_id: {
                "project_checkout_commit": project_validation[project_id]["checkout"]["head"],
                "checkout_attestation": "locally_verified_exact_checkout",
                "runtime_binding_attestation": preflight["api_preflight"][project_id]["runtime_binding_attestation"],
                "public_project_identity": preflight["api_preflight"][project_id]["public_project_identity"],
                "query_endpoint": preflight["api_preflight"][project_id]["endpoints"]["query"],
            }
            for project_id in ("my_agent", "pydantic_ai")
        },
        "engineering_knowledge": preflight["api_preflight"]["my_agent"]["knowledge"],
        "api_preflight": {
            project_id: {
                "capabilities": preflight["api_preflight"][project_id]["capabilities"],
                "knowledge": preflight["api_preflight"][project_id]["knowledge"],
                "public_project_identity": preflight["api_preflight"][project_id]["public_project_identity"],
            }
            for project_id in ("my_agent", "pydantic_ai")
        },
        "manual_only_metrics": {
            "full_task_success": "NOT SCORED",
            "partial_or_better": "NOT SCORED",
            "evidence_coverage": "NOT SCORED",
            "evidence_correctness": "NOT SCORED",
            "claim_grounding": "NOT SCORED",
            "remediation_correctness": "NOT SCORED",
            "docs_semantic_label_correctness": "NOT SCORED",
        },
        "artifact_safety": {
            "absolute_paths_in_artifact": False,
            "raw_provider_responses_recorded": False,
            "private_cot_recorded": False,
            "full_prompt_recorded": False,
            "request_payload_contains_only_question": True,
        },
    }


def _write_run_report(
    path: Path,
    manifest: Mapping[str, Any],
    cases: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    lines = [
        "# G12 System C Evaluation Run",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- workflow status: `{manifest['run_status']}`",
        f"- final classification: `{manifest['final_classification']}`",
        f"- dataset freeze: `{manifest['frozen_dataset']['gate12_dataset_freeze_id']}`",
        f"- acceptance contract: `{manifest['acceptance_contract']['sha256']}`",
        f"- System C product commit: `{manifest['system_c_factor']['product_commit']}`",
        "- Each request contains only the frozen case question; no Gold, case, family, or requirement metadata is sent.",
        "- Evidence Sufficiency and Guard metrics are evaluator-side automatic structural diagnostics.",
        "- Manual Task Success, Evidence Coverage/Correctness, Claim Grounding, and Docs labels remain pending.",
        "",
        "## Frozen Baseline A",
        "",
        "```json",
        json.dumps(manifest["baseline_comparison"]["baseline_metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Automatic Gate Snapshot",
        "",
        "```json",
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Automatic Metrics",
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
                f"- evidence sufficient/premature: `{case['evidence_sufficient']}` / `{case['premature_finalization']}`",
                f"- Guard blocks/recovery/refusal: `{case['guard_block_count']}` / `{case['guard_recovery_succeeded']}` / `{case['guard_final_refusal']}`",
                f"- provider/tool/iterations: `{case['provider_call_count']}` / `{case['tool_calls_used']}` / `{case['iterations_used']}`",
                f"- tool sequence: `{' -> '.join(case['tool_sequence']) or '(none)'}`",
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


def execute_system_c(
    *,
    client: HttpClient,
    my_agent_url: str,
    pydantic_ai_url: str,
    evaluator_git_root: str | Path,
    evaluator_commit: str,
    my_agent_root: str | Path,
    pydantic_ai_root: str | Path,
    corpus_root: str | Path,
    output_root: str | Path,
    run_id: str,
    label: str = "g12-system-c",
    system_c_product_commit: str = SYSTEM_C_PRODUCT_COMMIT,
) -> Path:
    run_id = validate_run_id(run_id)
    preflight = run_preflight(
        client=client,
        evaluator_git_root=evaluator_git_root,
        evaluator_commit=evaluator_commit,
        my_agent_root=my_agent_root,
        pydantic_ai_root=pydantic_ai_root,
        corpus_root=corpus_root,
        my_agent_url=my_agent_url,
        pydantic_ai_url=pydantic_ai_url,
        system_c_product_commit=system_c_product_commit,
    )
    roots = list(preflight["roots"].values())
    output_base = _validate_output_root(output_root, preflight["roots"]["evaluator"])
    output = output_base / run_id
    if output.exists():
        raise FileExistsError("System C output run already exists")
    normalized_cases: list[dict[str, Any]] = []
    try:
        for case in preflight["dataset"]["cases"]:
            endpoint = route_case(
                case, my_agent_url=my_agent_url, pydantic_ai_url=pydantic_ai_url
            )
            started = time.perf_counter()
            response = _post_case(client, endpoint, case)
            normalized = normalize_system_c_case(
                case,
                response,
                latency_ms=(time.perf_counter() - started) * 1000,
                roots=roots,
            )
            normalized_cases.append(add_system_c_case_flags(normalized, case))
    except InfrastructureFailure as exc:
        output.mkdir(parents=True, exist_ok=False)
        diagnostic = sanitize_for_artifact(
            {
                "schema_version": "g12_system_c_infrastructure_failure_v1",
                "run_id": run_id,
                "run_status": "INVALID / INFRASTRUCTURE FAILURE",
                "final_classification": "INVALID",
                "failure_stage": "case_request",
                "completed_case_count": len(normalized_cases),
                "diagnostic_code": "HTTP_OR_RESPONSE_SCHEMA_FAILURE",
                "diagnostic_message": str(exc),
                "baseline_conclusion": "NOT PRODUCED",
                "manual_gold": "NOT PRODUCED",
            },
            roots,
        )
        (output / "infrastructure_failure.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        validate_system_c_artifact_safety(output, roots)
        raise
    manifest = sanitize_for_artifact(
        build_system_c_manifest(run_id=run_id, label=label, preflight=preflight), roots
    )
    metrics = summarize_system_c_metrics(normalized_cases)
    snapshot = build_acceptance_snapshot(metrics)
    manual_review = [
        build_system_c_manual_review_entry(case, result)
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
    (output / "acceptance_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "manual_review_template.jsonl").open("w", encoding="utf-8") as handle:
        for entry in manual_review:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _write_run_report(output / "run_report.md", manifest, normalized_cases, metrics, snapshot)
    validate_system_c_artifact_safety(output, roots)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen G12 System C evaluator.")
    parser.add_argument("--my-agent-url", required=True)
    parser.add_argument("--pydantic-ai-url", required=True)
    parser.add_argument("--evaluator-git-root", required=True)
    parser.add_argument("--evaluator-commit", required=True)
    parser.add_argument("--my-agent-root", required=True)
    parser.add_argument("--pydantic-ai-root", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--label", default="g12-system-c")
    parser.add_argument("--system-c-product-commit", default=SYSTEM_C_PRODUCT_COMMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = execute_system_c(
            client=urllib_http_client,
            my_agent_url=args.my_agent_url,
            pydantic_ai_url=args.pydantic_ai_url,
            evaluator_git_root=args.evaluator_git_root,
            evaluator_commit=args.evaluator_commit,
            my_agent_root=args.my_agent_root,
            pydantic_ai_root=args.pydantic_ai_root,
            corpus_root=args.corpus_root,
            output_root=args.output_root,
            run_id=args.run_id,
            label=args.label,
            system_c_product_commit=args.system_c_product_commit,
        )
    except (BaselineContractError, InfrastructureFailure, FileExistsError) as exc:
        print(f"G12 System C: INVALID / INFRASTRUCTURE FAILURE: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output": str(output),
                "run_status": "VALID / MANUAL GOLD PENDING",
                "final_classification": "PENDING_MANUAL_REVIEW",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
