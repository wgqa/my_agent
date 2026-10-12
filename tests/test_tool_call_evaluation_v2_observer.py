"""Passive instrumentation, safe defaults and saved-run integrity; no network."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.tool_calls_v2.manifest import business_fingerprint
from evaluation.tool_calls_v2.observer import RecordedDecisionProvider, Recorder, observe, record_provider_calls
from evaluation.tool_calls_v2.product_runtime import ScriptedReferenceProvider, build_product_runtime
from evaluation.tool_calls_v2.reporting import write_json
from evaluation.tool_calls_v2 import runner
from evaluation.tool_calls_v2.schema import PRIMARY_TOOLS, digest
from evaluation.tool_calls_v2.scorer import score_case, summarize
from tests.test_tool_call_evaluation_v2 import CASES, fixture_tools, proof


def test_decision_wrapper_preserves_inputs_outcome_and_excludes_public_answer_until_terminal(fixture_tools):
    from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction
    _, registry = fixture_tools
    result = AgentDecisionOutcome(action=FinalAnswerAction(action="final_answer", answer="public answer"), failure_code=None, call_metadata=None)
    context, control = [], object()
    calls = []

    class Delegate:
        def decide(self, passed_registry, query, *, context=(), control_state=None):
            calls.append((passed_registry, query, context, control_state))
            return result

    recorder = Recorder("dev-043")
    wrapper = RecordedDecisionProvider(Delegate(), recorder)
    observed = wrapper.decide(registry, "hello", context=context, control_state=control)
    assert observed is result and calls == [(registry, "hello", context, control)]
    assert calls[0][2] is context and calls[0][3] is control
    assert recorder.events[0]["action"] == {"action": "final_answer"}
    assert "public answer" not in json.dumps(recorder.events)


def test_executor_wrapper_preserves_result_and_restores_class_after_exception(fixture_tools):
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall
    _, registry = fixture_tools
    executor, call = ToolExecutor(registry), ToolCall.create("calculator", {"expression": "2+3"})
    baseline, original = executor.execute(call), ToolExecutor.execute
    recorder = Recorder("dev-001")
    with pytest.raises(RuntimeError, match="probe"):
        with observe(recorder):
            observed = executor.execute(call)
            assert observed == baseline
            raise RuntimeError("probe")
    assert ToolExecutor.execute is original
    assert recorder.events[0]["result"] == {"value": 5}


def test_retrieval_observer_preserves_lexical_query_keyword_and_result(monkeypatch):
    from core.engineering_retrieval import EngineeringRetrievalComponent

    outcome, component, delegated = object(), object(), []
    result = SimpleNamespace(route_decision=SimpleNamespace(route="direct_answer", retrieval_strategy="bm25"),
                             retrieval_call_count=0, knowledge_evidence=())

    def retrieve(passed_component, resolved_input, planner_outcome, *, retrieval_query=None):
        delegated.append((passed_component, resolved_input, planner_outcome, retrieval_query))
        return result

    monkeypatch.setattr(EngineeringRetrievalComponent, "retrieve", retrieve)
    recorder = Recorder("lexical-query-probe")
    query = '{"current_request":"它的默认值？","reference_context":"settings.RETRIES"}'
    lexical = "它的默认值？ settings.RETRIES"
    with observe(recorder):
        observed = EngineeringRetrievalComponent.retrieve(component, query, outcome, retrieval_query=lexical)
    assert observed is result and delegated == [(component, query, outcome, lexical)]
    assert EngineeringRetrievalComponent.retrieve is retrieve
    assert recorder.events[0]["retrieval_query"] == lexical


def test_fault_does_not_trigger_on_schema_invalid_input_and_restores_handler(fixture_tools):
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall
    _, registry = fixture_tools
    recorder = Recorder("dev-041", fault=CASES["dev-041"]["fault"])
    executor = ToolExecutor(registry)
    handler = registry.resolve("read_project_context").handler
    with observe(recorder):
        invalid = executor.execute(ToolCall.create("read_project_context", {"path": "agent_demo/cache.py"}))
        assert invalid.error_code == "INVALID_TOOL_ARGUMENTS" and not recorder.fault_triggered
        valid = executor.execute(ToolCall.create("read_project_context", {"path": "agent_demo/cache.py", "target": {"kind": "symbols", "names": ["fetch"]}}))
        assert valid.error_code == "TOOL_EXECUTION_FAILED" and recorder.fault_triggered
    assert registry.resolve("read_project_context").handler is handler
    assert executor.execute(ToolCall.create("read_project_context", {"path": "agent_demo/cache.py", "target": {"kind": "symbols", "names": ["fetch"]}})).status == "ok"


def test_recorder_whitelist_redacts_private_values_and_retains_all_reader_targets(fixture_tools):
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall
    _, registry = fixture_tools
    recorder = Recorder("dev-012", private_strings=("PRIVATE_HOST_PATH", "private_api_key"))
    recorder.add("test", data="PRIVATE_HOST_PATH/private_api_key")
    with observe(recorder):
        ToolExecutor(registry).execute(ToolCall.create("read_project_context", CASES["dev-012"]["reference_calls"][0]["arguments"]))
    tool = recorder.events[1]
    assert len(tool["result"]["targets"]) == 2 and len(tool["result"]["regions"]) == 2
    assert tool["arguments"]["target"]["names"] == ["Transport.backoff", "Transport.can_retry"]
    saved = json.dumps(recorder.events)
    assert "PRIVATE_HOST_PATH" not in saved and "private_api_key" not in saved
    assert "prompt" not in tool and "thought" not in saved and "raw_output" not in saved


def test_sdk_observation_retains_individual_missing_usage_without_messages_or_outputs():
    responses = [SimpleNamespace(usage=SimpleNamespace(prompt_tokens=50, completion_tokens=None), secret_body="raw output"),
                 SimpleNamespace(usage=SimpleNamespace(prompt_tokens=60, completion_tokens=8), secret_body="raw output")]
    inputs = []

    def create(**kwargs):
        inputs.append(kwargs)
        return responses[len(inputs) - 1]

    resource = SimpleNamespace(create=create)
    provider = SimpleNamespace(_client=SimpleNamespace(chat=SimpleNamespace(completions=resource)))
    recorder = Recorder("dev-043")
    messages = [{"role": "system", "content": "prompt containing private_api_key"}]
    with record_provider_calls(provider, "decision", recorder):
        first = resource.create(model="fake", messages=messages)
        second = resource.create(model="fake", messages=messages)
    assert first is responses[0] and second is responses[1] and resource.create is create
    assert inputs[0]["messages"] is messages
    assert [e["output_tokens"] for e in recorder.events] == [None, 8]
    assert "private_api_key" not in json.dumps(recorder.events) and "raw output" not in json.dumps(recorder.events)


def test_absolute_path_is_not_persisted_but_remains_an_unsafe_attempt(fixture_tools):
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall
    _, registry = fixture_tools
    case = CASES["dev-046"]
    recorder = Recorder(case["id"], private_strings=("C:/private",))
    with observe(recorder):
        ToolExecutor(registry).execute(ToolCall.create("read_project_context", {"path": "C:/private/project/file.py", "target": {"kind": "file", "start_line": 1}}))
    recorder.add("terminal", status="refused", reason_code="UNSAFE_REQUEST", failure_code=None, iterations_used=1, tool_calls_used=1, elapsed_ms=1)
    score = score_case(case, recorder.events, mode="gold_proof")
    assert score["unsafe_attempt_count"] == 1 and score["verdict"] == "FAIL"
    assert "C:/private" not in json.dumps(recorder.events)
    assert recorder.events[0]["arguments"]["path"] == "<absolute-path-redacted>"


def test_sdk_error_is_reraised_identically_without_exception_text():
    failure = RuntimeError("Authorization: private_api_key")

    def create(**kwargs):
        raise failure

    resource = SimpleNamespace(create=create)
    provider = SimpleNamespace(_client=SimpleNamespace(chat=SimpleNamespace(completions=resource)))
    recorder = Recorder("dev-043")
    with record_provider_calls(provider, "decision", recorder):
        with pytest.raises(RuntimeError) as caught:
            resource.create(messages=[{"content": "secret prompt"}])
    assert caught.value is failure and recorder.events[0]["status"] == "transport_error"
    assert "Authorization" not in json.dumps(recorder.events) and "private_api_key" not in json.dumps(recorder.events)


@pytest.mark.parametrize("case_id", ["dev-001", "dev-009", "dev-025", "dev-029", "dev-039", "dev-040", "dev-041", "dev-046", "dev-048"])
def test_actual_product_factory_scripted_path_and_disabled_knowledge(case_id, fixture_tools, tmp_path, monkeypatch):
    import api.app as backend
    from core.knowledge_library import KnowledgeLibrary
    from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
    from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner

    def no_real_client(*args, **kwargs):
        pytest.fail("Offline product replay attempted to instantiate a real provider client")

    monkeypatch.setattr(OpenAICompatibleAgentDecisionProvider, "_build_default_client", no_real_client)
    monkeypatch.setattr(OpenAICompatibleQueryPlanner, "_build_default_client", no_real_client)
    root, _ = fixture_tools
    before = backend.engineering_knowledge_backend
    library = KnowledgeLibrary(tmp_path / "own-knowledge.sqlite3")
    case = CASES[case_id]
    recorder = Recorder(case_id, fault=case["fault"])
    result = runner.run_facade(case, root, library, recorder, live=False)
    assert backend.engineering_knowledge_backend is before
    score = score_case(case, recorder.events, mode="scripted")
    # Scripted fixtures exercise record integrity and wiring only; they are
    # not model-generated answers and must not be counted as Agent quality.
    assert score["valid"] is True, score.get("record_problems")
    assert score["mode"] == "scripted"
    assert result.iterations_used == len([e for e in recorder.events if e["stage"] == "decision"])
    expected_tools = sorted((*PRIMARY_TOOLS, "get_project_info"))
    assert recorder.events[-1]["enabled_tools"] == expected_tools
    assert all(e["available_tools"] == expected_tools for e in recorder.events if e["stage"] == "decision")
    assert [e["stage"] for e in recorder.events][:2] == ["planner", "pre_retrieval"]
    assert not any(e["stage"] == "provider_call" for e in recorder.events)


def test_all_seven_real_tool_contracts_but_only_six_primary(fixture_tools):
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall
    _, registry = fixture_tools
    assert len(registry.list_specs()) == 7
    assert registry.get_spec("read_project_context").version == "read_project_context_v4"
    assert registry.get_spec("code_search").version == "code_search_v7"
    observation = ToolExecutor(registry).execute(ToolCall.create("knowledge_search", {"query": "BM25"}))
    assert observation.status == "ok" and observation.result["matches"]
    primary = registry.without(frozenset({"knowledge_search"}))
    assert len(primary.list_specs()) == 6 and "knowledge_search" not in primary


def test_declared_product_toolset_rejects_expansion_and_step_drift(fixture_tools, tmp_path):
    from copy import deepcopy
    from core.knowledge_library import KnowledgeLibrary

    root, _ = fixture_tools
    case = CASES["dev-001"]
    recorder = Recorder(case["id"])
    runner.run_facade(case, root, KnowledgeLibrary(tmp_path / "identity-check.sqlite3"), recorder, live=False)
    assert score_case(case, recorder.events, mode="scripted")["valid"]
    drift = deepcopy(recorder.events)
    next(e for e in drift if e["stage"] == "decision")["available_tools"].append("knowledge_search")
    assert "PRIMARY_TOOLSET_CHANGED" in score_case(case, drift, mode="scripted")["record_problems"]
    expanded = deepcopy(recorder.events)
    expanded[-1]["enabled_tools"].append("invented_tool")
    for event in expanded:
        if event["stage"] == "decision":
            event["available_tools"].append("invented_tool")
    assert "PRIMARY_TOOLSET_CHANGED" in score_case(case, expanded, mode="scripted")["record_problems"]


def test_default_cli_has_no_live_flag_and_prepare_mode_only_prepares(monkeypatch, tmp_path):
    executed, prepared = [], []
    monkeypatch.setattr(runner, "execute", lambda cases, **kwargs: executed.append(kwargs) or
                        {"mode": kwargs["mode"], "recorded_requests": len(cases), "verdicts": {"PASS": len(cases)},
                         "is_model_quality_result": False, "invalid_records": 0, "not_run": [], "planned_requests": len(cases)})
    assert runner.main(["--case", "dev-001", "--output", str(tmp_path / "report")]) == 0
    assert executed[0]["mode"] == "gold_proof"
    monkeypatch.setattr(runner, "prepare_source_cache", prepared.append)
    assert runner.main(["--prepare-sources", "--source-cache", str(tmp_path / "cache")]) == 0
    assert len(executed) == 1 and prepared == [tmp_path / "cache"]
    with pytest.raises(SystemExit):
        runner.main(["--live"])
    assert len(executed) == 1


def metadata(*, count=1, repair=False, category=None, input_tokens=100, output_tokens=10):
    return {"call_count": count, "repair_attempted": repair, "repair_succeeded": repair, "initial_parse_category": category,
            "input_tokens": input_tokens, "output_tokens": output_tokens}


def synthetic_parse_records(case):
    recorder = Recorder(case["id"])
    recorder.add("provider_call", role="planner", input_tokens=100, output_tokens=10, status="response")
    recorder.add("planner", metadata=metadata(), failure_code=None)
    recorder.add("pre_retrieval", retrieval_call_count=0)
    recorder.add("provider_call", role="decision", input_tokens=50, output_tokens=None, status="response")
    recorder.add("provider_call", role="decision", input_tokens=60, output_tokens=8, status="response")
    recorder.add("decision", action={"action": "final_answer"}, metadata=metadata(count=2, repair=True, category="ARGUMENTS_SCHEMA_INVALID", input_tokens=110, output_tokens=8),
                 failure_code=None, available_tools=sorted(PRIMARY_TOOLS), elapsed_ms=1)
    recorder.add("terminal", status="completed", reason_code=None, failure_code=None, iterations_used=1, tool_calls_used=0, elapsed_ms=2)
    return recorder.events


def test_initial_schema_errors_count_before_any_executor_call_and_usage_is_not_double_counted():
    case = CASES["dev-043"]
    events = synthetic_parse_records(case)
    score = score_case(case, events, mode="live")
    summary = summarize([case], [score], {case["id"]: events}, mode="live")
    metrics, cost = summary["metrics"], summary["cost"]
    assert score["verdict"] == "PASS" and score["first_action_repaired"] is True
    assert metrics["initial_parse_valid"] == {"numerator": 0, "denominator": 1, "rate": 0}
    assert metrics["after_repair_parse_valid"]["rate"] == 1 and metrics["parse_repair_success"]["rate"] == 1
    assert metrics["initial_argument_schema_errors_unknown_tool_attribution"] == 1 and metrics["executor_argument_errors"] == 0
    assert cost["provider_calls_known"] == 3 and cost["logical_metadata_call_count"] == 3
    assert cost["input_tokens_known"] == 210 and cost["output_tokens_known"] == 18
    assert cost["output_usage_missing_calls"] == 1 and cost["input_usage_missing_calls"] == 0


def test_provider_failure_and_missing_provider_records_are_invalid():
    case = CASES["dev-043"]
    events = synthetic_parse_records(case)
    events[-2]["action"], events[-2]["failure_code"] = None, "ACTION_PROVIDER_ERROR"
    events[-1]["status"], events[-1]["failure_code"] = "failed", "ACTION_PROVIDER_ERROR"
    score = score_case(case, events, mode="live")
    assert score["verdict"] == "INVALID" and "PROVIDER_UNAVAILABLE" in score["record_problems"]
    events = synthetic_parse_records(case)
    events = [e for e in events if e["stage"] != "provider_call"]
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
    assert "PROVIDER_OBSERVATION_INCOMPLETE" in score_case(case, events, mode="live")["record_problems"]


def saved_run(path: Path, case: dict, events: list[dict]):
    path.mkdir()
    runner._json_lines(path / "cases.jsonl", [case])
    runner._json_lines(path / "calls.jsonl", events)
    write_json(path / "manifest.json", {"run_id": "offline_unit", "code_head": "unit", "business": {"sha256": "unit"},
               "mode": "gold_proof", "cases_sha256": digest([case]), "scoring_sha256": runner.scoring_identity(),
               "artifacts_sha256": {name: hashlib.sha256((path / name).read_bytes()).hexdigest() for name in ("cases.jsonl", "calls.jsonl")}})


def test_saved_run_recomputes_without_provider_and_detects_tampering(fixture_tools, tmp_path):
    _, registry = fixture_tools
    case, events = proof("dev-009", registry)
    source = tmp_path / "original"
    saved_run(source, case, events)
    before = (source / "calls.jsonl").read_bytes()
    summary = runner.recompute(source, tmp_path / "recomputed")
    assert summary["verdicts"] == {"PASS": 1} and summary["is_model_quality_result"] is False
    assert (source / "calls.jsonl").read_bytes() == before
    with (source / "calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="Saved artifact changed"):
        runner.recompute(source, tmp_path / "tampered")


def test_rule_change_needs_a_new_analysis_not_overwrite(fixture_tools, tmp_path, monkeypatch):
    _, registry = fixture_tools
    case, events = proof("dev-009", registry)
    source = tmp_path / "original"
    saved_run(source, case, events)
    monkeypatch.setattr(runner, "scoring_identity", lambda: "different-rule-version")
    with pytest.raises(ValueError, match="Scoring rules changed"):
        runner.recompute(source, tmp_path / "new")
    summary = runner.recompute(source, tmp_path / "new", allow_rule_change=True)
    assert summary["recorded_requests"] == 1
    assert json.loads((tmp_path / "new/manifest.json").read_text())["scoring_rules_changed"]
    with pytest.raises(FileExistsError):
        runner.recompute(source, source, allow_rule_change=True)


@pytest.mark.parametrize("mode,invalid,not_run,exit_code", [
    ("live", 0, [], 0),
    ("gold_proof", 0, [], 1),
    ("live", 1, [], 1),
    ("live", 0, ["dev-002"], 1),
])
def test_rescore_cli_uses_saved_mode_and_keeps_infrastructure_exit_failures(mode, invalid, not_run, exit_code, monkeypatch, tmp_path):
    summary = {"mode": mode, "invalid_records": invalid, "not_run": not_run, "verdicts": {"FAIL": 1},
               "planned_requests": 1, "recorded_requests": 1, "is_model_quality_result": mode == "live"}
    calls = []

    def rescore(source, destination, *, allow_rule_change):
        calls.append((source, destination, allow_rule_change))
        return summary

    monkeypatch.setattr(runner, "recompute", rescore)
    assert runner.main(["--rescore", str(tmp_path / "saved"), "--output", str(tmp_path / "analysis"),
                        "--run-id", "cli-mode-check"]) == exit_code
    assert calls == [(tmp_path / "saved", tmp_path / "analysis", False)]


def test_live_metadata_must_match_frozen_runtime():
    expected = {"provider": "fake", "model": "fake-model", "decision": {"version": "v4", "sha256": "0" * 64},
                "primary_toolset_sha256": "1" * 64}
    event = {"stage": "decision", "metadata": {"provider": "fake", "model": "fake-model", "prompt_version": "v4",
             "prompt_sha256": "0" * 64, "toolset_sha256": "1" * 64}}
    runner.assert_live_identity([event], expected)
    event["metadata"]["toolset_sha256"] = "2" * 64
    with pytest.raises(RuntimeError, match="RUNTIME_IDENTITY_CHANGED"):
        runner.assert_live_identity([event], expected)


def test_live_wiring_with_fake_sdk_covers_planner_repair_usage_and_no_gold_leak(fixture_tools, tmp_path, monkeypatch):
    """Exercise the explicit live branch with fake clients: still zero network."""
    import api.app as backend
    from core.knowledge_library import KnowledgeLibrary
    from core.query_planning.openai_compatible import OpenAICompatibleQueryPlanner
    from core.tool_agent.openai_compatible import OpenAICompatibleAgentDecisionProvider
    from evaluation.tool_calls_v2.manifest import runtime_identity

    def response(content, input_tokens, output_tokens):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens) if input_tokens is not None else None)

    class FakeClient:
        def __init__(self, responses):
            self.responses, self.inputs, self.closed = iter(responses), [], False
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            self.inputs.append(kwargs)
            return next(self.responses)

        def close(self):
            self.closed = True

    planner = FakeClient([response({"query_type": "unanswerable_or_no_retrieval", "retrieval_required": False,
                                   "action": "no_retrieval", "reason_code": "NO_RETRIEVAL_NEEDED", "subqueries": []}, 100, 10)])
    decision = FakeClient([
        response({"action": "tool_call", "tool_name": "calculator", "arguments": {"expression": 25}}, None, None),
        response({"action": "tool_call", "tool_name": "calculator", "arguments": {"expression": "(12000-9000)/12000*100"}}, 60, 8),
        response({"action": "final_answer", "answer": "下降百分比是 25%。"}, 20, 5),
    ])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-placeholder-not-a-real-key")
    monkeypatch.setattr(OpenAICompatibleQueryPlanner, "_build_default_client", lambda self, key: planner)
    monkeypatch.setattr(OpenAICompatibleAgentDecisionProvider, "_build_default_client", lambda self, key: decision)
    resolver_config = []

    def no_history_resolver(**kwargs):
        resolver_config.append(kwargs["prompt_version"])
        return None

    monkeypatch.setattr(backend, "OpenAICompatibleConversationQueryResolver", no_history_resolver)
    root, registry = fixture_tools
    case = CASES["dev-001"]
    recorder = Recorder(case["id"])
    runner.run_facade(case, root, KnowledgeLibrary(tmp_path / "fake-sdk-knowledge.sqlite3"), recorder, live=True)
    from evaluation.tool_calls_v2.product_runtime import build_evaluation_registry
    identity = runtime_identity(build_evaluation_registry(root, KnowledgeLibrary(tmp_path / "identity.sqlite3").retrieval_port))
    runner.assert_live_identity(recorder.events, identity)
    assert resolver_config == [identity["context"]["version"]]
    assert next(e for e in recorder.events if e["stage"] == "pre_retrieval")["retrieval_query"] == case["query"]
    score = score_case(case, recorder.events, mode="live")
    summary = summarize([case], [score], {case["id"]: recorder.events}, mode="live")
    assert not score["record_problems"], score["record_problems"]
    assert score["verdict"] == "PASS", score
    assert summary["cost"]["provider_calls_known"] == 4 and summary["cost"]["logical_decisions"] == 2
    assert summary["cost"]["input_tokens_known"] == 180 and summary["cost"]["output_tokens_known"] == 23
    assert summary["cost"]["input_usage_missing_calls"] == 1
    assert summary["cost"]["output_usage_missing_calls"] == 1
    assert planner.closed and decision.closed
    sent = json.dumps([planner.inputs, decision.inputs], ensure_ascii=False)
    assert case["query"] in sent
    for gold_only_key in ("reference_calls", "source_hashes", "rationale", "terminal_statuses"):
        assert gold_only_key not in sent
    assert "messages" not in json.dumps(recorder.events)
