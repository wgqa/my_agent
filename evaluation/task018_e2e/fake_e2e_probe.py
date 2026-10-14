"""Task 018 probe through the existing product Runtime.

Fake mode uses only httpx.MockTransport. Live mode is enabled only for a
single parent-scheduled case, requires a shared durable budget gate, and sends
through the official DeepSeek base URL. Each worker loads one checkout so B2
and Task 017 Python modules cannot be mixed in sys.modules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

_TASK018_DIR = str(Path(__file__).resolve().parent)
if _TASK018_DIR not in sys.path:
    sys.path.insert(0, _TASK018_DIR)
from shared_budget import BudgetGateStop, SharedBudgetGate, canonical_json


FLASH_MODEL = "deepseek-flash"
OFFLINE_API_KEY = "task018-offline-only-placeholder"
MAX_REQUESTS = 60
MAX_TOKENS = 200_000
MAX_ESTIMATED_USD = 0.15
INPUT_PRICE_PER_MILLION = 0.30
OUTPUT_PRICE_PER_MILLION = 1.20
BASE_REF = "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad"
HEAD_REF = "d6b6c100d5e2e441957d834a29a73a8bc4ac1693"


@dataclass(frozen=True)
class Case:
    case_id: str
    prompt: str
    fixture: str
    operation: str | None = None
    status: str | None = None
    open_analysis: bool = False
    rag: bool = False
    knowledge_db: str = "case08_knowledge.sqlite3"


CASES = {
    "case09": Case("case09", "解释 src/main.py 中 scale 函数的实现。", "commit_range"),
    "case10": Case("case10", f"列出 {BASE_REF} 到 {HEAD_REF} 之间已删除的源码文件路径。",
                   "commit_range", operation="filter_status", status="deleted"),
    "case01": Case(
        "case01",
        f"列出 {BASE_REF} 到 {HEAD_REF} 之间全部变更文件及状态。",
        "commit_range",
        operation="list_all",
    ),
    "case02": Case(
        "case02",
        f"列出 {BASE_REF} 到 {HEAD_REF} 之间已删除的文件。",
        "commit_range",
        operation="filter_status",
        status="deleted",
    ),
    "case03": Case(
        "case03",
        f"列出 {BASE_REF} 到 {HEAD_REF} 之间重命名文件的旧路径和新路径。",
        "commit_range",
        operation="filter_status",
        status="renamed",
    ),
    "case04": Case(
        "case04",
        "检查当前 working_tree，并列出完整的可见变更文件清单。",
        "working_tree_clean",
        operation="list_all",
    ),
    "case05": Case(
        "case05",
        "列出当前 working_tree 中所有 untracked 文件。",
        "working_tree_untracked",
        operation="filter_status",
        status="untracked",
    ),
    "case06": Case(
        "case06",
        "列出当前项目中已删除的源码文件路径。",
        "commit_range",
        operation="filter_status",
        status="deleted",
    ),
    "case07": Case(
        "case07",
        f"结合 {BASE_REF} 到 {HEAD_REF} 的变更，判断哪项最重要并说明依据。",
        "commit_range",
        open_analysis=True,
    ),
    "case08": Case(
        "case08",
        "根据知识库资料，服务的标准重试窗口是多少秒？",
        "case08_corpus",
        rag=True,
    ),
    # Task 022 fixed cross-capability matrix. These are bounded adaptations
    # of the existing Dev/Validation and Task 018/021 question families to
    # the already-frozen Task 018 Git fixture. Gold stays in the parent
    # runner and is never passed to this Runtime process.
    "t22_gs_01": Case("t22_gs_01", f"列出 {BASE_REF} 到 {HEAD_REF} 之间全部可见变更文件及状态。", "commit_range", operation="list_all"),
    "t22_gs_02": Case("t22_gs_02", f"只列出 {BASE_REF} 到 {HEAD_REF} 中状态为 deleted 的文件。", "commit_range", operation="filter_status", status="deleted"),
    "t22_gs_03": Case("t22_gs_03", f"列出 {BASE_REF} 到 {HEAD_REF} 的重命名旧路径和新路径。", "commit_range", operation="filter_status", status="renamed"),
    "t22_gs_04": Case("t22_gs_04", "列出当前 working_tree 中全部未跟踪文件。", "working_tree_untracked", operation="filter_status", status="untracked"),
    "t22_ga_01": Case("t22_ga_01", f"结合 {BASE_REF} 到 {HEAD_REF} 的实际差异，选一项最重要的变更并说明证据范围。", "commit_range", open_analysis=True),
    "t22_ga_02": Case("t22_ga_02", f"说明 {BASE_REF} 到 {HEAD_REF} 的 src/main.py 改了什么，及其对 scale 结果的影响。", "commit_range", open_analysis=True),
    "t22_ga_03": Case("t22_ga_03", f"检查 {BASE_REF} 到 {HEAD_REF} 新增的 docs/usage.md 和 src/main.py 的差异，说明能从材料确认什么。", "commit_range", open_analysis=True),
    "t22_ga_04": Case("t22_ga_04", f"完整分析 {BASE_REF} 到 {HEAD_REF} 所有变更文件及其影响；如果材料覆盖不全请明确说明。", "commit_range", open_analysis=True),
    "t22_src_01": Case("t22_src_01", "只定位 src/main.py 中 scale 的定义文件和行号，不需要解释实现。", "commit_range"),
    "t22_src_02": Case("t22_src_02", "解释 src/main.py 中 scale 函数如何计算；把它直接使用的同文件常量值也查清。", "commit_range"),
    "t22_src_03": Case("t22_src_03", "解释 src/new_parser.py 中 parse(data) 对输入字符串做了什么处理。", "commit_range"),
    "t22_src_04": Case("t22_src_04", "依据当前 src/main.py 的实现，scale(3) 返回什么？说明公式和实际常量。", "commit_range"),
    "t22_xt_01": Case("t22_xt_01", "比较 src/main.py 的 scale 实现和 tests/test_main.py 中对应断言；说明二者表达的预期是否一致，不要声称测试已执行。", "commit_range"),
    "t22_xt_02": Case("t22_xt_02", "为 src/main.py 查找候选测试文件，并说明候选位置，不要说成已覆盖或已运行。", "commit_range"),
    "t22_xt_03": Case("t22_xt_03", f"结合 {BASE_REF} 到 {HEAD_REF} 的变更，比较 src/old_parser.py 与 src/new_parser.py 的内容和状态。", "commit_range", open_analysis=True),
    "t22_xt_04": Case("t22_xt_04", "读取 tests/test_main.py 的完整内容，指出它实际断言了什么，以及从这份源码不能推出什么。", "commit_range"),
    "t22_rag_01": Case("t22_rag_01", "说明为什么更换 corpus commit 后不能直接沿用旧 retrieval hit 结论；哪些 parser、chunker、embedding 信息和固定评测方式需要跟踪？", "task022_knowledge_corpus", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_rag_02": Case("t22_rag_02", "资料如何区分证据支持度与世界事实正确性？回答通过 evidence verification 能推出什么，不能推出什么？", "task022_knowledge_corpus", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_rag_03": Case("t22_rag_03", "文档增量更新时，内容没变、内容改变和源文件消失分别应该如何处理？", "task022_knowledge_corpus", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_rag_04": Case("t22_rag_04", "资料中 Mock 和 Stub 有什么区别？行覆盖率与分支覆盖率又分别关注什么？", "task022_knowledge_corpus", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_mix_01": Case("t22_mix_01", "读取 src/new_parser.py，说明 parse 的实际处理步骤；结合 Function Calling 资料解释，为什么仅有这份源码不能声称函数已经被工具执行成功。", "commit_range", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_mix_02": Case("t22_mix_02", "知识资料中的标准重试窗口是多少？再读取 src/main.py 的 scale 实现与常量。两者数值相同是否就能证明 LIMIT 是服务重试配置？请分别列出依据。", "commit_range", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_mix_03": Case("t22_mix_03", "结合单元测试资料，检查 tests/test_main.py 中 scale 的断言；它能说明什么测试意图，哪些结论仍需要实际运行测试才能确认？", "commit_range", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_mix_04": Case("t22_mix_04", "读取项目 docs/usage.md 与 src/main.py，结合知识资料对来源元数据的要求，说明文档与实现的对应关系，并区分知识资料和当前仓库源码的证据身份。", "commit_range", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_ev_01": Case("t22_ev_01", "读取 src/missing.py 并解释 Missing.run 的实现；如果文件或定义不存在，请明确说明，不要猜测。", "commit_range"),
    "t22_ev_02": Case("t22_ev_02", "请实际执行这个隔离项目的 pytest，并告诉我真实通过数量。", "commit_range"),
    "t22_ev_03": Case("t22_ev_03", "确认当前生产服务的默认重试窗口是否为 12 秒，并提供项目配置依据。", "commit_range", rag=True, knowledge_db="task022_knowledge.sqlite3"),
    "t22_ev_04": Case("t22_ev_04", "确认这个提交范围里的 pytest 是否全部通过；如果只有测试源码或候选位置，请不要推断执行结果。", "commit_range"),
}


class OfflineGuardError(RuntimeError):
    """Fail-closed error in the offline SDK overlay; contains no credential data."""


class OfflineBudget:
    """Small per-run guard used only by the offline SDK adapter."""

    def __init__(self, *, max_requests: int = MAX_REQUESTS, max_tokens: int = MAX_TOKENS,
                 max_estimated_usd: float = MAX_ESTIMATED_USD):
        self.max_requests = max_requests
        self.max_tokens = max_tokens
        self.max_estimated_usd = max_estimated_usd
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.estimated_usd = 0.0

    def before_request(self, *, output_cap: int) -> None:
        if self.requests >= self.max_requests:
            raise OfflineGuardError("PROVIDER_REQUEST_BUDGET_STOP")
        if self.input_tokens + self.output_tokens + output_cap > self.max_tokens:
            raise OfflineGuardError("TOKEN_BUDGET_STOP")
        worst_next_output = output_cap * OUTPUT_PRICE_PER_MILLION / 1_000_000
        if self.estimated_usd + worst_next_output > self.max_estimated_usd:
            raise OfflineGuardError("ESTIMATED_COST_BUDGET_STOP")
        self.requests += 1

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.estimated_usd = (
            self.input_tokens * INPUT_PRICE_PER_MILLION
            + self.output_tokens * OUTPUT_PRICE_PER_MILLION
        ) / 1_000_000
        if self.input_tokens + self.output_tokens > self.max_tokens:
            raise OfflineGuardError("TOKEN_BUDGET_STOP_AFTER_RESPONSE")
        if self.estimated_usd > self.max_estimated_usd:
            raise OfflineGuardError("ESTIMATED_COST_BUDGET_STOP_AFTER_RESPONSE")


class FakeHTTPProvider:
    """OpenAI-compatible local HTTP endpoint with a fixed response sequence."""

    def __init__(self, case: Case, variant: str, *, request_limit: int = MAX_REQUESTS,
                 token_limit: int = MAX_TOKENS, cost_limit: float = MAX_ESTIMATED_USD,
                 fault: dict[str, Any] | None = None,
                 shared_budget: SharedBudgetGate | None = None,
                 task_order: int = 0):
        self.case = case
        self.variant = variant
        self.budget = OfflineBudget(max_requests=request_limit, max_tokens=token_limit,
                                    max_estimated_usd=cost_limit)
        self.fault = fault or {}
        self.shared_budget = shared_budget
        self.task_order = task_order
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.guard_stops: list[dict[str, Any]] = []
        self.http_attempts = 0
        self._httpx = None
        self._transport = None
        self._cursor = 0

    def _steps(self) -> list[tuple[str, dict[str, Any]]]:
        def planner(retrieval: bool = False):
            if retrieval:
                content = json.dumps({
                    "query_type": "fact", "retrieval_required": True,
                    "action": "single_retrieval", "reason_code": "SIMPLE_FACT",
                    "subqueries": [],
                }, ensure_ascii=False)
            else:
                content = json.dumps({
                    "query_type": "unanswerable_or_no_retrieval",
                    "retrieval_required": False, "action": "no_retrieval",
                    "reason_code": "NO_RETRIEVAL_NEEDED", "subqueries": [],
                }, ensure_ascii=False)
            if self.variant in {"task020", "task021", "hybrid"}:
                value = json.loads(content)
                operation = ("knowledge_answer" if self.case.rag else "source_read"
                    if self.case.case_id == "case09" else "change_analysis"
                    if self.case.open_analysis else "file_status")
                git_range = self.case.fixture == "commit_range" and operation != "source_read"
                value["task_contract"] = {
                    "operation": operation,
                    "object_kind": ("knowledge" if self.case.rag else "function"
                        if operation == "source_read" else "source_files"
                        if self.case.case_id == "case10" else "files"),
                    "target_paths": ["src/main.py"] if operation == "source_read" else [],
                    "target_symbols": ["scale"] if operation == "source_read" else [],
                    "scope_mode": ("knowledge" if self.case.rag else "project"
                        if operation == "source_read" else "commit_range" if git_range else "working_tree"),
                    "base_ref": BASE_REF if git_range else None,
                    "head_ref": HEAD_REF if git_range else None,
                    "status": self.case.status or "any",
                    "requires_source_body": operation == "source_read",
                    "requires_diff": operation == "change_analysis",
                    "requires_complete_list": operation == "file_status",
                    "requires_test_execution": False, "requires_knowledge": self.case.rag,
                }
                content = json.dumps(value, ensure_ascii=False)
            return ("planner", {"content": content})

        def decision(payload: dict[str, Any]):
            return ("decision", {"content": json.dumps(payload, ensure_ascii=False)})

        steps = [planner(self.case.rag)]
        if self.case.rag:
            steps.append(decision({
                "action": "final_answer",
                "answer": "知识库给出的标准重试窗口是 12 秒。[E1]",
            }))
            return steps

        if self.case.case_id == "case09":
            steps.extend([
                decision({"action": "tool_call", "tool_name": "read_project_context", "arguments": {
                    "path": "src/main.py", "target": {"kind": "file", "start_line": 1}}}),
                decision({"action": "final_answer", "answer":
                    "scale(value) 返回 value * LIMIT；同文件 LIMIT = 12，因此输入乘以 12。[E1]"}),
            ])
            return steps

        if self.case.open_analysis:
            steps.extend([
                decision({"action": "tool_call", "tool_name": "changed_files", "arguments": {
                    "mode": "commit_range", "base_ref": BASE_REF, "head_ref": HEAD_REF,
                }}),
                decision({"action": "tool_call", "tool_name": "git_diff", "arguments": {
                    "mode": "commit_range", "base_ref": BASE_REF, "head_ref": HEAD_REF,
                    "path": "src/main.py",
                }}),
                decision({"action": "final_answer", "answer":
                    "目前只有 src/main.py 的 diff，单凭这一项不足以可靠比较各项改动的重要性。[E2]"}),
            ])
            if self.variant == "task017":
                steps.append(("selector", {"content": json.dumps({
                    "response_type": "refusal", "reason_code": "unsupported_request",
                })}))
            return steps

        tool_arguments = {"mode": "working_tree"}
        if self.case.fixture == "commit_range":
            tool_arguments = {"mode": "commit_range", "base_ref": BASE_REF, "head_ref": HEAD_REF}
        steps.append(decision({"action": "tool_call", "tool_name": "changed_files", "arguments": tool_arguments}))
        if self.variant in {"direct_hybrid", "task020", "task021", "converged"}:
            selected = {"action": "changed_files_finalization", "evidence_id": "E1",
                        "operation": self.case.operation}
            if self.case.operation == "filter_status":
                selected["status"] = self.case.status
            if self.case.case_id == "case03":
                selected["type"] = "json_object"
            steps.append(decision(selected))
        else:
            answer = (
                "已删除的源码文件见工具结果。"
                if self.case.case_id == "case06"
                else "已检查变更文件并整理结果。"
            )
            steps.append(decision({"action": "final_answer", "answer": answer}))
        if self.case.case_id == "case06":
            # The status list cannot satisfy PROJECT_CODE_V1. The scripted
            # response demonstrates that direct mode keeps the Requirement.
            steps.append(decision({"action": "refuse", "reason_code": "INSUFFICIENT_INFORMATION"}))
        if self.variant == "task017" and self.case.case_id != "case06":
            selected = {"evidence_id": "E1", "operation": self.case.operation}
            if self.case.operation == "filter_status":
                selected["status"] = self.case.status
            steps.append(("selector", {"content": json.dumps(selected, ensure_ascii=False)}))
        return steps

    @staticmethod
    def _role(body: dict[str, Any]) -> str:
        messages = body.get("messages") or []
        first = messages[0].get("content", "") if messages else ""
        if "你是 RAG 系统的查询规划器" in first:
            return "planner"
        if "Identify only the conversation referents" in first:
            return "context_resolver"
        if "You select a bounded presentation" in first:
            return "selector"
        if any("上一轮结构化输出未通过系统严格校验" in str(message.get("content", ""))
               for message in messages):
            return "decision_repair"
        return "decision"

    def _response_body(self, request: dict[str, Any], role: str) -> tuple[int, dict[str, Any]]:
        fault = self.fault
        if fault.get("role") == role and fault.get("kind") == "http_503":
            return 503, {"error": {"message": "fake offline provider failure", "type": "server_error"}}
        if role == "context_resolver":
            content = '{"reference_context":null}'
        else:
            steps = self._steps()
            if self._cursor >= len(steps):
                return 500, {"error": {"message": "unexpected fake request sequence", "type": "test_error"}}
            expected_role, scripted = steps[self._cursor]
            if expected_role != role:
                return 500, {"error": {"message": f"unexpected fake role: {role}", "type": "test_error"}}
            self._cursor += 1
            content = scripted["content"]
        response_model = fault.get("response_model", FLASH_MODEL) if fault.get("role") == role else FLASH_MODEL
        usage = fault.get("usage", {"prompt_tokens": 120, "completion_tokens": 24}) if fault.get("role") == role else {"prompt_tokens": 120, "completion_tokens": 24}
        body = {
            "id": f"chatcmpl-offline-{self.http_attempts}",
            "object": "chat.completion",
            "created": 1_797_000_000,
            "model": response_model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        }
        if usage is not None:
            body["usage"] = {"prompt_tokens": usage["prompt_tokens"],
                             "completion_tokens": usage["completion_tokens"],
                             "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"]}
        return 200, body

    def _handle(self, request):
        import httpx

        self.http_attempts += 1
        try:
            body = json.loads(request.content.decode("utf-8"))
        except Exception:
            body = {}
        role = self._role(body)
        messages_json = json.dumps(body.get("messages", []), ensure_ascii=False,
                                   sort_keys=True, separators=(",", ":"))
        paired_messages_json = re.sub(r"call_[0-9a-f]{32}", "call_<per-run>", messages_json)
        observed = {
            "seq": self.http_attempts,
            "role": role,
            "method": request.method,
            "host": request.url.host,
            "path": request.url.path,
            "model": body.get("model"),
            "thinking": body.get("thinking"),
            "temperature": body.get("temperature"),
            "max_tokens": body.get("max_tokens"),
            "prompt_sha256": hashlib.sha256(messages_json.encode("utf-8")).hexdigest(),
            "paired_prompt_sha256": hashlib.sha256(paired_messages_json.encode("utf-8")).hexdigest(),
            "response_format": body.get("response_format"),
        }
        self.requests.append(observed)
        if body.get("model") != FLASH_MODEL:
            return httpx.Response(409, json={"error": {"message": "wrong model", "type": "offline_guard"}})
        if body.get("thinking") != {"type": "disabled"}:
            return httpx.Response(409, json={"error": {"message": "Thinking not disabled", "type": "offline_guard"}})
        if fault := self.fault:
            if fault.get("role") == role and fault.get("kind") == "transport_error":
                self.responses.append({"seq": self.http_attempts, "role": role,
                                       "status": "transport_error", "response_model": None,
                                       "usage": None, "latency_ms": 0})
                raise httpx.ConnectError("fake transport error", request=request)
        status, payload = self._response_body(body, role)
        response_model = payload.get("model")
        usage = payload.get("usage")
        self.responses.append({
            "seq": self.http_attempts,
            "role": role,
            "status": "response" if status == 200 else "http_error",
            "response_model": response_model,
            "usage": usage,
            "latency_ms": 0,
            "content": payload.get("choices", [{}])[0].get("message", {}).get("content") if status == 200 else None,
        })
        return httpx.Response(status, json=payload)

    def build_openai_client(self, **_kwargs):
        import httpx
        from openai import OpenAI

        if self._httpx is None:
            self._httpx = httpx.Client(transport=httpx.MockTransport(self._handle))
        client = OpenAI(
            api_key=OFFLINE_API_KEY,
            base_url="https://offline.invalid/v1",
            http_client=self._httpx,
            max_retries=0,
        )
        resource = client.chat.completions
        original_create = resource.create

        def create(*args, **kwargs):
            model = kwargs.get("model")
            if model != FLASH_MODEL:
                self.guard_stops.append({"status": "wrong_request_model", "model": model})
                raise OfflineGuardError("REQUEST_MODEL_MISMATCH")
            max_output = kwargs.get("max_tokens", 0)
            try:
                self.budget.before_request(output_cap=max_output if type(max_output) is int else 0)
            except OfflineGuardError as exc:
                self.guard_stops.append({"status": "budget_stop", "reason": str(exc),
                                         "role": "unknown-until-wire", "model": model})
                raise
            kwargs["extra_body"] = {**(kwargs.get("extra_body") or {}),
                                    "thinking": {"type": "disabled"}}
            shared_seq = None
            if self.shared_budget is not None:
                try:
                    shared_seq = self.shared_budget.reserve(
                        task_order=self.task_order, case_id=self.case.case_id,
                        variant=self.variant, role=self._role(kwargs),
                        request_model=model, request_payload=kwargs,
                        output_cap=max_output,
                    )
                except BudgetGateStop as exc:
                    self.guard_stops.append({"status": "shared_budget_stop",
                                             "reason": str(exc), "role": self._role(kwargs)})
                    raise OfflineGuardError(str(exc)) from None
            started = time.perf_counter()
            try:
                response = original_create(*args, **kwargs)
            except Exception as exc:
                if shared_seq is not None:
                    self.shared_budget.record_provider_error(
                        seq=shared_seq, error_category=type(exc).__name__,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                if self.responses and self.responses[-1].get("seq") == self.http_attempts:
                    self.responses[-1].update(status="provider_error",
                        exception_type=type(exc).__name__,
                        latency_ms=(time.perf_counter() - started) * 1000)
                else:
                    self.responses.append({"seq": self.http_attempts, "status": "provider_error",
                        "exception_type": type(exc).__name__,
                        "latency_ms": (time.perf_counter() - started) * 1000})
                raise OfflineGuardError(f"PROVIDER_REQUEST_FAILED:{type(exc).__name__}") from None
            latency = (time.perf_counter() - started) * 1000
            response_model = getattr(response, "model", None)
            usage = getattr(response, "usage", None)
            if shared_seq is not None:
                raw_response = response.model_dump(mode="json")
                shared_stop = self.shared_budget.record_response(
                    seq=shared_seq,
                    response_model=response_model,
                    response_payload=raw_response,
                    usage=(usage.model_dump(mode="json") if usage is not None else None),
                    latency_ms=latency,
                )
                if shared_stop and shared_stop not in {
                    "TOKEN_BUDGET_STOP_AFTER_RESPONSE",
                    "ESTIMATED_COST_BUDGET_STOP_AFTER_RESPONSE",
                }:
                    raise OfflineGuardError(shared_stop)
            if response_model != FLASH_MODEL:
                if self.responses and self.responses[-1].get("seq") == self.http_attempts:
                    self.responses[-1].update(status="response_model_mismatch",
                        response_model=response_model, latency_ms=latency)
                raise OfflineGuardError("RESPONSE_MODEL_MISMATCH")
            if usage is None or type(getattr(usage, "prompt_tokens", None)) is not int or type(getattr(usage, "completion_tokens", None)) is not int:
                if self.responses and self.responses[-1].get("seq") == self.http_attempts:
                    self.responses[-1].update(status="missing_usage",
                        response_model=response_model, latency_ms=latency)
                raise OfflineGuardError("USAGE_REQUIRED_TO_CONTINUE")
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            self.budget.record_usage(prompt_tokens, completion_tokens)
            if self.responses and self.responses[-1].get("seq") == self.http_attempts:
                self.responses[-1]["latency_ms"] = latency
            return response

        resource.create = create
        return client


class LiveHTTPProvider:
    """Task 018-only OpenAI SDK overlay with the same durable budget gate."""

    OFFICIAL_BASE_URL = "https://api.deepseek.com/v1"

    def __init__(self, case: Case, variant: str, *, shared_budget: SharedBudgetGate,
                 task_order: int, api_key: str, sdk_factory=None):
        if not api_key or not api_key.strip():
            raise OfflineGuardError("DEEPSEEK_API_KEY_MISSING")
        self.case = case
        self.variant = variant
        self.shared_budget = shared_budget
        self.task_order = task_order
        self.api_key = api_key
        self.sdk_factory = sdk_factory
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.guard_stops: list[dict[str, Any]] = []
        self.http_attempts = 0

    @staticmethod
    def _safe_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
        # chat.completions.create kwargs are request body fields, not headers.
        return {key: value for key, value in kwargs.items()
                if key not in {"timeout", "extra_headers", "max_retries"}}

    def build_openai_client(self, **client_kwargs):
        from openai import OpenAI

        supplied_base_url = client_kwargs.get("base_url") or self.OFFICIAL_BASE_URL
        parsed = urlsplit(supplied_base_url)
        if (parsed.scheme != "https" or parsed.hostname != "api.deepseek.com"
                or parsed.path.rstrip("/") not in {"", "/v1"}):
            raise OfflineGuardError("UNEXPECTED_PROVIDER_BASE_URL")
        timeout = client_kwargs.get("timeout", 20.0)
        # The frozen product providers are configured for zero retries. Enforce
        # that property at the actual SDK boundary as well.
        if client_kwargs.get("max_retries", 0) != 0:
            raise OfflineGuardError("SDK_RETRIES_MUST_BE_ZERO")
        sdk_kwargs = {"api_key": self.api_key,
                      "base_url": self.OFFICIAL_BASE_URL,
                      "timeout": timeout,
                      "max_retries": 0}
        if client_kwargs.get("default_headers"):
            sdk_kwargs["default_headers"] = client_kwargs["default_headers"]
        client = (self.sdk_factory or OpenAI)(**sdk_kwargs)
        resource = client.chat.completions
        original_create = resource.create

        def create(*args, **kwargs):
            model = kwargs.get("model")
            if model != FLASH_MODEL:
                raise OfflineGuardError("REQUEST_MODEL_MISMATCH")
            if kwargs.get("temperature") != 0:
                raise OfflineGuardError("REQUEST_TEMPERATURE_MISMATCH")
            output_cap = kwargs.get("max_tokens")
            if type(output_cap) is not int or output_cap <= 0:
                raise OfflineGuardError("INVALID_OUTPUT_RESERVATION")
            kwargs["extra_body"] = {**(kwargs.get("extra_body") or {}),
                                    "thinking": {"type": "disabled"}}
            payload = self._safe_payload(kwargs)
            role = FakeHTTPProvider._role(payload)
            try:
                seq = self.shared_budget.reserve(
                    task_order=self.task_order, case_id=self.case.case_id,
                    variant=self.variant, role=role, request_model=model,
                    request_payload=payload, output_cap=output_cap,
                )
            except BudgetGateStop as exc:
                self.guard_stops.append({"reason": str(exc), "role": role})
                raise OfflineGuardError(str(exc)) from None
            self.http_attempts += 1
            request_record = {
                "seq": seq, "task_order": self.task_order,
                "case_id": self.case.case_id, "variant": self.variant,
                "role": role, "model": model,
                "prompt_sha256": hashlib.sha256(canonical_json(
                    payload.get("messages", [])).encode("utf-8")).hexdigest(),
                "request_sha256": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
                "thinking": {"type": "disabled"},
                "temperature": kwargs.get("temperature"),
                "max_tokens": output_cap,
                "provider_base": "https://api.deepseek.com/v1",
            }
            self.requests.append(request_record)
            started = time.perf_counter()
            try:
                response = original_create(*args, **kwargs)
            except Exception as exc:
                latency = (time.perf_counter() - started) * 1000
                self.shared_budget.record_provider_error(
                    seq=seq, error_category=type(exc).__name__, latency_ms=latency,
                )
                self.responses.append({
                    "seq": seq, "status": "provider_error",
                    "exception_type": type(exc).__name__,
                    "billing_status": "unknown", "latency_ms": latency,
                })
                raise OfflineGuardError("PROVIDER_ERROR_BILLING_UNKNOWN") from None
            latency = (time.perf_counter() - started) * 1000
            response_model = getattr(response, "model", None)
            usage_obj = getattr(response, "usage", None)
            usage = usage_obj.model_dump(mode="json") if usage_obj is not None else None
            raw_response = response.model_dump(mode="json")
            shared_stop = self.shared_budget.record_response(
                seq=seq, response_model=response_model,
                response_payload=raw_response, usage=usage, latency_ms=latency,
            )
            usage_valid = usage is not None
            self.responses.append({
                "seq": seq, "status": "response" if response_model == FLASH_MODEL and usage_valid else "response_invalid",
                "response_model": response_model, "usage": usage,
                "raw_response": raw_response, "latency_ms": latency,
                "billing_status": "known" if usage_valid else "unknown",
                "estimated_cost_usd": (round((usage["prompt_tokens"] * 0.30
                    + usage["completion_tokens"] * 1.20) / 1_000_000, 8)
                    if usage_valid else None),
            })
            if shared_stop and shared_stop not in {
                "TOKEN_BUDGET_STOP_AFTER_RESPONSE",
                "ESTIMATED_COST_BUDGET_STOP_AFTER_RESPONSE",
            }:
                raise OfflineGuardError(shared_stop)
            if response_model != FLASH_MODEL:
                raise OfflineGuardError("RESPONSE_MODEL_IDENTITY_MISMATCH")
            if not usage_valid:
                raise OfflineGuardError("PROVIDER_USAGE_MISSING_OR_INCONSISTENT")
            # If a valid response crosses a limit, it can be consumed by the
            # current Runtime, but the shared gate blocks any subsequent call.
            return response

        resource.create = create
        return client


def _provider_usage_summary(recorder: Any) -> dict[str, Any]:
    if hasattr(recorder, "budget"):
        return {"input": recorder.budget.input_tokens,
                "output": recorder.budget.output_tokens,
                "total": recorder.budget.input_tokens + recorder.budget.output_tokens,
                "usage_unknown": any(row.get("usage") is None
                                      for row in recorder.responses)}
    known_input = known_output = 0
    unknown = False
    for row in recorder.responses:
        usage = row.get("usage")
        if not isinstance(usage, dict):
            unknown = True
            continue
        if type(usage.get("prompt_tokens")) is not int or type(usage.get("completion_tokens")) is not int:
            unknown = True
            continue
        known_input += usage["prompt_tokens"]
        known_output += usage["completion_tokens"]
    return {"input": known_input, "output": known_output,
            "total": known_input + known_output, "usage_unknown": unknown}


def _provider_cost_summary(recorder: Any) -> float | None:
    if hasattr(recorder, "budget"):
        return round(recorder.budget.estimated_usd, 8)
    if any(row.get("billing_status") == "unknown" for row in recorder.responses):
        return None
    return round(sum(float(row.get("estimated_cost_usd", 0.0))
                     for row in recorder.responses), 8)


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=checkout, check=True,
                          capture_output=True, text=True).stdout.strip()


def _cleanup_task018_temp(path: Path, prefix: str) -> None:
    resolved = path.resolve(strict=True)
    temp_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if (resolved.parent != temp_parent or not resolved.name.startswith(prefix)
            or not resolved.is_dir() or resolved.is_symlink()):
        raise RuntimeError("Refusing to remove an unverified Task 018 temporary directory")

    def make_writable_and_retry(function, filename, _exc_info):
        os.chmod(filename, stat.S_IWRITE | stat.S_IREAD)
        function(filename)

    shutil.rmtree(resolved, onerror=make_writable_and_retry)


def _append_diagnostic_event(path: Path | None, *, run_id: str | None,
                             task_order: int, case_id: str, event_type: str,
                             payload: dict[str, Any], shared_budget: SharedBudgetGate | None) -> None:
    if path is None:
        return
    record = {"run_id": run_id, "task_order": task_order, "case_id": case_id,
              "event_type": event_type, "payload": payload}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if shared_budget is not None:
            shared_budget.stop("RESULT_PERSISTENCE_FAILED", billing_unknown=False)
        raise OfflineGuardError("RESULT_PERSISTENCE_FAILED") from None


def _install_checkout(checkout: Path) -> None:
    checkout = checkout.resolve(strict=True)
    _git(checkout, "rev-parse", "--show-toplevel")
    # Keep the script's checkout off sys.path; this process loads exactly one tree.
    target = str(checkout)
    script_root = str(Path(__file__).resolve().parents[2])
    sys.path[:] = [p for p in sys.path if str(Path(p or ".").resolve()) not in {target, script_root}]
    sys.path.insert(0, target)
    os.chdir(checkout)


def run_case(checkout: Path, variant: str, case: Case, fixture_root: Path,
             *, fault: dict[str, Any] | None = None, request_limit: int = MAX_REQUESTS,
             token_limit: int = MAX_TOKENS, cost_limit: float = MAX_ESTIMATED_USD,
              model_override: str = FLASH_MODEL,
              knowledge_db_override: str | None = None,
              provider_mode: str = "fake",
              shared_budget: SharedBudgetGate | None = None,
              task_order: int = 0,
              run_id: str | None = None,
              diagnostic_log: Path | None = None) -> dict[str, Any]:
    _install_checkout(checkout)
    knowledge_db_name = knowledge_db_override or case.knowledge_db
    if provider_mode == "fake":
        # Ensure dotenv can only observe a dummy value in this isolated process.
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ["DEEPSEEK_API_KEY"] = OFFLINE_API_KEY
    elif provider_mode == "live":
        if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
            raise OfflineGuardError("DEEPSEEK_API_KEY_MISSING")
        if shared_budget is None:
            raise OfflineGuardError("SHARED_BUDGET_GATE_REQUIRED")
    else:
        raise OfflineGuardError("UNSUPPORTED_PROVIDER_MODE")

    import api.app as app_module
    import core.tool_agent.integration as integration_module
    import core.query_planning.openai_compatible as planner_provider_module
    import core.tool_agent.openai_compatible as decision_provider_module
    import core.conversation_context.resolver as context_provider_module
    import core.tool_agent.runtime as runtime_module
    import core.tool_agent.runtime_models as runtime_models_module
    import core.unified_engineering_runtime as unified_module
    from api.project_workspace import EngineeringProject
    from core.engineering_planning import EngineeringEvidencePlanner
    from core.knowledge_library import KnowledgeLibrary
    from core.tool_agent.executor import ToolExecutor

    source_root = fixture_root / case.fixture
    db_source = fixture_root / knowledge_db_name
    if not source_root.is_dir():
        raise ValueError(f"missing fixture: {case.fixture}")
    if case.rag and not db_source.is_file():
        raise ValueError("local corpus fixture is incomplete")
    if not db_source.is_file():
        raise ValueError("local knowledge database fixture is incomplete")

    if provider_mode == "live":
        recorder = LiveHTTPProvider(
            case, variant, shared_budget=shared_budget, task_order=task_order,
            api_key=os.environ["DEEPSEEK_API_KEY"],
        )
    else:
        recorder = FakeHTTPProvider(
            case, variant, request_limit=request_limit,
            token_limit=token_limit, cost_limit=cost_limit, fault=fault,
            shared_budget=shared_budget, task_order=task_order,
        )
    tools: list[dict[str, Any]] = []
    planner_events: list[dict[str, Any]] = []
    requirement_events: list[dict[str, Any]] = []
    gate_events: list[dict[str, Any]] = []
    typed_events: list[dict[str, Any]] = []
    open_answer_events: list[dict[str, Any]] = []
    temp_prefix = f"task018-{provider_mode}-"
    temp_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    try:
        with ExitStack() as stack:
            # Each Agent run receives a fresh copy, so even accidental writes
            # cannot alter the prepared source fixture or another run.
            project_root = temp_root / "project"
            has_git_fixture = case.fixture in {
                "commit_range", "working_tree_clean", "working_tree_untracked"
            }
            if has_git_fixture:
                shutil.copytree(source_root, project_root)
            else:
                project_root.mkdir()
            db_path = temp_root / "knowledge.sqlite3"
            shutil.copy2(fixture_root / knowledge_db_name, db_path)
            library = KnowledgeLibrary(db_path)
            stack.enter_context(patch.object(app_module, "engineering_knowledge_backend", library))
            stack.enter_context(patch.object(app_module, "FROZEN_TOOL_MODEL", model_override))
            stack.enter_context(patch.object(integration_module, "FROZEN_TOOL_MODEL", model_override))
            fake_builder = recorder.build_openai_client
            stack.enter_context(patch.object(planner_provider_module, "OpenAI", fake_builder))
            stack.enter_context(patch.object(decision_provider_module, "OpenAI", fake_builder))
            stack.enter_context(patch.object(context_provider_module, "OpenAI", fake_builder))
            original_execute = ToolExecutor.execute

            def record_execute(executor, call, tool_call_allowed=True):
                observation = original_execute(executor, call, tool_call_allowed)
                item = {"call": call.to_dict(), "status": observation.status,
                              "error_code": observation.error_code,
                              "result": observation.result_copy()}
                tools.append(item)
                _append_diagnostic_event(diagnostic_log, run_id=run_id,
                    task_order=task_order, case_id=case.case_id, event_type="tool_observation",
                    payload=item, shared_budget=shared_budget)
                return observation

            stack.enter_context(patch.object(ToolExecutor, "execute", record_execute))
            original_plan = EngineeringEvidencePlanner.plan

            def record_plan(planner, resolved_input):
                outcome = original_plan(planner, resolved_input)
                item = {"plan": outcome.plan.to_dict(),
                                       "fallback_used": outcome.fallback_used,
                                        "failure_code": outcome.failure_code}
                contract = getattr(outcome, "task_contract", None)
                item["task_contract"] = contract.to_dict() if contract is not None else None
                planner_events.append(item)
                _append_diagnostic_event(diagnostic_log, run_id=run_id,
                    task_order=task_order, case_id=case.case_id, event_type="planner",
                    payload=item, shared_budget=shared_budget)
                return outcome

            stack.enter_context(patch.object(EngineeringEvidencePlanner, "plan", record_plan))
            original_route = unified_module.route_engineering_evidence_requirement

            def record_route(question):
                requirement = original_route(question)
                requirement_events.append({"profile": requirement.requirement_profile.value,
                    "required_evidence_groups": [list(x) for x in requirement.required_evidence_groups],
                    "min_distinct_project_code_paths": requirement.min_distinct_project_code_paths,
                    "router_version": requirement.router_version})
                _append_diagnostic_event(diagnostic_log, run_id=run_id,
                    task_order=task_order, case_id=case.case_id, event_type="requirement",
                    payload=requirement_events[-1], shared_budget=shared_budget)
                return requirement

            stack.enter_context(patch.object(unified_module, "route_engineering_evidence_requirement", record_route))
            original_gate = runtime_module._run_finalization_verifier

            def record_gate(verifier, evidence, answer):
                result = original_gate(verifier, evidence, answer)
                item = {"candidate_answer": answer,
                    "stage": "legacy_answer_gate" if answer is not None else "requirement_precheck",
                    "can_finalize": result.can_finalize,
                    "requirement_satisfied": result.evidence_requirement_satisfied,
                    "binding_status": result.answer_evidence_binding_status,
                    "cited_evidence_ids": list(result.cited_evidence_ids),
                    "reasons": list(result.insufficiency_reasons)}
                gate_events.append(item)
                _append_diagnostic_event(diagnostic_log, run_id=run_id,
                    task_order=task_order, case_id=case.case_id,
                    event_type=item["stage"],
                    payload=item, shared_budget=shared_budget)
                return result

            stack.enter_context(patch.object(runtime_module, "_run_finalization_verifier", record_gate))
            if hasattr(runtime_module, "_lightweight_open_answer_check"):
                original_open_check = runtime_module._lightweight_open_answer_check

                def record_open_check(verifier, current_evidence, answer, **kwargs):
                    error_code = original_open_check(verifier, current_evidence, answer, **kwargs)
                    item = {"candidate_answer": answer,
                        "accepted": error_code is None,
                        "error_code": error_code,
                        "available_evidence_ids": [
                            getattr(value, "evidence_id", None)
                            for value in current_evidence
                        ]}
                    open_answer_events.append(item)
                    _append_diagnostic_event(diagnostic_log, run_id=run_id,
                        task_order=task_order, case_id=case.case_id,
                        event_type="open_answer_source_check", payload=item,
                        shared_budget=shared_budget)
                    return error_code

                stack.enter_context(patch.object(
                    runtime_module, "_lightweight_open_answer_check", record_open_check
                ))
            if hasattr(runtime_module, "finalize_changed_files_typed"):
                original_typed = runtime_module.finalize_changed_files_typed

                def record_typed(*args, **kwargs):
                    result = original_typed(*args, **kwargs)
                    item = {"selector": args[0] if args else kwargs.get("selector"),
                        "protocol_valid": result.protocol_valid,
                        "source_valid": result.source_valid,
                        "accepted": result.accepted,
                        "error_code": result.error_code,
                        "requirement_satisfied": result.requirement_satisfied,
                        "rendered_answer": result.rendered_answer}
                    typed_events.append(item)
                    _append_diagnostic_event(diagnostic_log, run_id=run_id,
                        task_order=task_order, case_id=case.case_id, event_type="typed_finalization",
                        payload=item, shared_budget=shared_budget)
                    return result

                stack.enter_context(patch.object(runtime_module, "finalize_changed_files_typed", record_typed))
            project = EngineeringProject(root=project_root.resolve(strict=True),
                project_name=source_root.name, source="configured")
            if variant in {"direct_hybrid", "task020", "task021", "hybrid", "converged"}:
                assembled = app_module._build_engineering_project_runtime(
                    project, finalization_strategy=("converged_hybrid" if variant == "converged" else "hybrid_task_contract"
                        if variant in {"task020", "task021", "hybrid"} else "direct_hybrid")
                )
            else:
                assembled = app_module._build_engineering_project_runtime(project)
            context_before = len(recorder.requests)
            result = assembled.facade.run(case.prompt)
            runtime_result = {
                "status": result.status,
                "answer": result.answer,
                "reason_code": result.reason_code,
                "failure_code": result.failure_code,
                "iterations_used": result.iterations_used,
                "tool_calls_used": result.tool_calls_used,
                "tool_errors_used": result.tool_errors_used,
                "execution": result.execution.to_dict() if result.execution else None,
                "evidence": [item.to_dict() for item in result.evidence],
                "trace": [item.to_dict() for item in result.trace],
                "task_contract": (result.task_contract.to_dict()
                    if getattr(result, "task_contract", None) is not None else None),
                "can_finalize": result.status == "completed",
                "task_coverage": getattr(result, "task_coverage", "unknown"),
                "semantic_correctness": "not_evaluated",
            }
            output = {
                "case_id": case.case_id,
                "variant": variant,
                "question": case.prompt,
                "fixture_id": case.fixture,
                "knowledge_db_fixture": knowledge_db_name,
                "fixture_head": _git(project_root, "rev-parse", "HEAD") if has_git_fixture else None,
                "fixture_status": _git(project_root, "status", "--short") if has_git_fixture else None,
                "code_head": _git(checkout, "rev-parse", "HEAD"),
                "requested_model": model_override,
                "expected_model": FLASH_MODEL,
                "thinking": "disabled",
                "provider": "deepseek",
                "transport": "httpx.MockTransport" if provider_mode == "fake" else "deepseek-official-api",
                "planner": planner_events,
                "requirement": requirement_events,
                "agent_budget": {
                    "max_agent_iterations": assembled.tool_runtime._budget.max_agent_iterations,
                    "max_tool_calls": assembled.tool_runtime._budget.max_tool_calls,
                    "max_tool_errors": assembled.tool_runtime._budget.max_tool_errors,
                    "deadline_seconds": runtime_models_module.ENGINEERING_RUN_DEADLINE_SECONDS,
                },
                "enabled_tools": [spec.name for spec in assembled.tool_runtime._registry.list_specs()],
                "tools": tools,
                "gate": gate_events,
                "open_answer_source_check": open_answer_events,
                "typed_finalization": typed_events,
                "provider_requests": recorder.requests,
                "provider_responses": recorder.responses,
                "provider_guard_stops": recorder.guard_stops,
                "provider_request_count": recorder.http_attempts,
                "provider_tokens": _provider_usage_summary(recorder),
                "estimated_cost_usd": _provider_cost_summary(recorder),
                "final": runtime_result,
                "infrastructure_status": "ok",
                "context_requests_before_agent": context_before,
            }
            _append_diagnostic_event(diagnostic_log, run_id=run_id,
                task_order=task_order, case_id=case.case_id, event_type="runtime_result",
                payload={"status": result.status, "reason_code": result.reason_code,
                         "failure_code": result.failure_code, "answer": result.answer},
                shared_budget=shared_budget)
            return output
    except OfflineGuardError as exc:
        return {
            "case_id": case.case_id, "variant": variant,
            "question": case.prompt, "requested_model": model_override,
            "expected_model": FLASH_MODEL,
            "thinking": "disabled", "provider_requests": recorder.requests,
            "provider_responses": recorder.responses,
            "provider_guard_stops": recorder.guard_stops,
            "provider_request_count": recorder.http_attempts,
            "provider_tokens": _provider_usage_summary(recorder),
            "estimated_cost_usd": _provider_cost_summary(recorder),
            "tools": tools, "planner": planner_events,
            "requirement": requirement_events, "gate": gate_events,
            "open_answer_source_check": open_answer_events,
            "typed_finalization": typed_events,
            "infrastructure_status": "stopped",
            "stop_reason": str(exc),
        }
    finally:
        transport_client = getattr(recorder, "_httpx", None)
        if transport_client is not None:
            transport_client.close()
        _cleanup_task018_temp(temp_root, temp_prefix)


def run_context_resolver_probe(checkout: Path, fixture_root: Path, *,
                               shared_budget: SharedBudgetGate | None = None,
                               task_order: int = 0) -> dict[str, Any]:
    """Exercise the existing resolver with history, outside the 12 planned runs."""
    _install_checkout(checkout)
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ["DEEPSEEK_API_KEY"] = OFFLINE_API_KEY
    import api.app as app_module
    import core.tool_agent.integration as integration_module
    import core.query_planning.openai_compatible as planner_provider_module
    import core.tool_agent.openai_compatible as decision_provider_module
    import core.conversation_context.resolver as context_provider_module
    from api.project_workspace import EngineeringProject
    from core.knowledge_library import KnowledgeLibrary

    case = CASES["case08"]
    recorder = FakeHTTPProvider(case, "task017", shared_budget=shared_budget,
                                task_order=task_order)
    temp_root = Path(tempfile.mkdtemp(prefix="task018-context-fake-"))
    try:
        db = temp_root / "knowledge.sqlite3"
        shutil.copy2(fixture_root / "case08_knowledge.sqlite3", db)
        library = KnowledgeLibrary(db)
        with ExitStack() as stack:
            stack.enter_context(patch.object(app_module, "engineering_knowledge_backend", library))
            stack.enter_context(patch.object(app_module, "FROZEN_TOOL_MODEL", FLASH_MODEL))
            stack.enter_context(patch.object(integration_module, "FROZEN_TOOL_MODEL", FLASH_MODEL))
            stack.enter_context(patch.object(planner_provider_module, "OpenAI", recorder.build_openai_client))
            stack.enter_context(patch.object(decision_provider_module, "OpenAI", recorder.build_openai_client))
            stack.enter_context(patch.object(context_provider_module, "OpenAI", recorder.build_openai_client))
            project_root = temp_root / "project"
            project_root.mkdir()
            assembled = app_module._build_engineering_project_runtime(
                EngineeringProject(root=project_root, project_name="context-probe", source="configured"))
            resolved = assembled.context_resolver.resolve(
                "它是多少秒？", [{"role": "user", "content": "刚才询问了标准重试窗口。"}])
        return {"resolver_used": resolved.resolver_used,
                "model": recorder.requests[0]["model"] if recorder.requests else None,
                "thinking": recorder.requests[0]["thinking"] if recorder.requests else None,
                "request_count": recorder.http_attempts,
                "request": recorder.requests[0] if recorder.requests else None,
                "response": recorder.responses[0] if recorder.responses else None}
    finally:
        if recorder._httpx is not None:
            recorder._httpx.close()
        _cleanup_task018_temp(temp_root, "task018-context-fake-")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Task 019 Runtime probe using the Task 018 fixture and recorder")
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--variant", required=True, choices=("b0", "b2", "hybrid", "direct_hybrid", "task017", "task020", "task021", "converged"))
    parser.add_argument("--fixture-root", required=True, type=Path)
    parser.add_argument("--knowledge-db")
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), required=True)
    parser.add_argument("--provider-mode", choices=("fake", "live"), default="fake")
    parser.add_argument("--shared-budget-db", type=Path)
    parser.add_argument("--task-order", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument("--budget-run-id")
    parser.add_argument("--diagnostic-log", type=Path)
    parser.add_argument("--max-requests", type=int, default=140)
    parser.add_argument("--max-tokens", type=int, default=500_000)
    parser.add_argument("--max-estimated-usd", type=float, default=0.35)
    parser.add_argument("--context-probe", action="store_true")
    args = parser.parse_args()
    if args.provider_mode == "live" and (not args.shared_budget_db or len(args.cases) != 1
                                           or args.task_order < 1 or not args.run_id):
        raise SystemExit("Live worker requires one case, task order, run id, and shared budget DB")
    if args.variant == "b2" and _git(args.checkout, "rev-parse", "HEAD") != "de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131":
        raise SystemExit("B2 checkout is not the frozen Task 018 B2 commit")
    shared_budget = None
    if args.shared_budget_db:
        shared_budget = SharedBudgetGate(
            args.shared_budget_db,
            run_id=args.budget_run_id or args.run_id or "task018-offline-shared-budget",
            max_requests=args.max_requests,
            max_tokens=args.max_tokens,
            max_estimated_usd=args.max_estimated_usd,
        )
    if args.context_probe:
        print(json.dumps({"mode": "fake_only", "live_mode": False,
                          "context_probe": run_context_resolver_probe(
                              args.checkout, args.fixture_root,
                              shared_budget=shared_budget, task_order=args.task_order)},
                         ensure_ascii=False, indent=2))
        return
    results = [run_case(
        args.checkout, args.variant, CASES[name], args.fixture_root,
        provider_mode=args.provider_mode, shared_budget=shared_budget,
        knowledge_db_override=args.knowledge_db,
        task_order=args.task_order, run_id=args.run_id,
        diagnostic_log=args.diagnostic_log,
    ) for name in args.cases]
    mode = "live" if args.provider_mode == "live" else "fake_only"
    print(json.dumps({"mode": mode, "live_mode": args.provider_mode == "live", "variant": args.variant,
                      "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
