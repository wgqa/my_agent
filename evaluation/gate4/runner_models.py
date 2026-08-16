"""G4-EVAL-06B-01：Gate 4 正式 Runner 数据模型（ExecutionCase / 安全事实 / RunConfig /
Recording Provider）。

只做数据模型与安全记录。不实现执行、评测、文件、CLI 逻辑（见 runner.py /
evaluator.py / scripts/run_gate4_tool_use_dev.py）。

Gold 隔离第一优先级：Phase A 模型可见的最小执行对象只有 case_id + query。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from core.tool_agent.actions import AgentDecisionCallMetadata, AgentDecisionOutcome

# 正式执行冻结的 Provider / 模型配置（本任务不调用真实模型）
FROZEN_PROVIDER = "deepseek"
FROZEN_MODEL = "deepseek-chat"
FROZEN_TEMPERATURE = 0
FROZEN_MAX_TOKENS = 600
FROZEN_MAX_RETRIES = 0
FROZEN_TIMEOUT_SECONDS = 20.0

# 冻结预算（与 ToolAgentBudget 系统冻结一致）
FROZEN_MAX_AGENT_ITERATIONS = 5
FROZEN_MAX_TOOL_CALLS = 4
FROZEN_MAX_TOOL_ERRORS = 2

# 冻结 knowledge tool 配置（沿用项目已验证配置，不因 Gate4 Dev 结果调参）
FROZEN_KNOWLEDGE_STRATEGY = "bm25"
FROZEN_KNOWLEDGE_TOP_K = 5
FROZEN_CHUNK_STRATEGY = "recursive"
FROZEN_CHUNK_SIZE = 512
FROZEN_CHUNK_OVERLAP = 64


@dataclass(frozen=True)
class Gate4ExecutionCase:
    """Phase A 模型可见的最小执行对象：只允许 case_id + query。"""

    case_id: str
    query: str

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "query": self.query}


@dataclass(frozen=True)
class DecisionSummary:
    """一条 Decision 的安全摘要：最多 iteration / action_type / tool_name /
    failure_code / call_metadata。绝不含 raw output / CoT / prompt / key。"""

    iteration: int
    action_type: str
    tool_name: Optional[str]
    failure_code: Optional[str]
    call_metadata: Optional[dict]

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "action_type": self.action_type,
            "tool_name": self.tool_name,
            "failure_code": self.failure_code,
            "call_metadata": self.call_metadata,
        }


@dataclass(frozen=True)
class Gate4ExecutionResult:
    """一个 case 的安全执行事实（Gold-free；不含任何 Gold-only 字段）。"""

    case_id: str
    status: str
    answer: Optional[str]
    reason_code: Optional[str]
    failure_code: Optional[str]
    iterations_used: int
    tool_calls_used: int
    tool_errors_used: int
    trace: tuple[dict, ...]
    decisions: tuple[DecisionSummary, ...]
    # 该 case 的 provider 聚合（安全事实）
    decision_call_count: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_latency_ms: float
    prompt_version: Optional[str]
    prompt_sha256: Optional[str]
    toolset_sha256: Optional[str]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "answer": self.answer,
            "reason_code": self.reason_code,
            "failure_code": self.failure_code,
            "iterations_used": self.iterations_used,
            "tool_calls_used": self.tool_calls_used,
            "tool_errors_used": self.tool_errors_used,
            "trace": list(self.trace),
            "decisions": [d.to_dict() for d in self.decisions],
            "provider": {
                "decision_call_count": self.decision_call_count,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_latency_ms": self.total_latency_ms,
                "prompt_version": self.prompt_version,
                "prompt_sha256": self.prompt_sha256,
                "toolset_sha256": self.toolset_sha256,
            },
        }


@dataclass(frozen=True)
class Gate4ToolUseRunConfig:
    """正式 Run 的强类型配置；canonical identity → run_id。

    不进入 identity：API key、时间、本地绝对路径、output root、对象 repr。
    """

    source_commit: str
    evaluation_set_id: str
    dataset_jsonl_sha256: str
    code_reference_commit: str
    knowledge_corpus_id: str
    knowledge_corpus_file_count: int
    provider: str
    model: str
    prompt_version: str
    prompt_sha256: str
    toolset_sha256: str
    max_agent_iterations: int = FROZEN_MAX_AGENT_ITERATIONS
    max_tool_calls: int = FROZEN_MAX_TOOL_CALLS
    max_tool_errors: int = FROZEN_MAX_TOOL_ERRORS
    knowledge_strategy: str = FROZEN_KNOWLEDGE_STRATEGY
    knowledge_top_k: int = FROZEN_KNOWLEDGE_TOP_K
    chunk_strategy: str = FROZEN_CHUNK_STRATEGY
    chunk_size: int = FROZEN_CHUNK_SIZE
    chunk_overlap: int = FROZEN_CHUNK_OVERLAP

    def __post_init__(self) -> None:
        _require_sha(self.source_commit, 40, "source_commit")
        _require_sha(self.evaluation_set_id, 12, "evaluation_set_id")
        _require_sha(self.dataset_jsonl_sha256, 64, "dataset_jsonl_sha256")
        _require_sha(self.code_reference_commit, 40, "code_reference_commit")
        _require_sha(self.knowledge_corpus_id, 12, "knowledge_corpus_id")
        if not isinstance(self.knowledge_corpus_file_count, int):
            raise TypeError("knowledge_corpus_file_count 必须是 int")
        for label in ("provider", "model", "prompt_version", "prompt_sha256",
                      "toolset_sha256", "knowledge_strategy", "chunk_strategy"):
            _require_non_empty_str(getattr(self, label), label)
        _require_sha(self.prompt_sha256, 64, "prompt_sha256")
        _require_sha(self.toolset_sha256, 64, "toolset_sha256")
        for label, value in (
            ("max_agent_iterations", self.max_agent_iterations),
            ("max_tool_calls", self.max_tool_calls),
            ("max_tool_errors", self.max_tool_errors),
            ("knowledge_top_k", self.knowledge_top_k),
            ("chunk_size", self.chunk_size),
            ("chunk_overlap", self.chunk_overlap),
        ):
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} 必须是正整数")

    def identity_payload(self) -> dict:
        """不含 run_id 的 canonical payload（避免自指）。"""
        return {
            "source_commit": self.source_commit,
            "evaluation_set_id": self.evaluation_set_id,
            "dataset_jsonl_sha256": self.dataset_jsonl_sha256,
            "code_reference_commit": self.code_reference_commit,
            "knowledge_corpus_id": self.knowledge_corpus_id,
            "knowledge_corpus_file_count": self.knowledge_corpus_file_count,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "toolset_sha256": self.toolset_sha256,
            "max_agent_iterations": self.max_agent_iterations,
            "max_tool_calls": self.max_tool_calls,
            "max_tool_errors": self.max_tool_errors,
            "knowledge_strategy": self.knowledge_strategy,
            "knowledge_top_k": self.knowledge_top_k,
            "chunk_strategy": self.chunk_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    def to_dict(self) -> dict:
        out = self.identity_payload()
        out["run_id"] = self.compute_run_id()
        return out

    def compute_run_id(self) -> str:
        canonical = json.dumps(
            self.identity_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


class RecordingDecisionProvider:
    """evaluation 层 wrapper：delegate 任意 AgentDecisionProvider，只额外记录安全事实。

    不改动 Runtime / 原 Provider；Runtime 仍只依赖原 AgentDecisionProvider Protocol。
    记录：call 安全摘要（action_type / tool_name / failure_code / call_metadata）。
    不获得 raw response / CoT / prompt / key。
    """

    def __init__(self, inner: Any) -> None:
        if not hasattr(inner, "decide"):
            raise TypeError("inner 必须实现 decide(registry, user_query, *, context)")
        self._inner = inner
        self.history: list[dict] = []
        self.call_count = 0

    @property
    def inner(self) -> Any:
        return self._inner

    def decide(
        self, registry: object, user_query: str, *, context: Sequence[Any] = ()
    ) -> AgentDecisionOutcome:
        self.call_count += 1
        outcome = self._inner.decide(registry, user_query, context=context)
        if not isinstance(outcome, AgentDecisionOutcome):
            raise TypeError("delegate 必须返回 AgentDecisionOutcome")
        self.history.append(self._summarize(outcome))
        return outcome

    @staticmethod
    def _summarize(outcome: AgentDecisionOutcome) -> dict:
        action = outcome.action
        if action is None:
            action_type = "failure"
            tool_name = None
        else:
            action_type = action.action
            tool_name = getattr(action, "tool_name", None)
        meta: Optional[dict] = None
        if outcome.call_metadata is not None:
            if not isinstance(outcome.call_metadata, AgentDecisionCallMetadata):
                raise TypeError("call_metadata 必须是 AgentDecisionCallMetadata")
            meta = outcome.call_metadata.to_dict()
        return {
            "action_type": action_type,
            "tool_name": tool_name,
            "failure_code": outcome.failure_code,
            "call_metadata": meta,
        }

    def slice_decisions(self, start: int, end: int) -> tuple[DecisionSummary, ...]:
        """按调用序号切出某 case 的 DecisionSummary（iteration 1 起）。"""
        out: list[DecisionSummary] = []
        for offset, raw in enumerate(self.history[start:end], 1):
            out.append(
                DecisionSummary(
                    iteration=offset,
                    action_type=raw["action_type"],
                    tool_name=raw["tool_name"],
                    failure_code=raw["failure_code"],
                    call_metadata=raw["call_metadata"],
                )
            )
        return tuple(out)

    @staticmethod
    def aggregate(decisions: Sequence[DecisionSummary]) -> dict:
        """该 case 的 provider 安全聚合（tokens / latency / prompt / toolset）。"""
        metas = [d.call_metadata for d in decisions if d.call_metadata is not None]
        input_tokens = _sum_optional(metas, "input_tokens")
        output_tokens = _sum_optional(metas, "output_tokens")
        latency = sum(float(m.get("latency_ms", 0.0)) for m in metas)
        last = metas[-1] if metas else {}
        return {
            "decision_call_count": len(decisions),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_latency_ms": round(latency, 6),
            "prompt_version": last.get("prompt_version"),
            "prompt_sha256": last.get("prompt_sha256"),
            "toolset_sha256": last.get("toolset_sha256"),
        }


def _sum_optional(metas: Sequence[dict], key: str) -> Optional[int]:
    values = [int(m[key]) for m in metas if m.get(key) is not None]
    if not values:
        return None
    return sum(values)


def _require_sha(value: str, length: int, label: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{label} 必须是字符串")
    if len(value) != length:
        raise ValueError(f"{label} 必须是 {length} 位小写十六进制")
    int(value, 16)


def _require_non_empty_str(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串")


__all__ = [
    "FROZEN_PROVIDER",
    "FROZEN_MODEL",
    "FROZEN_TEMPERATURE",
    "FROZEN_MAX_TOKENS",
    "FROZEN_MAX_RETRIES",
    "FROZEN_TIMEOUT_SECONDS",
    "FROZEN_MAX_AGENT_ITERATIONS",
    "FROZEN_MAX_TOOL_CALLS",
    "FROZEN_MAX_TOOL_ERRORS",
    "FROZEN_KNOWLEDGE_STRATEGY",
    "FROZEN_KNOWLEDGE_TOP_K",
    "FROZEN_CHUNK_STRATEGY",
    "FROZEN_CHUNK_SIZE",
    "FROZEN_CHUNK_OVERLAP",
    "Gate4ExecutionCase",
    "DecisionSummary",
    "Gate4ExecutionResult",
    "Gate4ToolUseRunConfig",
    "RecordingDecisionProvider",
]
