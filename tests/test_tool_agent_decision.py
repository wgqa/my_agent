"""Tests for G4-AGENT-04 single-step structured tool decision.

Covers: AgentAction parsing (exact fields, refuse codes, answer bounds),
strict JSON (duplicate keys, fence/prose, non-object), tool allowlist from
Registry, decision-layer arguments schema validation, provider structural
checks, metadata identity/safety, and the no-tool-execution guarantee.
Uses only a Fake client — no network, no real LLM, no Holdout, no Gate 3
modification.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from core.tool_agent import (
    ACTION_PARSE_FAILED,
    ACTION_PROVIDER_ERROR,
    ACTION_TIMEOUT,
    AgentDecisionCallMetadata,
    AgentDecisionOutcome,
    FinalAnswerAction,
    OpenAICompatibleAgentDecisionProvider,
    RefuseAction,
    ToolCallAction,
    ToolRegistry,
    ToolSpec,
)
from core.tool_agent.action_parser import parse_agent_action_text, strict_json_loads_no_duplicates
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    DECISION_PROMPT_TEMPLATE,
    DECISION_PROMPT_VERSION,
    build_decision_messages,
    compute_toolset_sha256,
)
from core.tool_agent.openai_compatible import (
    AgentDecisionProviderError,
    AgentDecisionTimeoutError,
)
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC
from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC

GOOD_CALC = '{"action": "tool_call", "tool_name": "calculator", "arguments": {"expression": "12 * 7"}}'


class CountingHandler:
    def __init__(self):
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return {"matches": []}  # 占位；decide 不执行 Tool，故不被调用


class FakeDecisionClient:
    def __init__(self, content="", usage=None, error=None, response=None):
        self._content = content
        self._usage = usage
        self._error = error
        self._response = response
        self.calls = 0
        self.last_kwargs = None

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        if self._response is not None:
            return self._response
        usage = self._usage if self._usage is not None else {
            "prompt_tokens": 7, "completion_tokens": 3
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            usage=SimpleNamespace(**usage),
        )


def build_registry():
    handlers = {
        "calculator": CountingHandler(),
        "code_search": CountingHandler(),
        "knowledge_search": CountingHandler(),
    }
    reg = ToolRegistry()
    reg.register(CALCULATOR_SPEC, handlers["calculator"])
    reg.register(CODE_SEARCH_SPEC, handlers["code_search"])
    reg.register(KNOWLEDGE_SEARCH_SPEC, handlers["knowledge_search"])
    return reg, handlers


def build_provider(client, **kwargs):
    return OpenAICompatibleAgentDecisionProvider(
        provider="fake", model="fake-model", api_key="sk-test", client=client, **kwargs
    )


def decide_with(content, registry, **client_kwargs):
    client = FakeDecisionClient(content=content, **client_kwargs)
    provider = build_provider(client)
    outcome = provider.decide(registry, "测试请求")
    return outcome, client


# ---- ToolCallAction ----


class TestToolCallAction:
    @pytest.mark.parametrize("content,expected", [
        (GOOD_CALC, ("calculator", {"expression": "12 * 7"})),
        ('{"action": "tool_call", "tool_name": "code_search", "arguments": {"query": "Adapter"}}',
         ("code_search", {"query": "Adapter"})),
        ('{"action": "tool_call", "tool_name": "knowledge_search", "arguments": {"query": "RRF"}}',
         ("knowledge_search", {"query": "RRF"})),
    ])
    def test_valid_tool_call(self, content, expected):
        reg, _ = build_registry()
        outcome, _ = decide_with(content, reg)
        assert outcome.action is not None
        assert isinstance(outcome.action, ToolCallAction)
        assert outcome.action.tool_name == expected[0]
        assert dict(outcome.action.arguments) == expected[1]
        assert outcome.failure_code is None


# ---- FinalAnswer ----


class TestFinalAnswer:
    def test_valid(self):
        reg, _ = build_registry()
        outcome, _ = decide_with('{"action": "final_answer", "answer": "84"}', reg)
        assert isinstance(outcome.action, FinalAnswerAction)
        assert outcome.action.answer == "84"

    def test_empty_answer_rejected(self):
        reg, _ = build_registry()
        outcome, _ = decide_with('{"action": "final_answer", "answer": ""}', reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_overlong_answer_rejected(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(
            '{"action": "final_answer", "answer": "' + ("x" * 4001) + '"}', reg
        )
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_carries_tool_field_rejected(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(
            '{"action": "final_answer", "answer": "84", "tool_name": "calculator"}', reg
        )
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED


# ---- Refuse ----


class TestRefuse:
    def test_valid_reason(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(
            '{"action": "refuse", "reason_code": "UNSUPPORTED_REQUEST"}', reg
        )
        assert isinstance(outcome.action, RefuseAction)
        assert outcome.action.reason_code == "UNSUPPORTED_REQUEST"

    def test_unknown_reason_rejected(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(
            '{"action": "refuse", "reason_code": "WHATEVER"}', reg
        )
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED


# ---- Strict JSON ----


class TestStrictJSON:
    @pytest.mark.parametrize("bad", [
        "",                                   # 空输出
        "   ",                                # 纯空白
        "not json",                           # 非法 JSON
        "```json\n" + GOOD_CALC + "\n```",    # markdown fence
        "当然，调用如下：\n" + GOOD_CALC,        # JSON 前有 prose
        GOOD_CALC + "\n解释：因为...",          # JSON 后有 prose
        "[1, 2, 3]",                          # 数组而非 object
        "42",                                 # 标量而非 object
    ])
    def test_parse_failed(self, bad):
        reg, _ = build_registry()
        outcome, _ = decide_with(bad, reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_duplicate_top_level_key(self):
        reg, _ = build_registry()
        text = ('{"action": "tool_call", "action": "final_answer", '
                '"tool_name": "calculator", "arguments": {}}')
        outcome, _ = decide_with(text, reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_duplicate_nested_argument_key(self):
        reg, _ = build_registry()
        text = ('{"action": "tool_call", "tool_name": "calculator", '
                '"arguments": {"expression": "1+1", "expression": "2+2"}}')
        outcome, _ = decide_with(text, reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_unknown_field_rejected(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(
            '{"action": "tool_call", "tool_name": "calculator", "arguments": {}, "thought": "hmm"}',
            reg,
        )
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_missing_field_rejected(self):
        reg, _ = build_registry()
        outcome, _ = decide_with('{"action": "tool_call", "tool_name": "calculator"}', reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_strict_loader_rejects_duplicates_directly(self):
        with pytest.raises(ValueError, match="duplicate"):
            strict_json_loads_no_duplicates('{"a": 1, "a": 2}')


# ---- Tool security ----


class TestToolSecurity:
    @pytest.mark.parametrize("tool", ["shell", "python", "os.system", "not_a_tool"])
    def test_unknown_tool_rejected(self, tool):
        reg, _ = build_registry()
        text = '{"action": "tool_call", "tool_name": "%s", "arguments": {}}' % tool
        outcome, _ = decide_with(text, reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_model_provides_call_id_rejected(self):
        reg, _ = build_registry()
        text = ('{"action": "tool_call", "tool_name": "calculator", '
                '"arguments": {"expression": "1+1"}, "call_id": "forged"}')
        outcome, _ = decide_with(text, reg)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_arguments_schema_invalid(self):
        reg, _ = build_registry()
        # expression 缺字符串 → Decision 层 schema 校验失败
        outcome, _ = decide_with(
            '{"action": "tool_call", "tool_name": "calculator", "arguments": {"expression": 123}}',
            reg,
        )
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_arguments_extra_field(self):
        reg, _ = build_registry()
        # calculator input_schema 只允许 expression；extra 字段 → 拒绝
        outcome, _ = decide_with(
            '{"action": "tool_call", "tool_name": "calculator", '
            '"arguments": {"expression": "1+1", "top_k": 100}}',
            reg,
        )
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED


# ---- Provider ----


class TestProvider:
    def test_timeout(self):
        reg, _ = build_registry()
        outcome, _ = decide_with("", reg, error=AgentDecisionTimeoutError("slow"))
        assert outcome.action is None
        assert outcome.failure_code == ACTION_TIMEOUT

    def test_provider_error(self):
        reg, _ = build_registry()
        outcome, _ = decide_with("", reg, error=AgentDecisionProviderError("boom"))
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PROVIDER_ERROR

    def test_empty_choices(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(
            response=SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))
        )
        outcome = build_provider(client).decide(reg, "x")
        assert outcome.failure_code == ACTION_PROVIDER_ERROR

    def test_missing_message(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(
            response=SimpleNamespace(
                choices=[SimpleNamespace(message=None)],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )
        )
        outcome = build_provider(client).decide(reg, "x")
        assert outcome.failure_code == ACTION_PROVIDER_ERROR

    def test_non_string_content(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(
            response=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=123))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )
        )
        outcome = build_provider(client).decide(reg, "x")
        assert outcome.failure_code == ACTION_PROVIDER_ERROR

    def test_usage_missing(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(
            response=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"action": "final_answer", "answer": "hi"}'))],
                usage=None,
            )
        )
        outcome = build_provider(client).decide(reg, "x")
        assert isinstance(outcome.action, FinalAnswerAction)
        assert outcome.call_metadata.input_tokens is None
        assert outcome.call_metadata.output_tokens is None

    def test_usage_invalid(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(
            response=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                usage=SimpleNamespace(prompt_tokens="x", completion_tokens=0),
            )
        )
        outcome = build_provider(client).decide(reg, "x")
        assert outcome.failure_code == ACTION_PROVIDER_ERROR


# ---- Safety / identity ----


class TestSafetyIdentity:
    def test_api_key_not_in_repr(self):
        provider = build_provider(FakeDecisionClient())
        assert "sk-test" not in repr(provider)

    def test_raw_output_not_in_outcome_to_dict(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(GOOD_CALC, reg)
        d = outcome.to_dict()
        assert "raw" not in str(d)
        assert "sk-test" not in str(d)

    def test_prompt_sha_stable_and_64hex(self):
        assert len(DECISION_PROMPT_SHA256) == 64
        assert all(c in "0123456789abcdef" for c in DECISION_PROMPT_SHA256)
        assert DECISION_PROMPT_SHA256 == hashlib.sha256(
            DECISION_PROMPT_TEMPLATE.encode("utf-8")
        ).hexdigest()

    def test_prompt_version(self):
        assert DECISION_PROMPT_VERSION == "tool_agent_decision_prompt_v2"

    def test_tool_specs_deterministic_order(self):
        reg, _ = build_registry()
        messages = build_decision_messages(reg.list_specs(), "x")
        system = messages[0]["content"]
        names = [s.name for s in reg.list_specs()]
        assert names == ["calculator", "code_search", "knowledge_search"]
        assert system.index("- name: calculator") < system.index("- name: code_search")
        assert system.index("- name: code_search") < system.index("- name: knowledge_search")
        # 只提供 name/description/input_schema；工具列表段不暴露 output_schema/handler
        # （模板整体允许出现 "handler" 一词作为"禁止输出"指令，因此只查工具段）
        assert "output_schema" not in system
        tool_section = system.split("可用 Tool：", 1)[1]
        assert "handler" not in tool_section

    def test_call_count_is_one_and_single_create(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(content=GOOD_CALC)
        provider = build_provider(client)
        outcome = provider.decide(reg, "x")
        assert client.calls == 1
        assert outcome.call_metadata.call_count == 1


# ---- 本任务不执行 Tool ----


class TestNoToolExecution:
    def test_decision_has_no_tool_side_effect(self):
        reg, handlers = build_registry()
        for content in [
            GOOD_CALC,
            '{"action": "tool_call", "tool_name": "code_search", "arguments": {"query": "Adapter"}}',
            '{"action": "tool_call", "tool_name": "knowledge_search", "arguments": {"query": "RRF"}}',
        ]:
            outcome, _ = decide_with(content, reg)
            assert isinstance(outcome.action, ToolCallAction)
        # Decision Provider 不能产生 Tool side effect
        for handler in handlers.values():
            assert handler.calls == 0


# ---- 不用异常代表模型输出错了 ----


class TestOutcomeContract:
    def test_parse_failure_is_outcome_not_exception(self):
        reg, _ = build_registry()
        outcome, _ = decide_with("not json", reg)
        assert isinstance(outcome, AgentDecisionOutcome)
        assert outcome.action is None
        assert outcome.failure_code == ACTION_PARSE_FAILED

    def test_action_and_failure_mutually_exclusive(self):
        reg, _ = build_registry()
        outcome, _ = decide_with(GOOD_CALC, reg)
        assert outcome.action is not None and outcome.failure_code is None


# ---- R1：JSON Decision Reliability ----


class TestR1JSONReliability:
    def test_request_has_json_object_response_format(self):
        reg, _ = build_registry()
        client = FakeDecisionClient(content=GOOD_CALC)
        provider = build_provider(client)
        provider.decide(reg, "x")
        assert client.last_kwargs["response_format"] == {"type": "json_object"}

    def test_prompt_v2_contains_examples_and_reason_codes(self):
        reg, _ = build_registry()
        system = build_decision_messages(reg.list_specs(), "x")[0]["content"]
        assert '"action": "tool_call"' in system
        assert '"tool_name": "calculator"' in system
        assert '"expression": "12 * 7"' in system
        assert '"action": "final_answer"' in system
        assert '"action": "refuse"' in system
        assert "UNSUPPORTED_REQUEST" in system
        assert "UNSAFE_REQUEST" in system
        assert "INSUFFICIENT_INFORMATION" in system

    def test_toolset_sha256_stable_for_same_registry(self):
        reg, _ = build_registry()
        s1 = compute_toolset_sha256(reg.list_specs())
        s2 = compute_toolset_sha256(reg.list_specs())
        assert s1 == s2
        assert len(s1) == 64
        assert all(c in "0123456789abcdef" for c in s1)

    def test_toolset_sha256_differs_on_different_toolset(self):
        reg_a, _ = build_registry()
        reg_b = ToolRegistry()
        reg_b.register(CALCULATOR_SPEC, CountingHandler())  # 只注册 calculator
        assert compute_toolset_sha256(reg_a.list_specs()) != compute_toolset_sha256(reg_b.list_specs())

    def test_toolset_sha256_differs_on_modified_input_schema(self):
        reg_a, _ = build_registry()
        sa = compute_toolset_sha256(reg_a.list_specs())
        new_input = dict(CALCULATOR_SPEC.input_schema)
        new_input["properties"]["expression"]["maxLength"] = 999
        modified = ToolSpec(
            name="calculator",
            description=CALCULATOR_SPEC.description,
            input_schema=new_input,
            output_schema=CALCULATOR_SPEC.output_schema,
            version=CALCULATOR_SPEC.version,
        )
        reg_b = ToolRegistry()
        reg_b.register(modified, CountingHandler())
        assert compute_toolset_sha256(reg_b.list_specs()) != sa

    def test_tool_call_action_nested_arguments_mutation_attack(self):
        args = {"query": "x", "nested": {"limit": 5}}
        action = ToolCallAction(action="tool_call", tool_name="echo", arguments=args)
        # 外部改原 dict → 快照不变
        args["nested"]["limit"] = 999
        assert action.arguments_copy()["nested"]["limit"] == 5
        # 外部改 property 返回值 → 快照不变
        action.arguments["nested"]["limit"] = 777
        assert action.arguments_copy()["nested"]["limit"] == 5

    def test_outcome_to_dict_nested_mutation_isolation(self):
        action = ToolCallAction(
            action="tool_call", tool_name="echo", arguments={"nested": {"limit": 5}}
        )
        md = AgentDecisionCallMetadata(
            provider="p", model="m", prompt_version="v",
            prompt_sha256="0" * 64, toolset_sha256="0" * 64,
            call_count=1, input_tokens=None, output_tokens=None, latency_ms=1.0,
        )
        outcome = AgentDecisionOutcome(action=action, failure_code=None, call_metadata=md)
        d = outcome.to_dict()
        d["action"]["arguments"]["nested"]["limit"] = 999
        assert action.arguments_copy()["nested"]["limit"] == 5
        # 再次 to_dict 仍是干净快照
        assert outcome.to_dict()["action"]["arguments"]["nested"]["limit"] == 5
