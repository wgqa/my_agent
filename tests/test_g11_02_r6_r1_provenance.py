from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app
import scripts.run_g11_02_theory_code as runner
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent import (
    AgentDecisionCallMetadata,
    AgentDecisionOutcome,
    FinalAnswerAction,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    build_tool_agent_runtime,
)
from tests._engineering_runtime_support import build_full_unified_runtime


LEGACY_TRACE_KEYS = {
    "event_type",
    "iteration",
    "action_type",
    "tool_name",
    "call_id",
    "tool_status",
    "error_code",
    "iterations_used",
    "tool_calls_used",
    "tool_errors_used",
}
ENGINEERING_TRACE_EXTRA_KEYS = {
    "provider_call_count",
    "repair_attempted",
    "repair_succeeded",
    "parse_failure_category",
}


class EmptyRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


class MetadataProvider:
    def decide(self, registry, user_query, *, context=(), control_state=None):
        metadata = AgentDecisionCallMetadata(
            provider="fake",
            model="fake-model",
            prompt_version="engineering_agent_decision_prompt_v2",
            prompt_sha256=ENGINEERING_DECISION_PROMPT_V2_SHA256,
            toolset_sha256="b" * 64,
            call_count=2,
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
            repair_attempted=True,
            repair_succeeded=True,
            initial_parse_category="INVALID_JSON",
            initial_finish_reason="stop",
        )
        return AgentDecisionOutcome(
            action=FinalAnswerAction(action="final_answer", answer="ok"),
            failure_code=None,
            call_metadata=metadata,
        )


def _install_metadata_runtime(monkeypatch, tmp_path: Path) -> None:
    runtime = build_tool_agent_runtime(
        repo_root=tmp_path,
        retrieval_port=EmptyRetrievalPort(),
        provider=MetadataProvider(),
    )
    monkeypatch.setattr(api.app, "tool_agent_runtime", runtime)
    monkeypatch.setattr(
        api.app,
        "engineering_agent_facade",
        EngineeringAgentFacade(
            build_full_unified_runtime(runtime)
        ),
    )


def test_legacy_endpoint_keeps_exact_frozen_trace_keys(monkeypatch, tmp_path):
    _install_metadata_runtime(monkeypatch, tmp_path)
    response = TestClient(api.app.app).post(
        "/tool-agent/query", json={"question": "legacy trace"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace
    assert all(set(event) == LEGACY_TRACE_KEYS for event in trace)
    assert all(not ENGINEERING_TRACE_EXTRA_KEYS.intersection(event) for event in trace)


def test_engineering_endpoint_exposes_only_safe_repair_fields(monkeypatch, tmp_path):
    _install_metadata_runtime(monkeypatch, tmp_path)
    response = TestClient(api.app.app).post(
        "/engineering/query", json={"question": "engineering trace"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    decision = next(event for event in trace if event["event_type"] == "decision_completed")
    assert set(decision) == LEGACY_TRACE_KEYS | ENGINEERING_TRACE_EXTRA_KEYS
    assert decision["provider_call_count"] == 2
    assert decision["repair_attempted"] is True
    assert decision["repair_succeeded"] is True
    assert decision["parse_failure_category"] == "INVALID_JSON"
    assert all(set(event) <= LEGACY_TRACE_KEYS | ENGINEERING_TRACE_EXTRA_KEYS for event in trace)


def _case_spec(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "question": case_id,
        "required": runner.REQUIRED_TOOLS,
        "forbidden": runner.FORBIDDEN_TOOLS,
        "obligations": [{"id": "O1", "description": "deterministic test case"}],
    }


def _normalized_case(case_id: str, *, status: str, failure_code: str | None) -> dict:
    response = {
        "status": status,
        "answer": "ok" if status == "completed" else None,
        "reason_code": None,
        "failure_code": failure_code,
        "iterations_used": 1,
        "tool_calls_used": 0,
        "tool_errors_used": 0,
        "trace": [
            {
                "event_type": "decision_completed",
                "provider_call_count": 2,
                "repair_attempted": True,
                "repair_succeeded": failure_code is None,
                "parse_failure_category": "INVALID_JSON",
            }
        ],
        "evidence": [],
    }
    return runner._normalize_case(_case_spec(case_id), response, 1.0)


def test_metrics_distinguish_initial_and_final_parse_failures():
    cases = [
        _normalized_case("A", status="completed", failure_code=None),
        _normalized_case(
            "B", status="failed", failure_code="ACTION_PARSE_FAILED"
        ),
    ]

    metrics = runner._metrics(cases)

    assert metrics["initial_parse_failure_cases"] == 2
    assert metrics["repair_attempted_cases"] == 2
    assert metrics["repair_succeeded_cases"] == 1
    assert metrics["parse_failure_cases"] == 1
    assert metrics["provider_calls_total"] == 4


def test_repair_identity_and_manifest_report_provenance(monkeypatch, tmp_path):
    assert runner.validate_repair_prompt_identity(
        runner.REPAIR_PROMPT_VERSION, runner.REPAIR_PROMPT_SHA256.upper()
    ) == (runner.REPAIR_PROMPT_VERSION, runner.REPAIR_PROMPT_SHA256)
    with pytest.raises(ValueError):
        runner.validate_repair_prompt_identity(
            runner.REPAIR_PROMPT_VERSION, "0" * 64
        )

    knowledge_status = {
        "schema_version": "engineering_knowledge_status_v1",
        "ready": True,
        "verified": True,
        "corpus_id": runner.KNOWLEDGE_CORPUS_ID,
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": "dbc497c796d5",
    }
    monkeypatch.setattr(runner, "validate_source_commit", lambda value, git_root: value)
    monkeypatch.setattr(runner, "_get_json", lambda url: knowledge_status)
    monkeypatch.setattr(
        runner,
        "_post_json",
        lambda url, payload: {
            "status": "completed",
            "answer": "ok",
            "reason_code": None,
            "failure_code": None,
            "iterations_used": 1,
            "tool_calls_used": 0,
            "tool_errors_used": 0,
            "trace": [],
            "evidence": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_g11_02_theory_code.py",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "r1-provenance",
            "--url",
            "http://127.0.0.1:8765/engineering/query",
            "--source-commit",
            "a" * 40,
            "--git-root",
            str(tmp_path),
            "--prompt-version",
            "engineering_agent_decision_prompt_v2",
            "--prompt-sha256",
            ENGINEERING_DECISION_PROMPT_V2_SHA256,
        ],
    )

    assert runner.main() == 0
    output = tmp_path / "r1-provenance"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    report = (output / "run_report.md").read_text(encoding="utf-8")

    assert manifest["repair_prompt_version"] == runner.REPAIR_PROMPT_VERSION
    assert manifest["repair_prompt_sha256"] == runner.REPAIR_PROMPT_SHA256
    assert manifest["max_parse_repairs"] == runner.MAX_PARSE_REPAIRS == 1
    assert f"repair_prompt_version: `{runner.REPAIR_PROMPT_VERSION}`" in report
    assert f"repair_prompt_sha256: `{runner.REPAIR_PROMPT_SHA256}`" in report
    assert "max_parse_repairs: `1`" in report
