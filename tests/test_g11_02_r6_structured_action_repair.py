from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.tool_agent import (
    ACTION_PARSE_FAILED,
    ACTION_PROVIDER_ERROR,
    ACTION_TIMEOUT,
    AGENT_BUDGET_EXCEEDED,
    ActionParseCategory,
    FinalAnswerAction,
    OpenAICompatibleAgentDecisionProvider,
    ToolAgentBudget,
    ToolAgentRuntime,
    ToolCallAction,
    ToolRegistry,
)
from core.tool_agent.action_parser import diagnose_agent_action_text
from core.tool_agent.decision_prompt import (
    ACTION_REPAIR_PROMPT_SHA256,
    ACTION_REPAIR_PROMPT_VERSION,
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
)
from core.tool_agent.openai_compatible import (
    AgentDecisionProviderError,
    AgentDecisionTimeoutError,
)
from core.tool_agent.runtime_models import DecisionControlState
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler


VALID_FINAL = '{"action":"final_answer","answer":"ok"}'
VALID_CALC = '{"action":"tool_call","tool_name":"calculator","arguments":{"expression":"1+1"}}'


class SequenceClient:
    def __init__(self, *contents, finish_reasons=None, error=None):
        self._contents = list(contents)
        self._finish_reasons = list(finish_reasons or [])
        self._error = error
        self.calls = 0
        self.requests = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        if self._error is not None:
            raise self._error
        index = min(self.calls - 1, len(self._contents) - 1)
        reason = self._finish_reasons[index] if index < len(self._finish_reasons) else None
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._contents[index]),
                    finish_reason=reason,
                )
            ],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3),
        )


def registry() -> ToolRegistry:
    result = ToolRegistry()
    result.register(CALCULATOR_SPEC, CalculatorHandler())
    return result


def provider(client, *, legacy=False):
    return OpenAICompatibleAgentDecisionProvider(
        provider="fake",
        model="fake-model",
        api_key="sk-test",
        client=client,
        prompt_profile=None if legacy else ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    )


@pytest.mark.parametrize(
    ("content", "category"),
    [
        ("", ActionParseCategory.EMPTY_OUTPUT),
        ("{", ActionParseCategory.INVALID_JSON),
        ('{"a":1,"a":2}', ActionParseCategory.DUPLICATE_KEY),
        ('{"action":"bogus"}', ActionParseCategory.ACTION_SCHEMA_INVALID),
        ('{"action":"tool_call","tool_name":"missing","arguments":{}}', ActionParseCategory.UNKNOWN_TOOL),
        ('{"action":"tool_call","tool_name":"calculator","arguments":{"expression":1}}', ActionParseCategory.ARGUMENTS_SCHEMA_INVALID),
    ],
)
def test_strict_taxonomy_preserves_public_failure_code(content, category):
    result = diagnose_agent_action_text(content, registry())
    assert result.action is None
    assert result.failure_code == ACTION_PARSE_FAILED
    assert result.category is category


def test_first_valid_uses_one_call_and_no_repair():
    client = SequenceClient(VALID_FINAL)
    outcome = provider(client).decide(registry(), "question")
    assert isinstance(outcome.action, FinalAnswerAction)
    assert client.calls == 1
    assert outcome.call_metadata.call_count == 1
    assert outcome.call_metadata.repair_attempted is False
    assert outcome.call_metadata.repair_succeeded is False


@pytest.mark.parametrize(
    "first",
    [
        "{",
        '{"action":"bogus"}',
        '{"action":"tool_call","tool_name":"missing","arguments":{}}',
        '{"action":"tool_call","tool_name":"calculator","arguments":{"expression":1}}',
    ],
)
def test_parse_failure_repair_accepts_strict_valid_action(first):
    client = SequenceClient(first, VALID_CALC)
    outcome = provider(client).decide(registry(), "question")
    assert isinstance(outcome.action, ToolCallAction)
    assert outcome.action.tool_name == "calculator"
    assert outcome.failure_code is None
    assert client.calls == 2
    assert outcome.call_metadata.call_count == 2
    assert outcome.call_metadata.repair_attempted is True
    assert outcome.call_metadata.repair_succeeded is True
    assert outcome.call_metadata.input_tokens == 4
    assert outcome.call_metadata.output_tokens == 6


def test_length_failure_is_classified_as_truncated_and_repaired():
    client = SequenceClient("{", VALID_FINAL, finish_reasons=["length", "stop"])
    outcome = provider(client).decide(registry(), "question")
    assert isinstance(outcome.action, FinalAnswerAction)
    assert outcome.call_metadata.initial_parse_category == "OUTPUT_TRUNCATED"
    assert outcome.call_metadata.initial_finish_reason == "length"
    assert client.calls == 2


def test_complete_json_with_length_reason_is_not_repaired():
    client = SequenceClient(VALID_FINAL, "{\"action\":\"bogus\"}", finish_reasons=["length"])
    outcome = provider(client).decide(registry(), "question")
    assert isinstance(outcome.action, FinalAnswerAction)
    assert client.calls == 1
    assert outcome.call_metadata.initial_finish_reason == "length"


def test_repair_failure_keeps_public_parse_failure():
    malformed = "malformed-repair-output"
    client = SequenceClient("{", malformed)
    outcome = provider(client).decide(registry(), "question")
    assert outcome.action is None
    assert outcome.failure_code == ACTION_PARSE_FAILED
    assert outcome.call_metadata.call_count == 2
    assert outcome.call_metadata.repair_attempted is True
    assert outcome.call_metadata.repair_succeeded is False


def test_unknown_repair_usage_does_not_fake_a_cumulative_total():
    class UsageSequenceClient(SequenceClient):
        def create(self, **kwargs):
            self.calls += 1
            self.requests.append(kwargs)
            content = self._contents[min(self.calls - 1, len(self._contents) - 1)]
            usage = (
                SimpleNamespace(prompt_tokens=2, completion_tokens=3)
                if self.calls == 1
                else None
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=usage,
            )

    client = UsageSequenceClient("{", VALID_FINAL)
    outcome = provider(client).decide(registry(), "question")
    assert isinstance(outcome.action, FinalAnswerAction)
    assert outcome.call_metadata.input_tokens is None
    assert outcome.call_metadata.output_tokens is None


@pytest.mark.parametrize(
    "error,expected",
    [
        (AgentDecisionProviderError("provider"), ACTION_PROVIDER_ERROR),
        (AgentDecisionTimeoutError("timeout"), ACTION_TIMEOUT),
    ],
)
def test_provider_and_timeout_errors_do_not_repair(error, expected):
    client = SequenceClient("{", error=error)
    outcome = provider(client).decide(registry(), "question")
    assert outcome.failure_code == expected
    assert client.calls == 1
    assert outcome.call_metadata.call_count == 1
    assert outcome.call_metadata.repair_attempted is False


def test_legacy_parse_failure_has_no_repair():
    client = SequenceClient("{", VALID_FINAL)
    outcome = provider(client, legacy=True).decide(registry(), "question")
    assert outcome.failure_code == ACTION_PARSE_FAILED
    assert client.calls == 1
    assert outcome.call_metadata.repair_attempted is False


def test_must_terminate_repair_final_answer_is_accepted():
    client = SequenceClient("{", VALID_FINAL)
    state = DecisionControlState(
        iteration=1,
        remaining_iterations=0,
        remaining_tool_calls=1,
        tool_call_allowed=False,
        must_terminate=True,
    )
    outcome = provider(client).decide(registry(), "question", control_state=state)
    assert isinstance(outcome.action, FinalAnswerAction)
    assert "must_terminate" in client.requests[1]["messages"][-1]["content"]


def test_must_terminate_tool_repair_stays_at_runtime_boundary():
    client = SequenceClient("{", VALID_CALC)
    rt = ToolAgentRuntime(
        registry=registry(),
        provider=provider(client),
        budget=ToolAgentBudget(1, 1, 1),
    )
    result = rt.run("question")
    assert result.status == "refused"
    assert result.reason_code == AGENT_BUDGET_EXCEEDED
    assert result.tool_calls_used == 0
    assert client.calls == 2


def test_raw_malformed_output_is_not_repair_input_or_metadata_or_trace():
    raw = "SENSITIVE malformed raw output"
    client = SequenceClient(raw, "still malformed")
    outcome = provider(client).decide(registry(), "question")
    assert raw not in client.requests[1]["messages"][-1]["content"]
    encoded = json.dumps(outcome.to_dict(), ensure_ascii=False)
    assert raw not in encoded
    rt = ToolAgentRuntime(
        registry=registry(),
        provider=provider(SequenceClient(raw, "still malformed")),
        budget=ToolAgentBudget(1, 1, 1),
    )
    trace_text = json.dumps([event.to_dict() for event in rt.run("question").trace])
    assert raw not in trace_text


def test_engineering_trace_exposes_only_safe_repair_fields():
    client = SequenceClient("{", VALID_FINAL)
    result = ToolAgentRuntime(
        registry=registry(),
        provider=provider(client),
        budget=ToolAgentBudget(1, 1, 1),
    ).run("question")
    event = result.trace[0].to_dict()
    assert event["provider_call_count"] == 2
    assert event["repair_attempted"] is True
    assert event["repair_succeeded"] is True
    assert event["parse_failure_category"] == "INVALID_JSON"
    assert "content" not in event


def test_repair_prompt_has_independent_identity():
    assert ACTION_REPAIR_PROMPT_VERSION == "engineering_action_repair_prompt_v1"
    assert len(ACTION_REPAIR_PROMPT_SHA256) == 64
