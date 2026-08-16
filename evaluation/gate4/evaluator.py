"""G4-EVAL-06B-01：Gate 4 评测器（deterministic assertions / case score / 15 项冻结指标）。

确定性断言精确语义（protocol §14/§16 冻结，不使用 LLM-as-Judge）：

- answer_nonempty    : status == completed 且 answer.strip() != ""
- answer_contains    : Unicode exact substring
- answer_contains_all: 所有指定字符串都必须 exact substring 命中
- answer_number_equals: 数字 token 提取 + Decimal 数值比较（不允许 str(expected) in
  answer，否则 84 会误命中 184）；至少支持 84 / 8 / -7 / 35 / 8192 / 12 / 512 / 8.0
- path_contains      : answer 统一 \\ → / 后做 repo-relative substring
- status_equals      : 严格比较 status

多条 assertion 为 AND。15 项指标逐字实现 protocol §8 冻结公式；zero denominator
时 value=null（不伪造 0.0），并保留 numerator / denominator。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence

from core.tool_agent import (
    ACTION_PARSE_FAILED,
    AGENT_BUDGET_EXCEEDED,
    AGENT_DUPLICATE_TOOL_CALL,
)
from evaluation.gate4.runner_models import Gate4ExecutionResult
from evaluation.gate4.schema import CompletionAssertion, Gate4ToolUseCase

_NUMBER_TOKEN_RE = re.compile(r"-?\d+(?:\.\d+)?")

# 15 项正式预注册指标（protocol §8）
METRIC_NAMES = (
    "first_action_accuracy",
    "first_tool_accuracy",
    "required_tool_coverage",
    "task_completion_rate",
    "final_answer_correct_rate",
    "unnecessary_tool_call_rate",
    "forbidden_tool_call_rate",
    "duplicate_tool_call_rate",
    "termination_accuracy",
    "average_agent_iterations",
    "average_tool_calls",
    "tool_error_rate",
    "budget_stop_rate",
    "parse_failure_rate",
    "allowed_sequence_match_rate",
)


@dataclass(frozen=True)
class CaseScore:
    """一个 case 的评测事实层（不只产 pass=true，便于事后错误分析）。"""

    case_id: str
    category: str
    expected_terminal: str
    expected_first_action: str
    expected_first_tool: Optional[str]
    expected_first_tools: tuple[str, ...]
    required_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    allowed_tool_sequences: tuple[tuple[str, ...], ...]
    actual_first_action: str
    actual_first_tool: Optional[str]
    executed_tool_sequence: tuple[str, ...]
    required_tools_hit: int
    required_tools_total: int
    forbidden_tool_used: bool
    unnecessary_tool_call_count: int
    assertions_passed: bool
    terminal_correct: bool
    termination_correct: bool
    allowed_sequence_match: Optional[bool]
    status: str
    reason_code: Optional[str]
    failure_code: Optional[str]
    iterations: int
    tool_calls: int
    tool_errors: int

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "expected_terminal": self.expected_terminal,
            "expected_first_action": self.expected_first_action,
            "expected_first_tool": self.expected_first_tool,
            "expected_first_tools": list(self.expected_first_tools),
            "required_tools": list(self.required_tools),
            "forbidden_tools": list(self.forbidden_tools),
            "allowed_tool_sequences": [
                list(s) for s in self.allowed_tool_sequences
            ],
            "actual_first_action": self.actual_first_action,
            "actual_first_tool": self.actual_first_tool,
            "executed_tool_sequence": list(self.executed_tool_sequence),
            "required_tools_hit": self.required_tools_hit,
            "required_tools_total": self.required_tools_total,
            "forbidden_tool_used": self.forbidden_tool_used,
            "unnecessary_tool_call_count": self.unnecessary_tool_call_count,
            "assertions_passed": self.assertions_passed,
            "terminal_correct": self.terminal_correct,
            "termination_correct": self.termination_correct,
            "allowed_sequence_match": self.allowed_sequence_match,
            "status": self.status,
            "reason_code": self.reason_code,
            "failure_code": self.failure_code,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
        }


# ---------------------------------------------------------------------- #
# Deterministic assertions
# ---------------------------------------------------------------------- #


def evaluate_assertion(
    assertion: CompletionAssertion, result: Gate4ExecutionResult
) -> bool:
    """按协议 §16 精确语义评估一条确定性 assertion。"""
    a_type = assertion.type
    if a_type == "answer_nonempty":
        return result.status == "completed" and bool(
            result.answer and result.answer.strip()
        )
    if a_type == "answer_contains":
        return bool(result.answer) and assertion.value in result.answer
    if a_type == "answer_contains_all":
        return bool(result.answer) and all(
            v in result.answer for v in assertion.value
        )
    if a_type == "answer_number_equals":
        return _number_matches(result.answer, assertion.value)
    if a_type == "path_contains":
        normalized = (result.answer or "").replace("\\", "/")
        return assertion.value in normalized
    if a_type == "status_equals":
        return result.status == assertion.value
    raise ValueError(f"未知断言类型：{a_type!r}")


def _number_matches(answer: Optional[str], expected: object) -> bool:
    """数字 token 提取 + Decimal 数值比较；绝不使用 str(expected) in answer。"""
    if not answer:
        return False
    expected_decimal = Decimal(str(expected))
    for token in _NUMBER_TOKEN_RE.findall(answer):
        if Decimal(token) == expected_decimal:
            return True
    return False


def assertions_pass(
    assertions: Sequence[CompletionAssertion], result: Gate4ExecutionResult
) -> bool:
    """多条 assertion 为 AND。"""
    return all(evaluate_assertion(a, result) for a in assertions)


# ---------------------------------------------------------------------- #
# Case score
# ---------------------------------------------------------------------- #


def executed_tool_sequence(result: Gate4ExecutionResult) -> tuple[str, ...]:
    """真正执行过的 Tool 顺序（来自 tool_observation trace）。

    Runtime 对 duplicate/budget 硬停止不发射 tool_observation，因此被 duplicate
    guard 拦截的第二次重复调用不会进入 executed sequence（protocol §17）。
    """
    return tuple(
        e["tool_name"]
        for e in result.trace
        if e.get("event_type") == "tool_observation" and e.get("tool_name")
    )


def evaluate_case(case: Gate4ToolUseCase, result: Gate4ExecutionResult) -> CaseScore:
    seq = executed_tool_sequence(result)
    seq_set = set(seq)

    first_decision = result.decisions[0] if result.decisions else None
    actual_first_action = (
        first_decision.action_type if first_decision is not None else "none"
    )
    actual_first_tool: Optional[str] = None
    if first_decision is not None and first_decision.action_type == "tool_call":
        actual_first_tool = first_decision.tool_name

    required_set = set(case.required_tools)
    required_tools_hit = sum(1 for t in case.required_tools if t in seq_set)
    forbidden_tool_used = bool(set(case.forbidden_tools) & seq_set)
    unnecessary_tool_call_count = sum(
        1
        for t in seq
        if t not in required_set and t not in set(case.forbidden_tools)
    )

    terminal_correct = result.status == case.expected_terminal
    termination_correct = terminal_correct and (
        result.status != "refused"
        or (result.reason_code in case.allowed_refuse_reason_codes)
    )

    allowed_match: Optional[bool] = None
    if case.allowed_tool_sequences:
        allowed_match = any(
            seq == allowed_seq
            for allowed_seq in case.allowed_tool_sequences
        )

    return CaseScore(
        case_id=case.case_id,
        category=case.category,
        expected_terminal=case.expected_terminal,
        expected_first_action=case.expected_first_action,
        expected_first_tool=case.expected_first_tool,
        expected_first_tools=case.expected_first_tools,
        required_tools=case.required_tools,
        forbidden_tools=case.forbidden_tools,
        allowed_tool_sequences=case.allowed_tool_sequences,
        actual_first_action=actual_first_action,
        actual_first_tool=actual_first_tool,
        executed_tool_sequence=seq,
        required_tools_hit=required_tools_hit,
        required_tools_total=len(case.required_tools),
        forbidden_tool_used=forbidden_tool_used,
        unnecessary_tool_call_count=unnecessary_tool_call_count,
        assertions_passed=assertions_pass(case.completion_assertions, result),
        terminal_correct=terminal_correct,
        termination_correct=termination_correct,
        allowed_sequence_match=allowed_match,
        status=result.status,
        reason_code=result.reason_code,
        failure_code=result.failure_code,
        iterations=result.iterations_used,
        tool_calls=result.tool_calls_used,
        tool_errors=result.tool_errors_used,
    )


# ---------------------------------------------------------------------- #
# 15 项冻结指标（protocol §8 逐字公式）
# ---------------------------------------------------------------------- #


def _rate(numerator: int, denominator: int) -> dict:
    """保存 numerator / denominator / value；denominator==0 时 value=null。"""
    if denominator == 0:
        return {"numerator": numerator, "denominator": 0, "value": None}
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6),
    }


def first_tool_correct(score: CaseScore) -> bool:
    """first_tool 正确：multi-step 用 actual ∈ expected_first_tools；否则精确相等。"""
    if score.category == "multi_step":
        return score.actual_first_tool in set(score.expected_first_tools)
    return score.actual_first_tool == score.expected_first_tool


def compute_metrics(scores: Sequence[CaseScore]) -> dict:
    """15 项正式指标；逐字实现 protocol §8 冻结 numerator/denominator。"""
    n = len(scores)
    metrics: dict[str, dict] = {}

    metrics["first_action_accuracy"] = _rate(
        sum(1 for s in scores if s.actual_first_action == s.expected_first_action), n
    )

    tool_call_cases = [s for s in scores if s.expected_first_action == "tool_call"]
    metrics["first_tool_accuracy"] = _rate(
        sum(1 for s in tool_call_cases if first_tool_correct(s)),
        len(tool_call_cases),
    )

    metrics["required_tool_coverage"] = _rate(
        sum(s.required_tools_hit for s in scores),
        sum(s.required_tools_total for s in scores),
    )

    metrics["task_completion_rate"] = _rate(
        sum(1 for s in scores if s.termination_correct and s.assertions_passed), n
    )

    completed = [s for s in scores if s.expected_terminal == "completed"]
    metrics["final_answer_correct_rate"] = _rate(
        sum(1 for s in completed if s.assertions_passed), len(completed)
    )

    total_tool_calls = sum(s.tool_calls for s in scores)
    metrics["unnecessary_tool_call_rate"] = _rate(
        sum(s.unnecessary_tool_call_count for s in scores), total_tool_calls
    )

    metrics["forbidden_tool_call_rate"] = _rate(
        sum(1 for s in scores if s.forbidden_tool_used), n
    )

    metrics["duplicate_tool_call_rate"] = _rate(
        sum(1 for s in scores if s.failure_code == AGENT_DUPLICATE_TOOL_CALL), n
    )

    metrics["termination_accuracy"] = _rate(
        sum(1 for s in scores if s.termination_correct), n
    )

    metrics["average_agent_iterations"] = _rate(
        sum(s.iterations for s in scores), n
    )

    metrics["average_tool_calls"] = _rate(sum(s.tool_calls for s in scores), n)

    metrics["tool_error_rate"] = _rate(
        sum(s.tool_errors for s in scores), total_tool_calls
    )

    metrics["budget_stop_rate"] = _rate(
        sum(1 for s in scores if s.reason_code == AGENT_BUDGET_EXCEEDED), n
    )

    metrics["parse_failure_rate"] = _rate(
        sum(1 for s in scores if s.failure_code == ACTION_PARSE_FAILED), n
    )

    multi_step = [s for s in scores if s.category == "multi_step"]
    metrics["allowed_sequence_match_rate"] = _rate(
        sum(1 for s in multi_step if s.allowed_sequence_match is True),
        len(multi_step),
    )

    return metrics


__all__ = [
    "METRIC_NAMES",
    "CaseScore",
    "evaluate_assertion",
    "assertions_pass",
    "executed_tool_sequence",
    "evaluate_case",
    "first_tool_correct",
    "compute_metrics",
]
