"""Run the fixed G11-03 Change Impact and Test Recommendation cases.

This runner is an HTTP client for the existing Engineering Agent. It records
only the public response, safe trace fields, fixed case metadata, and bounded
evidence. It does not capture provider output, prompts, credentials, or local
repository paths.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_IDENTITY = "my_agent_repository"
WORKFLOW_ID = "g11-03-change-impact-test-recommendation-v1"
KNOWLEDGE_CORPUS_ID = "870e5864df67"
TOOLSET_SHA256 = "9b846d9e72e8d5536c2b3de8730f61433a96d7ff59f557a70f07c6a0c33bb85f"
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
MAX_PARSE_REPAIRS = 1
BUDGET = {
    "max_agent_iterations": 5,
    "max_tool_calls": 4,
    "max_tool_errors": 2,
}
REGISTRY_SIZE = 7
MAX_OUTPUT_TOKENS = 600
PROVIDER_NETWORK_RETRIES = 0

REQUIRED_TOOLS = (
    "changed_files",
    "git_diff",
    "find_tests",
    "read_project_context",
)
FORBIDDEN_TOOLS = ("knowledge_search", "calculator")
SAFE_TRACE_KEYS = frozenset(
    {
        "event_type",
        "iteration",
        "action_type",
        "tool_name",
        "tool_status",
        "error_code",
        "iterations_used",
        "tool_calls_used",
        "tool_errors_used",
        "provider_call_count",
        "repair_attempted",
        "repair_succeeded",
        "parse_failure_category",
    }
)

_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_PROMPT_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/][^\s\"'<>]+|\\\\[^\\/\s\"'<>]+[\\/][^\\/\s\"'<>]+(?:[\\/][^\s\"'<>]+)?)"
)
_SECRET_RE = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{4,}\b")


def _obligation(identifier: str, description: str) -> dict[str, str]:
    return {"id": identifier, "description": description}


def _case(
    case_id: str,
    target_commit: str,
    focus_path: str,
    accepted_test_paths: list[str],
    question: str,
    obligations: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "target_commit": target_commit,
        "base_ref": f"{target_commit}^",
        "head_ref": target_commit,
        "focus_path": focus_path,
        "accepted_test_paths": accepted_test_paths,
        "question": question,
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": obligations,
    }


CASES = (
    _case(
        "CI01",
        "465dd65e950e9c4a119820a5a27f558e74ad5892",
        "api/app.py",
        ["tests/test_engineering_agent_api.py"],
        (
            "审查 commit range "
            "base_ref=465dd65e950e9c4a119820a5a27f558e74ad5892^ "
            "head_ref=465dd65e950e9c4a119820a5a27f558e74ad5892。"
            "重点分析 api/app.py 中 fix: preserve legacy tool-agent evidence numbering "
            "的实际变更。请区分 Git 改动、合理行为影响、find_tests 返回的 candidate、"
            "测试推荐理由和测试源码中真正覆盖的断言；完成 legacy /tool-agent/query 兼容性"
            "的 change impact 与 test recommendation。按 changed_files -> git_diff -> "
            "find_tests -> read_project_context 推进，不调用 knowledge_search 或 calculator。"
        ),
        [
            _obligation("D1", "changed_files 确认 api/app.py 属于本 commit change set。"),
            _obligation(
                "D2",
                "git_diff 读取 api/app.py：legacy response 不再直接沿用 Runtime unified "
                "evidence_id，而是在过滤 legacy 可见的 RuntimeEngineeringEvidence 后，"
                "重新 enumerate(..., 1) 生成 E1/E2/...。",
            ),
            _obligation(
                "I1",
                "说明 Unified Runtime 可能先存在 Knowledge Evidence，但 legacy endpoint "
                "不暴露 knowledge；直接沿用 unified evidence_id 可能使 legacy response "
                "从 E2/E3 开头或出现编号缺口。",
            ),
            _obligation(
                "I2",
                "说明修复目标是保持 legacy public evidence 连续从 E1 开始，而不是修改 "
                "Engineering unified evidence contract。",
            ),
            _obligation("T1", "使用 find_tests(api/app.py) 发现 candidate test。"),
            _obligation(
                "T2",
                "最终推荐优先 tests/test_engineering_agent_api.py。",
            ),
            _obligation(
                "T3",
                "read_project_context 读取该测试，并确认 tool_agent_query_response_v1、"
                "legacy evidence E1、kind=project_code，以及 legacy response 不暴露 "
                "Knowledge-only fields。",
            ),
        ],
    ),
    _case(
        "CI02",
        "766a836a6728dc7fd4f4f22e9ec8a2387758c5a9",
        "core/engineering_knowledge.py",
        ["tests/test_g11_02_r4_knowledge.py"],
        (
            "审查 commit range "
            "base_ref=766a836a6728dc7fd4f4f22e9ec8a2387758c5a9^ "
            "head_ref=766a836a6728dc7fd4f4f22e9ec8a2387758c5a9。"
            "重点分析 core/engineering_knowledge.py 中 feat: bind engineering agent "
            "to verified knowledge corpus 的实际变更：独立 backend 的工程行为、"
            "corpus identity/manifest 不合法时的风险和最应回归的测试。必须读取 candidate "
            "测试源码后再说明实际覆盖，不调用 knowledge_search 或 calculator。"
        ),
        [
            _obligation(
                "D1",
                "changed_files 确认 core/engineering_knowledge.py 属于 change set。",
            ),
            _obligation(
                "D2",
                "git_diff 读取 core/engineering_knowledge.py 的真实变化。",
            ),
            _obligation(
                "I1",
                "识别这是独立、verified、read-only Engineering Knowledge backend。",
            ),
            _obligation(
                "I2",
                "识别 corpus_id、file_count、chunk_count、retrieval strategy、manifest "
                "identity 以及 corpus 文件真实性校验等身份约束。",
            ),
            _obligation(
                "I3",
                "不得声称只要路径存在就认为 corpus 合法；backend 有显式 verification。",
            ),
            _obligation(
                "I4",
                "不得把该 backend 描述成复用 legacy 默认 vector store。",
            ),
            _obligation(
                "T1", "使用 find_tests(core/engineering_knowledge.py) 发现 candidate test。"
            ),
            _obligation(
                "T2", "最终推荐优先 tests/test_g11_02_r4_knowledge.py。"
            ),
            _obligation(
                "T3",
                "read_project_context 读取测试后，说明其对 verified identity、"
                "invalid/missing corpus、manifest/file validation 或 backend startup "
                "contract 的实际覆盖。",
            ),
        ],
    ),
    _case(
        "CI03",
        "129175ec422b88677b48c0c5d5997a1a8f229b92",
        "core/tool_agent/decision_prompt.py",
        ["tests/test_g11_02_r5_budget_control.py"],
        (
            "审查 commit range "
            "base_ref=129175ec422b88677b48c0c5d5997a1a8f229b92^ "
            "head_ref=129175ec422b88677b48c0c5d5997a1a8f229b92。"
            "围绕 Budget-Aware Decision Guidance，重点分析 core/tool_agent/decision_prompt.py "
            "在 feat: add budget-aware engineering decisions 中如何把 trusted Runtime "
            "control state 渲染到 Engineering v2 system policy；说明 tool_call_allowed、"
            "must_terminate、remaining_* 的作用、它是否替代 Runtime hard enforcement，"
            "以及最值得回归的测试。必须从读取到的测试源码解释实际 budget invariant，"
            "不调用 knowledge_search 或 calculator。"
        ),
        [
            _obligation(
                "D1", "changed_files 确认 decision_prompt.py 属于 change set。"
            ),
            _obligation(
                "D2",
                "git_diff 读取 decision_prompt.py 的真实变化：build_messages 与 "
                "_build_messages_from_template 可以接收 control_state；trusted Runtime "
                "control state 被渲染到 system message；Engineering v2 profile 设置 "
                "render_control_state=True；Engineering v2 增加 budget guidance。",
            ),
            _obligation(
                "I1",
                "说明 control state 是 system-managed、trusted Runtime metadata，"
                "不是用户输入或 Tool Observation。",
            ),
            _obligation(
                "I2",
                "说明 remaining_iterations 与 remaining_tool_calls 是只读的剩余能力信息。",
            ),
            _obligation(
                "I3",
                "当 tool_call_allowed=false 或 must_terminate=true 时，模型应使用 "
                "final_answer 或 refuse，而不是请求新的 Tool。",
            ),
            _obligation(
                "I4",
                "不得声称 Prompt guidance 替代 Runtime hard budget enforcement。"
            ),
            _obligation(
                "T1",
                "使用 find_tests(core/tool_agent/decision_prompt.py) 发现 candidate test。",
            ),
            _obligation(
                "T2", "最终推荐优先 tests/test_g11_02_r5_budget_control.py。"
            ),
            _obligation(
                "T3",
                "read_project_context 读取目标测试后，解释其对 Engineering v2 trusted "
                "state 只出现在 system message、remaining_tool_calls 实际渲染、legacy "
                "v3 不渲染 control state、must_terminate/tool_call_allowed 边界，或 "
                "Runtime 最终 hard-stop 越界 Tool call 中至少一类的真实覆盖。",
            ),
        ],
    ),
    _case(
        "CI04",
        "23073a5aa6471b2e671385907108008253788dba",
        "core/tool_agent/tools/git_change.py",
        ["tests/test_git_change_tools.py"],
        (
            "审查 commit range "
            "base_ref=23073a5aa6471b2e671385907108008253788dba^ "
            "head_ref=23073a5aa6471b2e671385907108008253788dba。"
            "重点分析 core/tool_agent/tools/git_change.py 中 fix: preserve bounded git "
            "output truncation 的边界修复：截断与真实 Git command failure 的区别、"
            "安全记录和 bounded git_diff contract。必须读取 candidate 测试源码后再推荐 "
            "测试，不调用 knowledge_search 或 calculator。"
        ),
        [
            _obligation(
                "D1", "changed_files 确认 git_change.py 属于 change set。"
            ),
            _obligation(
                "D2", "git_diff 读取 git_change.py 的真实变化。"
            ),
            _obligation(
                "I1",
                "识别 capture 被资源上限主动截断时，process 非零 return code 不能自动 "
                "解释成真正 Git failure。",
            ),
            _obligation(
                "I2",
                "识别 truncated output 只保留完整、安全记录，不能把半截 path/record 当作 "
                "有效结果。",
            ),
            _obligation(
                "I3",
                "识别 changed_files.total_count 在 truncated=true 时不是完整仓库变更总数。",
            ),
            _obligation(
                "I4", "识别 git_diff 仍必须受 chars/lines bounded contract 限制。"
            ),
            _obligation(
                "T1", "使用 find_tests(git_change.py) 发现 candidate test。"
            ),
            _obligation(
                "T2", "最终推荐优先 tests/test_git_change_tools.py。"
            ),
            _obligation(
                "T3",
                "read_project_context 读取测试后，识别 raw diff overflow safe prefix、"
                "name-status overflow observed records、real git failure != truncation 或 "
                "bounded chars/lines 等真实测试覆盖。",
            ),
        ],
    ),
)


def _run_git(git_root: str | Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
    )


def validate_source_commit(value: object, *, git_root: str | Path) -> str:
    """Require the declared source commit to be the locally tested checkout HEAD."""

    if type(value) is not str or not _COMMIT_RE.fullmatch(value):
        raise ValueError("source_commit must be exactly 40 hexadecimal characters")
    normalized = value.lower()
    requested_root = Path(git_root)
    top_level = _run_git(requested_root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0 or not top_level.stdout.strip():
        raise ValueError("git_root is not a Git working tree")
    actual_head = _run_git(requested_root, "rev-parse", "HEAD")
    actual_head_value = actual_head.stdout.strip().lower()
    if actual_head.returncode != 0 or actual_head_value != normalized:
        raise ValueError("declared source_commit does not match git_root HEAD")
    verified = _run_git(requested_root, "cat-file", "-e", f"{normalized}^{{commit}}")
    if verified.returncode != 0:
        raise ValueError("source_commit is not a valid commit object")
    status = _run_git(
        requested_root, "status", "--porcelain", "--untracked-files=no"
    )
    if status.returncode != 0:
        raise ValueError("could not inspect git_root tracked status")
    if status.stdout.strip():
        raise ValueError("git_root has tracked modifications")
    return normalized


def validate_case_identities(
    cases: tuple[dict[str, Any], ...] = CASES,
    *,
    git_root: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Validate the fixed case IDs, commit shapes, refs, and optional checkout."""

    expected_ids = ("CI01", "CI02", "CI03", "CI04")
    if tuple(case.get("case_id") for case in cases) != expected_ids:
        raise ValueError("G11-03 case identity drifted")
    for case in cases:
        target = case.get("target_commit")
        if type(target) is not str or not _COMMIT_RE.fullmatch(target):
            raise ValueError("target_commit must be exactly 40 hexadecimal characters")
        if case.get("head_ref") != target or case.get("base_ref") != f"{target}^":
            raise ValueError("case base_ref/head_ref identity drifted")
        if git_root is not None:
            target_object = _run_git(
                git_root, "rev-parse", "--verify", f"{target}^{{commit}}"
            )
            if target_object.returncode != 0 or target_object.stdout.strip().lower() != target.lower():
                raise ValueError(f"target commit is not present: {target}")
            parent = _run_git(git_root, "rev-parse", "--verify", case["base_ref"])
            if parent.returncode != 0 or not _COMMIT_RE.fullmatch(parent.stdout.strip()):
                raise ValueError(f"target commit has no valid parent: {target}")
    return cases


def validate_prompt_identity(version: object, sha256: object) -> tuple[str, str]:
    if type(version) is not str or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("prompt_version must be a bounded non-empty identifier")
    if version not in KNOWN_PROMPT_IDENTITIES:
        raise ValueError("G11-03 requires the production Engineering v2 prompt")
    if type(sha256) is not str or not _SHA256_RE.fullmatch(sha256):
        raise ValueError("prompt_sha256 must be exactly 64 hexadecimal characters")
    normalized_sha = sha256.lower()
    if normalized_sha != KNOWN_PROMPT_IDENTITIES[version]:
        raise ValueError("prompt_version and prompt_sha256 do not match")
    return version, normalized_sha


def validate_repair_prompt_identity(version: object, sha256: object) -> tuple[str, str]:
    if type(version) is not str or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("repair_prompt_version must be a bounded non-empty identifier")
    if version != REPAIR_PROMPT_VERSION:
        raise ValueError("repair_prompt_version is not the supported identity")
    if type(sha256) is not str or not _SHA256_RE.fullmatch(sha256):
        raise ValueError("repair_prompt_sha256 must be exactly 64 hexadecimal characters")
    normalized_sha = sha256.lower()
    if normalized_sha != REPAIR_PROMPT_SHA256:
        raise ValueError("repair_prompt_version and repair_prompt_sha256 do not match")
    return version, normalized_sha


def _validate_run_id(value: object) -> str:
    if type(value) is not str or not _RUN_ID_RE.fullmatch(value):
        raise ValueError("run_id must be a bounded path-safe identifier")
    return value


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {body[:200]}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("API response is not an object")
    return decoded


def _get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {body[:200]}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("API response is not an object")
    return decoded


def _knowledge_url(query_url: str) -> str:
    parsed = urllib.parse.urlsplit(query_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("engineering query URL must be an absolute HTTP URL")
    path = parsed.path.rstrip("/")
    suffix = "/engineering/query"
    if not path.endswith(suffix):
        raise ValueError("engineering query URL must end with /engineering/query")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path[: -len(suffix)] + "/engineering/knowledge", "", "")
    )


def validate_knowledge_backend(status: object) -> dict[str, Any]:
    if not isinstance(status, dict):
        raise ValueError("Engineering Knowledge status is not an object")
    expected = {
        "schema_version": "engineering_knowledge_status_v1",
        "ready": True,
        "verified": True,
        "corpus_id": KNOWLEDGE_CORPUS_ID,
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": "dbc497c796d5",
    }
    for field, expected_value in expected.items():
        if status.get(field) != expected_value:
            raise ValueError(
                f"Engineering Knowledge status mismatch: {field}={status.get(field)!r}"
            )
    return {field: status[field] for field in expected}


def _safe_trace(trace: object) -> list[dict[str, Any]]:
    if not isinstance(trace, list):
        return []
    return [
        {key: event[key] for key in SAFE_TRACE_KEYS if key in event}
        for event in trace
        if isinstance(event, dict)
    ]


def _tool_sequence(trace: list[dict[str, Any]]) -> list[str]:
    return [
        event["tool_name"]
        for event in trace
        if event.get("event_type") == "tool_observation"
        and isinstance(event.get("tool_name"), str)
    ]


def _evidence_kinds(response: dict[str, Any]) -> list[str]:
    evidence = response.get("evidence")
    if not isinstance(evidence, list):
        return []
    return [
        item["kind"]
        for item in evidence
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    ]


def _sanitize_for_artifact(value: Any, git_root: str | Path) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_for_artifact(item, git_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_artifact(item, git_root) for item in value]
    if not isinstance(value, str):
        return value
    root = str(Path(git_root).resolve())
    sanitized = value.replace(root, "<repo>").replace(root.replace("\\", "/"), "<repo>")
    sanitized = _ABSOLUTE_PATH_RE.sub("<absolute-path>", sanitized)
    sanitized = _SECRET_RE.sub("<redacted-secret>", sanitized)
    return sanitized.replace("\\", "/")


def _normalize_case(
    case: dict[str, Any], response: dict[str, Any], elapsed_ms: float, git_root: str | Path
) -> dict[str, Any]:
    trace = _sanitize_for_artifact(_safe_trace(response.get("trace")), git_root)
    sequence = _tool_sequence(trace)
    decision_events = [
        event for event in trace if event.get("event_type") == "decision_completed"
    ]
    provider_calls = sum(event.get("provider_call_count") or 0 for event in decision_events)
    repair_attempted = any(event.get("repair_attempted") is True for event in decision_events)
    repair_succeeded = any(event.get("repair_succeeded") is True for event in decision_events)
    parse_categories = [
        event["parse_failure_category"]
        for event in decision_events
        if isinstance(event.get("parse_failure_category"), str)
    ]
    evidence = response.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    iterations = response.get("iterations_used")
    tool_calls = response.get("tool_calls_used")
    tool_errors = response.get("tool_errors_used")
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "target_commit": case["target_commit"],
        "base_ref": case["base_ref"],
        "head_ref": case["head_ref"],
        "focus_path": case["focus_path"],
        "accepted_test_paths": case["accepted_test_paths"],
        "status": response.get("status"),
        "answer": _sanitize_for_artifact(response.get("answer"), git_root),
        "reason_code": response.get("reason_code"),
        "failure_code": response.get("failure_code"),
        "iterations": iterations,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "iterations_used": iterations,
        "tool_calls_used": tool_calls,
        "tool_errors_used": tool_errors,
        "provider_calls_total": provider_calls,
        "repair_attempted": repair_attempted,
        "repair_succeeded": repair_succeeded,
        "initial_parse_categories": parse_categories,
        "latency_ms": round(elapsed_ms, 2),
        "trace": trace,
        "tool_sequence": sequence,
        "evidence": _sanitize_for_artifact(evidence, git_root),
        "evidence_kinds": _evidence_kinds(response),
        "required_tools": list(case["required"]),
        "forbidden_tools": list(case["forbidden"]),
        "gold_obligations": case["obligations"],
    }


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    completed = sum(item.get("status") == "completed" for item in cases)
    required_coverage = {
        tool: sum(tool in (item.get("tool_sequence") or []) for item in cases)
        for tool in REQUIRED_TOOLS
    }
    total_tool_calls = sum(len(item.get("tool_sequence") or []) for item in cases)
    forbidden_calls = sum(
        sum(tool in FORBIDDEN_TOOLS for tool in (item.get("tool_sequence") or []))
        for item in cases
    )
    non_target_calls = sum(
        sum(tool not in REQUIRED_TOOLS for tool in (item.get("tool_sequence") or []))
        for item in cases
    )
    exact_sequence_cases = sum(
        (item.get("tool_sequence") or []) == list(REQUIRED_TOOLS) for item in cases
    )
    change_cases = sum("project_change" in (item.get("evidence_kinds") or []) for item in cases)
    test_cases = sum("project_test" in (item.get("evidence_kinds") or []) for item in cases)
    pair_cases = sum(
        {"project_change", "project_test"}.issubset(set(item.get("evidence_kinds") or []))
        for item in cases
    )
    case_count = len(cases)
    return {
        "case_count": case_count,
        "completed_cases": completed,
        "completion_rate": completed / case_count if case_count else 0,
        "required_tool_coverage": required_coverage,
        "required_tool_coverage_rate": (
            sum(required_coverage.values()) / (len(REQUIRED_TOOLS) * case_count)
            if case_count
            else 0
        ),
        "exact_target_sequence_cases": exact_sequence_cases,
        "exact_target_sequence_rate": exact_sequence_cases / case_count if case_count else 0,
        "forbidden_tool_calls": forbidden_calls,
        "forbidden_tool_call_rate": (
            forbidden_calls / total_tool_calls if total_tool_calls else 0
        ),
        "non_target_tool_calls": non_target_calls,
        "non_target_tool_call_rate": non_target_calls / total_tool_calls if total_tool_calls else 0,
        "change_evidence_cases": change_cases,
        "test_evidence_cases": test_cases,
        "change_test_pair_cases": pair_cases,
        "change_test_pair_rate": pair_cases / case_count if case_count else 0,
        "avg_tool_calls": (
            sum(item.get("tool_calls") or 0 for item in cases) / case_count
            if case_count
            else 0
        ),
        "avg_iterations": (
            sum(item.get("iterations") or 0 for item in cases) / case_count
            if case_count
            else 0
        ),
        "evidence_count": sum(len(item.get("evidence") or []) for item in cases),
        "failed_cases": sum(item.get("status") == "failed" for item in cases),
        "refused_cases": sum(item.get("status") == "refused" for item in cases),
        "provider_calls_total": sum(item.get("provider_calls_total") or 0 for item in cases),
        "repair_attempted_cases": sum(item.get("repair_attempted") is True for item in cases),
        "repair_succeeded_cases": sum(item.get("repair_succeeded") is True for item in cases),
        "parse_failure_cases": sum(
            item.get("failure_code") == "ACTION_PARSE_FAILED" for item in cases
        ),
        "initial_parse_failure_cases": sum(
            bool(item.get("initial_parse_categories")) for item in cases
        ),
        "initial_parse_categories": [
            category
            for item in cases
            for category in item.get("initial_parse_categories", [])
        ],
    }


def _write_report(path: Path, manifest: dict[str, Any], cases: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    lines = [
        "# G11-03 Change Impact & Test Recommendation Run",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- source_commit: `{manifest['source_commit']}`",
        f"- endpoint: `{manifest['endpoint']}`",
        f"- prompt_version: `{manifest['prompt_version']}`",
        f"- prompt_sha256: `{manifest['prompt_sha256']}`",
        f"- repair_prompt_version: `{manifest['repair_prompt_version']}`",
        f"- repair_prompt_sha256: `{manifest['repair_prompt_sha256']}`",
        f"- max_parse_repairs: `{manifest['max_parse_repairs']}`",
        f"- workflow: `{manifest['workflow']}`",
        "- correctness: not automatically scored; Gold obligations require manual audit.",
        "- formal run: this artifact is produced only when the operator explicitly runs the runner.",
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
                f"- target/base/head: `{item['target_commit']}` / `{item['base_ref']}` / `{item['head_ref']}`",
                f"- focus path: `{item['focus_path']}`",
                f"- status: `{item['status']}`",
                f"- reason_code: `{item['reason_code']}`",
                f"- failure_code: `{item['failure_code']}`",
                f"- provider calls/repair attempted/succeeded: `{item['provider_calls_total']}/{item['repair_attempted']}/{item['repair_succeeded']}`",
                f"- tool sequence: `{' -> '.join(item['tool_sequence']) or '(none)'}`",
                f"- iterations/tool calls/errors: `{item['iterations']}/{item['tool_calls']}/{item['tool_errors']}`",
                f"- evidence kinds: `{', '.join(item['evidence_kinds']) or '(none)'}`",
                f"- Gold obligations: `{', '.join(obligation['id'] for obligation in item['gold_obligations'])}`",
                "",
                "#### Gold obligation definitions",
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


def _string_is_safe(value: str, git_root: str | Path) -> bool:
    root = str(Path(git_root).resolve())
    normalized_root = root.replace("\\", "/")
    value_casefold = value.casefold()
    return (
        root.casefold() not in value_casefold
        and normalized_root.casefold() not in value_casefold
        and _ABSOLUTE_PATH_RE.search(value) is None
        and _SECRET_RE.search(value) is None
    )


def _validate_value_safety(value: Any, git_root: str | Path) -> bool:
    """Validate decoded artifact values, keeping JSON escaping out of the scan."""
    if isinstance(value, str):
        return _string_is_safe(value, git_root)
    if isinstance(value, dict):
        return all(
            _validate_value_safety(key, git_root)
            and _validate_value_safety(item, git_root)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_validate_value_safety(item, git_root) for item in value)
    return True


def _artifact_is_safe(text: str, git_root: str | Path) -> bool:
    """Apply the text policy used for Markdown and unknown artifact files."""
    return _string_is_safe(text, git_root)


def validate_artifact_safety(output: Path, git_root: str | Path) -> None:
    for path in sorted(output.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"artifact contains invalid JSON: {path.name}") from exc
            safe = _validate_value_safety(payload, git_root)
        elif path.suffix.lower() == ".jsonl":
            safe = True
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"artifact contains invalid JSONL at {path.name}:{line_number}"
                    ) from exc
                if not _validate_value_safety(payload, git_root):
                    safe = False
                    break
        else:
            safe = _artifact_is_safe(path.read_text(encoding="utf-8"), git_root)
        if not safe:
            raise ValueError(f"artifact contains unsafe local path or secret: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/engineering/query")
    parser.add_argument("--knowledge-url", default=None)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--label", default="transfer-validation")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--git-root", required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--repair-prompt-version", default=REPAIR_PROMPT_VERSION)
    parser.add_argument("--repair-prompt-sha256", default=REPAIR_PROMPT_SHA256)
    args = parser.parse_args()

    run_id = _validate_run_id(args.run_id)
    source_commit = validate_source_commit(args.source_commit, git_root=args.git_root)
    validate_case_identities(git_root=args.git_root)
    prompt_version, prompt_sha256 = validate_prompt_identity(
        args.prompt_version, args.prompt_sha256
    )
    repair_prompt_version, repair_prompt_sha256 = validate_repair_prompt_identity(
        args.repair_prompt_version, args.repair_prompt_sha256
    )
    knowledge_status = validate_knowledge_backend(
        _get_json(args.knowledge_url or _knowledge_url(args.url))
    )

    output = Path(args.output_root).resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "g11_03_change_impact_manifest_v1",
        "workflow": WORKFLOW_ID,
        "run_id": run_id,
        "label": args.label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": args.url,
        "source_commit": source_commit,
        "source_commit_attestation": "operator_declared_and_locally_verified_checkout",
        "project_identity": PROJECT_IDENTITY,
        "knowledge_corpus_id": knowledge_status["corpus_id"],
        "knowledge_backend": knowledge_status,
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
        "target_commits": [case["target_commit"] for case in CASES],
        "absolute_paths_in_artifact": False,
        "provider_raw_responses_recorded": False,
        "cot_recorded": False,
    }
    cases: list[dict[str, Any]] = []
    for case in CASES:
        started = time.perf_counter()
        response = _post_json(args.url, {"question": case["question"]})
        cases.append(
            _normalize_case(
                case, response, (time.perf_counter() - started) * 1000, args.git_root
            )
        )

    metrics = _metrics(cases)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "case_results.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    (output / "summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Validate structured payloads before rendering the Markdown report.
    validate_artifact_safety(output, args.git_root)
    _write_report(output / "run_report.md", manifest, cases, metrics)
    validate_artifact_safety(output, args.git_root)
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
