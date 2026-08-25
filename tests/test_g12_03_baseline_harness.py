"""Offline deterministic tests for the G12 Baseline A evaluator harness."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

import evaluation.gate12.baseline_contract as contract
from evaluation.gate12.candidate_contract import validate_repository_checkout
from evaluation.gate12.baseline_contract import (
    BaselineContractError,
    InfrastructureFailure,
    add_case_contract_flags,
    build_manual_review_entry,
    build_request_payload,
    evaluate_evidence_shape,
    load_frozen_final_dataset,
    normalize_case_result,
    route_case,
    summarize_structural_metrics,
    validate_api_preflight,
    validate_baseline_artifact_safety,
    validate_distinct_roots,
    validate_frozen_dataset_identity,
    validate_product_baseline_attestation,
)
from scripts import run_g12_baseline_a as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE12_DIR = REPO_ROOT / "evaluation" / "gate12"


def _response(
    *,
    status: str = "completed",
    answer: str | None = "bounded answer",
    failure_code: str | None = None,
    reason_code: str | None = None,
    trace: list[dict] | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "engineering_query_response_v1",
        "status": status,
        "answer": answer,
        "reason_code": reason_code,
        "failure_code": failure_code,
        "iterations_used": 2,
        "tool_calls_used": 1,
        "tool_errors_used": 0,
        "trace": trace or [],
        "evidence": evidence or [],
    }


def _project_evidence(kind: str, path: str, *, evidence_id: str = "E1") -> dict:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "path": path,
        "start_line": 1,
        "end_line": 3,
        "snippet": "def verified_behavior():\n    return True\n",
    }


def _knowledge_evidence() -> dict:
    return {
        "evidence_id": "E1",
        "kind": "knowledge",
        "source_name": "tool_calling/工具设计.md",
        "chunk_id": "chunk-1",
        "score": 1.0,
        "rank": 1,
        "snippet": "bounded knowledge",
    }


def _case(case_id: str) -> dict:
    return next(case for case in load_frozen_final_dataset(GATE12_DIR)["cases"] if case["case_id"] == case_id)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return completed.stdout.strip()


def _temporary_git_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "g12@example.test")
    _git(root, "config", "user.name", "G12 Test")
    (root / "core").mkdir()
    (root / "core" / "baseline.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root, _git(root, "rev-parse", "HEAD")


def _valid_preflight() -> dict:
    dataset = load_frozen_final_dataset(GATE12_DIR)
    roots = {
        "evaluator": REPO_ROOT,
        "my_agent": REPO_ROOT,
        "pydantic_ai": REPO_ROOT,
        "knowledge_corpus": REPO_ROOT,
    }
    api = {
        project_id: {
            "endpoints": {"query": f"http://{project_id}.test/engineering/query"},
            "capabilities": {"schema_version": "capabilities_response_v1", "engineering_agent": True},
            "knowledge": contract.KNOWLEDGE_STATUS,
            "public_project_identity": {"project_name": project_id, "source": "configured"},
            "runtime_binding_attestation": "operator_started_api_with_configured_project_root",
        }
        for project_id in ("my_agent", "pydantic_ai")
    }
    return {
        "roots": roots,
        "dataset": dataset,
        "product": {
            "evaluator_commit": "1" * 40,
            "evaluator_commit_attestation": "locally_verified",
            "product_baseline_commit": contract.PRODUCT_BASELINE_COMMIT,
            "product_source_paths": ["core/", "api/", "demo/", "config.yaml"],
            "product_source_diff_clean": True,
            "product_identity": contract.validate_product_identity(),
        },
        "project_validation": {
            "projects": {
                "my_agent": {"checkout": {"head": contract.MY_AGENT_COMMIT}},
                "pydantic_ai": {"checkout": {"head": contract.PYDANTIC_AI_COMMIT}},
            }
        },
        "api_preflight": api,
    }


def test_exact_16_frozen_identities_and_hashes_are_bound_before_requests():
    dataset = load_frozen_final_dataset(GATE12_DIR)

    assert [case["case_id"] for case in dataset["cases"]] == [f"g12q{index:03d}" for index in range(1, 17)]
    assert dataset["identity"] == {
        "gate12_dataset_freeze_id": "gate12-v1-630fc8b527c2",
        "final_benchmark_sha256": "630fc8b527c22d3e7afc4f4288788524f5dfb52f5ed6ade13ec050abc35f215f",
        "reviewer_selection_sha256": "53d93f34a43a3de62a159fc0c8029062ec9390f1d2dfc5cab6d67589b8d98d18",
        "candidate_pool_sha256": "d3d217066b72deaaa6bb9f0f20a84b1e97940f16214d96b8f614ed14dd3935b8",
        "repository_manifest_sha256": "392279dc0348723ddfebef4eefb1fa269f7b4d67a534c63a4de2344a5571ba43",
    }


def test_baseline_manual_gold_and_correction_artifacts_are_frozen():
    manual_path = GATE12_DIR / "baseline_a_manual_review_v1.jsonl"
    manual_manifest = json.loads(
        (GATE12_DIR / "baseline_a_manual_review_manifest_v1.json").read_text(encoding="utf-8")
    )
    manual = [json.loads(line) for line in manual_path.read_text(encoding="utf-8").splitlines()]

    assert manual_manifest["run_id"] == contract.BASELINE_A_FORMAL_RUN_ID
    assert manual_manifest["evaluator_commit"] == contract.BASELINE_A_EVALUATOR_COMMIT
    assert manual_manifest["formal_manifest_sha256"] == contract.BASELINE_A_FORMAL_MANIFEST_SHA256
    assert manual_manifest["case_count"] == 16
    assert manual_manifest["case_ids"] == [f"g12q{index:03d}" for index in range(1, 17)]
    assert manual_manifest["manual_review_sha256"] == contract.file_sha256(manual_path)
    assert manual_manifest["original_manual_review_template_sha256"] == contract.BASELINE_A_MANUAL_TEMPLATE_SHA256
    assert {item["case_id"] for item in manual} == set(manual_manifest["case_ids"])
    assert sum(item["full_task_success"] == "PASS" for item in manual) == 2
    assert sum(item["full_task_success"] == "PARTIAL" for item in manual) == 8
    assert sum(item["full_task_success"] == "FAIL" for item in manual) == 6
    by_id = {item["case_id"]: item for item in manual}
    assert manual_manifest["reviewer_verdicts"] == {
        item["case_id"]: {
            key: item[key]
            for key in ("full_task_success", "evidence_coverage", "claim_grounding", "evidence_correctness")
        }
        for item in manual
    }
    assert by_id["g12q004"]["evidence_coverage"] == "PARTIAL"
    assert by_id["g12q004"]["full_task_success"] == "PARTIAL"
    assert by_id["g12q006"]["evidence_coverage"] == "PARTIAL"
    assert by_id["g12q006"]["full_task_success"] == "PASS"

    correction = json.loads(
        (GATE12_DIR / "baseline_a_metric_correction_v1.json").read_text(encoding="utf-8")
    )
    assert correction["run_id"] == contract.BASELINE_A_FORMAL_RUN_ID
    assert correction["formal_manifest_sha256"] == contract.BASELINE_A_FORMAL_MANIFEST_SHA256
    assert correction["case_results_sha256"] == contract.BASELINE_A_CASE_RESULTS_SHA256
    assert sum(correction["case_provider_call_counts"].values()) == 54
    assert correction["original_summary_values"] == {
        "provider_calls_total": 17,
        "avg_provider_calls": 1.0625,
    }
    assert correction["corrected_summary_values"] == {
        "provider_calls_total": 54,
        "avg_provider_calls": 3.375,
    }


def test_dataset_hash_mismatch_fails_before_request():
    dataset = load_frozen_final_dataset(GATE12_DIR)
    manifest = deepcopy(dataset["final_manifest"])
    manifest["gate12_dataset_freeze_id"] = "gate12-v1-deadbeef0000"

    with pytest.raises(BaselineContractError, match="dataset identity"):
        validate_frozen_dataset_identity(
            manifest,
            dataset["candidate_manifest"],
            final_benchmark_sha256=dataset["identity"]["final_benchmark_sha256"],
            reviewer_selection_sha256=dataset["identity"]["reviewer_selection_sha256"],
            repository_manifest_sha256=dataset["identity"]["repository_manifest_sha256"],
        )


def test_evaluator_wrong_head_and_tracked_dirty_are_rejected(tmp_path: Path):
    root, head = _temporary_git_repo(tmp_path)

    with pytest.raises(ValueError, match="evaluator_commit"):
        validate_product_baseline_attestation(
            evaluator_git_root=root,
            evaluator_commit="0" * 40,
            product_baseline_commit=contract.PRODUCT_BASELINE_COMMIT,
        )

    (root / "core" / "baseline.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tracked modifications"):
        validate_product_baseline_attestation(
            evaluator_git_root=root,
            evaluator_commit=head,
            product_baseline_commit=contract.PRODUCT_BASELINE_COMMIT,
        )


def test_product_source_diff_from_baseline_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, base = _temporary_git_repo(tmp_path)
    (root / "core" / "baseline.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "product drift")
    head = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(contract, "PRODUCT_BASELINE_COMMIT", base)

    with pytest.raises(BaselineContractError, match="production source differs"):
        validate_product_baseline_attestation(
            evaluator_git_root=root,
            evaluator_commit=head,
            product_baseline_commit=base,
        )


def test_reused_project_checkout_validator_rejects_wrong_head_and_tracked_dirty(tmp_path: Path):
    root, head = _temporary_git_repo(tmp_path)
    origin = "https://example.test/my_agent.git"
    _git(root, "remote", "add", "origin", origin)
    registry = {"my_agent": {"project_source_commit": "0" * 40, "origin_url": origin}}

    with pytest.raises(contract.CandidateContractError, match="project HEAD mismatch"):
        validate_repository_checkout("my_agent", root, registry)

    registry["my_agent"]["project_source_commit"] = head
    (root / "core" / "baseline.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(contract.CandidateContractError, match="tracked-dirty"):
        validate_repository_checkout("my_agent", root, registry)


def test_same_evaluator_and_project_root_is_rejected(tmp_path: Path):
    evaluator = tmp_path / "evaluator"
    other = tmp_path / "other"
    evaluator.mkdir()
    other.mkdir()

    with pytest.raises(BaselineContractError, match="distinct roots"):
        validate_distinct_roots(evaluator, evaluator, other, other)


def test_two_project_routing_and_request_payload_never_include_gold_metadata():
    my_case = _case("g12q001")
    external_case = _case("g12q003")

    assert route_case(
        my_case,
        my_agent_url="http://my.test/engineering/query",
        pydantic_ai_url="http://pydantic.test/engineering/query",
    ) == "http://my.test/engineering/query"
    assert route_case(
        external_case,
        my_agent_url="http://my.test/engineering/query",
        pydantic_ai_url="http://pydantic.test/engineering/query",
    ) == "http://pydantic.test/engineering/query"
    assert build_request_payload(my_case) == {"question": my_case["question"]}
    assert set(build_request_payload(my_case)) == {"question"}


def test_api_preflight_requires_configured_public_project_identity():
    root = REPO_ROOT
    urls = contract.derive_api_urls("http://api.test/engineering/query")
    responses = {
        urls["capabilities"]: {"schema_version": "capabilities_response_v1", "features": {"engineering_agent": True}},
        urls["knowledge"]: contract.KNOWLEDGE_STATUS,
        urls["project"]: {"project_name": root.name, "source": "configured"},
    }

    assert validate_api_preflight(
        get_json=responses.__getitem__, query_url=urls["query"], project_root=root
    )["public_project_identity"] == {"project_name": root.name, "source": "configured"}
    responses[urls["project"]] = {"project_name": root.name, "source": "default_repo"}
    with pytest.raises(InfrastructureFailure, match="configured"):
        validate_api_preflight(get_json=responses.__getitem__, query_url=urls["query"], project_root=root)


@pytest.mark.parametrize(
    ("status", "answer", "reason_code", "failure_code"),
    [
        ("completed", "answer", None, None),
        ("refused", None, "INSUFFICIENT_INFORMATION", None),
        ("failed", None, None, "ACTION_PARSE_FAILED"),
    ],
)
def test_all_http_200_agent_terminal_statuses_are_valid(
    status: str, answer: str | None, reason_code: str | None, failure_code: str | None
):
    result = normalize_case_result(
        _case("g12q001"),
        _response(status=status, answer=answer, reason_code=reason_code, failure_code=failure_code),
        latency_ms=1,
        roots=[REPO_ROOT],
    )

    assert result["status"] == status


def test_non_200_http_is_infrastructure_failure():
    case = _case("g12q001")
    client = lambda method, url, payload: runner.HttpReply(status_code=503, payload=None)

    with pytest.raises(InfrastructureFailure, match="non-200"):
        runner._post_agent_case(client, "http://api.test/engineering/query", case)


def test_and_of_or_evidence_sufficiency_and_cross_file_path_rule():
    theory = _case("g12q001")
    sufficient = evaluate_evidence_shape(
        theory, [_knowledge_evidence(), _project_evidence("project_code", "core/tool_agent/registry.py", evidence_id="E2")]
    )
    insufficient = evaluate_evidence_shape(theory, [_project_evidence("project_code", "core/tool_agent/registry.py")])
    assert sufficient["evidence_sufficient"] is True
    assert insufficient["missing_evidence_groups"] == [["knowledge"]]

    diagnosis = _case("g12q009")
    one_path = evaluate_evidence_shape(diagnosis, [_project_evidence("project_code", "core/conversation_context/models.py")])
    two_paths = evaluate_evidence_shape(
        diagnosis,
        [
            _project_evidence("project_code", "core/conversation_context/models.py"),
            _project_evidence("project_code", "core/conversation_context/resolver.py", evidence_id="E2"),
        ],
    )
    assert one_path["cross_file_shape_satisfied"] is False
    assert two_paths["cross_file_shape_satisfied"] is True


def test_completed_insufficient_is_premature_but_refused_is_not():
    case = _case("g12q001")
    completed = normalize_case_result(case, _response(), latency_ms=1, roots=[REPO_ROOT])
    refused = normalize_case_result(
        case,
        _response(status="refused", answer=None, reason_code="INSUFFICIENT_INFORMATION"),
        latency_ms=1,
        roots=[REPO_ROOT],
    )

    assert completed["premature_finalization"] is True
    assert refused["premature_finalization"] is False


def test_provider_calls_sum_decision_metadata_and_parse_repair_are_case_level():
    trace = [
        {"event_type": "decision_completed", "provider_call_count": 1, "repair_attempted": False},
        {
            "event_type": "decision_completed",
            "provider_call_count": 2,
            "repair_attempted": True,
            "repair_succeeded": True,
            "parse_failure_category": "ARGUMENTS_SCHEMA_INVALID",
        },
        {"event_type": "decision_completed", "provider_call_count": 1, "repair_attempted": False},
        {"event_type": "runtime_stopped", "error_code": "AGENT_DUPLICATE_TOOL_CALL"},
    ]
    result = normalize_case_result(
        _case("g12q001"), _response(trace=trace), latency_ms=1, roots=[REPO_ROOT]
    )

    assert result["provider_call_count"] == 4
    assert result["repair_attempted"] is True
    assert result["repair_succeeded"] is True
    assert result["initial_parse_categories"] == ["ARGUMENTS_SCHEMA_INVALID"]
    assert result["duplicate_tool_stop"] is True
    assert "L1 Transport / Parsing" in result["structural_failure_layers"]
    assert "L2 Planning / Tool-loop" in result["structural_failure_layers"]


def test_provider_call_count_sums_four_normal_decisions():
    trace = [
        {"event_type": "decision_completed", "provider_call_count": 1}
        for _ in range(4)
    ]
    result = normalize_case_result(
        _case("g12q001"), _response(trace=trace), latency_ms=1, roots=[REPO_ROOT]
    )

    assert result["provider_call_count"] == 4


def test_automatic_metrics_are_structural_only_and_cover_family_repository_slices():
    first = add_case_contract_flags(
        normalize_case_result(_case("g12q001"), _response(), latency_ms=1, roots=[REPO_ROOT]),
        _case("g12q001"),
    )
    second = add_case_contract_flags(
        normalize_case_result(
            _case("g12q009"),
            _response(evidence=[
                _project_evidence("project_code", "core/conversation_context/models.py"),
                _project_evidence("project_code", "core/conversation_context/resolver.py", evidence_id="E2"),
            ]),
            latency_ms=2,
            roots=[REPO_ROOT],
        ),
        _case("g12q009"),
    )
    metrics = summarize_structural_metrics([first, second])

    assert metrics["overall"]["case_count"] == 2
    assert metrics["overall"]["premature_finalization_cases"] == 1
    assert metrics["overall"]["cross_file_shape_satisfied_cases"] == 1
    assert metrics["manual_only_metrics"]["task_success"] == "NOT AUTO SCORED"
    assert set(metrics["by_task_family"]) == {"Diagnosis / Config", "Theory <-> Code"}


def test_artifact_safety_rejects_absolute_paths_and_sensitive_raw_fields(tmp_path: Path):
    (tmp_path / "bad.json").write_text(
        json.dumps({"answer": "C:\\secret\\source.py"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unsafe local path"):
        validate_baseline_artifact_safety(tmp_path, [REPO_ROOT])

    (tmp_path / "bad.json").write_text(json.dumps({"raw_model_output": "private"}), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="forbidden sensitive field"):
        validate_baseline_artifact_safety(tmp_path, [REPO_ROOT])

    (tmp_path / "bad.json").unlink()
    (tmp_path / "bad.md").write_text(
        "# Report\n\n```json\n{\"private_cot\": \"not allowed\"}\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(BaselineContractError, match="forbidden sensitive field"):
        validate_baseline_artifact_safety(tmp_path, [REPO_ROOT])


def test_successful_fake_two_api_run_routes_all_cases_and_writes_manual_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def fake_client(method: str, url: str, payload: Mapping[str, Any] | None) -> runner.HttpReply:
        calls.append((method, url, payload))
        return runner.HttpReply(status_code=200, payload=_response())

    monkeypatch.setattr(runner, "run_preflight", lambda **kwargs: _valid_preflight())
    monkeypatch.setattr(runner, "_validate_output_root", lambda output_root, evaluator_root: tmp_path)
    output = runner.execute_baseline_a(
        client=fake_client,
        my_agent_url="http://my.test/engineering/query",
        pydantic_ai_url="http://pydantic.test/engineering/query",
        evaluator_git_root=REPO_ROOT,
        evaluator_commit="1" * 40,
        my_agent_root=REPO_ROOT,
        pydantic_ai_root=REPO_ROOT,
        corpus_root=REPO_ROOT,
        output_root=tmp_path,
        run_id="offline-fake-run",
    )

    assert len(calls) == 16
    assert all(method == "POST" and set(payload or ()) == {"question"} for method, _, payload in calls)
    assert sum("my.test" in url for _, url, _ in calls) == 8
    assert sum("pydantic.test" in url for _, url, _ in calls) == 8
    assert {path.name for path in output.iterdir()} == {
        "manifest.json", "summary.json", "case_results.jsonl", "run_report.md", "manual_review_template.jsonl"
    }
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["frozen_dataset"] == _valid_preflight()["dataset"]["identity"]
    assert manifest["product_baseline"]["commit"] == contract.PRODUCT_BASELINE_COMMIT
    assert manifest["product_baseline"]["prompt_version"] == "engineering_agent_decision_prompt_v2"
    assert manifest["project_checkouts"] == {
        "my_agent": {
            "project_checkout_commit": contract.MY_AGENT_COMMIT,
            "checkout_attestation": "locally_verified_exact_checkout",
            "runtime_binding_attestation": "operator_started_api_with_configured_project_root",
            "public_project_identity": {"project_name": "my_agent", "source": "configured"},
            "query_endpoint": "http://my_agent.test/engineering/query",
        },
        "pydantic_ai": {
            "project_checkout_commit": contract.PYDANTIC_AI_COMMIT,
            "checkout_attestation": "locally_verified_exact_checkout",
            "runtime_binding_attestation": "operator_started_api_with_configured_project_root",
            "public_project_identity": {"project_name": "pydantic_ai", "source": "configured"},
            "query_endpoint": "http://pydantic_ai.test/engineering/query",
        },
    }
    review = [json.loads(line) for line in (output / "manual_review_template.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(review) == 16
    assert all(entry["task_success"] == "NOT SCORED" for entry in review)
    assert all(entry["claim_grounding"] == "NOT SCORED" for entry in review)


def test_manual_review_entry_has_gold_only_in_evaluator_output_not_request():
    case = _case("g12q001")
    result = normalize_case_result(case, _response(), latency_ms=1, roots=[REPO_ROOT])
    entry = build_manual_review_entry(case, result)

    assert entry["gold_obligations"] == case["gold_obligations"]
    assert entry["gold_source_proofs"] == case["source_proofs"]
    assert "gold_obligations" not in build_request_payload(case)
