from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT.parent
FIXTURES = PROJECTS / "_task018_e2e_fixtures"
B2_CHECKOUT = PROJECTS / "rag-knowledge-base-b2-exact-de0ca"
TASK019_CHECKOUT = ROOT
TASK017_CHECKOUT = TASK019_CHECKOUT  # Retained for old probe fault scenarios.
PROBE_PATH = ROOT / "evaluation" / "task018_e2e" / "fake_e2e_probe.py"


def _probe_module():
    spec = importlib.util.spec_from_file_location("task018_fake_e2e_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _live_runner_module():
    path = ROOT / "evaluation" / "task018_e2e" / "live_e2e_runner.py"
    spec = importlib.util.spec_from_file_location("task018_live_e2e_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _worker(checkout: Path, variant: str, cases: list[str], *, context: bool = False):
    command = [sys.executable, "-I", str(PROBE_PATH), "--checkout", str(checkout),
               "--variant", variant, "--fixture-root", str(FIXTURES)]
    if context:
        command.extend(["--cases", "case08", "--context-probe"])
    else:
        command.extend(["--cases", *cases])
    child_env = os.environ.copy()
    child_env.pop("DEEPSEEK_API_KEY", None)
    child_env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(command, cwd=checkout, env=child_env,
                               capture_output=True, timeout=120, check=False)
    stdout = completed.stdout or b""
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    assert completed.returncode == 0, stderr + "\n" + stdout[-3000:].decode("utf-8", errors="replace")
    marker = b'"mode": "fake_only"'
    marker_position = stdout.rfind(marker)
    assert marker_position >= 0, stdout[-3000:].decode("utf-8", errors="replace")
    position = stdout.rfind(b"{", 0, marker_position)
    assert position >= 0, stdout[-3000:].decode("utf-8", errors="replace")
    return json.loads(stdout[position:].decode("utf-8", errors="strict"))


@pytest.mark.parametrize("checkout,variant", [
    (PROJECTS / "rag-knowledge-base-hybrid-task-contract", "task020"),
    (ROOT, "task021"),
])
def test_task021_measurement_seam_observes_real_task020_runtime_offline(checkout, variant):
    result = _worker(checkout, variant,
                     ["case10", "case09", "case07", "case08"])
    assert result["live_mode"] is False
    assert len(result["results"]) == 4
    for row in result["results"]:
        assert row["infrastructure_status"] == "ok", row
        assert row["planner"][0]["task_contract"] is not None
        assert row["final"]["task_contract"] is not None
        assert row["final"]["status"] == "completed", row["final"]
        assert row["final"]["trace"]
        assert all(call["model"] == "deepseek-flash"
                   and call["thinking"] == {"type": "disabled"}
                   for call in row["provider_requests"])
        assert all(call["host"] == "offline.invalid" for call in row["provider_requests"])
    assert result["results"][0]["tools"][0]["call"]["tool_name"] == "changed_files"
    assert result["results"][1]["tools"][0]["call"]["tool_name"] == "read_project_context"


def test_task021_schedule_and_combined_budget_do_not_reset_between_phases():
    runner = _live_runner_module()
    runner.configure_task021("controls")
    assert len(runner.PLAN) == 8
    assert [item["variant"] for item in runner.PLAN] == ["direct_hybrid", "task020"] * 4
    assert [item["case_id"] for item in runner.PLAN[::2]] == ["case10", "case09", "case07", "case08"]
    budget_id = runner.TASK021_BUDGET_ID
    runner.configure_task021("candidate")
    assert len(runner.PLAN) == 4
    assert [item["task_order"] for item in runner.PLAN] == [9, 10, 11, 12]
    assert runner.TASK021_BUDGET_ID == budget_id
    assert (runner.MAX_REQUESTS, runner.MAX_TOKENS, runner.MAX_ESTIMATED_USD) == (84, 400_000, 0.25)


def test_task019_matrix_uses_real_runtime_and_fake_http_only():
    b2 = _worker(B2_CHECKOUT, "b2", ["case01", "case02", "case03", "case04"])
    direct = _worker(TASK019_CHECKOUT, "direct_hybrid",
                     ["case01", "case02", "case03", "case04", "case05", "case07", "case08"])
    assert b2["live_mode"] is False
    assert direct["live_mode"] is False
    assert len(b2["results"]) == 4
    assert len(direct["results"]) == 7
    assert len(b2["results"]) + len(direct["results"]) == 11
    all_runs = b2["results"] + direct["results"]

    by_variant = {"b2": b2["results"], "direct_hybrid": direct["results"]}
    for row in all_runs:
        assert row["infrastructure_status"] == "ok", (
            row.get("variant"), row.get("case_id"), row.get("stop_reason"),
            [request.get("role") for request in row.get("provider_requests", [])],
            row.get("provider_responses"),
        )
        assert row["provider_request_count"] == len(row["provider_requests"])
        assert row["provider_request_count"] == len(row["provider_responses"])
        assert row["provider_request_count"] > 0
        assert row["provider_tokens"]["total"] > 0
        assert row["estimated_cost_usd"] > 0
        assert all(len(request["prompt_sha256"]) == 64 for request in row["provider_requests"])
        assert all(isinstance(response["latency_ms"], (int, float))
                   and response["latency_ms"] >= 0
                   for response in row["provider_responses"])
        assert all(request["model"] == "deepseek-flash" for request in row["provider_requests"])
        assert all(request["host"] == "offline.invalid" for request in row["provider_requests"])
        assert all(request["thinking"] == {"type": "disabled"} for request in row["provider_requests"])
        assert all(request["temperature"] == 0 for request in row["provider_requests"])
        assert all(response["response_model"] == "deepseek-flash" for response in row["provider_responses"])
        assert all(response["usage"] is not None for response in row["provider_responses"])
        assert row["fixture_head"] in (None, "d6b6c100d5e2e441957d834a29a73a8bc4ac1693")

    b2_by_id = {row["case_id"]: row for row in by_variant["b2"]}
    direct_by_id = {row["case_id"]: row for row in by_variant["direct_hybrid"]}
    for case_id in ("case01", "case02", "case03", "case04"):
        left, right = b2_by_id[case_id], direct_by_id[case_id]
        assert left["question"] == right["question"]
        assert left["fixture_id"] == right["fixture_id"]
        assert left["fixture_head"] == right["fixture_head"]
        assert left["requirement"] == right["requirement"]
        assert left["agent_budget"] == right["agent_budget"] == {
            "max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2,
            "deadline_seconds": 60,
        }
        assert left["enabled_tools"] == right["enabled_tools"]
        left_core_calls = [call for call in left["provider_requests"]
                           if call["role"] in ("planner", "decision")]
        right_core_calls = [call for call in right["provider_requests"]
                            if call["role"] in ("planner", "decision")]
        assert [call["role"] for call in left_core_calls] == [call["role"] for call in right_core_calls]
        assert [(call["model"], call["temperature"], call["max_tokens"], call["response_format"])
                for call in left_core_calls] == [
            (call["model"], call["temperature"], call["max_tokens"], call["response_format"])
            for call in right_core_calls
        ]
        assert left_core_calls[0]["prompt_sha256"] == right_core_calls[0]["prompt_sha256"]
        assert left_core_calls[1]["prompt_sha256"] != right_core_calls[1]["prompt_sha256"]
        assert left["final"]["status"] == "refused"
        assert right["final"]["status"] == "completed"
        assert len(left["tools"]) == len(right["tools"]) == 1
        assert left["tools"][0]["call"]["tool_name"] == right["tools"][0]["call"]["tool_name"] == "changed_files"
        assert right["typed_finalization"] and right["typed_finalization"][0]["accepted"] is True
        assert right["final"]["execution"]["selector_llm_calls"] == 0
        assert not any(request["role"] == "selector" for request in right["provider_requests"])
        assert left["final"]["evidence"][0]["result_sha256"] == right["final"]["evidence"][0]["result_sha256"]
        assert left["tools"][0]["result"] == right["tools"][0]["result"]
        assert left["gate"][-1]["stage"] == "legacy_answer_gate"
        assert left["gate"][-1]["can_finalize"] is False
        assert all(item["stage"] == "requirement_precheck" for item in right["gate"])
        assert right["open_answer_source_check"] == []

    assert all(fragment in direct_by_id["case01"]["final"]["answer"] for fragment in (
        "docs/usage.md", "src/main.py", "src/old_parser.py", "src/new_parser.py",
        "src/retired_source.py", "tests/test_main.py", "added", "modified", "renamed", "deleted",
    ))
    assert "src/retired_source.py" in direct_by_id["case02"]["final"]["answer"]
    assert "src/main.py" not in direct_by_id["case02"]["final"]["answer"]
    assert "src/old_parser.py" in direct_by_id["case03"]["final"]["answer"]
    assert "src/new_parser.py" in direct_by_id["case03"]["final"]["answer"]
    assert direct_by_id["case03"]["typed_finalization"][0]["accepted"] is True
    assert all(fragment in direct_by_id["case04"]["final"]["answer"] for fragment in (
        "working_tree", "成功检查", "清单为空", "结果完整", "未发现可见变更文件",
    ))
    assert direct_by_id["case05"]["final"]["status"] == "completed"
    assert direct_by_id["case05"]["typed_finalization"][0]["accepted"] is True
    assert "notes/local_sample.md" in direct_by_id["case05"]["final"]["answer"]
    assert direct_by_id["case07"]["final"]["status"] == "completed"
    assert direct_by_id["case07"]["typed_finalization"] == []
    assert direct_by_id["case07"]["open_answer_source_check"][0]["accepted"] is True
    assert direct_by_id["case07"]["provider_request_count"] == 4
    assert not any(response["role"] == "selector"
                   for response in direct_by_id["case07"]["provider_responses"])
    assert [tool["call"]["tool_name"] for tool in direct_by_id["case07"]["tools"]] == ["changed_files", "git_diff"]
    assert direct_by_id["case08"]["planner"][0]["plan"]["retrieval_required"] is True
    assert direct_by_id["case08"]["final"]["status"] == "completed"
    assert "12 秒" in direct_by_id["case08"]["final"]["answer"]
    assert direct_by_id["case08"]["open_answer_source_check"][0]["accepted"] is True
    assert any(item["kind"] == "knowledge" and "12 秒" in item["snippet"]
               for item in direct_by_id["case08"]["final"]["evidence"])


def test_context_resolver_uses_flash_and_explicit_thinking_disabled():
    result = _worker(TASK019_CHECKOUT, "task017", ["case08"], context=True)["context_probe"]
    assert result["resolver_used"] is True
    assert result["request_count"] == 1
    assert result["model"] == "deepseek-flash"
    assert result["thinking"] == {"type": "disabled"}
    assert result["response"]["response_model"] == "deepseek-flash"
    assert result["response"]["usage"] is not None


@pytest.mark.parametrize(
    "fault,model_override,request_limit,expected_stop,expected_sent",
    [
        (None, "deepseek-chat", 65, "REQUEST_MODEL_MISMATCH", 0),
        ({"role": "planner", "kind": "response_model", "response_model": "other-model"},
         "deepseek-flash", 65, "RESPONSE_MODEL_MISMATCH", 1),
        ({"role": "planner", "usage": None}, "deepseek-flash", 65,
         "USAGE_REQUIRED_TO_CONTINUE", 1),
        (None, "deepseek-flash", 0, "PROVIDER_REQUEST_BUDGET_STOP", 0),
        ({"role": "planner", "kind": "http_503"}, "deepseek-flash", 65,
         "PROVIDER_REQUEST_FAILED:InternalServerError", 1),
    ],
)
def test_model_usage_provider_and_budget_faults_stop_without_retry(
    fault, model_override, request_limit, expected_stop, expected_sent,
):
    module = _probe_module()
    row = module.run_case(TASK017_CHECKOUT, "task017", module.CASES["case01"], FIXTURES,
                          fault=fault, model_override=model_override,
                          request_limit=request_limit)
    assert row["infrastructure_status"] == "stopped"
    assert expected_stop in row["stop_reason"]
    assert row["provider_request_count"] == expected_sent
    assert len(row["provider_responses"]) == expected_sent
    assert len(row["provider_requests"]) == expected_sent
    assert len(row["provider_guard_stops"]) == (1 if expected_sent == 0 else 0)


@pytest.mark.parametrize(
    "token_limit,cost_limit,expected_stop,expected_sent",
    [
        (100, 0.20, "TOKEN_BUDGET_STOP", 0),
        (1_000, 0.20, "TOKEN_BUDGET_STOP", 1),
        (300_000, 0.0005, "ESTIMATED_COST_BUDGET_STOP", 0),
        (300_000, 0.0012, "ESTIMATED_COST_BUDGET_STOP", 1),
    ],
)
def test_token_and_estimated_cost_stops_happen_before_next_http_request(
    token_limit, cost_limit, expected_stop, expected_sent,
):
    module = _probe_module()
    row = module.run_case(TASK017_CHECKOUT, "task017", module.CASES["case01"], FIXTURES,
                          token_limit=token_limit, cost_limit=cost_limit)
    assert row["infrastructure_status"] == "stopped"
    assert expected_stop in row["stop_reason"]
    assert row["provider_request_count"] == expected_sent
    assert len(row["provider_responses"]) == expected_sent
    assert len(row["provider_guard_stops"]) == 1


def _shared_fake_worker(checkout: Path, variant: str, case_id: str, task_order: int,
                        budget_db: Path, run_id: str, *, max_requests: int = 60,
                        max_tokens: int = 200_000, max_cost: float = 0.15):
    command = [sys.executable, "-I", str(PROBE_PATH), "--checkout", str(checkout),
               "--variant", variant, "--fixture-root", str(FIXTURES),
               "--cases", case_id, "--provider-mode", "fake",
               "--shared-budget-db", str(budget_db), "--task-order", str(task_order),
               "--run-id", run_id, "--max-requests", str(max_requests),
               "--max-tokens", str(max_tokens), "--max-estimated-usd", str(max_cost)]
    child_env = os.environ.copy()
    child_env.pop("DEEPSEEK_API_KEY", None)
    child_env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(command, cwd=checkout, env=child_env,
                               capture_output=True, timeout=120, check=False)
    stdout = completed.stdout or b""
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    assert completed.returncode == 0, stderr + "\n" + stdout[-2000:].decode("utf-8", errors="replace")
    marker = b'"mode": "fake_only"'
    marker_position = stdout.rfind(marker)
    assert marker_position >= 0, stdout[-2000:].decode("utf-8", errors="replace")
    position = stdout.rfind(b"{", 0, marker_position)
    assert position >= 0, stdout[-2000:].decode("utf-8", errors="replace")
    return json.loads(stdout[position:].decode("utf-8", errors="strict"))["results"][0]


def test_shared_budget_gate_covers_fixed_11_fake_runtime_schedule(tmp_path):
    module = _probe_module()
    live_runner = _live_runner_module()
    run_id = "task018-shared-fake-matrix"
    database = tmp_path / "shared.sqlite3"
    gate = module.SharedBudgetGate(database, run_id=run_id)
    rows = []
    for item in live_runner.PLAN:
        order, case_id, variant = item["task_order"], item["case_id"], item["variant"]
        checkout = B2_CHECKOUT if variant == "b2" else TASK017_CHECKOUT
        rows.append(_shared_fake_worker(checkout, variant, case_id, order,
                                        database, run_id))
    assert len(rows) == 11
    assert all(row["infrastructure_status"] == "ok" for row in rows)
    snapshot = gate.snapshot()
    assert snapshot["requests_reserved"] == 33
    assert snapshot["total_tokens"] == 33 * 144
    assert snapshot["estimated_usd"] == pytest.approx(33 * 0.0000648)
    assert snapshot["pending_provider_results"] == 0
    assert snapshot["call_status_counts"] == {"response_recorded": 33}
    gate.export_calls_jsonl(tmp_path / "provider_calls.jsonl")
    calls = [json.loads(line) for line in (tmp_path / "provider_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["role"] for row in calls} == {"planner", "decision"}
    assert all(row["request_model"] == row["response_model"] == "deepseek-flash" for row in calls)
    assert all(row["billing_status"] == "known" and row["response"] is not None for row in calls)
    assert [row["task_order"] for row in calls] == sorted(row["task_order"] for row in calls)
    assert [(item["case_id"], item["variant"]) for item in live_runner.PLAN] == [
        ("case01", "b2"), ("case01", "direct_hybrid"),
        ("case02", "b2"), ("case02", "direct_hybrid"),
        ("case03", "b2"), ("case03", "direct_hybrid"),
        ("case04", "b2"), ("case04", "direct_hybrid"),
        ("case05", "direct_hybrid"),
        ("case07", "direct_hybrid"), ("case08", "direct_hybrid"),
    ]


def test_live_preflight_checks_fixed_code_and_fixture_identities_without_provider():
    live_runner = _live_runner_module()
    identities = live_runner._check_git_identity()
    fixtures = live_runner._fixture_identity()
    assert identities["b2"]["head"] == "de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131"
    assert identities["task019_direct_hybrid"]["branch"] == "experiment/task019-direct-hybrid"
    assert identities["task019_direct_hybrid"]["head"] != identities["b2"]["head"]
    assert identities["b2"]["business_fingerprint"]["sha256"] == (
        "2101868665a1c8f3732d66517b63bc1142a16968941368854be8ebd96201f028"
    )
    assert fixtures["git"]["commit_range"]["head"] == "d6b6c100d5e2e441957d834a29a73a8bc4ac1693"
    assert fixtures["git"]["working_tree_untracked"]["status_porcelain"] == "?? notes/local_sample.md"


def test_runtime_source_hashes_use_version_specific_file_sets():
    runner = _live_runner_module()
    direct = runner._hash_map(
        runner.TASK019_CHECKOUT, runner.DIRECT_RUNTIME_IDENTITY_FILES
    )
    b2 = runner._hash_map(runner.B2_CHECKOUT, runner.SHARED_RUNTIME_IDENTITY_FILES)
    assert "core/tool_agent/changed_files_typed_finalization.py" in direct
    assert "core/tool_agent/changed_files_typed_finalization.py" not in b2
    assert len(direct) == len(runner.DIRECT_RUNTIME_IDENTITY_FILES)
    assert len(b2) == len(runner.SHARED_RUNTIME_IDENTITY_FILES)


def test_live_worker_json_parser_tolerates_binary_diagnostics_but_keeps_json_strict():
    runner = _live_runner_module()
    record = {"mode": "live", "live_mode": True, "results": [{"case_id": "case01"}]}
    encoded = json.dumps(record, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode("utf-8")
    assert runner._parse_worker_json(b"\xff diagnostic\r\n" + encoded) == record
    with pytest.raises(RuntimeError, match="WORKER_OUTPUT_RECORD_MISSING"):
        runner._parse_worker_json(b'{\r\n  "mode": "live",\r\n  "live_mode": true,\r\n  "results": [\xff]}')


def test_live_provider_boundary_accounts_planner_decision_repair_selector_and_context(tmp_path):
    module = _probe_module()
    gate = module.SharedBudgetGate(tmp_path / "shared.sqlite3", run_id="all-provider-roles")

    class Usage:
        prompt_tokens = 10
        completion_tokens = 2
        total_tokens = 12

        def model_dump(self, mode="json"):
            return {"prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.total_tokens}

    class Response:
        model = "deepseek-flash"
        usage = Usage()

        def model_dump(self, mode="json"):
            return {"id": "fake-response", "model": self.model,
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "usage": self.usage.model_dump()}

    class ClientFactory:
        def __call__(self, **_kwargs):
            class Completions:
                def create(self, **_request):
                    return Response()
            class Chat:
                completions = Completions()
            class Client:
                chat = Chat()
            return Client()

    messages_by_role = {
        "planner": [{"role": "system", "content": "你是 RAG 系统的查询规划器"}],
        "decision": [{"role": "system", "content": "ordinary decision"}],
        "decision_repair": [{"role": "system", "content": "ordinary decision"},
                             {"role": "system", "content": "上一轮结构化输出未通过系统严格校验。"}],
        "selector": [{"role": "system", "content": "You select a bounded presentation"}],
        "context_resolver": [{"role": "system", "content": "Identify only the conversation referents"}],
    }
    for messages in messages_by_role.values():
        provider = module.LiveHTTPProvider(module.CASES["case01"], "task017",
            shared_budget=gate, task_order=1, api_key="offline-placeholder",
            sdk_factory=ClientFactory())
        client = provider.build_openai_client(api_key="offline-placeholder",
            base_url="https://api.deepseek.com/v1", timeout=20, max_retries=0)
        client.chat.completions.create(model="deepseek-flash", messages=messages,
                                       temperature=0, max_tokens=32)
    gate.export_calls_jsonl(tmp_path / "calls.jsonl")
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["role"] for row in calls] == [
        "planner", "decision", "decision_repair", "selector", "context_resolver",
    ]
    assert gate.snapshot()["requests_reserved"] == 5
    assert gate.snapshot()["total_tokens"] == 60
    assert not gate.snapshot()["billing_unknown"]


def test_shared_request_cap_stops_before_next_runtime_provider_request(tmp_path):
    module = _probe_module()
    run_id = "task018-shared-request-stop"
    database = tmp_path / "shared.sqlite3"
    gate = module.SharedBudgetGate(database, run_id=run_id, max_requests=3)
    first = _shared_fake_worker(B2_CHECKOUT, "b2", "case01", 1,
                                database, run_id, max_requests=3)
    assert first["infrastructure_status"] == "ok"
    assert first["provider_request_count"] == 3
    second = _shared_fake_worker(TASK017_CHECKOUT, "task017", "case01", 2,
                                 database, run_id, max_requests=3)
    assert second["infrastructure_status"] == "stopped"
    assert second["provider_request_count"] == 0
    assert "PROVIDER_REQUEST_BUDGET_STOP" in second["stop_reason"]
    assert gate.snapshot()["requests_reserved"] == 3


def test_shared_token_cost_usage_and_provider_failures_fail_closed(tmp_path):
    module = _probe_module()
    payload = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}],
               "temperature": 0, "max_tokens": 10,
               "extra_body": {"thinking": {"type": "disabled"}}}

    token_gate = module.SharedBudgetGate(tmp_path / "token.sqlite3", run_id="token", max_tokens=120)
    seq = token_gate.reserve(task_order=1, case_id="case01", variant="b2", role="planner",
                             request_model="deepseek-flash", request_payload=payload, output_cap=10)
    stop = token_gate.record_response(seq=seq, response_model="deepseek-flash",
        response_payload={"model": "deepseek-flash"},
        usage={"prompt_tokens": 80, "completion_tokens": 50, "total_tokens": 130}, latency_ms=1)
    assert stop == "TOKEN_BUDGET_STOP_AFTER_RESPONSE"
    assert token_gate.snapshot()["stopped"] is True
    with pytest.raises(module.BudgetGateStop, match="TOKEN_BUDGET_STOP_AFTER_RESPONSE"):
        token_gate.reserve(task_order=2, case_id="case02", variant="b2", role="decision",
                           request_model="deepseek-flash", request_payload=payload, output_cap=10)

    cost_gate = module.SharedBudgetGate(tmp_path / "cost.sqlite3", run_id="cost",
                                        max_estimated_usd=0.0002)
    seq = cost_gate.reserve(task_order=1, case_id="case01", variant="b2", role="planner",
                            request_model="deepseek-flash", request_payload=payload, output_cap=10)
    stop = cost_gate.record_response(seq=seq, response_model="deepseek-flash",
        response_payload={"model": "deepseek-flash"},
        usage={"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600}, latency_ms=1)
    assert stop == "ESTIMATED_COST_BUDGET_STOP_AFTER_RESPONSE"

    unknown_gate = module.SharedBudgetGate(tmp_path / "unknown.sqlite3", run_id="unknown")
    seq = unknown_gate.reserve(task_order=1, case_id="case01", variant="b2", role="planner",
                               request_model="deepseek-flash", request_payload=payload, output_cap=10)
    unknown_gate.record_response(seq=seq, response_model="deepseek-flash",
        response_payload={"model": "deepseek-flash"},
        usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 99}, latency_ms=1)
    snapshot = unknown_gate.snapshot()
    assert snapshot["stopped"] and snapshot["billing_unknown"]
    assert snapshot["stop_reason"] == "PROVIDER_USAGE_MISSING_OR_INCONSISTENT"

    error_gate = module.SharedBudgetGate(tmp_path / "error.sqlite3", run_id="error")
    seq = error_gate.reserve(task_order=1, case_id="case01", variant="b2", role="planner",
                             request_model="deepseek-flash", request_payload=payload, output_cap=10)
    error_gate.record_provider_error(seq=seq, error_category="ConnectTimeout", latency_ms=20)
    assert error_gate.snapshot()["billing_unknown"] is True
    assert error_gate.snapshot()["stop_reason"] == "PROVIDER_ERROR_BILLING_UNKNOWN"

    response_identity_gate = module.SharedBudgetGate(
        tmp_path / "identity.sqlite3", run_id="identity")
    seq = response_identity_gate.reserve(task_order=1, case_id="case01", variant="b2",
        role="planner", request_model="deepseek-flash", request_payload=payload,
        output_cap=10)
    stop = response_identity_gate.record_response(seq=seq, response_model="unexpected-model",
        response_payload={"model": "unexpected-model"},
        usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}, latency_ms=1)
    assert stop == "RESPONSE_MODEL_IDENTITY_MISMATCH"
    identity_snapshot = response_identity_gate.snapshot()
    assert identity_snapshot["stopped"] and not identity_snapshot["billing_unknown"]
    assert identity_snapshot["input_tokens"] == 10

    reservation_gate = module.SharedBudgetGate(
        tmp_path / "reservation.sqlite3", run_id="reservation",
        max_estimated_usd=0.000001)
    with pytest.raises(module.BudgetGateStop, match="ESTIMATED_COST_BUDGET_STOP"):
        reservation_gate.reserve(task_order=1, case_id="case01", variant="b2",
            role="planner", request_model="deepseek-flash", request_payload=payload,
            output_cap=10)
    assert reservation_gate.snapshot()["requests_reserved"] == 0


def test_shared_budget_persistence_failure_blocks_request_reservation(tmp_path, monkeypatch):
    module = _probe_module()
    database = tmp_path / "unavailable.sqlite3"
    gate = module.SharedBudgetGate(database, run_id="persistence-failure")
    def fail_to_open_database():
        raise OSError("simulated persistence failure")
    monkeypatch.setattr(gate, "_connect", fail_to_open_database)
    payload = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}],
               "temperature": 0, "max_tokens": 10}
    with pytest.raises(module.BudgetGateStop, match="BUDGET_PERSISTENCE_UNAVAILABLE"):
        gate.reserve(task_order=1, case_id="case01", variant="b2", role="planner",
                     request_model="deepseek-flash", request_payload=payload, output_cap=10)


def test_live_provider_adapter_can_be_fake_backed_and_uses_same_shared_gate(tmp_path):
    module = _probe_module()
    gate = module.SharedBudgetGate(tmp_path / "shared.sqlite3", run_id="live-adapter-fake")
    fake = module.FakeHTTPProvider(module.CASES["case01"], "b2")
    live = module.LiveHTTPProvider(module.CASES["case01"], "b2", shared_budget=gate,
                                   task_order=1, api_key="offline-placeholder",
                                   sdk_factory=fake.build_openai_client)
    client = live.build_openai_client(api_key="offline-placeholder",
        base_url="https://api.deepseek.com/v1", timeout=20, max_retries=0)
    client.chat.completions.create(model="deepseek-flash",
        messages=[{"role": "system", "content": "你是 RAG 系统的查询规划器"}],
        temperature=0, max_tokens=800)
    assert gate.snapshot()["requests_reserved"] == 1
    assert gate.snapshot()["call_status_counts"] == {"response_recorded": 1}
    assert live.requests[0]["role"] == "planner"
    assert live.responses[0]["response_model"] == "deepseek-flash"
    assert live.responses[0]["usage"]["total_tokens"] == 144

