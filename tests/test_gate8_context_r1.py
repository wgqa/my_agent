"""G8-CONTEXT-02-R1 clean-corpus and validity-gate contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evaluation.gate8.r1_infrastructure import (
    EXPECTED_COMMIT,
    EXPECTED_CORPUS_ID,
    EXPECTED_FILE_COUNT,
    EXPECTED_REPOSITORY,
    EXPECTED_CORPUS_PATH,
    R1PreflightError,
    assert_expected_identity,
    build_corpus_provenance,
    load_r1_cases,
    safe_provider_summary,
    validate_index_source_identities,
)
from evaluation.gate8.run_conversation_context_r1 import run_r1_check


REPO_ROOT = Path(__file__).parents[1]
CORPUS_ROOT = REPO_ROOT.parent / "rag数据集" / "benchmark_work" / "agent_ai_v1" / "02_corpus_candidate"
CASES = REPO_ROOT / "evaluation" / "gate8" / "conversation_context_cases_r1.jsonl"


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _payload(*, answer="turn1 answer", source="检索与生成.md", status="completed", history=0):
    return {
        "status": status,
        "answer": answer,
        "sources": [{"citation_id": "[C1]", "source": source, "rank": 1}],
        "planner": {"plan": {"action": "single_retrieval", "query_type": "fact"}},
        "route": {"route": "single_retrieval", "retrieval_strategy": "hybrid"},
        "verification": {"status": "supported", "evidence_count": 1, "can_generate": True},
        "warnings": [],
        "trace": [{
            "event_type": "context_prepared",
            "data": {
                "history_messages_received": history,
                "history_messages_used": history,
                "history_tokens_used": 10,
                "history_truncated": False,
                "resolver_used": history > 0,
                "resolver_fallback": False,
            },
        }],
    }


class _ValidSession:
    def __init__(self, *, refused_turn1=False):
        self.calls = []
        self.refused_turn1 = refused_turn1
        self.turn1_sources = [
            "高级RAG.md",
            "核心概念.md",
            "MCP协议-02-能力发现与传输.md",
            "提示工程基础.md",
            "Transformer架构-04-采样与工程联系.md",
            "量化技术.md",
        ]

    def post(self, url, *, json, timeout):
        self.calls.append(json)
        call_no = len(self.calls)
        if call_no <= 6:
            return _Response(_payload(
                source=self.turn1_sources[call_no - 1],
                status="refused" if self.refused_turn1 and call_no == 1 else "completed",
                answer="turn1 answer",
            ))
        if "history" not in json:
            return _Response(_payload(answer="检索 文档 生成 相关", history=0))
        return _Response(_payload(answer="检索 文档 生成 相关", history=2))


@pytest.fixture(scope="module")
def provenance():
    return build_corpus_provenance(CORPUS_ROOT, repo_root=REPO_ROOT)


def test_clean_corpus_identity_and_exactly_six_valid_frozen_cases(provenance):
    assert provenance["repository"] == EXPECTED_REPOSITORY
    assert provenance["commit"] == EXPECTED_COMMIT
    assert provenance["path"] == EXPECTED_CORPUS_PATH
    assert provenance["corpus_id"] == EXPECTED_CORPUS_ID
    assert provenance["file_count"] == EXPECTED_FILE_COUNT
    cases = load_r1_cases(CASES, provenance)
    assert len(cases) == 6
    assert all(set(case["turn1_source_paths"]).issubset(provenance["relative_paths"]) for case in cases)


def test_wrong_corpus_identity_rejected():
    with pytest.raises(R1PreflightError):
        assert_expected_identity(
            repository=EXPECTED_REPOSITORY,
            commit=EXPECTED_COMMIT,
            path=EXPECTED_CORPUS_PATH,
            corpus_id="wrong-corpus",
            file_count=EXPECTED_FILE_COUNT,
        )


def test_contaminated_source_preflight_rejected(provenance):
    source_map = {Path(path).name: path for path in provenance["relative_paths"]}
    with pytest.raises(R1PreflightError):
        validate_index_source_identities([r"C:\Users\tester\Temp\rag_test.txt"], source_map)


def test_absolute_source_is_sanitized_and_exposure_is_recorded(provenance):
    source_map = {Path(path).name: path for path in provenance["relative_paths"]}
    summary, exposed = safe_provider_summary(
        _payload(source=r"D:\Users\local\02_corpus_candidate\rag\检索与生成.md"),
        1.0,
        source_map,
    )
    assert exposed is True
    assert summary["sources"][0]["source"] == "rag/检索与生成.md"
    assert "D:\\" not in str(summary)
    assert "C:\\Users" not in str(summary)
    assert "AppData" not in str(summary)
    assert "Temp" not in str(summary)


def test_turn1_refused_is_invalid_and_sends_no_ab(provenance):
    cases = load_r1_cases(CASES, provenance)
    session = _ValidSession(refused_turn1=True)
    results = run_r1_check(
        cases,
        base_url="http://test",
        provenance=provenance,
        index_proof={"isolated": True},
        session=session,
    )
    assert len(session.calls) == 6
    assert results[0]["execution_status"] == "INVALID_CASE"
    assert results[0]["turn1_valid"] is False
    assert all(item["no_history"] is None for item in results)
    assert all(item["with_history"] is None for item in results)


def test_formal_run_has_a_without_history_and_b_with_real_turn1_history(provenance):
    cases = load_r1_cases(CASES, provenance)
    session = _ValidSession()
    results = run_r1_check(
        cases,
        base_url="http://test",
        provenance=provenance,
        index_proof={"isolated": True},
        session=session,
    )
    assert len(session.calls) == 18
    assert all(item["execution_status"] == "COMPLETED" for item in results)
    for payload in session.calls[:6]:
        assert set(payload) == {"question", "top_k"}
    for offset in range(6, 18, 2):
        no_history, with_history = session.calls[offset:offset + 2]
        assert set(no_history) == {"question", "top_k"}
        assert set(with_history) == {"question", "top_k", "history"}
        assert with_history["history"][1] == {"role": "assistant", "content": "turn1 answer"}


def test_sealed_holdout_infrastructure_is_untouched(provenance):
    holdout = REPO_ROOT / "evaluation" / "gate3" / "holdout.py"
    before = hashlib.sha256(holdout.read_bytes()).hexdigest()
    load_r1_cases(CASES, provenance)
    after = hashlib.sha256(holdout.read_bytes()).hexdigest()
    assert before == after
