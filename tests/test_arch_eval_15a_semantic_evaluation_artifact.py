"""Provider-free contracts for ARCH-EVAL-15A semantic artifact freezing."""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

from evaluation.integration_v7.runner_worker import _context_payload
from evaluation.integration_v7.semantic_evaluation_artifact import (
    NOT_APPLICABLE_INVALID_RUN,
    SEMANTIC_EVALUATION_ARTIFACT_VERSION,
    SemanticEvaluationArtifactContractError,
    project_semantic_evaluation_artifact,
)


_CASE = {"case_id": "v7d003", "task_family": "repo_only"}
_COUNTS = {
    "knowledge": 1,
    "project_code": 1,
    "project_doc": 0,
    "project_change": 0,
    "project_test": 0,
}


def _project_evidence(**overrides):
    value = {
        "evidence_id": "E1",
        "kind": "project_code",
        "path": "core/tool_agent/runtime.py",
        "start_line": 470,
        "end_line": 520,
        "snippet": "return public evidence",
    }
    value.update(overrides)
    return value


def _knowledge_evidence(**overrides):
    value = {
        "evidence_id": "E2",
        "kind": "knowledge",
        "source_name": "rag/advanced-rag.md",
        "chunk_id": "chunk-7",
        "rank": 1,
        "score": 3.14,
        "snippet": "retrieval evidence excerpt",
    }
    value.update(overrides)
    return value


def _valid_payload(**overrides):
    value = {
        "execution_validity": "VALID",
        "infrastructure_code": None,
        "result": {
            "status": "completed",
            "answer": "The implementation reads bounded public evidence.",
            "reason_code": None,
            "failure_code": None,
            "evidence": [_project_evidence(), _knowledge_evidence()],
        },
        "requirement_state": {
            "satisfied": True,
            "missing_evidence_groups": [],
            "evidence_kind_counts": dict(_COUNTS),
            "distinct_project_code_paths": 1,
            "required_min_distinct_project_code_paths": 1,
        },
        "requirement_contract_match": True,
        "context": {
            "input_mode": "frozen_conversation_context",
            "resolver_used": True,
            "resolver_fallback": False,
            "resolved_input": "Explain the runtime evidence requirement.",
            "resolution_correct": False,
        },
        "tool_sequence": ["code_search", "read_project_context"],
    }
    value.update(overrides)
    return value


def _artifact(payload=None):
    return project_semantic_evaluation_artifact(
        frozen_case=_CASE,
        worker_payload=_valid_payload() if payload is None else payload,
    ).to_dict()


def test_completed_answer_and_complete_public_evidence_are_retained_in_safe_artifact():
    artifact = _artifact()
    assert artifact["schema_version"] == SEMANTIC_EVALUATION_ARTIFACT_VERSION
    assert artifact["final"] == {
        "status": "completed",
        "answer": "The implementation reads bounded public evidence.",
        "reason_code": None,
        "failure_code": None,
    }
    assert artifact["public_evidence"] == [_project_evidence(), _knowledge_evidence()]
    assert artifact["semantic_evaluation_availability"] == "AVAILABLE"


@pytest.mark.parametrize(
    ("status", "reason_code", "failure_code"),
    [("refused", "INSUFFICIENT_EVIDENCE_TO_FINALIZE", None), ("failed", None, "ACTION_TIMEOUT")],
)
def test_refused_and_failed_results_cannot_fabricate_an_answer(status, reason_code, failure_code):
    payload = _valid_payload()
    payload["result"].update(
        {"status": status, "answer": None, "reason_code": reason_code, "failure_code": failure_code}
    )
    artifact = _artifact(payload)
    assert artifact["final"]["answer"] is None
    assert artifact["final"]["status"] == status

    payload["result"]["answer"] = "invented answer"
    with pytest.raises(SemanticEvaluationArtifactContractError):
        _artifact(payload)


def test_project_and_knowledge_evidence_keep_their_full_bounded_public_shapes():
    artifact = _artifact()
    project, knowledge = artifact["public_evidence"]
    assert project == _project_evidence()
    assert knowledge == _knowledge_evidence()
    assert knowledge["score"] == 3.14
    assert _artifact(
        _valid_payload(
            result={
                **_valid_payload()["result"],
                "evidence": [_knowledge_evidence(score=None)],
            }
        )
    )["public_evidence"][0]["score"] is None


def test_shared_safe_artifact_boundary_redacts_secrets_and_absolute_paths():
    payload = _valid_payload()
    payload["result"]["answer"] = "token sk-123456789012 at C:\\Users\\private\\answer.txt"
    payload["result"]["evidence"][0]["snippet"] = "See /home/agent/private.txt"
    artifact = _artifact(payload)
    serialized = repr(artifact)
    assert "sk-123456789012" not in serialized
    assert "C:\\Users\\private" not in serialized
    assert "/home/agent/private" not in serialized
    assert "<REDACTED_SECRET>" in serialized
    assert "<REDACTED_PATH>" in serialized


def test_existing_safe_boundary_rejects_forbidden_raw_artifact_keys():
    payload = _valid_payload()
    payload["raw_provider_response"] = "DO_NOT_PERSIST"
    with pytest.raises(SemanticEvaluationArtifactContractError, match="shared safe artifact"):
        _artifact(payload)


def test_valid_artifact_persists_the_complete_precomputed_runtime_requirement_state():
    artifact = _artifact()
    assert artifact["runtime_requirement_state"] == {
        "satisfied": True,
        "missing_evidence_groups": [],
        "evidence_kind_counts": dict(sorted(_COUNTS.items())),
        "distinct_project_code_paths": 1,
        "required_min_distinct_project_code_paths": 1,
    }


def test_valid_artifact_preserves_worker_contract_match_without_router_reconstruction():
    payload = _valid_payload(requirement_contract_match=False)
    artifact = _artifact(payload)
    assert artifact["router_gold_contract_match"] is False
    source = inspect.getsource(project_semantic_evaluation_artifact)
    assert "route_engineering_evidence_requirement" not in source
    assert "gold_obligations" not in source


def test_worker_resolved_input_is_preserved_and_old_exact_metric_is_renamed():
    snapshot = SimpleNamespace(
        received_count=2,
        used_count=2,
        used_tokens=20,
        truncated=False,
        resolver_used=True,
        resolver_fallback=False,
        resolved_input="Explain the resolved context semantically.",
    )
    context = _context_payload(
        {"task_family": "context_followup", "expected_standalone_intent": "Different frozen text"},
        "B",
        snapshot,
        SimpleNamespace(call_attempts=1),
    )
    artifact = _artifact(_valid_payload(context=context))
    assert artifact["context"] == {
        "input_mode": "question_only",
        "resolver_used": True,
        "resolver_fallback": False,
        "resolved_input": "Explain the resolved context semantically.",
        "resolution_correct_frozen_exact": False,
    }
    assert "resolution_correct" not in artifact["context"]


def test_invalid_runs_are_not_semantic_scoring_inputs():
    artifact = project_semantic_evaluation_artifact(
        frozen_case=_CASE,
        worker_payload={
            "execution_validity": "INVALID",
            "infrastructure_code": "worker_process_failure",
        },
    ).to_dict()
    assert artifact["run_validity"] == "INVALID"
    assert artifact["semantic_evaluation_availability"] == NOT_APPLICABLE_INVALID_RUN
    for key in (
        "final",
        "public_evidence",
        "runtime_requirement_state",
        "router_gold_contract_match",
        "context",
        "tool_sequence",
    ):
        assert artifact[key] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["result"].pop("answer"),
        lambda payload: payload["result"].pop("evidence"),
        lambda payload: payload.pop("requirement_state"),
        lambda payload: payload.pop("requirement_contract_match"),
        lambda payload: payload.pop("context"),
        lambda payload: payload.pop("tool_sequence"),
    ],
)
def test_valid_payload_missing_required_semantic_fact_fails_closed(mutation):
    payload = _valid_payload()
    mutation(payload)
    with pytest.raises(SemanticEvaluationArtifactContractError):
        _artifact(payload)


def test_artifact_excludes_gold_and_raw_execution_fields_and_is_json_safe_deterministic():
    payload = _valid_payload()
    payload["gold_obligations"] = [{"id": "O1"}]
    payload["source_proofs"] = [{"kind": "project_code"}]
    payload["tool_arguments"] = {"query": "do not retain"}
    artifact_a = _artifact(payload)
    artifact_b = _artifact(payload)
    assert artifact_a == artifact_b
    assert json.loads(json.dumps(artifact_a, sort_keys=True, allow_nan=False)) == artifact_a
    serialized = repr(artifact_a).lower()
    for forbidden in (
        "gold_obligations",
        "source_proofs",
        "tool_arguments",
        "raw_provider_response",
        "prompt",
        "trace",
        "arguments",
        "observation",
    ):
        assert forbidden not in serialized
