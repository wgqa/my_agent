"""G8-CONTEXT-02 runner contracts; all tests use fake HTTP responses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from evaluation.gate8.run_conversation_context_check import (
    EXPECTED_CASE_COUNT,
    RESULT_SCHEMA_VERSION,
    load_cases,
    run_check,
    write_artifacts,
)

CASES = Path(__file__).parents[1] / "evaluation" / "gate8" / "conversation_context_cases_v1.jsonl"


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _payload(*, answer: str, history_received: int, resolver_used: bool):
    return {
        "status": "completed",
        "answer": answer,
        "sources": [{
            "citation_id": "[C1]",
            "source": "public.md",
            "rank": 1,
            "query_id": "secret standalone query",
        }],
        "planner": {"plan": {"action": "single_retrieval", "query_type": "fact"}},
        "route": {
            "route": "single_retrieval",
            "queries": ["secret standalone query"],
        },
        "verification": {
            "status": "supported",
            "covered_query_ids": ["secret standalone query"],
        },
        "warnings": [],
        "trace": [{
            "event_type": "context_prepared",
            "data": {
                "history_messages_received": history_received,
                "history_messages_used": history_received,
                "history_tokens_used": 10,
                "history_truncated": False,
                "resolver_used": resolver_used,
                "resolver_fallback": False,
            },
        }],
    }


class _Session:
    def __init__(self, *, blocked=False):
        self.calls = []
        self.blocked = blocked

    def post(self, url, *, json, timeout):
        self.calls.append(json)
        if self.blocked:
            raise requests.exceptions.ConnectionError("secret transport detail")
        if len(self.calls) % 3 == 1:
            return _Response(_payload(answer="turn1 real answer", history_received=0, resolver_used=False))
        if len(self.calls) % 3 == 2:
            return _Response(_payload(answer="no history answer", history_received=0, resolver_used=False))
        return _Response(_payload(answer="with history answer", history_received=2, resolver_used=True))


def test_case_schema_is_exactly_six_public_cases():
    cases = load_cases(CASES)
    assert len(cases) == EXPECTED_CASE_COUNT
    assert {case["case_type"] for case in cases} == {
        "pronoun_reference",
        "plural_reference",
        "previous_concept_reference",
        "previous_answer_reference",
        "short_elliptical_followup",
        "topic_switch_control",
    }


def test_runner_sends_a_without_history_and_b_with_real_turn1_answer(tmp_path):
    session = _Session()
    results = run_check(load_cases(CASES), base_url="http://test", session=session)
    assert len(results) == 6
    assert all(item["execution_status"] == "COMPLETED" for item in results)
    for offset in range(0, len(session.calls), 3):
        turn1, no_history, with_history = session.calls[offset : offset + 3]
        assert set(turn1) == {"question", "top_k"}
        assert set(no_history) == {"question", "top_k"}
        assert set(with_history) == {"question", "top_k", "history"}
        assert with_history["history"][1] == {
            "role": "assistant",
            "content": "turn1 real answer",
        }
    results_path = tmp_path / "results.jsonl"
    report_path = tmp_path / "report.md"
    write_artifacts(results, results_path=results_path, report_path=report_path, base_url="http://test")
    serialized = results_path.read_text(encoding="utf-8")
    assert "standalone_query" not in serialized
    assert "secret standalone query" not in serialized
    assert "turn1 real answer" in serialized
    assert "raw response" not in serialized.lower()
    assert json.loads(serialized.splitlines()[0])["schema_version"] == RESULT_SCHEMA_VERSION


def test_blocked_provider_is_not_scored_as_fail():
    results = run_check(load_cases(CASES), base_url="http://test", session=_Session(blocked=True))
    assert len(results) == EXPECTED_CASE_COUNT
    assert all(item["execution_status"] == "BLOCKED" for item in results)
    assert all(item["judgement"] is None for item in results)


def test_runner_rejects_case_count_mismatch(tmp_path):
    first = CASES.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "one.jsonl"
    path.write_text(first + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly 6"):
        load_cases(path)
