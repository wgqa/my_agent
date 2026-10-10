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
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from tests.test_engineering_requirement_planning import Client, llm, snapshot, output, goal
from core.engineering_completion_review import REVIEW_OUTPUT_VERSION


def review(verdicts):
    return {"schema_version": REVIEW_OUTPUT_VERSION, "decision": "accept",
            "goals": [{"goal_id": f"g{i}", "verdict": verdict, "evidence_ids": ids}
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
    for altered in ({**raw, "tool_action": {}}, {**raw, "goals": [{"goal_id": "g8", "verdict": "fulfilled", "evidence_ids": []}]}):
        with pytest.raises(ValueError):
            parse_review_output(json.dumps(altered), item)
    outcome = CompletionReviewOutcome("0" * 64, parse_review_output(json.dumps(raw), item), None, 1, 0)
    with pytest.raises(ValueError, match="identity mismatch"):
        ReviewRecord(item, outcome)


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
