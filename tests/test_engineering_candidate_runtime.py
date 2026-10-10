"""Real executor + fake models: wiring and hard limits, not LLM quality."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from core.engineering_candidate_models import CandidateToolAgentRunResult, CandidateTaskContext
from core.engineering_candidate_verification import CandidateEvidenceVerifier
from core.engineering_completion_review import (
    BaseCompletionReviewer, CompletionReviewOutcome, REVIEW_OUTPUT_VERSION, parse_review_output,
)
from core.engineering_context import EngineeringContextResolver
from core.engineering_planning import EngineeringEvidencePlanner
from core.engineering_retrieval import EngineeringRetrievalComponent
from core.engineering_requirement_planning import SelectedRequirementProvider, RuleRequirementProvider
from core.engineering_verification import EngineeringEvidenceVerifier
from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, RefuseAction, ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_CANDIDATE_V3_PROFILE
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import ToolAgentBudget, ToolAgentRunResult
from core.tool_agent.tools.code_search import CODE_SEARCH_TEST_VERSION
from core.tool_agent.tools.project_info import PROJECT_INFO_DOCUMENTATION_VERSION, ProjectBinding
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from core.unified_engineering_runtime import UnifiedEngineeringRuntime, LegacyToolAgentExecutionAdapter
from tests._engineering_runtime_support import EmptyRetrievalPort, NoRetrievalPlanner
from tests.test_engineering_requirement_planning import Client, goal, llm, output

QUESTION = "解释 A、B 两个函数的完整实现"


def answer(value="A 返回1，B 返回2。[E1] [E2]"):
    return FinalAnswerAction("final_answer", value)


def read(names):
    return ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "a.py", "target": {"kind": "symbols", "names": names}})


def review(decision="accept", verdicts=(("fulfilled", ["E1"]), ("fulfilled", ["E2"])), **kwargs):
    return {"schema_version": REVIEW_OUTPUT_VERSION, "decision": decision,
            "goals": [{"goal_id": f"g{i}", "verdict": verdict, "evidence_ids": ids}
                      for i, (verdict, ids) in enumerate(verdicts, 1)],
            "request_coverage": True, "missing_category": "none" if decision == "accept" else "material",
            "feedback": "审核通过" if decision == "accept" else "需要补充 B 的材料",
            "contract_issues": [], **kwargs}


class Reviewer(BaseCompletionReviewer):
    def __init__(self, outputs):
        self.outputs, self.inputs = list(outputs), []

    def review(self, review_input, *, timeout_seconds):
        self.inputs.append(review_input)
        raw = self.outputs[min(len(self.inputs)-1, len(self.outputs)-1)]
        if callable(raw):
            raw = raw(review_input)
        if type(raw) is str:
            return CompletionReviewOutcome(review_input.input_sha256, None, raw, 1, 0)
        try:
            result = parse_review_output(json.dumps(raw, ensure_ascii=False), review_input)
        except (ValueError, TypeError, KeyError):
            return CompletionReviewOutcome(review_input.input_sha256, None, "REVIEW_OUTPUT_INVALID", 1, 0)
        return CompletionReviewOutcome(review_input.input_sha256, result, None, 1, 3, 20, 10)


class Decision:
    def __init__(self, actions):
        self.actions, self.messages, self.contexts = list(actions), [], []

    def decide(self, registry, query, *, context=(), control_state=None):
        self.contexts.append(context)
        self.messages.append(ENGINEERING_DECISION_PROMPT_CANDIDATE_V3_PROFILE.build_messages(
            registry.list_specs(), query, context, control_state=control_state))
        action = self.actions[min(len(self.messages)-1, len(self.actions)-1)]
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def build(tmp_path, actions, *, reviewer=None, goals=None, budget=None, requirements=None, port=None, planner=None):
    (tmp_path / "a.py").write_text("def A():\n    return 1\n\ndef B():\n    return 2\n", encoding="utf-8")
    port = port or EmptyRetrievalPort()
    registry = build_readonly_tool_registry(tmp_path, port, code_search_version=CODE_SEARCH_TEST_VERSION,
        read_project_context_version=READ_PROJECT_TARGETS_VERSION,
        project_binding=ProjectBinding(tmp_path, "fixture", "configured"),
        project_info_version=PROJECT_INFO_DOCUMENTATION_VERSION)
    decision = Decision(actions)
    runtime = ToolAgentRuntime(registry=registry, provider=decision, budget=budget)
    provider = requirements or SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2",
                                      llm=llm(Client(output(*(goals or [goal(), goal("B", "B")])))))
    unified = UnifiedEngineeringRuntime(LegacyToolAgentExecutionAdapter(runtime),
        context_resolver=EngineeringContextResolver(), evidence_planner=EngineeringEvidencePlanner(planner or NoRetrievalPlanner()),
        retrieval_component=EngineeringRetrievalComponent(port), evidence_verifier=EngineeringEvidenceVerifier(),
        requirement_provider=provider,
        candidate_verifier=CandidateEvidenceVerifier(policy="semantic_v1" if reviewer else "structural_v2", reviewer=reviewer))
    return unified, decision


def test_missing_second_object_continues_in_same_loop_with_two_reviews(tmp_path):
    reviewer = Reviewer([review("need_material", (("fulfilled", ["E1"]), ("missing", []))), review()])
    runtime, decision = build(tmp_path, [read(["A"]), answer("A 返回1。[E1]"), read(["B"]), answer()], reviewer=reviewer)
    result = runtime.run(QUESTION)
    assert type(result) is CandidateToolAgentRunResult
    assert result.status == "completed"
    assert result.iterations_used == 4 and result.tool_calls_used == 2
    assert result.finalization.review_calls == 2 and len(reviewer.inputs) == 2
    assert len(result.materials) == 2
    assert result.finalization.review_input_tokens == 40
    assert result.review_records[-1].review_input.payload["submission"]["answer"] == result.answer
    assert any(type(item) is CandidateTaskContext for item in decision.contexts[-1])
    user_text = decision.messages[-1][-1]["content"]
    assert "需要补充 B 的材料" in user_text
    assert "需要补充 B 的材料" not in decision.messages[-1][0]["content"]


def test_direct_chat_zero_tools_still_has_submission_review(tmp_path):
    direct = goal("你好", None, "direct", [], False)
    reviewer = Reviewer([review(verdicts=(("fulfilled", []),))])
    runtime, _ = build(tmp_path, [answer("你好，有什么想聊的？")], reviewer=reviewer, goals=[direct])
    result = runtime.run("你好")
    assert result.status == "completed" and result.tool_calls_used == 0
    assert result.finalization.review_calls == 1 and result.evidence == ()
    assert len(result.submission_records) == 1
    assert result.submission_records[0].submission_input.payload["submission"]["answer"] == result.answer
    assert "submissions" not in result.to_dict()


def test_seeded_knowledge_cannot_hide_tool_fact_id_and_citation_format_is_recoverable(tmp_path):
    from tests._engineering_runtime_support import StaticKnowledgeRetrievalPort
    from tests.test_engineering_retrieval import _outcome

    class Planner(NoRetrievalPlanner):
        def plan(self, query):
            return _outcome(query)

    calculation = goal("2+3", None, "calculation", ["calculation"], False)
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E2"]),))])
    runtime, decision = build(tmp_path,
        [ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression": "2+3"}), answer("答案是5（依据 E2）。"), answer("答案是5 [E2]。")],
        reviewer=reviewer, goals=[calculation], port=StaticKnowledgeRetrievalPort(), planner=Planner())
    result = runtime.run("计算 2+3")
    assert result.status == "completed" and result.iterations_used == 3
    assert [item.kind for item in result.evidence] == ["knowledge", "tool_result"]
    assert "[E2]" in result.submission_records[0].feedback
    assert "[E1]" not in result.submission_records[0].feedback
    assert len(reviewer.inputs) == 1
    assert "available_evidence_refs" not in decision.messages[1][0]["content"]


def test_review_sees_actual_failed_attempt_and_preserves_confirmed_refusal_reason(tmp_path):
    requested = goal("missing.py", None, "body", ["project_code"], False)
    requested["target"]["path"] = "missing.py"

    def check_attempt(review_input):
        materials = review_input.payload["materials"]
        assert materials["materials"] == []
        assert materials["tool_attempts"][0]["error_code"] == "PROJECT_CONTEXT_FILE_NOT_FOUND"
        assert materials["tool_attempts"][0]["arguments"]["path"] == "missing.py"
        return review("refuse", verdicts=(("missing", []),), feedback="实际读取失败，不能编造正文")

    reviewer = Reviewer([check_attempt])
    runtime, _ = build(tmp_path,
        [ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "missing.py", "target": {"kind": "file", "start_line": 1}}),
         RefuseAction("refuse", "INSUFFICIENT_INFORMATION")], reviewer=reviewer, goals=[requested])
    result = runtime.run("读取 missing.py 的实现")
    assert result.status == "refused" and result.reason_code == "INSUFFICIENT_INFORMATION"
    assert result.evidence == () and result.answer is None
    assert result.finalization.review_calls == 1 and result.tool_errors_used == 1


def test_early_refusal_requires_agent_to_write_answer_then_review(tmp_path):
    direct = goal("你好", None, "direct", [], False)
    reviewer = Reviewer([review("revise_answer", (("fulfilled", []),), missing_category="answer", feedback="可以直接回答问候"),
                         review(verdicts=(("fulfilled", []),))])
    runtime, _ = build(tmp_path, [RefuseAction("refuse", "INSUFFICIENT_INFORMATION"), answer("你好！")],
                        reviewer=reviewer, goals=[direct])
    result = runtime.run("你好")
    assert result.status == "completed" and result.iterations_used == 2 and result.answer == "你好！"
    assert [r.review_input.payload["submission"]["action"] for r in result.review_records] == ["refuse", "final_answer"]


def test_refusal_cannot_be_approved_into_an_answer(tmp_path):
    direct = goal("你好", None, "direct", [], False)
    reviewer = Reviewer([review(verdicts=(("fulfilled", []),))])
    runtime, _ = build(tmp_path, [RefuseAction("refuse", "INSUFFICIENT_INFORMATION")], reviewer=reviewer, goals=[direct])
    result = runtime.run("你好")
    assert result.status == "failed" and result.failure_code == "REVIEW_OUTPUT_INVALID" and result.answer is None


def test_unknown_citation_can_be_fixed_without_tools_or_review_retry(tmp_path):
    calculation = goal("2+3", None, "calculation", ["calculation"], False)
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E1"]),))])
    actions = [ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression": "2+3"}), answer("等于5。[E999]"), answer("等于5。[E1]")]
    runtime, decision = build(tmp_path, actions, reviewer=reviewer, goals=[calculation],
                       budget=ToolAgentBudget(max_tool_calls=1))
    result = runtime.run("计算 2+3")
    assert [s.decision for s in result.submission_records] == ["revise_answer", "accept"]
    assert result.submission_records[0].submission_input.payload["submission"]["answer"] == "等于5。[E999]"
    assert result.to_audit_dict()["schema_version"] == "engineering_candidate_audit_v2"
    assert "available_evidence_refs" not in decision.messages[1][0]["content"]
    assert "material_catalog" in decision.messages[1][-1]["content"]
    assert result.status == "completed" and result.tool_calls_used == 1 and result.iterations_used == 3
    assert result.finalization.review_calls == 1
    assert result.evidence[0].kind == "tool_result"


@pytest.mark.parametrize("failure", ["REVIEW_TIMEOUT", "REVIEW_PROVIDER_ERROR", "REVIEW_OUTPUT_TRUNCATED"])
def test_review_technical_failure_is_failed_not_evidence_refusal(tmp_path, failure):
    reviewer = Reviewer([failure])
    runtime, _ = build(tmp_path, [read(["A", "B"]), answer()], reviewer=reviewer)
    result = runtime.run(QUESTION)
    assert result.status == "failed" and result.failure_code == failure and result.answer is None
    assert len(reviewer.inputs) == 1


def test_unknown_review_evidence_fails_closed(tmp_path):
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E99"]), ("fulfilled", ["E2"])))])
    runtime, _ = build(tmp_path, [read(["A", "B"]), answer()], reviewer=reviewer)
    result = runtime.run(QUESTION)
    assert result.failure_code == "REVIEW_OUTPUT_INVALID"


def test_original_request_mismatch_is_not_silently_replanned(tmp_path):
    reviewer = Reviewer([review("refuse", (("fulfilled", ["E1"]),), request_coverage=False,
                               missing_category="contract", contract_issues=["原问题要求 B，但合同遗漏了 B"] )])
    runtime, _ = build(tmp_path, [read(["A"]), answer("A 返回1。[E1]")], reviewer=reviewer, goals=[goal()])
    result = runtime.run(QUESTION)
    assert result.status == "failed" and result.failure_code == "REQUIREMENT_CONTRACT_MISMATCH"
    assert result.requirement_planning.metadata.call_count == 1


def test_known_truncation_cannot_be_overridden_by_model_approval(tmp_path):
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E1"]),))])
    runtime, _ = build(tmp_path, [read(["A"]), answer("A 的完整实现是 pass。[E1]")], reviewer=reviewer, goals=[goal()])
    (tmp_path / "a.py").write_text("def A():\n" + "    pass\n" * 130, encoding="utf-8")
    result = runtime.run("解释 A 的完整实现")
    assert result.status == "refused" and result.answer is None
    assert result.materials[0].details["content_complete"] is False
    assert result.finalization.review_calls <= 2


def test_repeated_answer_revision_cannot_expand_original_budget(tmp_path):
    reviewer = Reviewer([review("revise_answer", missing_category="answer", feedback="答案漏了返回值")])
    runtime, _ = build(tmp_path, [read(["A", "B"]), answer()], reviewer=reviewer)
    result = runtime.run(QUESTION)
    assert result.status == "refused" and result.answer is None
    assert result.finalization.review_calls == 2 and result.iterations_used == 3


def test_stale_review_hash_cannot_approve_new_answer_or_materials(tmp_path):
    reviewer = Reviewer([review()])
    runtime, _ = build(tmp_path, [read(["A", "B"]), answer()], reviewer=reviewer)
    result = runtime.run(QUESTION)
    with pytest.raises(ValueError, match="actual answer"):
        replace(result, answer="改成另一份未经审核的答案")
    with pytest.raises(ValueError):
        replace(result, evidence=result.evidence[:1], materials=result.materials[:1])


def test_legacy_types_remain_strict_and_structural_comparison_has_no_review(tmp_path):
    runtime, _ = build(tmp_path, [read(["A", "B"]), answer()])
    result = runtime.run(QUESTION)
    assert result.finalization.policy == "structural_v2" and result.finalization.review_calls == 0
    assert result.status == "completed"
    with pytest.raises(ValueError):
        ToolAgentRunResult("failed", None, None, "REVIEW_TIMEOUT", 1, 0, 0, ())


def test_rule_compatibility_does_not_invent_named_goals(tmp_path):
    runtime, _ = build(tmp_path, [answer("未要求项目事实的一般说明")],
                       requirements=RuleRequirementProvider(evidence_policy="goal_v2"))
    result = runtime.run("你好")
    assert result.requirement_planning.requirement.goals == ()
    assert result.finalization.policy == "structural_v2" and result.status == "completed"


def test_cancel_after_review_prevents_publication(tmp_path):
    reviewer = Reviewer([review()])
    runtime, _ = build(tmp_path, [read(["A", "B"]), answer()], reviewer=reviewer)
    result = runtime.run(QUESTION, cancel_requested=lambda: len(reviewer.inputs) > 0)
    assert result.status == "refused" and result.reason_code == "ENGINEERING_RUN_CANCELLED"
    assert result.answer is None


def test_shared_assembly_keeps_materials_and_review_records_per_run(tmp_path):
    reviewer = Reviewer([review(verdicts=(("fulfilled", []),))])
    direct = goal("你好", None, "direct", [], False)
    runtime, _ = build(tmp_path, [answer("你好！")], reviewer=reviewer, goals=[direct])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(runtime.run, ["你好", "你好"]))
    assert all(result.status == "completed" and len(result.review_records) == 1 for result in results)
    assert all(result.materials == () and result.finalization.review_calls == 1 for result in results)
