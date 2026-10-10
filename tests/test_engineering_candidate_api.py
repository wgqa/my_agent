"""Candidate payloads keep their cited sources through HTTP and SSE V2."""
import json

from fastapi.testclient import TestClient
import pytest

import api.app as app_module
from api.engineering_stream_v2 import stream_engineering_query_v2
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent.actions import ToolCallAction
from core.engineering_materials import capability_manifest
from core.tool_agent.tools.calculator import CALCULATOR_SPEC
from tests.test_engineering_candidate_runtime import Reviewer, build, answer, review
from tests.test_engineering_requirement_planning import goal


def calculator_runtime(tmp_path, *, failure=None):
    reviewer = Reviewer([failure or review(verdicts=(("fulfilled", ["E1"]),))])
    return build(tmp_path, [ToolCallAction(action="tool_call", tool_name="calculator", arguments={"expression": "2+3"}),
        answer("等于5。[E1]")], reviewer=reviewer,
        goals=[goal("2+3", None, "calculation", ["calculation"], False)])[0]


def test_candidate_http_does_not_downcast_to_legacy_or_drop_sources(tmp_path, monkeypatch):
    runtime = calculator_runtime(tmp_path)
    monkeypatch.setattr(app_module, "_get_engineering_agent_facade", lambda: EngineeringAgentFacade(runtime))
    response = TestClient(app_module.app).post("/engineering/query", json={"question": "计算 2+3"})
    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == "engineering_query_response_v2"
    assert result["finalization"]["policy"] == "semantic_v1"
    assert result["evidence"][0]["payload"] == {"value": 5}
    assert result["evidence"][0]["evidence_id"] == "E1"
    assert "start_line" not in result["evidence"][0]
    assert "reviews" not in result and "materials" not in result
    assert "PRIVATE_COT" not in json.dumps(result)


@pytest.mark.parametrize("failure", [None, "REVIEW_TIMEOUT"])
def test_candidate_v2_sse_only_streams_approved_answer_and_keeps_actual_sources(tmp_path, failure):
    runtime = calculator_runtime(tmp_path, failure=failure)
    frames = stream_engineering_query_v2(EngineeringAgentFacade(runtime), "计算 2+3",
                                         build_response=app_module._build_engineering_response)
    events = [json.loads(frame[6:].strip()) for frame in frames if frame.startswith("data: ")]
    evidence = next(event for event in events if event["type"] == "evidence_added")
    assert evidence["kind"] == "tool_result" and evidence["result_type"] == "calculation"
    assert not any(event["type"] == "error" for event in events)
    result = next(event["result"] for event in events if event["type"] == "final")
    assert result["evidence"][0]["payload"]["value"] == 5
    deltas = [event for event in events if event["type"] == "answer_delta"]
    if failure:
        assert result["status"] == "failed" and result["answer"] is None and not deltas
        assert result["feedback"]["title"] == "回答审核超时"
    else:
        assert "".join(event["delta"] for event in deltas) == "等于5。[E1]"


@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("surface", ["http", "sse_v2"])
def test_actual_missing_file_has_refusal_feedback_without_body_or_answer_stream(tmp_path, monkeypatch, semantic, surface):
    requested = goal("missing.py", None, "body", ["project_code"], False)
    requested["target"]["path"] = "missing.py"

    def unavailable(review_input):
        state = review_input.payload["goal_availability"][0]
        raw = review("refuse", (("unavailable", []),), feedback="读取失败，拒绝编造实现")
        raw["goals"][0]["attempt_ids"] = state["unavailable_attempt_ids"]
        return raw

    runtime, _ = build(tmp_path, [ToolCallAction(action="tool_call", tool_name="read_project_context",
        arguments={"path": "missing.py", "target": {"kind": "file", "start_line": 1}}),
        answer("无法读取 missing.py，不能编造实现")], goals=[requested],
        reviewer=Reviewer([unavailable]) if semantic else None)
    facade = EngineeringAgentFacade(runtime)
    question = "读取 missing.py 的正文，无法读取时拒绝编造实现"
    if surface == "http":
        monkeypatch.setattr(app_module, "_get_engineering_agent_facade", lambda: facade)
        response = TestClient(app_module.app).post("/engineering/query", json={"question": question})
        assert response.status_code == 200
        result = response.json()
    else:
        frames = stream_engineering_query_v2(facade, question, build_response=app_module._build_engineering_response)
        events = [json.loads(frame[6:].strip()) for frame in frames if frame.startswith("data: ")]
        assert not {"answer_start", "answer_delta", "evidence_added", "error"} & {event["type"] for event in events}
        result = next(event["result"] for event in events if event["type"] == "final")
    assert result["status"] == "refused" and result["reason_code"] == "INSUFFICIENT_INFORMATION"
    assert result["failure_code"] is None and result["answer"] is None and result["evidence"] == []
    assert result["feedback"]["action"] == "revise" and result["feedback"]["next_steps"]
    assert result["finalization"]["decision"] == "refuse"
    assert "reviews" not in result and "materials" not in result and "submissions" not in result


@pytest.mark.parametrize("mode,evidence,finalization", [
    ("rule", "legacy", "legacy"), ("shadow", "legacy", "legacy"),
    ("rule", "goal_v2", "structural_v2"), ("llm", "goal_v2", "structural_v2"),
    ("llm", "goal_v2", "semantic_v1"),
])
def test_product_only_accepts_explicit_valid_combinations(monkeypatch, mode, evidence, finalization):
    for key, value in (("ENGINEERING_REQUIREMENT_MODE", mode), ("ENGINEERING_EVIDENCE_POLICY", evidence),
                       ("ENGINEERING_FINALIZATION_POLICY", finalization)):
        monkeypatch.setenv(key, value)
    assert app_module._product_evidence_settings() == (mode, evidence, finalization)


@pytest.mark.parametrize("settings", [("llm", "legacy", "legacy"), ("shadow", "goal_v2", "semantic_v1"),
    ("rule", "goal_v2", "semantic_v1"), ("llm", "goal_v2", "legacy"), ("unknown", "legacy", "legacy")])
def test_illegal_combinations_do_not_silently_fallback(monkeypatch, settings):
    for key, value in zip(("ENGINEERING_REQUIREMENT_MODE", "ENGINEERING_EVIDENCE_POLICY", "ENGINEERING_FINALIZATION_POLICY"), settings):
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        app_module._product_evidence_settings()
