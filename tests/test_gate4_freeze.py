"""Tests for G4-CLOSE-08 Gate 4 system freeze identity.

从 committed gate4_freeze.json 独立重算 gate4_system_freeze_id（canonical payload
不含 self-id 的 SHA256[:12]），断言与文件记录一致，并校验四类冻结证据关键值。
纯离线，0 model / 0 network。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

FREEZE = Path(__file__).resolve().parents[1] / "docs" / "experiments" / "gate4_freeze.json"


def _load():
    return json.loads(FREEZE.read_text(encoding="utf-8"))


def _canonical_without_id(obj: dict) -> str:
    payload = {k: v for k, v in obj.items() if k != "gate4_system_freeze_id"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def test_freeze_id_recomputes_from_payload():
    obj = _load()
    recorded = obj["gate4_system_freeze_id"]
    recomputed = hashlib.sha256(
        _canonical_without_id(obj).encode("utf-8")
    ).hexdigest()[:12]
    assert len(recorded) == 12
    int(recorded, 16)
    assert recorded == recomputed


def test_schema_and_contract():
    obj = _load()
    assert obj["schema_version"] == "gate4_system_freeze_v1"
    core = obj["tool_agent_core"]
    assert core["tool_contract_status"] == "closed"
    assert core["real_tools"] == ["calculator", "code_search", "knowledge_search"]
    assert core["runtime_budget"] == {
        "max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2,
    }
    assert core["prompt_version"] == "tool_agent_decision_prompt_v2"
    assert core["provider"] == "deepseek"
    assert core["model"] == "deepseek-chat"


def test_baseline_identity_and_headline():
    obj = _load()
    b = obj["formal_dev_baseline"]
    assert b["run_id"] == "fa4ab9aa5f13"
    assert b["source_commit"].startswith("de17b809")
    assert b["evaluation_set_id"] == "5639ca57b09a"
    assert b["dataset_sha256"].startswith("93a32e64")
    assert b["headline_metrics"]["task_completion"] == "20/24"
    assert b["headline_metrics"]["required_tool_coverage"] == "14/20"
    assert b["headline_metrics"]["sequence_match"] == "1/4"
    assert b["headline_metrics"]["parse_failure"] == "2/24"
    assert b["bound_artifacts"]["seal_verdict"] == "valid_public_dev_baseline"


def test_api_e2e_and_replay_evidence_not_hidden():
    obj = _load()
    e = obj["api_e2e"]
    assert e["api_source_commit"].startswith("c94a371")
    assert e["endpoint"] == "POST /tool-agent/query"
    assert e["response_schema"] == "tool_agent_query_response_v1"
    assert e["safe_trace"] is True
    assert e["api_status"] == "reviewer_accepted_closed"
    smoke = e["e2e_smoke"]
    assert smoke["smoke_cases"] == 6
    assert smoke["first_pass_structured_http_200"] == 6
    assert smoke["evidence_replay_count"] == 1
    assert smoke["evidence_replay_reason"] == "local_recorder_console_encoding_failure"
    assert smoke["observed_tool_paths"] == [
        [], ["calculator"], ["code_search"], ["knowledge_search"],
        ["code_search", "calculator"], [],
    ]


def test_known_limitations_are_limitations_not_hidden_bugs():
    obj = _load()
    kl = obj["known_limitations"]
    assert "L1" in kl and "L6" in kl
    stmt = obj["known_limitations_statement"].lower()
    # 措辞明确："是已知 limitation，不是等待偷偷修复的 bug"
    assert stmt.startswith("these are known limitations")
    assert "not bugs" in stmt


def test_gate_status_not_writing_gate4_closed():
    obj = _load()
    gs = obj["gate_status"]
    assert gs["gate_1"] == "CLOSED"
    assert gs["gate_2"] == "CLOSED / FROZEN"
    assert gs["gate_3"] == "CLOSED / FROZEN"
    assert gs["gate_4"] == "CLOSE CANDIDATE / pending reviewer"
    assert gs["gate_5"] == "NEXT"
    # 执行 Agent 不能自写 Gate 4 = CLOSED
    assert "CLOSED" not in gs["gate_4"].upper()
