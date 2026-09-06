"""Safe, future-facing semantic-evaluation artifact contract.

This module projects one frozen case and one persisted worker payload into a
bounded evaluation artifact.  It defines no semantic score, calls neither a
provider nor a Router, and never copies evaluator Gold into the run artifact.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from .runner import RunnerPreflightError, safe_artifact


SEMANTIC_EVALUATION_ARTIFACT_VERSION = (
    "integration_v7_semantic_evaluation_artifact_v1"
)
SEMANTIC_EVALUATION_AVAILABLE = "AVAILABLE"
NOT_APPLICABLE_INVALID_RUN = "NOT_APPLICABLE_INVALID_RUN"
_PUBLIC_EVIDENCE_KINDS = frozenset(
    {"knowledge", "project_code", "project_doc", "project_test", "project_change"}
)
_PROJECT_EVIDENCE_KINDS = _PUBLIC_EVIDENCE_KINDS - {"knowledge"}
_VALID_RUN = "VALID"
_INVALID_RUN = "INVALID"


class SemanticEvaluationArtifactContractError(ValueError):
    """Raised when a worker payload cannot form a complete safe artifact."""


@dataclass(frozen=True)
class SemanticEvaluationArtifact:
    """A bounded fact record for a future semantic evaluator.

    The artifact intentionally contains product output facts only.  A scorer
    may join it with the frozen case oracle later, but this projection never
    embeds Gold obligations, source proofs, or expected answers.
    """

    case_id: str
    task_family: str
    run_validity: str
    infrastructure_code: str | None
    final: Mapping[str, Any] | None
    public_evidence: Sequence[Mapping[str, Any]] | None
    runtime_requirement_state: Mapping[str, Any] | None
    router_gold_contract_match: bool | None
    context: Mapping[str, Any] | None
    tool_sequence: Sequence[str] | None
    semantic_evaluation_availability: str

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, canonical JSON-safe copy of this artifact."""

        value = {
            "schema_version": SEMANTIC_EVALUATION_ARTIFACT_VERSION,
            "case_id": self.case_id,
            "task_family": self.task_family,
            "run_validity": self.run_validity,
            "infrastructure_code": self.infrastructure_code,
            "final": self.final,
            "public_evidence": self.public_evidence,
            "runtime_requirement_state": self.runtime_requirement_state,
            "router_gold_contract_match": self.router_gold_contract_match,
            "context": self.context,
            "tool_sequence": self.tool_sequence,
            "semantic_evaluation_availability": self.semantic_evaluation_availability,
        }
        return json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        )


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticEvaluationArtifactContractError(f"{label} must be an object")
    return value


def _require_non_empty_string(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise SemanticEvaluationArtifactContractError(f"{label} must be a non-empty string")
    return value


def _require_str_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, label)


def _require_strict_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise SemanticEvaluationArtifactContractError(f"{label} must be a strict boolean")
    return value


def _require_non_negative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SemanticEvaluationArtifactContractError(
            f"{label} must be a non-negative strict integer"
        )
    return value


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise SemanticEvaluationArtifactContractError(
            f"{label} fields do not match the frozen public contract"
        )


def _is_safe_relative_identity(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return not (
        "\\" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
        or any(part in {"", ".", ".."} for part in windows.parts)
    )


def _project_final(result: Mapping[str, Any]) -> dict[str, Any]:
    status = result.get("status")
    answer = result.get("answer")
    reason_code = result.get("reason_code")
    failure_code = result.get("failure_code")
    if status == "completed":
        if reason_code is not None or failure_code is not None:
            raise SemanticEvaluationArtifactContractError(
                "completed result has invalid terminal fields"
            )
        return {
            "status": status,
            "answer": _require_non_empty_string(answer, "completed result.answer"),
            "reason_code": None,
            "failure_code": None,
        }
    if status == "refused":
        if answer is not None or failure_code is not None:
            raise SemanticEvaluationArtifactContractError("refused result has invalid terminal fields")
        return {
            "status": status,
            "answer": None,
            "reason_code": _require_non_empty_string(reason_code, "refused result.reason_code"),
            "failure_code": None,
        }
    if status == "failed":
        if answer is not None or reason_code is not None:
            raise SemanticEvaluationArtifactContractError("failed result has invalid terminal fields")
        return {
            "status": status,
            "answer": None,
            "reason_code": None,
            "failure_code": _require_non_empty_string(failure_code, "failed result.failure_code"),
        }
    raise SemanticEvaluationArtifactContractError("result.status must be completed, refused, or failed")


def _project_project_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_keys(
        item,
        {"evidence_id", "kind", "path", "start_line", "end_line", "snippet"},
        "project evidence",
    )
    kind = item.get("kind")
    if kind not in _PROJECT_EVIDENCE_KINDS:
        raise SemanticEvaluationArtifactContractError("project evidence kind is invalid")
    path = item.get("path")
    if not _is_safe_relative_identity(path):
        raise SemanticEvaluationArtifactContractError("project evidence path must be repo-relative")
    start_line = _require_non_negative_int(item.get("start_line"), "project evidence.start_line")
    end_line = _require_non_negative_int(item.get("end_line"), "project evidence.end_line")
    if start_line < 1 or end_line < start_line:
        raise SemanticEvaluationArtifactContractError("project evidence line range is invalid")
    return {
        "evidence_id": _require_non_empty_string(item.get("evidence_id"), "project evidence.evidence_id"),
        "kind": kind,
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "snippet": _require_non_empty_string(item.get("snippet"), "project evidence.snippet"),
    }


def _project_knowledge_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_keys(
        item,
        {"evidence_id", "kind", "source_name", "chunk_id", "rank", "score", "snippet"},
        "knowledge evidence",
    )
    if item.get("kind") != "knowledge":
        raise SemanticEvaluationArtifactContractError("knowledge evidence kind is invalid")
    source_name = item.get("source_name")
    if not _is_safe_relative_identity(source_name):
        raise SemanticEvaluationArtifactContractError(
            "knowledge evidence source_name must be a safe relative identity"
        )
    score = item.get("score")
    if score is not None and (
        type(score) not in (int, float)
        or isinstance(score, bool)
        or not math.isfinite(float(score))
    ):
        raise SemanticEvaluationArtifactContractError("knowledge evidence.score must be finite or null")
    rank = _require_non_negative_int(item.get("rank"), "knowledge evidence.rank")
    if rank < 1:
        raise SemanticEvaluationArtifactContractError("knowledge evidence.rank must be positive")
    return {
        "evidence_id": _require_non_empty_string(item.get("evidence_id"), "knowledge evidence.evidence_id"),
        "kind": "knowledge",
        "source_name": source_name,
        "chunk_id": _require_str_or_none(item.get("chunk_id"), "knowledge evidence.chunk_id"),
        "rank": rank,
        "score": score,
        "snippet": _require_non_empty_string(item.get("snippet"), "knowledge evidence.snippet"),
    }


def _project_public_evidence(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SemanticEvaluationArtifactContractError("VALID result.evidence must be a list")
    output: list[dict[str, Any]] = []
    for item in value:
        evidence = _require_mapping(item, "public evidence item")
        kind = evidence.get("kind")
        if kind == "knowledge":
            output.append(_project_knowledge_evidence(evidence))
        elif kind in _PROJECT_EVIDENCE_KINDS:
            output.append(_project_project_evidence(evidence))
        else:
            raise SemanticEvaluationArtifactContractError("public evidence kind is invalid")
    return output


def _project_runtime_requirement_state(value: object) -> dict[str, Any]:
    state = _require_mapping(value, "VALID requirement_state")
    _require_exact_keys(
        state,
        {
            "satisfied",
            "missing_evidence_groups",
            "evidence_kind_counts",
            "distinct_project_code_paths",
            "required_min_distinct_project_code_paths",
        },
        "requirement_state",
    )
    missing = state.get("missing_evidence_groups")
    if not isinstance(missing, list):
        raise SemanticEvaluationArtifactContractError(
            "requirement_state.missing_evidence_groups must be a list"
        )
    canonical_missing: list[list[str]] = []
    for group in missing:
        if not isinstance(group, list) or not group:
            raise SemanticEvaluationArtifactContractError("requirement_state has an invalid missing group")
        if any(kind not in _PUBLIC_EVIDENCE_KINDS for kind in group) or len(set(group)) != len(group):
            raise SemanticEvaluationArtifactContractError("requirement_state has an invalid missing kind")
        canonical_missing.append(list(group))
    satisfied = _require_strict_bool(state.get("satisfied"), "requirement_state.satisfied")
    if satisfied and canonical_missing:
        raise SemanticEvaluationArtifactContractError(
            "satisfied requirement_state cannot contain missing evidence groups"
        )
    counts = _require_mapping(state.get("evidence_kind_counts"), "requirement_state.evidence_kind_counts")
    if set(counts) != _PUBLIC_EVIDENCE_KINDS:
        raise SemanticEvaluationArtifactContractError(
            "requirement_state.evidence_kind_counts must contain every public kind"
        )
    return {
        "satisfied": satisfied,
        "missing_evidence_groups": canonical_missing,
        "evidence_kind_counts": {
            kind: _require_non_negative_int(counts[kind], f"evidence_kind_counts[{kind!r}]")
            for kind in sorted(_PUBLIC_EVIDENCE_KINDS)
        },
        "distinct_project_code_paths": _require_non_negative_int(
            state.get("distinct_project_code_paths"),
            "requirement_state.distinct_project_code_paths",
        ),
        "required_min_distinct_project_code_paths": _require_non_negative_int(
            state.get("required_min_distinct_project_code_paths"),
            "requirement_state.required_min_distinct_project_code_paths",
        ),
    }


def _project_context(value: object) -> dict[str, Any]:
    context = _require_mapping(value, "VALID context")
    resolved_input = context.get("resolved_input")
    if resolved_input is not None:
        resolved_input = _require_non_empty_string(resolved_input, "context.resolved_input")
    resolver_used = _require_strict_bool(context.get("resolver_used"), "context.resolver_used")
    if resolver_used and resolved_input is None:
        raise SemanticEvaluationArtifactContractError(
            "context.resolved_input is required when the resolver was used"
        )
    resolution_correct = context.get("resolution_correct")
    if resolution_correct is not None:
        resolution_correct = _require_strict_bool(
            resolution_correct,
            "context.resolution_correct",
        )
    return {
        "input_mode": _require_non_empty_string(context.get("input_mode"), "context.input_mode"),
        "resolver_used": resolver_used,
        "resolver_fallback": _require_strict_bool(
            context.get("resolver_fallback"), "context.resolver_fallback"
        ),
        "resolved_input": resolved_input,
        "resolution_correct_frozen_exact": resolution_correct,
    }


def _project_tool_sequence(value: object) -> list[str]:
    if not isinstance(value, list) or any(type(name) is not str or not name for name in value):
        raise SemanticEvaluationArtifactContractError("VALID tool_sequence must be a list of names")
    return list(value)


def _sanitized_worker_payload(worker_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Use the existing runner serializer for redaction and forbidden-key rejection."""

    try:
        sanitized = safe_artifact(dict(worker_payload))
    except RunnerPreflightError as exc:
        raise SemanticEvaluationArtifactContractError(
            "worker payload violates the shared safe artifact boundary"
        ) from exc
    return _require_mapping(sanitized, "sanitized worker payload")


def project_semantic_evaluation_artifact(
    *,
    frozen_case: Mapping[str, Any],
    worker_payload: Mapping[str, Any],
) -> SemanticEvaluationArtifact:
    """Create a pure, deterministic semantic-review artifact from one worker payload."""

    case = _require_mapping(frozen_case, "frozen case")
    case_id = _require_non_empty_string(case.get("case_id"), "frozen case.case_id")
    task_family = _require_non_empty_string(
        case.get("task_family"), "frozen case.task_family"
    )
    payload = _sanitized_worker_payload(_require_mapping(worker_payload, "worker payload"))
    validity = payload.get("execution_validity")
    if validity not in {_VALID_RUN, _INVALID_RUN}:
        raise SemanticEvaluationArtifactContractError(
            "worker payload execution_validity must be VALID or INVALID"
        )
    if validity == _INVALID_RUN:
        infrastructure_code = _require_non_empty_string(
            payload.get("infrastructure_code"), "INVALID infrastructure_code"
        )
        return SemanticEvaluationArtifact(
            case_id=case_id,
            task_family=task_family,
            run_validity=validity,
            infrastructure_code=infrastructure_code,
            final=None,
            public_evidence=None,
            runtime_requirement_state=None,
            router_gold_contract_match=None,
            context=None,
            tool_sequence=None,
            semantic_evaluation_availability=NOT_APPLICABLE_INVALID_RUN,
        )

    result = _require_mapping(payload.get("result"), "VALID result")
    artifact = SemanticEvaluationArtifact(
        case_id=case_id,
        task_family=task_family,
        run_validity=validity,
        infrastructure_code=None,
        final=_project_final(result),
        public_evidence=_project_public_evidence(result.get("evidence")),
        runtime_requirement_state=_project_runtime_requirement_state(
            payload.get("requirement_state")
        ),
        router_gold_contract_match=_require_strict_bool(
            payload.get("requirement_contract_match"),
            "VALID requirement_contract_match",
        ),
        context=_project_context(payload.get("context")),
        tool_sequence=_project_tool_sequence(payload.get("tool_sequence")),
        semantic_evaluation_availability=SEMANTIC_EVALUATION_AVAILABLE,
    )
    # Apply the shared redaction boundary to every retained string, then make
    # a JSON copy so downstream scorers cannot mutate this dataclass's state.
    sanitized = safe_artifact(artifact.to_dict())
    return SemanticEvaluationArtifact(
        case_id=sanitized["case_id"],
        task_family=sanitized["task_family"],
        run_validity=sanitized["run_validity"],
        infrastructure_code=sanitized["infrastructure_code"],
        final=sanitized["final"],
        public_evidence=sanitized["public_evidence"],
        runtime_requirement_state=sanitized["runtime_requirement_state"],
        router_gold_contract_match=sanitized["router_gold_contract_match"],
        context=sanitized["context"],
        tool_sequence=sanitized["tool_sequence"],
        semantic_evaluation_availability=sanitized[
            "semantic_evaluation_availability"
        ],
    )


__all__ = [
    "NOT_APPLICABLE_INVALID_RUN",
    "SEMANTIC_EVALUATION_ARTIFACT_VERSION",
    "SEMANTIC_EVALUATION_AVAILABLE",
    "SemanticEvaluationArtifact",
    "SemanticEvaluationArtifactContractError",
    "project_semantic_evaluation_artifact",
]
