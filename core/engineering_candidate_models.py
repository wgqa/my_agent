"""Candidate result boundary; legacy result constraints remain unchanged."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Sequence

from core.engineering_materials import MaterialRecord, ToolResultEvidence
from core.engineering_completion_review import REVIEW_FAILURE_CODES, CompletionReviewInput, CompletionReviewOutcome
from core.engineering_requirement_planning import REQUIREMENT_FAILURE_CODES, RequirementPlanningOutcome
from core.tool_agent.actions import AGENT_DECISION_FAILURE_CODES, REFUSE_REASON_CODES
from core.tool_agent.runtime_models import (
    EngineeringEvidence, KnowledgeEvidence, RuntimeTraceEvent,
    ToolAgentExecutionMetrics, ToolAgentRunResult, validate_run_state,
)

CANDIDATE_FAILURE_CODES = frozenset((*AGENT_DECISION_FAILURE_CODES, *REQUIREMENT_FAILURE_CODES,
    *REVIEW_FAILURE_CODES, "MATERIAL_ADAPTER_UNAVAILABLE", "MATERIAL_RESULT_INVALID"))
CANDIDATE_FINALIZATION_VERSION = "engineering_candidate_finalization_v1"


@dataclass(frozen=True)
class CandidateTaskContext:
    """Explicit candidate data, not a fictitious tool observation."""

    payload_json: str

    def to_dict(self):
        from core.engineering_requirement_contract import canonical_json
        payload = json.loads(self.payload_json)
        if (canonical_json(payload) != self.payload_json
                or payload.get("schema_version") != "engineering_candidate_task_context_v2"):
            raise ValueError("invalid candidate task context")
        return payload


@dataclass(frozen=True)
class CandidateSubmissionBlockedTrace:
    """Candidate recovery is not a legacy kind/count verification event."""

    iteration: int
    decision: str
    iterations_used: int
    tool_calls_used: int
    tool_errors_used: int

    def to_dict(self):
        return {"event_type": "candidate_submission_blocked", "iteration": self.iteration,
                "guard_status": "blocked", "decision": self.decision,
                "iterations_used": self.iterations_used, "tool_calls_used": self.tool_calls_used,
                "tool_errors_used": self.tool_errors_used}


@dataclass(frozen=True)
class CandidateFinalizationSummary:
    policy: str
    review_calls: int = 0
    decision: str | None = None
    missing_goals: tuple[str, ...] = ()
    failure_code: str | None = None
    review_input_tokens: int | None = None
    review_output_tokens: int | None = None
    review_latency_ms: int = 0
    schema_version: str = CANDIDATE_FINALIZATION_VERSION

    def __post_init__(self):
        if (self.schema_version != CANDIDATE_FINALIZATION_VERSION
                or self.policy not in {"structural_v2", "semantic_v1", "structural_v3", "semantic_v2"}
                or type(self.review_calls) is not int or not 0 <= self.review_calls <= 2
                or self.decision not in {None, "accept", "need_material", "revise_answer", "refuse", "structural_accept"}
                or self.failure_code not in (None, *CANDIDATE_FAILURE_CODES)
                or type(self.missing_goals) is not tuple
                or any(goal not in {f"g{i}" for i in range(1, 9)} for goal in self.missing_goals)):
            raise ValueError("invalid candidate finalization summary")
        if self.policy.startswith("structural_") and self.review_calls:
            raise ValueError("structural comparison cannot claim semantic reviews")
        for value in (self.review_input_tokens, self.review_output_tokens, self.review_latency_ms):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("invalid review metrics")

    def to_dict(self):
        return {**{name: getattr(self, name) for name in self.__dataclass_fields__},
                "missing_goals": list(self.missing_goals)}


@dataclass(frozen=True)
class ReviewRecord:
    review_input: CompletionReviewInput
    outcome: CompletionReviewOutcome

    def __post_init__(self):
        if (type(self.review_input) is not CompletionReviewInput or type(self.outcome) is not CompletionReviewOutcome
                or self.review_input.input_sha256 != self.outcome.input_sha256):
            raise ValueError("review input/output identity mismatch")

    def to_dict(self):
        return {"input": self.review_input.payload, "input_sha256": self.review_input.input_sha256,
                "outcome": self.outcome.to_dict()}


@dataclass(frozen=True)
class CandidateSubmissionRecord:
    """Actual submitted text and deterministic check, including pre-review blocks."""

    submission_input: CompletionReviewInput
    decision: str
    missing_goals: tuple[str, ...] = ()
    failure_code: str | None = None
    feedback: str = ""
    refusal_reason_code: str | None = None

    def __post_init__(self):
        if (type(self.submission_input) is not CompletionReviewInput
                or self.decision not in {"accept", "need_material", "revise_answer", "refuse", "structural_accept", "failed"}
                or self.failure_code not in (None, *CANDIDATE_FAILURE_CODES)
                or self.refusal_reason_code not in (None, *REFUSE_REASON_CODES)
                or (self.refusal_reason_code is not None and self.decision != "refuse")
                or type(self.missing_goals) is not tuple or type(self.feedback) is not str):
            raise ValueError("invalid candidate submission record")
        goals = {g["goal_id"] for g in self.submission_input.payload["contract"]["goals"]}
        if not set(self.missing_goals).issubset(goals):
            raise ValueError("unknown submission goal")

    def to_dict(self):
        return {"input": self.submission_input.payload, "input_sha256": self.submission_input.input_sha256,
                "check": {"decision": self.decision, "missing_goals": list(self.missing_goals),
                          "failure_code": self.failure_code, "feedback": self.feedback,
                          "refusal_reason_code": self.refusal_reason_code}}


@dataclass(frozen=True)
class CandidateToolAgentRunResult:
    status: str
    answer: str | None
    reason_code: str | None
    failure_code: str | None
    iterations_used: int
    tool_calls_used: int
    tool_errors_used: int
    trace: Sequence[RuntimeTraceEvent]
    evidence: Sequence[EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence] = ()
    execution: ToolAgentExecutionMetrics | None = None
    requirement_planning: RequirementPlanningOutcome | None = field(default=None, repr=False, compare=False)
    finalization: CandidateFinalizationSummary = field(default_factory=lambda: CandidateFinalizationSummary("structural_v2"))
    materials: tuple[MaterialRecord, ...] = field(default=(), repr=False, compare=False)
    review_records: tuple[ReviewRecord, ...] = field(default=(), repr=False, compare=False)
    submission_records: tuple[CandidateSubmissionRecord, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self):
        validate_run_state(self, failure_codes=CANDIDATE_FAILURE_CODES)
        if type(self.finalization) is not CandidateFinalizationSummary:
            raise TypeError("candidate requires a typed finalization summary")
        evidence = tuple(self.evidence)
        if any(type(item) not in (EngineeringEvidence, KnowledgeEvidence, ToolResultEvidence) for item in evidence):
            raise TypeError("invalid candidate evidence type")
        if len({item.evidence_id for item in evidence}) != len(evidence):
            raise ValueError("candidate evidence IDs must be unique")
        object.__setattr__(self, "evidence", evidence)
        if any(type(item) is not MaterialRecord for item in self.materials):
            raise TypeError("invalid candidate material records")
        if self.materials and tuple(m.evidence for m in self.materials) != evidence:
            raise ValueError("public evidence/material snapshot mismatch")
        if any(type(item) is not ReviewRecord for item in self.review_records):
            raise TypeError("invalid review records")
        if any(type(item) is not CandidateSubmissionRecord for item in self.submission_records):
            raise TypeError("invalid submission records")
        if self.requirement_planning is not None and type(self.requirement_planning) is not RequirementPlanningOutcome:
            raise TypeError("invalid candidate planning metadata")
        if self.execution is not None and type(self.execution) is not ToolAgentExecutionMetrics:
            raise TypeError("invalid candidate execution metrics")
        if self.status == "completed":
            if self.finalization.policy.startswith("semantic_"):
                if (self.finalization.decision != "accept" or not self.review_records
                        or self.review_records[-1].outcome.result is None
                        or self.review_records[-1].outcome.result.decision != "accept"
                        or self.review_records[-1].review_input.payload["submission"] != {
                            "action": "final_answer", "answer": self.answer, "reason_code": None}):
                    raise ValueError("completed requires approval of this actual answer")
                reviewed = self.review_records[-1].review_input.payload["materials"]["materials"]
                if [m["evidence"] for m in reviewed] != [item.to_dict() for item in evidence]:
                    raise ValueError("stale approval/material snapshot")
            elif self.finalization.decision != "structural_accept":
                raise ValueError("structural comparison requires its explicit verdict")

    def to_dict(self):
        result = ToolAgentRunResult.to_dict(self)
        result["finalization"] = self.finalization.to_dict()
        return result

    def to_audit_dict(self):
        return {"schema_version": "engineering_candidate_audit_v3", "result": self.to_dict(),
                "materials": [m.to_dict() for m in self.materials],
                "reviews": [r.to_dict() for r in self.review_records],
                "submissions": [r.to_dict() for r in self.submission_records]}
