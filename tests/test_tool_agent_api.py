"""Tests for G4-E2E-07A POST /tool-agent/query (Structured Tool Agent API).

Fake / Scripted Decision Provider + Real Tool wiring（calculator / code_search /
knowledge_search）。覆盖：direct（0 tool call）、calculator、code_search（repo
sandbox）、knowledge_search（Fake RetrievalPort）、multi-step observation 反馈、
refuse reason、parse failure → HTTP 200、budget stop → HTTP 200、runtime None → 503、
blank/unknown/history/budget/provider-model → 422、响应序列化无 key/raw/CoT/prompt/
traceback、trace 不泄漏源文件正文。无 real LLM / 无网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.app
from core.tool_agent import (
    ACTION_PARSE_FAILED,
    AGENT_BUDGET_EXCEEDED,
    AgentDecisionOutcome,
    FinalAnswerAction,
    RefuseAction,
    ToolCallAction,
    build_tool_agent_runtime,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

client = TestClient(api.app.app)


class FakeRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, query, strategy, top_k):
        return ()


def _outcome(action, failure_code=None):
    return AgentDecisionOutcome(
        action=action, failure_code=failure_code, call_metadata=None
    )


class ScriptedProvider:
    """按脚本返回 AgentDecisionOutcome；decision 可以是 callable（读 context）。"""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def decide(self, registry, user_query, *, context=()):
        item = self._decisions[min(self.calls, len(self._decisions) - 1)]
        self.calls += 1
        if callable(item):
            return item(registry, user_query, context)
        return item


def _install(monkeypatch, decisions, port=None):
    provider = ScriptedProvider(decisions)
    rt = build_tool_agent_runtime(
        repo_root=REPO_ROOT,
        retrieval_port=port or FakeRetrievalPort(),
        provider=provider,
    )
    monkeypatch.setattr(api.app, "tool_agent_runtime", rt)
    return provider


def _post(question: str, **extra):
    body = {"question": question}
    body.update(extra)
    return client.post("/tool-agent/query", json=body)


# ---------------------------------------------------------------------- #
# 行为：Fake Provider + Real Tool
# ---------------------------------------------------------------------- #


class TestToolAgentEndpoint:
    def test_direct_answer_zero_tool_calls_completed(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(FinalAnswerAction("final_answer", "好的"))
        ])
        resp = _post("你好")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "tool_agent_query_response_v1"
        assert data["status"] == "completed"
        assert data["tool_calls_used"] == 0
        assert data["answer"]

    def test_calculator_real_handler(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(ToolCallAction(action="tool_call", tool_name="calculator",
                                    arguments={"expression": "12 * 7"})),
            _outcome(FinalAnswerAction("final_answer", "84")),
        ])
        resp = _post("12 乘以 7 等于多少？")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["answer"] == "84"
        assert data["tool_calls_used"] == 1
        assert data["tool_errors_used"] == 0

    def test_code_search_real_handler_repo_sandbox(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(ToolCallAction(action="tool_call", tool_name="code_search",
                                    arguments={"query": "ToolAgentRuntime"})),
            _outcome(FinalAnswerAction(
                "final_answer", "core/tool_agent/runtime.py")),
        ])
        resp = _post("ToolAgentRuntime 定义在哪个文件？")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "core/tool_agent/runtime.py" in data["answer"]
        assert data["tool_calls_used"] == 1

    def test_knowledge_search_fake_port_real_handler(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(ToolCallAction(action="tool_call", tool_name="knowledge_search",
                                    arguments={"query": "RRF"})),
            _outcome(FinalAnswerAction("final_answer", "RRF 基于排名")),
        ])
        resp = _post("RRF 融合基于什么？")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["tool_calls_used"] == 1

    def test_multi_step_observation_feedback(self, monkeypatch):
        def second_decision(registry, user_query, context):
            # Observation 真正反馈：context 里能看到 code_search 的 4096
            obs = context[-1]
            assert obs.observation_status == "ok"
            assert "4096" in str(obs.observation_result)
            return _outcome(ToolCallAction(
                action="tool_call", tool_name="calculator",
                arguments={"expression": "4096 * 2"}))

        _install(monkeypatch, [
            _outcome(ToolCallAction(action="tool_call", tool_name="code_search",
                                    arguments={"query": "MAX_INTEGER_BITS"})),
            second_decision,
            _outcome(FinalAnswerAction("final_answer", "8192")),
        ])
        resp = _post("找到 MAX_INTEGER_BITS 再计算它的两倍")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["answer"] == "8192"
        assert data["tool_calls_used"] == 2

    def test_refuse_reason_correct(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(RefuseAction("refuse", "UNSUPPORTED_REQUEST"))
        ])
        resp = _post("调用 shell 执行 rm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "refused"
        assert data["reason_code"] == "UNSUPPORTED_REQUEST"
        assert data["answer"] is None

    def test_parse_failure_is_http_200(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(None, failure_code=ACTION_PARSE_FAILED)
        ])
        resp = _post("随便")
        assert resp.status_code == 200  # Agent 结构化失败，不是 HTTP 错误
        data = resp.json()
        assert data["status"] == "failed"
        assert data["failure_code"] == ACTION_PARSE_FAILED

    def test_budget_stop_is_http_200(self, monkeypatch):
        tools = [
            _outcome(ToolCallAction(
                action="tool_call", tool_name="calculator",
                arguments={"expression": f"{i}+{i}"}))
            for i in range(1, 7)
        ]  # 6 个不同表达式，无 duplicate，撞 max_tool_calls=4 / iterations=5
        _install(monkeypatch, tools)
        resp = _post("一直算")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "refused"
        assert data["reason_code"] == AGENT_BUDGET_EXCEEDED
        assert data["tool_calls_used"] == 4


# ---------------------------------------------------------------------- #
# 边界与安全
# ---------------------------------------------------------------------- #


class TestToolAgentBoundaries:
    def test_runtime_none_returns_503(self, monkeypatch):
        monkeypatch.setattr(api.app, "tool_agent_runtime", None)
        resp = _post("你好")
        assert resp.status_code == 503
        assert "not initialized" in resp.json()["detail"]

    def test_blank_question_422(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(FinalAnswerAction("final_answer", "ok"))
        ])
        for bad in ("", "   "):
            resp = _post(bad)
            assert resp.status_code == 422, bad

    def test_unknown_field_422(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(FinalAnswerAction("final_answer", "ok"))
        ])
        assert _post("x", foo=1).status_code == 422

    def test_history_422(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(FinalAnswerAction("final_answer", "ok"))
        ])
        assert _post("x", history=[]).status_code == 422

    def test_budget_override_422(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(FinalAnswerAction("final_answer", "ok"))
        ])
        assert _post("x", max_tool_calls=10).status_code == 422
        assert _post("x", max_agent_iterations=99).status_code == 422

    def test_provider_model_override_422(self, monkeypatch):
        _install(monkeypatch, [
            _outcome(FinalAnswerAction("final_answer", "ok"))
        ])
        assert _post("x", provider="openai").status_code == 422
        assert _post("x", model="gpt-4o").status_code == 422

    def test_response_serialization_safe(self, monkeypatch):
        # code_search 后：响应不含 key / raw / CoT / prompt / traceback，
        # 也不泄漏源文件正文（trace 是安全字段白名单）
        _install(monkeypatch, [
            _outcome(ToolCallAction(action="tool_call", tool_name="code_search",
                                    arguments={"query": "ToolAgentRuntime"})),
            _outcome(FinalAnswerAction(
                "final_answer", "core/tool_agent/runtime.py")),
        ])
        resp = _post("ToolAgentRuntime 在哪？")
        assert resp.status_code == 200
        text = resp.text
        for marker in ("api_key", "Authorization", "raw_output",
                       "reasoning_content", "system_prompt", "traceback"):
            assert marker.lower() not in text.lower(), marker
        # 源文件正文（code_search 命中的 class 行）不得进入响应
        assert "class ToolAgentRuntime" not in text
        # trace 只含安全字段
        data = resp.json()
        allowed = {"event_type", "iteration", "action_type", "tool_name",
                   "call_id", "tool_status", "error_code",
                   "iterations_used", "tool_calls_used", "tool_errors_used"}
        for event in data["trace"]:
            assert set(event.keys()) <= allowed, event.keys()
