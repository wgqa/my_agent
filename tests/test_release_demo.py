"""Offline tests for the bounded Release Demo harness."""

from __future__ import annotations

import json

import pytest

from scripts import demo_release as demo


def _cases_by_id():
    return {case["id"]: case for case in demo.load_cases()}


class _RecordingClient:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.post_calls = []

    def post_json(self, endpoint, payload):
        self.post_calls.append((endpoint, payload))
        return 200, self.responses[endpoint]


def _all_ready():
    return demo.Preflight(
        health_ok=True,
        capabilities_ok=True,
        pipeline_ready=True,
        basic_rag_ready=True,
        agentic_rag_ready=True,
        tool_agent_ready=True,
    )


def _responses():
    return {
        "/query": {"answer": "RRF answer", "sources": [{"source": "a.md"}]},
        "/agent/query": {
            "schema_version": "agent_query_response_v1",
            "run_id": "run-demo",
            "status": "completed",
            "answer": "Agent answer",
            "sources": [{"citation_id": "[C1]"}],
            "planner": {"plan": {"query_type": "comparison"}},
            "route": {"route": "decomposed_retrieval"},
            "trace": [],
        },
        "/tool-agent/query": {
            "schema_version": "tool_agent_query_response_v1",
            "status": "completed",
            "answer": "703",
            "tool_calls_used": 1,
            "trace": [{"tool_name": "calculator"}],
        },
    }


def test_demo_catalog_has_six_unique_cases_and_one_observation():
    cases = demo.load_cases()
    assert len(cases) == 6
    assert len({case["id"] for case in cases}) == 6
    assert sum(bool(case.get("required", True)) for case in cases) == 5
    assert sum(bool(case.get("observational")) for case in cases) == 1


@pytest.mark.parametrize(
    ("case_id", "expected_keys", "forbidden_keys"),
    [
        ("demo-basic-01", {"question", "top_k"}, set()),
        ("demo-agent-01", {"question", "top_k"}, set()),
        ("demo-tool-calculator-01", {"question"}, {"top_k"}),
    ],
)
def test_demo_payloads_match_frozen_public_request_contract(
    case_id, expected_keys, forbidden_keys
):
    payload = demo.build_payload(_cases_by_id()[case_id])
    assert set(payload) == expected_keys
    assert not forbidden_keys.intersection(payload)


def test_capabilities_preflight_skips_unavailable_agent_without_request():
    client = _RecordingClient(_responses())
    status = demo.Preflight(
        health_ok=True,
        capabilities_ok=True,
        pipeline_ready=True,
        basic_rag_ready=True,
        agentic_rag_ready=False,
        tool_agent_ready=True,
    )
    result = demo.run_case(client, _cases_by_id()["demo-agent-01"], status)
    assert result.status == "skipped"
    assert result.error == "runtime unavailable; request skipped"
    assert client.post_calls == []


def test_required_and_observational_cases_are_reported_separately():
    cases = demo.load_cases()
    required = [case for case in cases if case.get("required", True)]
    observational = [case for case in cases if case.get("observational")]
    assert len(required) == 5
    assert [case["id"] for case in observational] == ["demo-tool-multistep-01"]
    assert observational[0]["required"] is False


def test_demo_summary_counts_required_and_observational_separately():
    results = [
        demo.CaseResult("required-pass", "/query", True, False, "pass"),
        demo.CaseResult("required-fail", "/query", True, False, "fail"),
        demo.CaseResult("required-skip", "/query", True, False, "skipped"),
        demo.CaseResult("observed-pass", "/tool-agent/query", False, True, "pass"),
    ]

    assert demo.summarize_results(results) == {
        "required_count": 3,
        "required_passed": 1,
        "required_failed": 1,
        "required_skipped": 1,
        "observational_status": "pass",
    }


def test_safety_case_never_invokes_shell_or_subprocess(monkeypatch):
    client = _RecordingClient(
        {
            "/tool-agent/query": {
                "schema_version": "tool_agent_query_response_v1",
                "status": "refused",
                "answer": "无法执行该危险操作。",
                "tool_calls_used": 0,
                "trace": [],
            }
        }
    )
    monkeypatch.setattr(
        demo.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("safety case must not invoke subprocess")
        ),
    )
    result = demo.run_case(client, _cases_by_id()["demo-safety-01"], _all_ready())
    assert result.status == "pass"
    assert result.tool_names == []


def test_api_error_is_bounded_and_does_not_dump_response(monkeypatch):
    class ErrorClient(_RecordingClient):
        def post_json(self, endpoint, payload):
            raise demo.DemoApiError("HTTP 500 " + "x" * 1000)

    result = demo.run_case(
        ErrorClient(), _cases_by_id()["demo-basic-01"], _all_ready()
    )
    assert result.status == "fail"
    assert len(result.error or "") <= 240
    assert "{" not in (result.error or "")


def test_all_six_cases_make_at_most_one_request_each():
    client = _RecordingClient(_responses())
    results = [demo.run_case(client, case, _all_ready()) for case in demo.load_cases()]
    assert len(results) == demo.MAX_CASES
    assert len(client.post_calls) == demo.MAX_CASES
    assert [endpoint for endpoint, _payload in client.post_calls].count("/query") == 1
    assert [endpoint for endpoint, _payload in client.post_calls].count("/agent/query") == 1
    assert [endpoint for endpoint, _payload in client.post_calls].count("/tool-agent/query") == 4


def test_artifact_contains_only_safe_summary_fields():
    result = demo.CaseResult(
        case_id="demo-safety-01",
        endpoint="/tool-agent/query",
        required=True,
        observational=False,
        status="pass",
        safe_summary="tools=none tool_calls=0 shell_executed=False",
    )
    artifact = demo.build_artifact(
        [result], "sk-secret-token", "2026-08-18T00:00:00+00:00"
    )
    serialized = json.dumps(artifact, ensure_ascii=False)
    for forbidden in ("api_key", "Authorization", "system_prompt", "raw_output", "traceback"):
        assert forbidden not in serialized
    assert "sk-secret-token" not in serialized
    assert set(artifact["cases"][0]) == {
        "case_id",
        "endpoint",
        "status",
        "required",
        "observational",
        "safe_summary",
        "tool_names",
        "counts",
    }
