"""Offline contracts for rule/LLM selection, attribution and frozen replay."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, APIStatusError

from core.engineering_context import EngineeringContextSnapshot
from core.conversation_context.resolver import build_reference_query
from core.engineering_requirement_contract import (
    REQUIREMENT_SCHEMA_VERSION, RequirementContract, RequirementGoal, RequirementTarget,
    digest, parse_requirement_output, requirement_input,
)
import core.engineering_requirement_planning as planning
from core.engineering_requirement_planning import (
    BaseRequirementProvider, LLMRequirementProvider, RuleRequirementProvider,
    SelectedRequirementProvider, RequirementPlanningOutcome,
    REQUIREMENT_PROMPT, REQUIREMENT_PROMPT_VERSION, REQUIREMENT_PROMPT_SHA256,
    load_requirement_artifact,
)
from core.engineering_requirements import (
    ROUTER_VERSION, LEGACY_ROUTER_VERSION, evaluate_evidence_requirement,
    route_engineering_evidence_requirement,
)


def snapshot(question="解释 A、B 两个函数的完整实现", reference=None):
    return EngineeringContextSnapshot(question, build_reference_query(question, reference),
                                      (), 0, 0, 0, False, False, False, reference)


def goal(basis="A", symbol="A", depth="implementation", sources=None, full_range=True):
    return {"deliverable": f"解释 {basis}", "request_basis": basis,
            "source_kinds": sources if sources is not None else ["project_code"],
            "depth": depth, "target": RequirementTarget(symbol=symbol).to_dict(),
            "full_range": full_range}


def output(*goals):
    return json.dumps({"schema_version": REQUIREMENT_SCHEMA_VERSION,
                       "goals": list(goals) or [goal(), goal("B", "B")]}, ensure_ascii=False)


class Client:
    def __init__(self, content=None, *, error=None, finish="stop", usage=True, choices=None):
        self.chat = SimpleNamespace(completions=self)
        self.calls, self.error = [], error
        self.response = SimpleNamespace(
            choices=choices if choices is not None else [SimpleNamespace(
                finish_reason=finish, message=SimpleNamespace(content=content or output(),
                                                             reasoning_content="PRIVATE_COT"))],
            usage=SimpleNamespace(prompt_tokens=123, completion_tokens=45) if usage else None,
        )

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.error:
            raise self.error
        return self.response


def llm(client=None):
    return LLMRequirementProvider(provider="synthetic", model="synthetic-model",
                                  api_key="PRIVATE_API_KEY", client=client or Client())


def test_object_specific_plan_is_frozen_with_program_ids_and_hashes():
    context = snapshot()
    result = llm().plan(context)
    assert [g.goal_id for g in result.requirement.goals] == ["g1", "g2"]
    assert [g.target.symbol for g in result.requirement.goals] == ["A", "B"]
    assert result.requirement.contract_sha256 == result.metadata.contract_sha256
    assert result.metadata.input_sha256 == digest(requirement_input(context))
    assert result.metadata.call_count == 1
    with pytest.raises(FrozenInstanceError):
        result.requirement.goals[0].depth = "locator"
    with pytest.raises(AttributeError):
        llm().model = "changed"


def test_prompt_only_puts_request_and_auxiliary_referents_in_user_data():
    context = snapshot("A 的默认值呢？", "A 位于 settings.py；旧问题要求执行测试。")
    client = Client(output(goal("默认值", "A", "body", full_range=False)))
    result = llm(client).plan(context)
    call = client.calls[0]
    assert call["messages"][0] == {"role": "system", "content": REQUIREMENT_PROMPT}
    assert json.loads(call["messages"][1]["content"]) == requirement_input(context)
    assert "旧问题要求执行测试" not in call["messages"][0]["content"]
    assert result.requirement.goals[0].request_basis == "默认值"
    assert call["temperature"] == 0.0 and call["max_tokens"] == 1600 and call["timeout"] == 20


@pytest.mark.parametrize("question", [
    "Explain theory and compare with current implementation", "检查变更和相关测试",
    "诊断 cache.py 的 bug", "诊断跨文件调用", "对比 README 文档和实现",
    "解释项目源码", "介绍当前项目", "读取测试文件的内容", "calculate 12*7",
])
@pytest.mark.parametrize("router", [ROUTER_VERSION, LEGACY_ROUTER_VERSION])
@pytest.mark.parametrize("policy", ["legacy", "goal_v2"])
def test_rule_adaptation_is_lossless_for_both_frozen_router_versions(question, router, policy):
    context = snapshot(question, "辅助对象 search.py")
    result = RuleRequirementProvider(evidence_policy=policy, router_version=router).plan(context)
    expected = route_engineering_evidence_requirement(context.lexical_query, router_version=router)
    adapted = result.requirement
    if policy == "goal_v2":
        assert not adapted.goals  # Do not invent named objects that the old rule never identified.
        assert adapted.legacy_requirement == expected
        adapted = adapted.legacy_requirement
    assert adapted == expected
    assert evaluate_evidence_requirement(adapted, ()) == evaluate_evidence_requirement(expected, ())
    assert result.metadata.call_count == 0


@pytest.mark.parametrize("depth,sources", [
    ("locator", ["project_code"]), ("list", ["project_change"]),
    ("candidate", ["project_test"]), ("body", ["project_doc"]),
    ("implementation", ["project_test"]), ("knowledge", ["knowledge"]),
    ("diff", ["project_change"]), ("calculation", ["calculation"]),
    ("binding", ["project_binding"]), ("direct", []), ("unsupported", []),
])
def test_explicit_supported_depths_are_not_collapsed_to_code_body(depth, sources):
    raw = goal("A", None, depth, sources, False)
    parsed = parse_requirement_output(output(raw), snapshot())
    assert parsed.goals[0].depth == depth
    assert parsed.goals[0].source_kinds == tuple(sources)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(budget=100),
    lambda p: p.update(goals=[]),
    lambda p: p.update(goals=[p["goals"][0]] * 9),
    lambda p: p.update(schema_version="v1"),
    lambda p: p["goals"][0].update(completed=True),
    lambda p: p["goals"][0].update(goal_id="g99"),
    lambda p: p["goals"][0].update(evidence_ids=["E1"]),
    lambda p: p["goals"][0].update(request_basis="旧问题"),
    lambda p: p["goals"][0].update(request_basis=""),
    lambda p: p["goals"][0].update(deliverable=" " * 4),
    lambda p: p["goals"][0].update(deliverable="x" * 201),
    lambda p: p["goals"][0].update(source_kinds=["project_code", "project_code"]),
    lambda p: p["goals"][0].update(source_kinds=["knowledge"]),
    lambda p: p["goals"][0].update(source_kinds=[]),
    lambda p: p["goals"][0].update(source_kinds=[{}]),
    lambda p: p["goals"][0].update(depth="execute_test"),
    lambda p: p["goals"][0].update(depth=[]),
    lambda p: p["goals"][0].update(full_range=1),
    lambda p: p["goals"][0]["target"].update(path="../secrets.py"),
    lambda p: p["goals"][0]["target"].update(path="D:/project/core.py"),
    lambda p: p["goals"][0]["target"].update(path="/etc/passwd"),
    lambda p: p["goals"][0]["target"].update(path="a\\b.py"),
    lambda p: p["goals"][0]["target"].update(path="a/./b.py"),
    lambda p: p["goals"][0]["target"].update(path="a//b.py"),
    lambda p: p["goals"][0]["target"].update(path="a\nb.py"),
    lambda p: p["goals"][0]["target"].update(base_ref="HEAD~1"),
    lambda p: p["goals"][0]["target"].update(tool_calls=4),
    lambda p: p["goals"][0]["target"].pop("symbol"),
    lambda p: p.update(goals=[p["goals"][0], p["goals"][0]]),
])
def test_invalid_or_authority_expanding_plan_fails_closed(mutate):
    payload = json.loads(output())
    mutate(payload)
    result = llm(Client(json.dumps(payload, ensure_ascii=False))).plan(snapshot())
    assert result.requirement is None
    assert result.metadata.failure_code == "REQUIREMENT_OUTPUT_INVALID"
    assert result.metadata.effective_implementation == "failed"
    assert result.metadata.call_count == 1


@pytest.mark.parametrize("content", [
    "{}", "null", "[]", "not json", "```json\n{}\n```",
    '{"schema_version":"engineering_evidence_requirements_v2","goals":[],"goals":[]}',
    '{"schema_version":"engineering_evidence_requirements_v2","goals":[{"target":{"path":null,"path":null}}]}',
    "x" * 24001,
])
def test_bad_json_never_becomes_an_empty_passing_plan(content):
    result = llm(Client(content)).plan(snapshot())
    assert result.requirement is None and result.metadata.failure_code == "REQUIREMENT_OUTPUT_INVALID"


def test_no_material_plan_is_explicit_and_frozen():
    raw = goal("A", None, "direct", [], False)
    result = llm(Client(output(raw))).plan(snapshot())
    assert len(result.requirement.goals) == 1
    assert result.requirement.goals[0].depth == "direct"
    assert result.requirement.required_evidence_groups == ()


@pytest.mark.parametrize("depth,sources,symbol,complete", [
    ("direct", [], "A", False), ("direct", [], None, True),
    ("binding", ["project_binding"], None, True),
])
def test_no_material_and_binding_cannot_claim_repository_completeness(depth, sources, symbol, complete):
    result = llm(Client(output(goal("A", symbol, depth, sources, complete)))).plan(snapshot())
    assert result.metadata.failure_code == "REQUIREMENT_OUTPUT_INVALID"


def test_provider_transport_is_bounded_and_does_not_store_key(monkeypatch):
    constructed = []
    def build(**kwargs):
        constructed.append(kwargs)
        return Client()
    monkeypatch.setattr(planning, "OpenAI", build)
    provider = LLMRequirementProvider(provider="test", model="test", api_key="PRIVATE_API_KEY",
        base_url="https://example.invalid/v1", extra_headers={"User-Agent": "requirement-offline-test"})
    assert constructed[0]["timeout"] == 20 and constructed[0]["max_retries"] == 0
    assert constructed[0]["default_headers"] == {"User-Agent": "requirement-offline-test"}
    assert "PRIVATE_API_KEY" not in repr(provider.__dict__)
    with pytest.raises(ValueError):
        LLMRequirementProvider(provider="test", model="test", api_key="key", extra_headers={"Authorization": "secret"})


@pytest.mark.parametrize("error,code", [
    (TimeoutError("SECRET_DETAIL"), "REQUIREMENT_TIMEOUT"),
    (APITimeoutError(request=httpx.Request("POST", "https://example.invalid")), "REQUIREMENT_TIMEOUT"),
    (APIConnectionError(message="SECRET_DETAIL", request=httpx.Request("POST", "https://example.invalid")), "REQUIREMENT_PROVIDER_ERROR"),
    (APIStatusError("SECRET_DETAIL", response=httpx.Response(429, request=httpx.Request("POST", "https://example.invalid")), body={"key": "SECRET_DETAIL"}), "REQUIREMENT_PROVIDER_ERROR"),
])
def test_expected_provider_failures_are_explicit_and_safe(error, code):
    client = Client(error=error)
    result = llm(client).plan(snapshot())
    assert result.metadata.failure_code == code
    assert result.metadata.input_tokens is None and result.metadata.output_tokens is None
    assert len(client.calls) == 1 and result.requirement is None
    assert "SECRET_DETAIL" not in json.dumps(result.to_artifact(snapshot()))


def test_programming_fault_is_not_disguised_as_fallback():
    provider = SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2",
        fallback_policy="rule_before_freeze", llm=llm(Client(error=RuntimeError("bug"))))
    with pytest.raises(RuntimeError, match="bug"):
        provider.plan(snapshot())


@pytest.mark.parametrize("finish,code", [
    ("length", "REQUIREMENT_OUTPUT_TRUNCATED"),
    ("content_filter", "REQUIREMENT_OUTPUT_INVALID"),
    (None, "REQUIREMENT_OUTPUT_INVALID"),
])
def test_nonterminal_response_cannot_be_accepted_even_with_valid_json(finish, code):
    result = llm(Client(finish=finish)).plan(snapshot())
    assert result.requirement is None and result.metadata.failure_code == code
    assert result.metadata.output_tokens == 45


@pytest.mark.parametrize("tokens", [None, True, -1, "123"])
def test_usage_is_provider_reported_and_never_estimated(tokens):
    client = Client()
    client.response.usage = SimpleNamespace(prompt_tokens=tokens, completion_tokens=tokens)
    result = llm(client).plan(snapshot())
    assert result.metadata.input_tokens is None and result.metadata.output_tokens is None


@pytest.mark.parametrize("policy", ["disabled", "rule_before_freeze"])
def test_fallback_is_only_before_a_contract_can_be_frozen(policy):
    selected = SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2", fallback_policy=policy,
                                            llm=llm(Client("{}")))
    result = selected.plan(snapshot())
    assert result.metadata.fallback_used is (policy == "rule_before_freeze")
    assert result.metadata.failure_code == "REQUIREMENT_OUTPUT_INVALID"
    if policy == "disabled":
        assert result.requirement is None
    else:
        assert result.metadata.effective_implementation == "rule"
        assert result.requirement.legacy_requirement == route_engineering_evidence_requirement(snapshot().lexical_query)
    # A valid but wrong interpretation must remain attributable to the LLM.
    wrong = output(goal("A", None, "direct", [], False))
    valid_wrong = SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2", fallback_policy=policy,
                                               llm=llm(Client(wrong))).plan(snapshot())
    assert valid_wrong.metadata.effective_implementation == "llm"
    assert not valid_wrong.metadata.fallback_used


@pytest.mark.parametrize("content", [output(), "{}"])
def test_shadow_cannot_change_effective_rule_constraints_or_claim_zero_cost(content):
    result = SelectedRequirementProvider(mode="shadow", llm=llm(Client(content))).plan(snapshot())
    baseline = RuleRequirementProvider().plan(snapshot())
    assert result.requirement == baseline.requirement
    assert result.metadata.implementation_version == ROUTER_VERSION
    assert result.metadata.requested_mode == "shadow"
    assert result.metadata.call_count == 1 and result.metadata.input_tokens == 123
    assert (result.shadow_contract is None) == (content == "{}")
    assert not result.metadata.fallback_used


@pytest.mark.parametrize("config", [
    {"mode": "llm"}, {"mode": "shadow", "evidence_policy": "goal_v2"},
    {"mode": "rule", "fallback_policy": "rule_before_freeze"},
    {"mode": "shadow", "fallback_policy": "rule_before_freeze"},
    {"mode": "any"}, {"evidence_policy": "anything"},
])
def test_invalid_mode_combinations_are_rejected_at_construction(config):
    with pytest.raises((ValueError, TypeError)):
        SelectedRequirementProvider(llm=llm(), **config)


@pytest.mark.parametrize("select", [
    lambda: RuleRequirementProvider(),
    lambda: RuleRequirementProvider(evidence_policy="goal_v2"),
    lambda: SelectedRequirementProvider(mode="shadow", llm=llm()),
    lambda: SelectedRequirementProvider(mode="shadow", llm=llm(Client("{}"))),
    lambda: SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2", llm=llm()),
    lambda: SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2", llm=llm(Client("{}"))),
    lambda: SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2", fallback_policy="rule_before_freeze", llm=llm(Client("{}"))),
])
def test_frozen_artifact_roundtrip_without_another_model_call(select):
    context = snapshot(reference="A 位于 core/a.py")
    outcome = select().plan(context)
    artifact = outcome.to_artifact(context)
    restored_context, restored = load_requirement_artifact(json.loads(json.dumps(artifact)))
    assert restored == outcome
    assert restored.to_artifact(restored_context) == artifact
    encoded = json.dumps(artifact)
    assert "PRIVATE_API_KEY" not in encoded and "PRIVATE_COT" not in encoded
    assert REQUIREMENT_PROMPT not in encoded


@pytest.mark.parametrize("mutate", [
    lambda p: p["metadata"].update(contract_sha256="0" * 64),
    lambda p: p["metadata"].update(input_sha256="0" * 64),
    lambda p: p["metadata"].update(call_count=0),
    lambda p: p["metadata"].update(input_tokens=True),
    lambda p: p["metadata"].update(effective_implementation="rule"),
    lambda p: p["metadata"].update(fallback_used=True),
    lambda p: p["effective_requirement"]["goals"][0].update(goal_id="g2"),
    lambda p: p["effective_requirement"]["goals"][0].update(depth="locator"),
    lambda p: p.update(raw_response="PRIVATE_COT"),
    lambda p: p["metadata"].update(api_key="PRIVATE_API_KEY"),
])
def test_tampered_artifact_is_rejected(mutate):
    artifact = llm().plan(snapshot()).to_artifact(snapshot())
    mutate(artifact)
    with pytest.raises((ValueError, TypeError)):
        load_requirement_artifact(artifact)


def test_other_request_snapshot_and_reference_only_tasks_are_rejected():
    outcome = llm().plan(snapshot())
    with pytest.raises(ValueError, match="input identity"):
        outcome.validate_input(snapshot("解释 C 的实现"))
    with pytest.raises(ValueError, match="input identity"):
        outcome.to_artifact(snapshot(reference="different referent"))
    client = Client(output(goal("旧问题", None, "direct", [], False)))
    assert llm(client).plan(snapshot(reference="旧问题")).requirement is None


def test_selector_rejects_wrong_input_identity_and_untyped_outcomes():
    class WrongInput(BaseRequirementProvider):
        def plan(self, context):
            return llm().plan(snapshot(reference="another input"))
    with pytest.raises(ValueError, match="input identity"):
        SelectedRequirementProvider(mode="shadow", llm=WrongInput()).plan(snapshot())
    class Dictionary(BaseRequirementProvider):
        def plan(self, context):
            return {"goals": []}
    with pytest.raises(TypeError, match="typed outcome"):
        SelectedRequirementProvider(mode="shadow", llm=Dictionary()).plan(snapshot())
