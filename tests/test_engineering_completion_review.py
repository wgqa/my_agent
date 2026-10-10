"""Protocol/provider failures and provenance of the new submission reviewer."""
from copy import deepcopy
import json

import pytest

from core.engineering_candidate_models import ReviewRecord
from core.engineering_completion_review import (
    CompletionReviewInput, CompletionReviewOutcome, LLMCompletionReviewer,
    REVIEW_PROMPT, REVIEW_PROMPT_VERSION, REVIEW_MAX_INPUT_CHARACTERS, parse_review_output,
)
from core.engineering_materials import MaterialLedger, capability_manifest
from core.engineering_requirement_contract import canonical_json
from core.engineering_requirement_planning import LLMRequirementProvider, REQUIREMENT_CANDIDATE_PROMPT_VERSION
from core.tool_agent.actions import FinalAnswerAction
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import ToolCall, ToolObservation
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from tests.test_engineering_requirement_planning import Client, llm, snapshot, output, goal
from core.engineering_completion_review import REVIEW_OUTPUT_VERSION


def review(verdicts):
    return {"schema_version": REVIEW_OUTPUT_VERSION, "decision": "accept",
            "goals": [{"goal_id": f"g{i}", "verdict": verdict, "evidence_ids": ids, "attempt_ids": []}
                      for i, (verdict, ids) in enumerate(verdicts, 1)],
            "request_coverage": True, "missing_category": "none", "feedback": "审核通过", "contract_issues": []}


def review_input():
    context = snapshot("你好")
    contract = llm(Client(output(goal("你好", None, "direct", [], False)))).plan(context).requirement
    return CompletionReviewInput.create(context, contract, MaterialLedger((CALCULATOR_SPEC,)),
                                       FinalAnswerAction("final_answer", "你好"), {"iterations": 4, "review_calls": 2})


def online(client):
    return LLMCompletionReviewer(provider="synthetic", model="synthetic-model", api_key="PRIVATE_API_KEY", client=client)


def test_provider_is_one_call_no_repairs_and_has_independent_prompt_usage():
    client = Client(json.dumps(review(verdicts=(("fulfilled", []),))))
    item = review_input()
    result = online(client).review(item, timeout_seconds=3)
    assert result.result.decision == "accept" and result.call_count == 1
    assert result.input_tokens == 123 and result.output_tokens == 45
    assert result.input_sha256 == item.input_sha256 and result.prompt_version == REVIEW_PROMPT_VERSION
    assert client.calls[0]["timeout"] == 3 and client.calls[0]["max_tokens"] == 1600
    assert client.calls[0]["messages"][0]["content"] == REVIEW_PROMPT
    assert client.calls[0]["messages"][1]["content"] == item.payload_json
    assert "PRIVATE_COT" not in canonical_json(result.to_dict())
    assert "PRIVATE_API_KEY" not in canonical_json(result.to_dict())


@pytest.mark.parametrize("content,finish,expected", [
    ("{}", "stop", "REVIEW_OUTPUT_INVALID"),
    ("{}", "length", "REVIEW_OUTPUT_TRUNCATED"),
    ("{}", "other", "REVIEW_OUTPUT_INVALID"),
    ('{"schema_version":"x","schema_version":"y"}', "stop", "REVIEW_OUTPUT_INVALID"),
])
def test_invalid_or_truncated_output_has_no_automatic_repair(content, finish, expected):
    client = Client(content, finish=finish)
    result = online(client).review(review_input(), timeout_seconds=20)
    assert result.failure_code == expected and result.result is None and len(client.calls) == 1
    if expected == "REVIEW_OUTPUT_INVALID":
        assert result.validation_error is not None


def test_input_overflow_is_explicit_and_makes_no_model_call():
    client = Client()
    item = review_input().payload
    item["submission"]["answer"] = "x" * REVIEW_MAX_INPUT_CHARACTERS
    result = online(client).review(CompletionReviewInput(canonical_json(item)), timeout_seconds=20)
    assert result.failure_code == "REVIEW_INPUT_LIMIT" and result.call_count == 0 and client.calls == []


def test_timeout_is_a_technical_failure_and_missing_usage_stays_null():
    client = Client(error=TimeoutError())
    result = online(client).review(review_input(), timeout_seconds=1)
    assert result.failure_code == "REVIEW_TIMEOUT" and result.call_count == 1
    assert result.input_tokens is None and result.output_tokens is None


def test_programming_fault_is_not_misreported_as_bad_evidence():
    with pytest.raises(RuntimeError, match="programming error"):
        online(Client(error=RuntimeError("programming error"))).review(review_input(), timeout_seconds=1)


def test_unknown_goal_extra_keys_and_stale_identity_are_rejected():
    item = review_input()
    raw = review(verdicts=(("fulfilled", []),))
    for altered in ({**raw, "tool_action": {}}, {**raw, "goals": [{"goal_id": "g8", "verdict": "fulfilled", "evidence_ids": [], "attempt_ids": []}]}):
        with pytest.raises(ValueError):
            parse_review_output(json.dumps(altered), item)
    outcome = CompletionReviewOutcome("0" * 64, parse_review_output(json.dumps(raw), item), None, 1, 0)
    with pytest.raises(ValueError, match="identity mismatch"):
        ReviewRecord(item, outcome)


def test_approval_can_have_no_gap_feedback_but_recovery_must_explain():
    item = review_input()
    raw = review(verdicts=(("fulfilled", []),))
    raw["feedback"] = ""
    assert parse_review_output(json.dumps(raw), item).decision == "accept"
    raw.update(decision="revise_answer", missing_category="answer")
    with pytest.raises(ValueError, match="gap explanation"):
        parse_review_output(json.dumps(raw), item)


def test_candidate_requirement_uses_real_capabilities_without_changing_v2_contract():
    capabilities = capability_manifest((CALCULATOR_SPEC,))
    client = Client(output(goal("2+3", None, "calculation", ["calculation"], False)))
    provider = LLMRequirementProvider(provider="synthetic", model="synthetic-model", api_key="PRIVATE_API_KEY",
        client=client, prompt_version=REQUIREMENT_CANDIDATE_PROMPT_VERSION, capabilities=capabilities)
    result = provider.plan(snapshot("计算 2+3"), timeout_seconds=2)
    assert result.requirement.schema_version == "engineering_evidence_requirements_v2"
    assert result.metadata.prompt_version == REQUIREMENT_CANDIDATE_PROMPT_VERSION
    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["capabilities"] == list(capabilities)
    assert client.calls[0]["timeout"] == 2
    assert [entry["tool_name"] for entry in payload["capabilities"]] == ["calculator"]


def failed_read_input(tmp_path, *, error_code=None, read_path="missing.py", successful_read=False, depth="locator"):
    from tests.test_engineering_materials import registry
    context = snapshot("检查 missing.py 是否能读取，无法读取时拒绝编造实现")
    requested = goal("missing.py", None, depth, ["project_code"], False)
    requested["target"]["path"] = "missing.py"
    contract = llm(Client(output(requested))).plan(context).requirement
    reg = registry(tmp_path)
    ledger = MaterialLedger(reg.list_specs())
    call = ToolCall.create("read_project_context", {"path": read_path, "target": {"kind": "file", "start_line": 1}})
    observation = (ToolExecutor(reg).execute(call) if error_code is None
                   else ToolObservation(call.call_id, call.tool_name, "error", None, error_code))
    ledger.observe(call, observation)
    if successful_read:
        (tmp_path / "missing.py").write_text("DEFAULT_VALUE = 6\n", encoding="utf-8")
        next_call = ToolCall.create(call.tool_name, call.arguments)
        ledger.observe(next_call, ToolExecutor(reg).execute(next_call))
    return CompletionReviewInput.create(context, contract, ledger,
        FinalAnswerAction("final_answer", "没有读到文件，不能编造实现"), {"iterations": 3, "review_calls": 2})


def unavailable_review(item):
    raw = review((("unavailable", []),))
    raw.update(decision="refuse", missing_category="material", feedback="实际读取失败，无法提供实现")
    raw["goals"][0]["attempt_ids"] = [item.payload["materials"]["tool_attempts"][0]["call_id"]]
    return raw


@pytest.mark.parametrize("depth", ["locator", "body", "implementation"])
@pytest.mark.parametrize("error_code", [None, "PROJECT_CONTEXT_FILE_UNREADABLE"])
def test_failed_read_can_explain_refusal_but_never_fulfill_content(tmp_path, depth, error_code):
    item = failed_read_input(tmp_path, depth=depth, error_code=error_code)
    assert item.payload["goal_availability"][0]["state"] == "unavailable"
    assert item.payload["materials"]["materials"] == []
    raw = unavailable_review(item)
    result = parse_review_output(json.dumps(raw), item)
    assert result.decision == "refuse" and result.goals[0].verdict == "unavailable"
    assert result.goals[0].evidence_ids == () and result.goals[0].attempt_ids
    raw.update(decision="accept", missing_category="none", feedback="")
    with pytest.raises(ValueError, match="approval invariant"):
        parse_review_output(json.dumps(raw), item)
    raw["goals"][0].update(verdict="fulfilled", attempt_ids=[])
    with pytest.raises(ValueError, match="fulfilled direct/material"):
        parse_review_output(json.dumps(raw), item)


@pytest.mark.parametrize("read_path,error_code,successful_read", [
    ("another.py", None, False),
    ("missing.py", "TOOL_EXECUTION_FAILED", False),
    ("missing.py", "INVALID_TOOL_ARGUMENTS", False),
    ("missing.py", "PROJECT_CONTEXT_LINE_OUT_OF_RANGE", False),
    ("missing.py", "PROJECT_CONTEXT_PATH_NOT_ALLOWED", False),
    ("missing.py", None, True),
])
def test_unavailable_verdict_rejects_other_path_transient_errors_and_successful_reads(tmp_path, read_path, error_code, successful_read):
    item = failed_read_input(tmp_path, read_path=read_path, error_code=error_code, successful_read=successful_read)
    assert item.payload["goal_availability"][0]["state"] != "unavailable"
    with pytest.raises(ValueError, match="unavailable goal support"):
        parse_review_output(json.dumps(unavailable_review(item)), item)


def test_refusal_attempt_ids_are_actual_and_cannot_be_used_as_evidence(tmp_path):
    item = failed_read_input(tmp_path)
    raw = unavailable_review(item)
    raw["goals"][0]["attempt_ids"] = ["call_invented"]
    with pytest.raises(ValueError, match="unavailable goal support"):
        parse_review_output(json.dumps(raw), item)
    raw = unavailable_review(item)
    raw["goals"][0]["evidence_ids"] = raw["goals"][0]["attempt_ids"]
    with pytest.raises(ValueError, match="goal verdict/references"):
        parse_review_output(json.dumps(raw), item)


def test_new_review_schema_does_not_silently_accept_old_goal_output():
    raw = review((("fulfilled", []),))
    raw["schema_version"] = "engineering_completion_review_output_v1"
    raw["goals"][0].pop("attempt_ids")
    result = online(Client(json.dumps(raw))).review(review_input(), timeout_seconds=1)
    assert result.failure_code == "REVIEW_OUTPUT_INVALID"
    assert result.validation_error == "ENVELOPE_INVALID" and result.call_count == 1
