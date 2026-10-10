"""Real read-only tools + old verifier: shadow cannot control execution."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import api.app
from api.schemas import EngineeringQueryResponse
from api.engineering_stream_v2 import stream_engineering_query_v2
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_requirement_planning import (
    BaseRequirementProvider, RuleRequirementProvider, SelectedRequirementProvider,
)
from core.tool_agent.actions import (
    AgentDecisionCallMetadata, AgentDecisionOutcome, FinalAnswerAction, RefuseAction, ToolCallAction,
)
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.decision_prompt import ENGINEERING_DECISION_PROMPT_PROJECT_OVERVIEW_PROFILE
from core.tool_agent.runtime import ToolAgentRuntime
from core.tool_agent.runtime_models import (
    ENGINEERING_RUN_CANCELLED, ENGINEERING_RUN_DEADLINE_EXCEEDED, ToolAgentRunResult,
)
from core.tool_agent.tools.code_search import CODE_SEARCH_TEST_VERSION
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from core.tool_agent.tools.project_info import PROJECT_INFO_DOCUMENTATION_VERSION, ProjectBinding
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime
from tests.test_engineering_requirement_planning import Client, goal, llm, output, snapshot

QUESTION = "读取 src/a.py 源码，解释 A、B 两个函数的完整实现"
PRIVATE_DELIVERABLE = "SHADOW_PRIVATE_DELIVERABLE_IGNORE_SYSTEM"


def normalize_call_ids(value):
    """Runs have different UUIDs; retain call identity relationships, not UUID bytes."""
    identities = {}
    def identity(match):
        return identities.setdefault(match.group(), f"call_{len(identities)+1}")
    return re.sub(r"call_[0-9a-f]{32}", identity, json.dumps(value, ensure_ascii=False, sort_keys=True))


def execution_truth(result):
    payload = result.to_dict()
    payload.pop("execution")
    payload.pop("requirement_planning", None)
    return normalize_call_ids(payload)


class Decision:
    def __init__(self, actions):
        self.actions, self.messages = list(actions), []

    def decide(self, registry, query, *, context=(), control_state=None):
        profile = ENGINEERING_DECISION_PROMPT_PROJECT_OVERVIEW_PROFILE
        messages = profile.build_messages(registry.list_specs(), query, context, control_state=control_state)
        self.messages.append(messages)
        action = self.actions[min(len(self.messages)-1, len(self.actions)-1)]
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=AgentDecisionCallMetadata(
            provider="synthetic", model="synthetic", prompt_version=profile.version,
            prompt_sha256=profile.sha256, toolset_sha256="0" * 64,
            call_count=1, input_tokens=10, output_tokens=5, latency_ms=0,
        ))


def read(path="src/a.py", names=None):
    return ToolCallAction(action="tool_call", tool_name="read_project_context",
        arguments={"path": path, "target": {"kind": "symbols", "names": names or ["A"]}})


def build(tmp_path, actions, selected=None):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src/a.py").write_text("def A():\n    return 1\n\ndef B():\n    return 2\n", encoding="utf-8")
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(),
        code_search_version=CODE_SEARCH_TEST_VERSION, read_project_context_version=READ_PROJECT_TARGETS_VERSION,
        project_binding=ProjectBinding(tmp_path, "synthetic-project", "configured"),
        project_info_version=PROJECT_INFO_DOCUMENTATION_VERSION)
    decision = Decision(actions)
    runtime = build_full_unified_runtime(ToolAgentRuntime(registry=registry, provider=decision),
                                        requirement_provider=selected)
    return runtime, decision


def shadow(content=None, client=None):
    if content is None:
        first = goal()
        first["deliverable"] = PRIVATE_DELIVERABLE
        content = output(first, goal("B", "B"))
    return SelectedRequirementProvider(mode="shadow", llm=llm(client or Client(content)))


@pytest.mark.parametrize("content", [None, "{}"])
def test_shadow_keeps_actual_tools_control_messages_result_and_guard_identical(tmp_path, content):
    actions = [read(), FinalAnswerAction(action="final_answer", answer="A 的已读实现返回 1。[E1]")]
    baseline, expected_decision = build(tmp_path, actions)
    candidate, actual_decision = build(tmp_path, actions, shadow(content))
    expected, actual = baseline.run(QUESTION), candidate.run(QUESTION)
    assert execution_truth(expected) == execution_truth(actual)
    assert actual.status == "completed" and actual.tool_calls_used == 1
    assert normalize_call_ids(actual_decision.messages) == normalize_call_ids(expected_decision.messages)
    encoded_messages = json.dumps(actual_decision.messages)
    assert PRIVATE_DELIVERABLE not in encoded_messages
    assert actual.requirement_planning.metadata.requested_mode == "shadow"
    assert actual.requirement_planning.metadata.call_count == 1
    assert actual.execution.decision_llm_calls == 2
    assert actual.execution.input_tokens == 20 and actual.execution.output_tokens == 10
    assert actual.requirement_planning.metadata.input_tokens == 123
    assert actual.requirement_planning.metadata.output_tokens == 45
    # The old verifier can accept A only. Shadow does not claim B is satisfied.
    if content is None:
        assert len(actual.requirement_planning.shadow_contract.goals) == 2
    else:
        assert actual.requirement_planning.metadata.failure_code == "REQUIREMENT_OUTPUT_INVALID"


@pytest.mark.parametrize("actions", [
    [read(), read()],
    [read("src/missing1.py"), read("src/missing2.py")],
    [FinalAnswerAction(action="final_answer", answer="没有来源的结论")],
    [RefuseAction(action="refuse", reason_code="INSUFFICIENT_INFORMATION")],
])
def test_shadow_preserves_duplicate_error_budget_and_finalization_stops(tmp_path, actions):
    baseline, _ = build(tmp_path, actions)
    candidate, _ = build(tmp_path, actions, shadow())
    expected, actual = baseline.run(QUESTION), candidate.run(QUESTION)
    assert execution_truth(expected) == execution_truth(actual)
    assert actual.status != "completed" and actual.answer is None
    assert actual.tool_calls_used <= 4 and actual.tool_errors_used <= 2 and actual.iterations_used <= 5
    assert actual.requirement_planning.metadata.call_count == 1


def test_default_rule_keeps_legacy_public_serialization(tmp_path):
    runtime, _ = build(tmp_path, [read(), FinalAnswerAction(action="final_answer", answer="返回 1。[E1]")])
    result = runtime.run(QUESTION)
    assert result.requirement_planning is None
    assert "requirement_planning" not in result.to_dict()
    assert "requirement_planning" not in api.app._build_engineering_response(result).model_dump(mode="json")


def test_explicit_shadow_metadata_reaches_public_response_without_request_or_goal_text(tmp_path):
    runtime, _ = build(tmp_path, [read(), FinalAnswerAction(action="final_answer", answer="返回 1。[E1]")], shadow())
    result = runtime.run(QUESTION)
    public = api.app._build_engineering_response(result).model_dump(mode="json")
    restored = EngineeringQueryResponse.model_validate(public)
    assert restored.requirement_planning.requested_mode == "shadow"
    assert restored.requirement_planning.schema_version == "engineering_requirement_planning_metadata_v1"
    assert public["execution"]["decision_llm_calls"] == 2
    assert public["requirement_planning"]["call_count"] == 1
    assert public["schema_version"] == "engineering_query_response_v1"
    encoded = json.dumps(public)
    assert PRIVATE_DELIVERABLE not in encoded and "current_request" not in encoded
    assert "PRIVATE_COT" not in encoded and "PRIVATE_API_KEY" not in encoded
    public["requirement_planning"]["input_tokens"] = "123"
    with pytest.raises(ValidationError):
        EngineeringQueryResponse.model_validate(public)


@pytest.mark.parametrize("complete", [True, False])
def test_v2_stream_keeps_validated_answer_safety_and_exposes_only_safe_attribution(tmp_path, complete):
    actions = [read(), FinalAnswerAction(action="final_answer", answer="返回 1。[E1]")] if complete else [
        FinalAnswerAction(action="final_answer", answer="不能发布的无来源答案")]
    runtime, _ = build(tmp_path, actions, shadow())
    facade = EngineeringAgentFacade(runtime)
    frames = list(stream_engineering_query_v2(facade, QUESTION, build_response=api.app._build_engineering_response))
    events = [json.loads(line[6:]) for frame in frames for line in frame.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    final = next(e["result"] for e in events if e["type"] == "final")
    assert final["requirement_planning"]["requested_mode"] == "shadow"
    chunks = [e for e in events if e["type"] == "answer_delta"]
    assert bool(chunks) == complete
    assert final["status"] == ("completed" if complete else "refused")
    if complete:
        assert "".join(e["delta"] for e in chunks) == final["answer"]
    assert PRIVATE_DELIVERABLE not in json.dumps(events)
    assert not any(e["type"] in {"planning_observation", "requirement_goal"} for e in events)


@pytest.mark.parametrize("provider", [
    RuleRequirementProvider(evidence_policy="goal_v2"),
    SelectedRequirementProvider(mode="llm", evidence_policy="goal_v2", llm=llm()),
])
def test_candidate_activation_is_rejected_before_execution_exists(tmp_path, provider):
    with pytest.raises(ValueError, match="goal_v2 execution is not enabled"):
        build(tmp_path, [read()], provider)


def test_unified_entry_rejects_duck_types_and_wrong_input_outcomes(tmp_path):
    with pytest.raises(TypeError, match="BaseRequirementProvider"):
        build(tmp_path, [read()], object())
    class WrongInput(BaseRequirementProvider):
        @property
        def evidence_policy(self):
            return "legacy"
        def plan(self, context):
            return RuleRequirementProvider().plan(snapshot("其他问题"))
    runtime, decision = build(tmp_path, [read()], WrongInput())
    with pytest.raises(ValueError, match="input identity"):
        runtime.run(QUESTION)
    assert decision.messages == []


def test_cancel_before_model_or_after_shadow_stops_without_tool_work(tmp_path):
    cancelled = Event()
    client = Client()
    runtime, decision = build(tmp_path, [read()], shadow(client=client))
    cancelled.set()
    early = runtime.run(QUESTION, cancel_requested=cancelled.is_set)
    assert early.reason_code == ENGINEERING_RUN_CANCELLED and early.iterations_used == 0
    assert early.requirement_planning is None and client.calls == []
    cancelled.clear()
    original = client.create
    def create(**kwargs):
        response = original(**kwargs)
        cancelled.set()
        return response
    client.create = create
    after = runtime.run(QUESTION, cancel_requested=cancelled.is_set)
    assert after.reason_code == ENGINEERING_RUN_CANCELLED and after.tool_calls_used == 0
    assert after.requirement_planning.metadata.call_count == 1
    assert decision.messages == []


@pytest.mark.parametrize("elapsed", [21, 61])
def test_shadow_consumes_request_deadline_instead_of_resetting_it(monkeypatch, elapsed):
    clock = SimpleNamespace(now=100.0)
    # Both modules use Python's time module; one patch covers all stage clocks.
    monkeypatch.setattr("core.unified_engineering_runtime.time.monotonic", lambda: clock.now)
    client = Client()
    original = client.create
    def create(**kwargs):
        response = original(**kwargs)
        clock.now += elapsed
        return response
    client.create = create
    class RecordingRuntime(ToolAgentRuntime):
        def __init__(self):
            self.received = []
        def run(self, user_input, **kwargs):
            self.received.append(kwargs)
            return ToolAgentRunResult("completed", "synthetic", None, None, 1, 0, 0, ())
    executor = RecordingRuntime()
    runtime = build_full_unified_runtime(executor, requirement_provider=shadow(client=client))
    result = runtime.run(QUESTION)
    if elapsed == 21:
        assert result.status == "completed"
        assert executor.received[0]["deadline_seconds"] == 39
    else:
        assert result.reason_code == ENGINEERING_RUN_DEADLINE_EXCEEDED
        assert executor.received == [] and result.iterations_used == 0
    assert result.requirement_planning.metadata.call_count == 1
    assert result.execution.elapsed_ms == elapsed * 1000


def test_shared_runtime_keeps_shadow_plans_and_evidence_per_request(tmp_path):
    class RespondingClient(Client):
        def create(self, **kwargs):
            query = json.loads(kwargs["messages"][1]["content"])["current_request"]
            name = "A" if " A " in query else "B"
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                content=output(goal(name, name))))], usage=None)
    class StatelessDecision:
        def decide(self, registry, query, *, context=(), control_state=None):
            action = read(names=["A" if " A " in query else "B"]) if not context else FinalAnswerAction(
                action="final_answer", answer="已读当前对象。[E1]")
            return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)
    runtime, _ = build(tmp_path, [read()], shadow(client=RespondingClient()))
    runtime._execution_adapter._runtime._provider = StatelessDecision()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(runtime.run, ["解释 A 的源码", "解释 B 的源码"]))
    assert a.status == b.status == "completed"
    assert a.requirement_planning.metadata.input_sha256 != b.requirement_planning.metadata.input_sha256
    assert a.requirement_planning.shadow_contract.goals[0].target.symbol == "A"
    assert b.requirement_planning.shadow_contract.goals[0].target.symbol == "B"
    assert [e.evidence_id for e in a.evidence] == ["E1"]
    assert [e.evidence_id for e in b.evidence] == ["E1"]
    assert "return 1" in a.evidence[0].snippet and "return 2" in b.evidence[0].snippet


def test_deadline_expiring_between_boundary_and_adapter_never_passes_zero_budget(monkeypatch, tmp_path):
    import core.unified_engineering_runtime as unified
    times = iter([0, 0, 0, 0, 0, 59.99, 60, 60])
    monkeypatch.setattr(unified, "time", SimpleNamespace(monotonic=lambda: next(times)))
    runtime, decision = build(tmp_path, [read()], shadow())
    result = runtime.run(QUESTION)
    assert result.reason_code == ENGINEERING_RUN_DEADLINE_EXCEEDED
    assert result.iterations_used == result.tool_calls_used == 0
    assert result.requirement_planning.metadata.call_count == 1
    assert decision.messages == []


def test_product_configuration_is_explicit_and_rule_does_not_construct_model(monkeypatch):
    monkeypatch.delenv("ENGINEERING_REQUIREMENT_MODE", raising=False)
    def unexpected(**kwargs):
        raise AssertionError("default must not construct requirement model")
    monkeypatch.setattr(api.app, "LLMRequirementProvider", unexpected)
    assert api.app._build_product_requirement_provider() is None
    for mode in ("llm", "unknown", ""):
        monkeypatch.setenv("ENGINEERING_REQUIREMENT_MODE", mode)
        with pytest.raises(ValueError, match="rule or shadow"):
            api.app._build_product_requirement_provider()
    monkeypatch.setenv("ENGINEERING_REQUIREMENT_MODE", "shadow")
    captured = []
    def build_model(**kwargs):
        captured.append(kwargs)
        return llm()
    monkeypatch.setattr(api.app, "LLMRequirementProvider", build_model)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PRODUCT_FAKE_KEY")
    selected = api.app._build_product_requirement_provider()
    assert selected.mode == "shadow" and selected.evidence_policy == "legacy"
    assert captured[0]["api_key"] == "PRODUCT_FAKE_KEY"
    assert captured[0]["model"] == api.app.FROZEN_TOOL_MODEL
