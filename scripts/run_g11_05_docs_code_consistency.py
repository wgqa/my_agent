"""Run the fixed G11-05 Docs <-> Code Consistency cases.

The runner evaluates the evidence shape of document-versus-current-code
comparisons.  It records public response fields, safe trace data, and bounded
project evidence, but never auto-scores the consistency label or correction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.run_g11_03_change_impact import (
    MAX_PARSE_REPAIRS,
    TOOLSET_SHA256,
    _get_json,
    _knowledge_url,
    _post_json,
    _safe_trace,
    _sanitize_for_artifact,
    _tool_sequence,
    validate_artifact_safety,
    validate_source_commit as _validate_source_commit,
)
from scripts.run_g11_04_diagnosis_config import (
    validate_engineering_knowledge_status,
    validate_engineering_project,
)


PROJECT_IDENTITY = "my_agent_repository"
WORKFLOW_ID = "g11-05-docs-code-consistency-v1"
KNOWLEDGE_CORPUS_ID = "870e5864df67"
PRODUCTION_PROMPT_VERSION = "engineering_agent_decision_prompt_v2"
PRODUCTION_PROMPT_SHA256 = (
    "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107"
)
KNOWN_PROMPT_IDENTITIES = {
    PRODUCTION_PROMPT_VERSION: PRODUCTION_PROMPT_SHA256,
}
REPAIR_PROMPT_VERSION = "engineering_action_repair_prompt_v1"
REPAIR_PROMPT_SHA256 = (
    "958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636"
)
BUDGET = {
    "max_agent_iterations": 5,
    "max_tool_calls": 4,
    "max_tool_errors": 2,
}
REGISTRY_SIZE = 7
MAX_OUTPUT_TOKENS = 1200
PROVIDER_NETWORK_RETRIES = 0
EXPECTED_PROJECT_NAME = "my_agent"
EXPECTED_PROJECT_SOURCE = "default_repo"

REQUIRED_TOOLS = ("code_search", "read_project_context")
FORBIDDEN_TOOLS = (
    "knowledge_search",
    "calculator",
    "changed_files",
    "git_diff",
    "find_tests",
)

EXPECTED_CASE_IDS = ("DOC01", "DOC02", "DOC03", "DOC04")
EXPECTED_CASE_LABELS = {
    "DOC01": "OUTDATED / INCONSISTENT",
    "DOC02": "OUTDATED / INCOMPLETE",
    "DOC03": "CONSISTENT",
    "DOC04": "CONSISTENT",
}
EXPECTED_CASE_SHAPE = {
    "DOC01": {
        "gold_label": "OUTDATED / INCONSISTENT",
        "document_source_paths": ("README.md",),
        "code_source_paths": (
            "core/tool_agent/default_tools.py",
            "core/tool_agent/integration.py",
        ),
        "doc_claim_anchors": (
            "knowledge_search",
            "code_search",
            "calculator",
        ),
    },
    "DOC02": {
        "gold_label": "OUTDATED / INCOMPLETE",
        "document_source_paths": ("README.md",),
        "code_source_paths": ("api/app.py",),
        "doc_claim_anchors": ("/tool-agent/query",),
    },
    "DOC03": {
        "gold_label": "CONSISTENT",
        "document_source_paths": ("README.md",),
        "code_source_paths": (
            "core/tool_agent/runtime_models.py",
            "core/tool_agent/integration.py",
        ),
        "doc_claim_anchors": (
            "5 iterations",
            "4 tool calls",
            "2 tool errors",
        ),
    },
    "DOC04": {
        "gold_label": "CONSISTENT",
        "document_source_paths": ("README.md",),
        "code_source_paths": (
            "api/app.py",
            "core/tool_agent/runtime_models.py",
        ),
        "doc_claim_anchors": ("Safe Trace", "Chain-of-Thought"),
    },
}

_PROMPT_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _obligation(identifier: str, description: str) -> dict[str, str]:
    return {"id": identifier, "description": description}


def _case(
    case_id: str,
    question: str,
    obligations: list[dict[str, str]],
) -> dict[str, Any]:
    shape = EXPECTED_CASE_SHAPE[case_id]
    return {
        "case_id": case_id,
        "question": question,
        "gold_label": shape["gold_label"],
        "document_source_paths": list(shape["document_source_paths"]),
        "code_source_paths": list(shape["code_source_paths"]),
        "doc_claim_anchors": list(shape["doc_claim_anchors"]),
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": obligations,
    }


CASES = (
    _case(
        "DOC01",
        (
            "README 当前把 Structured Tool Agent 的真实只读 Tool 限定为 "
            "knowledge_search、code_search、calculator，并在 Safety 中重复该三项 registry。"
            "请先读取 README 的实际 claim，再读取当前 default_tools registry 与 integration builder，"
            "判断文档是否仍准确、列出当前七个 Tool、解释新增 Tool 的 bounded read-only 安全边界，"
            "并给出不改历史 Gate 4 口径的文档维护建议。"
        ),
        [
            _obligation("D1", "README 确实把当前真实只读 Tool 描述为 knowledge_search、code_search、calculator。"),
            _obligation("C1", "build_readonly_tool_registry 当前注册七个 Tool。"),
            _obligation("C2", "build_tool_agent_runtime 使用该 seven-tool registry。"),
            _obligation("J1", "README 的当前 Tool 只有三个的声明已经过时。"),
            _obligation("J2", "read_project_context、changed_files、git_diff、find_tests 仍是 bounded read-only Tool。"),
            _obligation("J3", "不得声称存在 arbitrary shell Tool。"),
            _obligation("R1", "更新当前 Tool list/product surface，但不改历史 Gate 4 evidence 口径。"),
        ],
    ),
    _case(
        "DOC02",
        (
            "README 当前按 Basic RAG、Agentic RAG、Structured Tool Agent 三种模式描述产品，"
            "且 Public API 表没有 Engineering Agent。请读取文档 claim 与当前 api.app，列出缺少的"
            "Engineering 公开入口，并说明 README 已列出的 legacy/product endpoint 仍然存在。"
            "不要把文档摘要当作 API implementation evidence。"
        ),
        [
            _obligation("D1", "README 当前三种运行模式包含 /query、/agent/query、/tool-agent/query。"),
            _obligation("D2", "README Public API table 没有 Engineering product entry。"),
            _obligation("C1", "api.app 当前存在 GET /project、POST /engineering/query、GET /engineering/knowledge。"),
            _obligation("C2", "capabilities 的 features 包含 engineering_agent 状态。"),
            _obligation("J1", "README product/API surface incomplete。"),
            _obligation("J2", "README 已列出的 /query、/agent/query、/tool-agent/query 仍然存在。"),
            _obligation("J3", "/project、/engineering/knowledge、/engineering/query 分别具有公开入口语义。"),
            _obligation("R1", "增加 Engineering Agent 入口，不删除仍存在的 legacy/product endpoint。"),
        ],
    ),
    _case(
        "DOC03",
        (
            "README Safety 声明 Tool Agent 使用系统控制的 5 iterations、4 tool calls、2 tool errors。"
            "请读取 README 与当前 runtime_models/integration 实现，核对默认预算、冻结上限、builder"
            "是否允许调用方提高预算，以及 trusted remaining_* control metadata 是否能改变 hard budget。"
            "若一致，应给出 bounded no-change recommendation。"
        ),
        [
            _obligation("D1", "README 声明 5/4/2 是 system-controlled budget。"),
            _obligation("C1", "ToolAgentBudget 默认值是 max_agent_iterations=5、max_tool_calls=4、max_tool_errors=2。"),
            _obligation("C2", "ToolAgentBudget 拒绝超过冻结 cap 的值。"),
            _obligation("C3", "build_tool_agent_runtime 没有向调用方暴露任意 budget 参数。"),
            _obligation("C4", "builder 最终固定使用 ToolAgentBudget()。"),
            _obligation("J1", "README budget claim 与 current implementation 一致。"),
            _obligation("J2", "DecisionControlState / remaining_* 是 trusted read-only control metadata。"),
            _obligation("J3", "模型看到剩余预算不等于可以增加预算。"),
            _obligation("R1", "当前无需因该 claim 修改 README。"),
        ],
    ),
    _case(
        "DOC04",
        (
            "README 声明 Safe Trace 只记录受控执行事实，不暴露 private Chain-of-Thought、Prompt、"
            "raw model output、credentials 或 local filesystem path。请读取 README 与当前 api.app/runtime_models"
            "的 trace serialization，核对 Engineering trace 是否比 legacy trace 多字段，以及这些字段是否"
            "仍属于安全结构化 diagnostics。不要把 public trace contract 扩大为整个进程永远不持有模型数据。"
        ),
        [
            _obligation("D1", "README 声明 Safe Trace 不暴露 CoT、Prompt、raw output、credentials、local path。"),
            _obligation("C1", "LEGACY_TOOL_AGENT_TRACE_ALLOWED_KEYS 只包含受控执行 metadata。"),
            _obligation("C2", "ENGINEERING_TRACE_ALLOWED_KEYS 在 legacy whitelist 上增加四个 diagnostics 字段。"),
            _obligation("C3", "_safe_trace 只投影 allowlisted keys。"),
            _obligation("C4", "RuntimeTraceEvent 明确 Trace != CoT，并排除 raw output、CoT、Prompt、key、traceback、敏感路径。"),
            _obligation("J1", "README 的核心 Safe Trace security claim 当前一致。"),
            _obligation("J2", "Engineering 多出的字段是结构化 diagnostics，不是 private reasoning。"),
            _obligation("J3", "结论范围限于 public/runtime trace contract。"),
            _obligation("R1", "当前无需因该 claim 修改 README；可选补充 Engineering diagnostics 字段说明。"),
        ],
    ),
)


def validate_case_identities(
    cases: tuple[dict[str, Any], ...] = CASES,
    *,
    git_root: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Validate fixed case identity and source boundaries only."""

    if tuple(case.get("case_id") for case in cases) != EXPECTED_CASE_IDS:
        raise ValueError("G11-05 case identity drifted")
    for case in cases:
        case_id = case.get("case_id")
        expected = EXPECTED_CASE_SHAPE.get(case_id)
        if expected is None:
            raise ValueError("G11-05 case identity drifted")
        if case.get("gold_label") != expected["gold_label"]:
            raise ValueError(f"{case_id} Gold label identity drifted")
        for field in ("document_source_paths", "code_source_paths", "doc_claim_anchors"):
            if tuple(case.get(field) or ()) != expected[field]:
                raise ValueError(f"{case_id} {field} identity drifted")
        for field in ("document_source_paths", "code_source_paths"):
            paths = case.get(field) or ()
            if not paths or any(
                type(path) is not str
                or not path
                or path.startswith(("/", "\\"))
                or ".." in Path(path).parts
                for path in paths
            ):
                raise ValueError(f"{case_id} source path is not repo-relative")
            if git_root is not None:
                root = Path(git_root)
                if any(not (root / Path(path.replace("/", "\\"))).is_file() for path in paths):
                    raise ValueError(f"{case_id} source path is missing from git_root")
    validate_gold_label_distribution(cases)
    return cases


def validate_gold_label_distribution(
    cases: tuple[dict[str, Any], ...] = CASES,
) -> dict[str, int]:
    labels = [case.get("gold_label") for case in cases]
    counts = {
        "consistent": labels.count("CONSISTENT"),
        "outdated_or_incomplete": sum(
            label in {"OUTDATED / INCONSISTENT", "OUTDATED / INCOMPLETE"}
            for label in labels
        ),
    }
    if counts != {"consistent": 2, "outdated_or_incomplete": 2}:
        raise ValueError("G11-05 Gold label distribution must be 2 stale/incomplete and 2 consistent")
    return counts


def validate_required_and_forbidden_tools() -> tuple[tuple[str, ...], tuple[str, ...]]:
    if REQUIRED_TOOLS != ("code_search", "read_project_context"):
        raise ValueError("G11-05 required tool contract drifted")
    expected_forbidden = {
        "knowledge_search",
        "calculator",
        "changed_files",
        "git_diff",
        "find_tests",
    }
    if set(FORBIDDEN_TOOLS) != expected_forbidden:
        raise ValueError("G11-05 forbidden tool contract drifted")
    if set(REQUIRED_TOOLS) & set(FORBIDDEN_TOOLS):
        raise ValueError("G11-05 required and forbidden tools overlap")
    return REQUIRED_TOOLS, FORBIDDEN_TOOLS


def validate_source_commit(value: object, *, git_root: str | Path) -> str:
    return _validate_source_commit(value, git_root=git_root)


def validate_prompt_identity(version: object, sha256: object) -> tuple[str, str]:
    if type(version) is not str or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("prompt_version must be a bounded non-empty identifier")
    if version not in KNOWN_PROMPT_IDENTITIES:
        raise ValueError("G11-05 requires the production Engineering v2 prompt")
    if type(sha256) is not str or not _SHA256_RE.fullmatch(sha256):
        raise ValueError("prompt_sha256 must be exactly 64 hexadecimal characters")
    normalized = sha256.lower()
    if normalized != KNOWN_PROMPT_IDENTITIES[version]:
        raise ValueError("prompt_version and prompt_sha256 do not match")
    return version, normalized


def validate_repair_prompt_identity(version: object, sha256: object) -> tuple[str, str]:
    if type(version) is not str or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("repair_prompt_version must be a bounded non-empty identifier")
    if version != REPAIR_PROMPT_VERSION:
        raise ValueError("repair_prompt_version is not the supported identity")
    if type(sha256) is not str or not _SHA256_RE.fullmatch(sha256):
        raise ValueError("repair_prompt_sha256 must be exactly 64 hexadecimal characters")
    normalized = sha256.lower()
    if normalized != REPAIR_PROMPT_SHA256:
        raise ValueError("repair_prompt_version and repair_prompt_sha256 do not match")
    return version, normalized


def _project_url(query_url: str) -> str:
    parsed = urllib.parse.urlsplit(query_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("engineering query URL must be an absolute HTTP URL")
    path = parsed.path.rstrip("/")
    suffix = "/engineering/query"
    if not path.endswith(suffix):
        raise ValueError("engineering query URL must end with /engineering/query")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path[: -len(suffix)] + "/project", "", "")
    )


def validate_formal_environment(
    query_url: str,
    *,
    knowledge_url: str | None = None,
    project_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Verify the same public Knowledge and Project preflight as G11-04."""

    knowledge_status = validate_engineering_knowledge_status(
        _get_json(knowledge_url or _knowledge_url(query_url))
    )
    project_binding = validate_engineering_project(
        _get_json(project_url or _project_url(query_url))
    )
    return knowledge_status, project_binding


def _validate_run_id(value: object) -> str:
    if type(value) is not str or not _RUN_ID_RE.fullmatch(value):
        raise ValueError("run_id must be a bounded path-safe identifier")
    return value


def _evidence_items(response: dict[str, Any]) -> list[Any]:
    evidence = response.get("evidence")
    return evidence if isinstance(evidence, list) else []


def _evidence_paths(evidence: list[Any], *, kind_prefix: str | None = None) -> set[str]:
    return {
        item["path"]
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and (kind_prefix is None or item.get("kind", "").startswith(kind_prefix))
    }


def _evidence_kind_present(evidence: list[Any], kind: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("kind") == kind for item in evidence
    )


def doc_claim_visible(evidence: list[Any], anchors: list[str] | tuple[str, ...]) -> bool:
    """Diagnostic-only signal that a read document snippet contains its anchor."""

    snippets = [
        item.get("snippet", "")
        for item in evidence
        if isinstance(item, dict)
        and item.get("kind") == "project_doc"
        and isinstance(item.get("snippet"), str)
    ]
    return any(
        anchor.casefold() in snippet.casefold()
        for anchor in anchors
        for snippet in snippets
    )


_CODE_STRUCTURE_PATTERNS = (
    re.compile(r"(?m)^\s*(?:async\s+)?def\s+[A-Za-z_]\w*\s*\("),
    re.compile(r"(?m)^\s*@(?:app|router)\.[A-Za-z_]+\("),
    re.compile(r"(?m)^\s*[A-Z][A-Z0-9_]*\s*=\s*(?:frozenset|\(|\[|\{)"),
    re.compile(r"(?m)^\s*\w+\.(?:register|append)\("),
    re.compile(r"(?m)^\s*(?:class|@dataclass)\b"),
    re.compile(r"(?m)^\s*(?:if|elif|else\s*:|raise|return|try\s*:|except)\b"),
)


def code_behavior_visible(evidence: list[Any]) -> bool:
    """Conservative structural signal; never a consistency correctness score."""

    for item in evidence:
        if not isinstance(item, dict) or item.get("kind") != "project_code":
            continue
        snippet = item.get("snippet")
        if isinstance(snippet, str) and any(
            pattern.search(snippet) for pattern in _CODE_STRUCTURE_PATTERNS
        ):
            return True
    return False


def _project_source_hit(expected: list[str], observed: set[str]) -> bool:
    return bool(expected) and set(expected).issubset(observed)


def _provider_calls(trace: list[dict[str, Any]]) -> int:
    return sum(
        event.get("provider_call_count")
        for event in trace
        if isinstance(event.get("provider_call_count"), int)
        and not isinstance(event.get("provider_call_count"), bool)
        and event.get("provider_call_count") >= 0
    )


def _parse_categories(trace: list[dict[str, Any]]) -> list[str]:
    return [
        event["parse_failure_category"]
        for event in trace
        if isinstance(event.get("parse_failure_category"), str)
    ]


def _normalize_case(
    case: dict[str, Any],
    response: dict[str, Any],
    elapsed_ms: float,
    git_root: str | Path,
) -> dict[str, Any]:
    raw_trace = _safe_trace(response.get("trace"))
    trace = _sanitize_for_artifact(raw_trace, git_root)
    sequence = _tool_sequence(trace)
    raw_evidence = _evidence_items(response)
    evidence = _sanitize_for_artifact(raw_evidence, git_root)
    evidence_kinds = _sanitize_for_artifact(
        [
            item["kind"]
            for item in raw_evidence
            if isinstance(item, dict) and isinstance(item.get("kind"), str)
        ],
        git_root,
    )
    project_paths = _evidence_paths(raw_evidence, kind_prefix="project_")
    document_source_hit = _project_source_hit(
        case["document_source_paths"], project_paths
    )
    code_source_hit = _project_source_hit(case["code_source_paths"], project_paths)
    doc_evidence = _evidence_kind_present(raw_evidence, "project_doc")
    code_evidence = _evidence_kind_present(raw_evidence, "project_code")
    doc_code_pair = doc_evidence and code_evidence
    parse_categories = _parse_categories(trace)
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "gold_label": case["gold_label"],
        "document_source_paths": list(case["document_source_paths"]),
        "code_source_paths": list(case["code_source_paths"]),
        "doc_claim_anchors": list(case["doc_claim_anchors"]),
        "gold_obligations": case["obligations"],
        "status": _sanitize_for_artifact(response.get("status"), git_root),
        "reason_code": _sanitize_for_artifact(response.get("reason_code"), git_root),
        "failure_code": _sanitize_for_artifact(response.get("failure_code"), git_root),
        "iterations": response.get("iterations_used"),
        "tool_calls": response.get("tool_calls_used"),
        "tool_errors": response.get("tool_errors_used"),
        "iterations_used": response.get("iterations_used"),
        "tool_calls_used": response.get("tool_calls_used"),
        "tool_errors_used": response.get("tool_errors_used"),
        "tool_sequence": sequence,
        "evidence_kinds": evidence_kinds,
        "evidence": evidence,
        "answer": _sanitize_for_artifact(response.get("answer"), git_root),
        "provider_calls_total": _provider_calls(trace),
        "repair_attempted": any(
            event.get("repair_attempted") is True for event in trace
        ),
        "repair_succeeded": any(
            event.get("repair_succeeded") is True for event in trace
        ),
        "initial_parse_categories": parse_categories,
        "project_doc_evidence": doc_evidence,
        "project_code_evidence": code_evidence,
        "doc_code_pair": doc_code_pair,
        "doc_code_pair_evidence": doc_code_pair,
        "multi_file_evidence": len(project_paths) >= 2,
        "doc_claim_visible": doc_claim_visible(
            raw_evidence, case["doc_claim_anchors"]
        ),
        "code_behavior_visible": code_behavior_visible(raw_evidence),
        "document_source_hit": document_source_hit,
        "code_source_hit": code_source_hit,
        "expected_source_pair": document_source_hit and code_source_hit,
        "source_pair_observed": document_source_hit and code_source_hit,
        "latency_ms": round(elapsed_ms, 2),
        "required_tools": list(case["required"]),
        "forbidden_tools": list(case["forbidden"]),
        "gold_correctness_auto_scored": False,
        "claim_grounding_auto_scored": False,
    }


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_count = len(cases)
    completed = sum(item.get("status") == "completed" for item in cases)
    tool_sequences = [item.get("tool_sequence") or [] for item in cases]
    required_coverage = {
        tool: sum(tool in sequence for sequence in tool_sequences)
        for tool in REQUIRED_TOOLS
    }
    total_tool_calls = sum(len(sequence) for sequence in tool_sequences)
    forbidden_calls = sum(
        sum(tool in FORBIDDEN_TOOLS for tool in sequence)
        for sequence in tool_sequences
    )
    non_target_calls = sum(
        sum(tool not in REQUIRED_TOOLS for tool in sequence)
        for sequence in tool_sequences
    )

    def count_flag(name: str, fallback: Any = False) -> int:
        return sum(item.get(name, fallback) is True for item in cases)

    result = {
        "case_count": case_count,
        "completed_cases": completed,
        "completion_rate": completed / case_count if case_count else 0,
        "code_search_coverage": required_coverage["code_search"],
        "read_project_context_coverage": required_coverage[
            "read_project_context"
        ],
        "required_tool_coverage": required_coverage,
        "required_tool_coverage_rate": (
            sum(required_coverage.values()) / (len(REQUIRED_TOOLS) * case_count)
            if case_count
            else 0
        ),
        "project_doc_evidence_cases": count_flag("project_doc_evidence"),
        "project_code_evidence_cases": count_flag("project_code_evidence"),
        "doc_code_pair_cases": count_flag("doc_code_pair"),
        "doc_code_pair_rate": count_flag("doc_code_pair") / case_count if case_count else 0,
        "multi_file_evidence_cases": count_flag("multi_file_evidence"),
        "doc_claim_visible_cases": count_flag("doc_claim_visible"),
        "code_behavior_visible_cases": count_flag("code_behavior_visible"),
        "document_source_hit_cases": count_flag("document_source_hit"),
        "code_source_hit_cases": count_flag("code_source_hit"),
        "expected_source_pair_cases": count_flag("expected_source_pair"),
        "source_pair_observed_cases": count_flag("source_pair_observed"),
        "forbidden_tool_calls": forbidden_calls,
        "forbidden_tool_call_rate": (
            forbidden_calls / total_tool_calls if total_tool_calls else 0
        ),
        "non_target_tool_calls": non_target_calls,
        "non_target_tool_call_rate": (
            non_target_calls / total_tool_calls if total_tool_calls else 0
        ),
        "avg_tool_calls": total_tool_calls / case_count if case_count else 0,
        "avg_iterations": (
            sum(item.get("iterations") or 0 for item in cases) / case_count
            if case_count
            else 0
        ),
        "evidence_count": sum(len(item.get("evidence") or []) for item in cases),
        "failed_cases": sum(item.get("status") == "failed" for item in cases),
        "refused_cases": sum(item.get("status") == "refused" for item in cases),
        "provider_calls_total": sum(
            item.get("provider_calls_total") or 0 for item in cases
        ),
        "parse_failure_cases": sum(
            item.get("failure_code") == "ACTION_PARSE_FAILED" for item in cases
        ),
        "initial_parse_failure_cases": sum(
            bool(item.get("initial_parse_categories")) for item in cases
        ),
        "initial_parse_categories": [
            category
            for item in cases
            for category in item.get("initial_parse_categories") or []
        ],
        "repair_attempted_cases": sum(
            item.get("repair_attempted") is True for item in cases
        ),
        "repair_succeeded_cases": sum(
            item.get("repair_succeeded") is True for item in cases
        ),
        "gold_correctness_auto_scored": False,
        "claim_grounding_auto_scored": False,
        "source_pair_diagnostic_only": True,
    }
    for name in (
        "doc_code_pair_rate",
        "document_source_hit_cases",
        "code_source_hit_cases",
        "expected_source_pair_cases",
    ):
        result[f"{name}_diagnostic_only"] = True
    return result


def _write_report(
    path: Path,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> None:
    lines = [
        "# G11-05 Docs <-> Code Consistency Run",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- source_commit: `{manifest['source_commit']}`",
        f"- endpoint: `{manifest['endpoint']}`",
        f"- workflow: `{manifest['workflow']}`",
        f"- prompt: `{manifest['prompt_version']}` / `{manifest['prompt_sha256']}`",
        f"- repair: `{manifest['repair_prompt_version']}` / `{manifest['repair_prompt_sha256']}`",
        f"- cap/budget/registry: `{manifest['max_output_tokens']}` / `5/4/2` / `{manifest['registry_size']}`",
        f"- required tools: `{', '.join(manifest['required_tools'])}`",
        f"- forbidden tools: `{', '.join(manifest['forbidden_tools'])}`",
        "- consistency label and correction are not automatically scored; manual Gold review is required.",
        "- document/code source hits and evidence shape are diagnostic only.",
        "",
        "## Metrics",
        "",
        "```json",
        json.dumps(metrics, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Cases",
        "",
    ]
    for item in cases:
        lines.extend(
            [
                f"### {item['case_id']}",
                "",
                f"- Gold label: `{item['gold_label']}`",
                f"- document sources: `{', '.join(item['document_source_paths'])}`",
                f"- code sources: `{', '.join(item['code_source_paths'])}`",
                f"- source hits: document=`{item.get('document_source_hit', False)}`, code=`{item.get('code_source_hit', False)}`, pair=`{item.get('expected_source_pair', False)}`",
                f"- claim/behavior visible: document=`{item.get('doc_claim_visible', False)}`, code=`{item.get('code_behavior_visible', False)}`",
                f"- status: `{item['status']}`",
                f"- reason/failure: `{item['reason_code']}` / `{item['failure_code']}`",
                f"- provider calls/repair: `{item['provider_calls_total']}` / `{item['repair_attempted']}` / `{item['repair_succeeded']}`",
                f"- tool sequence: `{' -> '.join(item['tool_sequence']) or '(none)'}`",
                f"- evidence shape: `{', '.join(item.get('evidence_kinds') or []) or '(none)'}`; doc-code pair=`{item.get('doc_code_pair', False)}`; multi-file=`{item.get('multi_file_evidence', False)}`",
                f"- iterations/tools/errors: `{item['iterations']}` / `{item['tool_calls']}` / `{item['tool_errors']}`",
                f"- Gold obligations: `{', '.join(obligation['id'] for obligation in item['gold_obligations'])}`",
                "",
                "#### Gold obligations",
                "",
                "```json",
                json.dumps(item["gold_obligations"], ensure_ascii=False, indent=2),
                "```",
                "",
                "#### Final answer",
                "",
                item["answer"] or "(no final answer)",
                "",
                "#### Evidence",
                "",
                "```json",
                json.dumps(item["evidence"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def execute_formal_run(
    *,
    query_url: str,
    output_root: str | Path,
    run_id: str,
    source_commit: str,
    git_root: str | Path,
    prompt_version: str,
    prompt_sha256: str,
    repair_prompt_version: str = REPAIR_PROMPT_VERSION,
    repair_prompt_sha256: str = REPAIR_PROMPT_SHA256,
    label: str = "docs-code-consistency-transfer-validation",
    knowledge_url: str | None = None,
    project_url: str | None = None,
) -> Path:
    """Run only after preflight and all HTTP case responses are valid JSON."""

    run_id = _validate_run_id(run_id)
    source_commit = validate_source_commit(source_commit, git_root=git_root)
    validate_case_identities(git_root=git_root)
    validate_required_and_forbidden_tools()
    prompt_version, prompt_sha256 = validate_prompt_identity(
        prompt_version, prompt_sha256
    )
    repair_prompt_version, repair_prompt_sha256 = validate_repair_prompt_identity(
        repair_prompt_version, repair_prompt_sha256
    )
    knowledge_status, project_binding = validate_formal_environment(
        query_url,
        knowledge_url=knowledge_url,
        project_url=project_url,
    )

    output = Path(output_root).resolve() / run_id
    if output.exists():
        raise FileExistsError(f"Formal output run already exists: {run_id}")

    normalized_cases: list[dict[str, Any]] = []
    for case in CASES:
        started = time.perf_counter()
        response = _post_json(query_url, {"question": case["question"]})
        normalized_cases.append(
            _normalize_case(
                case,
                response,
                (time.perf_counter() - started) * 1000,
                git_root,
            )
        )

    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "g11_05_docs_code_consistency_manifest_v1",
        "workflow": WORKFLOW_ID,
        "run_id": run_id,
        "label": _sanitize_for_artifact(label, git_root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": _sanitize_for_artifact(query_url, git_root),
        "source_commit": source_commit,
        "source_commit_attestation": "operator_declared_and_locally_verified_checkout",
        "project_identity": PROJECT_IDENTITY,
        "engineering_knowledge_backend": _sanitize_for_artifact(
            knowledge_status, git_root
        ),
        "engineering_project": _sanitize_for_artifact(project_binding, git_root),
        "provider": "deepseek",
        "model": "deepseek-chat",
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "repair_prompt_version": repair_prompt_version,
        "repair_prompt_sha256": repair_prompt_sha256,
        "max_parse_repairs": MAX_PARSE_REPAIRS,
        "toolset_sha256": TOOLSET_SHA256,
        "registry_size": REGISTRY_SIZE,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "provider_network_retries": PROVIDER_NETWORK_RETRIES,
        "budget": BUDGET,
        "required_tools": list(REQUIRED_TOOLS),
        "forbidden_tools": list(FORBIDDEN_TOOLS),
        "case_ids": [case["case_id"] for case in CASES],
        "gold_labels": {case["case_id"]: case["gold_label"] for case in CASES},
        "document_source_paths": {
            case["case_id"]: case["document_source_paths"] for case in CASES
        },
        "code_source_paths": {
            case["case_id"]: case["code_source_paths"] for case in CASES
        },
        "doc_claim_anchors": {
            case["case_id"]: case["doc_claim_anchors"] for case in CASES
        },
        "gold_correctness_auto_scored": False,
        "claim_grounding_auto_scored": False,
        "source_pair_diagnostic_only": True,
        "absolute_paths_in_artifact": False,
        "provider_raw_responses_recorded": False,
        "cot_recorded": False,
    }
    metrics = _metrics(normalized_cases)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "case_results.jsonl").open("w", encoding="utf-8") as handle:
        for item in normalized_cases:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    (output / "summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    validate_artifact_safety(output, git_root)
    _write_report(output / "run_report.md", manifest, normalized_cases, metrics)
    validate_artifact_safety(output, git_root)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/engineering/query")
    parser.add_argument("--knowledge-url", default=None)
    parser.add_argument("--project-url", default=None)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--label", default="docs-code-consistency-transfer-validation")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--git-root", required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--repair-prompt-version", default=REPAIR_PROMPT_VERSION)
    parser.add_argument("--repair-prompt-sha256", default=REPAIR_PROMPT_SHA256)
    args = parser.parse_args()

    output = execute_formal_run(
        query_url=args.url,
        output_root=args.output_root,
        run_id=args.run_id,
        source_commit=args.source_commit,
        git_root=args.git_root,
        prompt_version=args.prompt_version,
        prompt_sha256=args.prompt_sha256,
        repair_prompt_version=args.repair_prompt_version,
        repair_prompt_sha256=args.repair_prompt_sha256,
        label=args.label,
        knowledge_url=args.knowledge_url,
        project_url=args.project_url,
    )
    metrics = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
