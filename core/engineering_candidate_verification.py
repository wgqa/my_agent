"""Candidate progress and submission checks for the existing bounded loop.

Progress is inexpensive and structural. Only submissions invoke semantic
review. Neither path adds a tool loop, a retrieval policy, or a budget.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from core.agent_runtime.runtime import MinimalEvidenceVerifier
from core.engineering_candidate_models import CandidateFinalizationSummary, ReviewRecord
from core.engineering_completion_review import (
    BaseCompletionReviewer, CompletionReviewInput, CompletionReviewOutcome,
    REVIEW_MAX_ATTEMPTS, REVIEW_MAX_INPUT_CHARACTERS, REVIEW_TIMEOUT_SECONDS, parse_review_output,
)
from core.engineering_materials import MaterialLedger, ToolResultEvidence
from core.engineering_requirement_contract import RequirementContract, PRODUCER_TOOLS, canonical_json
from core.engineering_requirements import evaluate_evidence_requirement
from core.engineering_verification import parse_answer_evidence_references, evidence_bundle_to_citation_blocks
from core.generator.citation import CitationValidator
from core.tool_agent.actions import FinalAnswerAction, RefuseAction
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence


@dataclass(frozen=True)
class CandidateProgress:
    goals: tuple[tuple[str, tuple[str, ...]], ...]
    missing_goals: tuple[str, ...]
    unsupported_goals: tuple[str, ...]
    knowledge_ready: bool
    legacy_ready: bool
    schema_version: str = "engineering_candidate_progress_v1"

    @property
    def structurally_ready(self):
        return not self.missing_goals and not self.unsupported_goals and self.knowledge_ready and self.legacy_ready

    def to_dict(self):
        return {"schema_version": self.schema_version,
                "goals": [{"goal_id": goal_id, "material_ids": list(ids)} for goal_id, ids in self.goals],
                "missing_goals": list(self.missing_goals), "unsupported_goals": list(self.unsupported_goals),
                "knowledge_ready": self.knowledge_ready, "legacy_ready": self.legacy_ready,
                "meaning": "structural progress only; not semantic approval"}


@dataclass(frozen=True)
class CandidateSubmissionCheck:
    decision: str
    missing_goals: tuple[str, ...] = ()
    failure_code: str | None = None
    feedback: str = ""


def material_matches_goal(goal, record):
    """Check verifiable identity/scope; do not guess semantic entailment."""
    if goal.depth in {"direct", "unsupported"} or not set(goal.source_kinds).intersection(record.source_kinds):
        return False
    forms = {"locator": {"locator", "body"}, "list": {"list"}, "candidate": {"candidate", "locator", "binding"},
             "body": {"body"}, "implementation": {"body"}, "knowledge": {"knowledge"},
             "diff": {"diff"}, "calculation": {"calculation"}, "binding": {"binding"}}
    if record.form not in forms[goal.depth]:
        return False
    item, details, target = record.evidence, record.details, goal.target
    request = details.get("request", {})
    if target.path:
        if type(item) is ToolResultEvidence:
            if item.tool_name == "code_search":
                if target.path not in {hit["path"] for hit in item.payload["matches"]}:
                    return False
            elif item.tool_name == "get_project_info":
                if target.path not in item.payload.get("documentation_entrypoints", ()):
                    return False
            elif request.get("path") != target.path:
                return False
        elif getattr(item, "path", None) != target.path:
            return False
    if target.symbol and goal.depth in {"body", "implementation"}:
        definitions = [t.get("definition") for t in details.get("targets", ())]
        definitions.append(details.get("definition"))
        if not any(definition and definition.get("name") == target.symbol for definition in definitions):
            return False
    if goal.depth == "implementation" and not (
            details.get("definition") or any(t.get("definition") for t in details.get("targets", ()))):
        return False
    if target.query and goal.depth == "locator" and record.form == "locator":
        if request.get("query") != target.query:
            return False
    for field, argument in (("change_mode", "mode"), ("base_ref", "base_ref"), ("head_ref", "head_ref")):
        value = getattr(target, field)
        if value is not None and request.get(argument) != value:
            return False
    if goal.full_range:
        if (details.get("content_complete") is not True
                or details.get("omitted_sensitive_count", 0)
                or details.get("selection_truncated")
                or details.get("documentation_truncated")):
            return False
        if goal.depth in {"body", "implementation"} and not target.symbol:
            # A complete *window* is not proof of a complete file/implementation.
            reader_target = request.get("target", {})
            if reader_target.get("kind") != "file" or reader_target.get("start_line") != 1:
                return False
    if goal.depth == "candidate" and type(item) is ToolResultEvidence and item.tool_name == "get_project_info":
        if "documentation_entrypoints" not in item.payload:
            return False
    return True


class CandidateEvidenceVerifier:
    def __init__(self, *, policy="structural_v2", reviewer=None):
        if policy not in {"structural_v2", "semantic_v1"}:
            raise ValueError("unknown candidate finalization policy")
        if (policy == "semantic_v1") != isinstance(reviewer, BaseCompletionReviewer):
            raise ValueError("semantic policy requires its reviewer; structural comparison has none")
        self.policy, self.reviewer = policy, reviewer

    def bind(self, snapshot, outcome, planner_outcome, retrieval_snapshot):
        if type(outcome.requirement) is not RequirementContract or outcome.metadata.evidence_policy != "goal_v2":
            raise TypeError("candidate verification requires a frozen candidate contract")
        outcome.validate_input(snapshot)
        if self.policy == "semantic_v1" and outcome.metadata.effective_implementation != "llm":
            raise ValueError("semantic candidate requires strict LLM requirements")
        if retrieval_snapshot.planner_outcome != planner_outcome:
            raise ValueError("candidate retrieval/planner identity mismatch")
        return BoundCandidateEvidenceVerifier(self, snapshot, outcome.requirement, planner_outcome, retrieval_snapshot)


@dataclass(frozen=True)
class BoundCandidateEvidenceVerifier:
    verifier: CandidateEvidenceVerifier
    snapshot: object
    contract: RequirementContract
    planner_outcome: object
    retrieval_snapshot: object

    def new_session(self, specs, initial_evidence, binding_identity):
        return CandidateVerificationSession(self, MaterialLedger(specs, initial_evidence, binding_identity=binding_identity))


class CandidateVerificationSession:
    """Private state for ONE execution, never stored on a shared runtime."""
    def __init__(self, bound, ledger):
        self.bound, self.ledger = bound, ledger
        self.records: list[ReviewRecord] = []
        self.last_check = CandidateSubmissionCheck("need_material")
        self.submission_corrections = 0
        self.feedback = None
        self.last_material_gap = None

    @property
    def review_calls(self):
        return sum(record.outcome.call_count for record in self.records)

    def progress(self, records=None):
        records = self.ledger.records if records is None else tuple(records)
        contract = self.bound.contract
        matches = tuple((goal.goal_id, tuple(r.evidence.evidence_id for r in records if material_matches_goal(goal, r)))
                        for goal in contract.goals)
        missing = tuple(goal.goal_id for goal, (_, ids) in zip(contract.goals, matches)
                        if goal.depth not in {"direct", "unsupported"} and not ids)
        unsupported = tuple(goal.goal_id for goal in contract.goals if goal.depth == "unsupported")
        knowledge_required = any("knowledge" in goal.source_kinds for goal in contract.goals)
        legacy = contract.legacy_requirement
        legacy_ready = True
        if legacy is not None:
            legacy_kinds = {kind for group in legacy.required_evidence_groups for kind in group}
            knowledge_required = "knowledge" in legacy_kinds or not any(k.startswith("project_") for k in legacy_kinds)
            legacy_ready = evaluate_evidence_requirement(legacy, [r.evidence for r in records
                            if type(r.evidence) in (EngineeringEvidence, KnowledgeEvidence)]).satisfied
        retrieval = self.bound.retrieval_snapshot
        knowledge = MinimalEvidenceVerifier().verify(
            self.bound.planner_outcome.plan, retrieval.evidence_bundle,
            required_query_ids=retrieval.required_query_ids, covered_query_ids=retrieval.covered_query_ids,
            upgrade_attempted=retrieval.upgrade_attempted, upgrade_used=retrieval.upgrade_used,
            retrieval_required=knowledge_required)
        return CandidateProgress(matches, missing, unsupported, knowledge.can_generate, legacy_ready)

    def task_context(self):
        return {"schema_version": "engineering_candidate_task_context_v1",
                "requirement": self.bound.contract.to_dict(), "progress": self.progress().to_dict(),
                "material_catalog": [m.to_dict() for m in self.ledger.records],
                "review_feedback": self.feedback}

    def submit(self, action, *, remaining, timeout_seconds):
        if type(action) not in (FinalAnswerAction, RefuseAction):
            raise TypeError("review requires an actual submission")
        progress = self.progress()
        if type(action) is FinalAnswerAction:
            refs = parse_answer_evidence_references(action.answer)
            known_ids = {item.evidence_id for item in self.ledger.evidence}
            malformed = re.findall(r"\[E[^\]\n]*\]", action.answer)
            if any(token[1:-1] not in known_ids for token in malformed) or any(ref not in known_ids for ref in refs):
                return self._check("revise_answer", feedback="使用本次资料中真实存在的 [E#]，删除未知或格式错误的引用。")
            cited = tuple(m for m in self.ledger.records if m.evidence.evidence_id in refs)
            citation = CitationValidator().validate(action.answer,
                list(evidence_bundle_to_citation_blocks(self.bound.retrieval_snapshot.evidence_bundle)))
            if citation.invalid:
                return self._check("revise_answer", feedback="知识库引用不属于本次检索，请改用当前真实资料。")
            if progress.structurally_ready and not self.progress(cited).structurally_ready:
                return self._check("revise_answer", feedback="资料已取得，但答案需要引用各目标对应的真实资料。")
        if self.bound.verifier.policy == "structural_v2":
            if type(action) is RefuseAction:
                return self._check("refuse")
            return self._check("structural_accept" if progress.structurally_ready else "need_material",
                               progress.missing_goals, feedback="尚未取得所需对象与范围的材料。")
        if self.review_calls >= REVIEW_MAX_ATTEMPTS:
            return self._check("refuse", progress.missing_goals, feedback="本次审核次数已用完，未取得可发布结论。")
        review_input = CompletionReviewInput.create(self.bound.snapshot, self.bound.contract, self.ledger, action, remaining)
        if len(review_input.payload_json) > REVIEW_MAX_INPUT_CHARACTERS:
            return self._check("failed", failure="REVIEW_INPUT_LIMIT")
        outcome = self.bound.verifier.reviewer.review(review_input,
                                                    timeout_seconds=min(timeout_seconds, REVIEW_TIMEOUT_SECONDS))
        if type(outcome) is not CompletionReviewOutcome:
            raise TypeError("reviewer must return CompletionReviewOutcome")
        if outcome.input_sha256 != review_input.input_sha256:
            return self._check("failed", failure="REVIEW_IDENTITY_MISMATCH")
        self.records.append(ReviewRecord(review_input, outcome))
        if outcome.failure_code:
            return self._check("failed", failure=outcome.failure_code)
        # Injected reviewers have the same strict protocol as the online parser.
        try:
            reviewed = parse_review_output(canonical_json(outcome.result.to_dict()), review_input)
        except (ValueError, TypeError, KeyError):
            return self._check("failed", failure="REVIEW_OUTPUT_INVALID")
        if not reviewed.request_coverage or reviewed.contract_issues or reviewed.missing_category == "contract":
            return self._check("failed", failure="REQUIREMENT_CONTRACT_MISMATCH")
        missing = tuple(goal.goal_id for goal in reviewed.goals if goal.verdict != "fulfilled")
        if reviewed.decision == "accept":
            if not progress.structurally_ready:
                return self._check("need_material", progress.missing_goals, feedback="审批所引用的材料未满足已知对象、范围或完整性条件。")
            records_by_id = {m.evidence.evidence_id: m for m in self.ledger.records}
            refs = set(parse_answer_evidence_references(action.answer))
            for goal, verdict in zip(self.bound.contract.goals, reviewed.goals):
                if ((goal.source_kinds and not any(material_matches_goal(goal, records_by_id[eid]) for eid in verdict.evidence_ids))
                        or not set(verdict.evidence_ids).issubset(refs)):
                    return self._check("revise_answer", (goal.goal_id,), feedback="审核批准所需的资料与答案引用不一致，需要修正提交。")
        return self._check(reviewed.decision, missing, feedback=reviewed.feedback)

    def _check(self, decision, missing=(), *, failure=None, feedback=""):
        self.last_check = CandidateSubmissionCheck(decision, tuple(missing), failure, feedback)
        self.feedback = {"decision": decision, "missing_goals": list(missing),
                         "failure_code": failure, "message": feedback}
        return self.last_check

    def can_recover(self, check, *, iterations, tool_calls, tool_errors, budget, enabled_tools):
        if (iterations >= budget.max_agent_iterations
                or (self.bound.verifier.policy == "semantic_v1" and self.review_calls >= REVIEW_MAX_ATTEMPTS)):
            return False
        if check.decision == "revise_answer":
            if self.submission_corrections >= 1:
                return False
            self.submission_corrections += 1
            return True
        if check.decision != "need_material" or (iterations + 1 >= budget.max_agent_iterations
                or tool_calls >= budget.max_tool_calls or tool_errors >= budget.max_tool_errors):
            return False
        goals = [g for g in self.bound.contract.goals if not check.missing_goals or g.goal_id in check.missing_goals]
        producers = {name for g in goals for name in PRODUCER_TOOLS[g.depth]}
        if self.bound.contract.legacy_requirement is not None:
            producers.update({"read_project_context", "git_diff"})
        if not producers.intersection(enabled_tools):
            return False
        gap = (self.ledger.snapshot_sha256, check.missing_goals)
        if gap == self.last_material_gap:
            return False
        self.last_material_gap = gap
        return True

    def summary(self):
        outcomes = [record.outcome for record in self.records]
        def total(name):
            values = [getattr(outcome, name) for outcome in outcomes if getattr(outcome, name) is not None]
            return sum(values) if values else None
        return CandidateFinalizationSummary(self.bound.verifier.policy, self.review_calls,
            self.last_check.decision if self.last_check.decision != "failed" else None,
            self.last_check.missing_goals, self.last_check.failure_code,
            total("input_tokens"), total("output_tokens"), sum(o.latency_ms for o in outcomes))
