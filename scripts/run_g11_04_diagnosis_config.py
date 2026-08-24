"""Run the fixed G11-04 Diagnosis & Config Analysis cases.

The runner is an HTTP client for the existing Engineering Agent.  It freezes
the diagnosis benchmark contract, records only the public structured response
and safe trace fields, and reports evidence shape for later human Gold review.
It does not score diagnosis, root-cause, remediation, or claim grounding.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
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
    validate_knowledge_backend as _validate_knowledge_backend,
    validate_source_commit as _validate_source_commit,
)


PROJECT_IDENTITY = "my_agent_repository"
WORKFLOW_ID = "g11-04-diagnosis-config-v1"
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
    "changed_files",
    "git_diff",
    "find_tests",
    "knowledge_search",
    "calculator",
)
WORKFLOW_STAGES = (
    "symptom_or_config_clue",
    "code_search",
    "read_project_context",
    "optional_second_implementation_point",
    "diagnosis",
    "remediation_or_verification",
)

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

EXPECTED_CASE_IDS = ("DC01", "DC02", "DC03", "DC04")
EXPECTED_CASE_SHAPE = {
    "DC01": {
        "focus_path": "api/project_workspace.py",
        "gold_source_paths": ("api/project_workspace.py", "api/app.py"),
    },
    "DC02": {
        "focus_path": "core/engineering_knowledge.py",
        "gold_source_paths": ("core/engineering_knowledge.py", "api/app.py"),
    },
    "DC03": {
        "focus_path": "core/config.py",
        "gold_source_paths": ("core/config.py", "api/app.py"),
    },
    "DC04": {
        "focus_path": "core/config.py",
        "gold_source_paths": (
            "core/config.py",
            "core/tool_agent/decision_prompt.py",
        ),
    },
}

_PROMPT_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _obligation(identifier: str, description: str) -> dict[str, str]:
    return {"id": identifier, "description": description}


def _case(
    case_id: str,
    focus_path: str,
    gold_source_paths: tuple[str, ...],
    question: str,
    obligations: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "focus_path": focus_path,
        "gold_source_paths": list(gold_source_paths),
        "question": question,
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": obligations,
    }


CASES = (
    _case(
        "DC01",
        "api/project_workspace.py",
        ("api/project_workspace.py", "api/app.py"),
        (
            "诊断显式 ENGINEERING_PROJECT_ROOT 指向不存在路径或非 directory 时的启动故障。"
            "请区分 env 未设置与 explicit invalid value，定位真正校验函数，解释为什么不能"
            "静默退回 repo root、故障发生在 startup 哪个阶段，并给出有证据的修复与验证建议。"
            "必须使用 code_search 定位，再用 read_project_context 读取实际实现；不要调用"
            "changed_files、git_diff、find_tests、knowledge_search 或 calculator。"
        ),
        [
            _obligation("D1", "定位 resolve_engineering_project。"),
            _obligation(
                "D2",
                "configured_root 或环境值为空时使用 default repo。",
            ),
            _obligation(
                "D3",
                '显式非空值不存在时抛出 ValueError("ENGINEERING_PROJECT_ROOT does not exist")。',
            ),
            _obligation(
                "D4",
                '显式值不是目录时抛出 ValueError("ENGINEERING_PROJECT_ROOT must be a directory")。',
            ),
            _obligation("I1", "explicit invalid config 不 fallback。"),
            _obligation(
                "I2",
                "这是 system-owned project binding；模型不能自行指定 project root。",
            ),
            _obligation(
                "I3",
                "api.app lifespan 在 Pipeline try-block 之前调用 resolve_engineering_project，"
                "所以该错误与普通 Pipeline init failure 的传播方式不同。",
            ),
            _obligation(
                "R1",
                "修复为真实 directory，或取消显式 override 以使用 default repo；不得建议忽略非法值。",
            ),
        ],
    ),
    _case(
        "DC02",
        "core/engineering_knowledge.py",
        ("core/engineering_knowledge.py", "api/app.py"),
        (
            "诊断 ENGINEERING_KNOWLEDGE_CORPUS_ROOT 缺失或为空导致 /engineering/query 不可用、"
            "Engineering Knowledge status not ready 的故障。请定位根因，解释为什么不 fallback 到"
            "legacy ./data/vector_store、哪些 runtime 仍可能存在、status 字段如何反映边界，并给出"
            "正确的 verified corpus 配置建议。必须读取实际源码，不调用 changed_files、git_diff、"
            "find_tests、knowledge_search 或 calculator。"
        ),
        [
            _obligation("D1", 'CORPUS_ENV_VAR = "ENGINEERING_KNOWLEDGE_CORPUS_ROOT"。'),
            _obligation(
                "D2",
                "VerifiedEngineeringKnowledge.from_repo 对 None 或 blank 直接抛出 EngineeringKnowledgeError。",
            ),
            _obligation(
                "D3",
                "Verified backend 是独立、verified、read-only 的 BM25 backend。",
            ),
            _obligation(
                "I1",
                "不得声称会 fallback 到 legacy ./data/vector_store。",
            ),
            _obligation(
                "I2",
                "Engineering Knowledge/runtime init 位于 legacy Tool Agent 初始化成功后的独立 try block。",
            ),
            _obligation(
                "I3",
                "失败会令 engineering_agent_runtime 和 engineering_agent_facade 为 None，"
                "不能笼统说整个 FastAPI 必然启动失败。",
            ),
            _obligation(
                "I4",
                "/engineering/knowledge 的 ready 取决于 facade，verified 取决于 backend identity。",
            ),
            _obligation(
                "R1",
                "配置已冻结且可验证的 corpus root，不是关闭 verification。",
            ),
        ],
    ),
    _case(
        "DC03",
        "core/config.py",
        ("core/config.py", "api/app.py"),
        (
            "诊断以下配置导致 Pipeline initialization failed 的原因，并解释 API startup 的传播：\n"
            "chunker:\n  size_tokens: 512\n  overlap_tokens: 512\n"
            "请找到真实 Config validation，说明合法关系、ConfigError 发生层次、api.app 如何处置，"
            "以及正确修复；不要把它误诊成 embedding/provider failure，也不要调用 changed_files、"
            "git_diff、find_tests、knowledge_search 或 calculator。"
        ),
        [
            _obligation("D1", "chunk_size > 0。"),
            _obligation("D2", "chunk_overlap >= 0。"),
            _obligation("D3", "chunk_overlap < chunk_size。"),
            _obligation("D4", "512 / 512 触发 ConfigError。"),
            _obligation(
                "I1",
                "错误发生于 Config construction / Pipeline init。",
            ),
            _obligation(
                "I2",
                "api.app 捕获 Pipeline init Exception，打印 warning，并设置 pipeline = None。",
            ),
            _obligation(
                "I3",
                "后续依赖 pipeline 的 runtimes 不能正常构建。",
            ),
            _obligation(
                "R1",
                "修复 overlap 为严格小于 size 的值，不绕过 Config validation。",
            ),
        ],
    ),
    _case(
        "DC04",
        "core/config.py",
        ("core/config.py", "core/tool_agent/decision_prompt.py"),
        (
            "诊断以下 generator 配置为什么启动失败，并分析它是否等于修改 Engineering Agent"
            " structured decision 的 1200 output cap：\n"
            "generator:\n  max_total_tokens: 4096\n  max_output_tokens: 4096\n"
            "请分别定位 Pipeline generator budget 与 Engineering v2 profile-scoped decision"
            " transport cap，避免因为两个配置同名而混淆；给出修复与验证建议。不要调用"
            "changed_files、git_diff、find_tests、knowledge_search 或 calculator。"
        ),
        [
            _obligation("D1", "generator.max_total_tokens 必须是正 int。"),
            _obligation("D2", "generator.max_output_tokens 必须是正 int。"),
            _obligation(
                "D3",
                "generator.max_output_tokens 必须严格小于 generator.max_total_tokens。",
            ),
            _obligation("D4", "4096 == 4096，因此触发 ConfigError。"),
            _obligation(
                "I1",
                "config.yaml generator token budget 属于 Pipeline / answer generator config。",
            ),
            _obligation(
                "I2",
                "Engineering Agent Decision Provider 的 1200 是 profile-scoped structured decision transport cap。",
            ),
            _obligation("I3", "二者不是同一个配置边界。"),
            _obligation(
                "I4",
                "修改 config.yaml generator.max_output_tokens 不会自动修改 Engineering v2 Decision Provider 的 1200 cap。",
            ),
            _obligation(
                "R1",
                "修复 Pipeline config 的 total/output 关系；讨论 Engineering Decision cap 时明确它是另一个代码级 policy。",
            ),
        ],
    ),
)


def validate_case_identities(
    cases: tuple[dict[str, Any], ...] = CASES,
    *,
    git_root: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Validate fixed IDs and Gold source boundaries without judging answers."""

    if tuple(case.get("case_id") for case in cases) != EXPECTED_CASE_IDS:
        raise ValueError("G11-04 case identity drifted")
    for case in cases:
        case_id = case.get("case_id")
        expected = EXPECTED_CASE_SHAPE.get(case_id)
        if expected is None:
            raise ValueError("G11-04 case identity drifted")
        if case.get("focus_path") != expected["focus_path"]:
            raise ValueError(f"{case_id} focus path identity drifted")
        sources = tuple(case.get("gold_source_paths") or ())
        if sources != expected["gold_source_paths"]:
            raise ValueError(f"{case_id} Gold source identity drifted")
        if not sources or any(
            type(path) is not str
            or not path
            or path.startswith(("/", "\\"))
            or ".." in Path(path).parts
            for path in sources
        ):
            raise ValueError(f"{case_id} Gold source path is not repo-relative")
        if git_root is not None:
            root = Path(git_root)
            if any(not (root / Path(path.replace("/", "\\"))).is_file() for path in sources):
                raise ValueError(f"{case_id} Gold source is missing from git_root")
    return cases


def validate_required_and_forbidden_tools() -> tuple[tuple[str, ...], tuple[str, ...]]:
    if REQUIRED_TOOLS != ("code_search", "read_project_context"):
        raise ValueError("G11-04 required tool contract drifted")
    expected_forbidden = {
        "changed_files",
        "git_diff",
        "find_tests",
        "knowledge_search",
        "calculator",
    }
    if set(FORBIDDEN_TOOLS) != expected_forbidden:
        raise ValueError("G11-04 forbidden tool contract drifted")
    if set(REQUIRED_TOOLS) & set(FORBIDDEN_TOOLS):
        raise ValueError("G11-04 required and forbidden tools overlap")
    return REQUIRED_TOOLS, FORBIDDEN_TOOLS


def validate_source_commit(value: object, *, git_root: str | Path) -> str:
    """Require the declared source commit to equal a tracked-clean local HEAD."""

    return _validate_source_commit(value, git_root=git_root)


def validate_prompt_identity(version: object, sha256: object) -> tuple[str, str]:
    if type(version) is not str or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("prompt_version must be a bounded non-empty identifier")
    if version not in KNOWN_PROMPT_IDENTITIES:
        raise ValueError("G11-04 requires the production Engineering v2 prompt")
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
    """Derive the public project identity endpoint from /engineering/query."""

    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(query_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("engineering query URL must be an absolute HTTP URL")
    path = parsed.path.rstrip("/")
    suffix = "/engineering/query"
    if not path.endswith(suffix):
        raise ValueError("engineering query URL must end with /engineering/query")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            path[: -len(suffix)] + "/project",
            "",
            "",
        )
    )


def validate_engineering_knowledge_status(status: object) -> dict[str, Any]:
    """Reuse the validated G11-03 backend identity contract."""

    return _validate_knowledge_backend(status)


def validate_engineering_project(project: object) -> dict[str, str]:
    """Accept only the Formal benchmark's system-owned project binding."""

    if not isinstance(project, dict):
        raise ValueError("Engineering Project status is not an object")
    if project.get("project_name") != EXPECTED_PROJECT_NAME:
        raise ValueError(
            "Engineering Project identity mismatch: "
            f"project_name={project.get('project_name')!r}"
        )
    if project.get("source") != EXPECTED_PROJECT_SOURCE:
        raise ValueError(
            "Engineering Project identity mismatch: "
            f"source={project.get('source')!r}"
        )
    return {
        "project_name": EXPECTED_PROJECT_NAME,
        "source": EXPECTED_PROJECT_SOURCE,
    }


def validate_formal_environment(
    query_url: str,
    *,
    knowledge_url: str | None = None,
    project_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Verify the HTTP runtime identity before any benchmark case is posted.

    The local Git checkout is not evidence that the HTTP runtime uses the same
    project or verified corpus.  Network/HTTP/JSON failures intentionally
    propagate as infrastructure failures.
    """

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


def _project_code_evidence(evidence: list[Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in evidence
        if isinstance(item, dict) and item.get("kind") == "project_code"
    ]


def _project_evidence_paths(evidence: list[Any]) -> set[str]:
    return {
        item["path"]
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item.get("kind", "").startswith("project_")
    }


def behavior_body_visible(evidence: list[Any]) -> bool:
    """Return a conservative structural signal, never a correctness judgment.

    Imports and a bare filename are insufficient.  A project-code snippet must
    expose a function declaration together with a body/control signal, or an
    explicit raise/branch signal.  The result is diagnostic-only.
    """

    function_re = re.compile(r"^\s*(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(")
    body_re = re.compile(
        r"^\s*(?:if\b|elif\b|else\s*:|raise\b|return\b|try\s*:|except\b|"
        r"for\b|while\b|with\b)"
    )
    for item in _project_code_evidence(evidence):
        snippet = item.get("snippet")
        if not isinstance(snippet, str):
            continue
        lines = snippet.splitlines()
        has_function = any(function_re.search(line) for line in lines)
        has_body_signal = any(body_re.search(line) for line in lines)
        has_explicit_behavior = any(
            re.search(r"^\s*(?:raise\b|if\b|elif\b|else\s*:)", line)
            for line in lines
        )
        if (has_function and has_body_signal) or has_explicit_behavior:
            return True
    return False


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
    raw_evidence_kinds = [
        item["kind"]
        for item in raw_evidence
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    ]
    evidence_kinds = _sanitize_for_artifact(raw_evidence_kinds, git_root)
    project_code = bool(_project_code_evidence(raw_evidence))
    multi_file = len(_project_evidence_paths(raw_evidence)) >= 2
    provider_calls = _provider_calls(trace)
    parse_categories = _parse_categories(trace)
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "focus_path": case["focus_path"],
        "gold_source_paths": list(case["gold_source_paths"]),
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
        "provider_calls_total": provider_calls,
        "repair_attempted": any(
            event.get("repair_attempted") is True for event in trace
        ),
        "repair_succeeded": any(
            event.get("repair_succeeded") is True for event in trace
        ),
        "initial_parse_categories": parse_categories,
        "project_code_evidence": project_code,
        "multi_file_evidence": multi_file,
        "behavior_body_visible": behavior_body_visible(raw_evidence),
        "latency_ms": round(elapsed_ms, 2),
        "required_tools": list(case["required"]),
        "forbidden_tools": list(case["forbidden"]),
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
    project_code_cases = sum(
        (
            item.get("project_code_evidence") is True
            if "project_code_evidence" in item
            else "project_code" in (item.get("evidence_kinds") or [])
        )
        for item in cases
    )
    multi_file_cases = sum(
        (
            item.get("multi_file_evidence") is True
            if "multi_file_evidence" in item
            else len(_project_evidence_paths(item.get("evidence") or [])) >= 2
        )
        for item in cases
    )
    behavior_body_cases = sum(
        (
            item.get("behavior_body_visible") is True
            if "behavior_body_visible" in item
            else behavior_body_visible(item.get("evidence") or [])
        )
        for item in cases
    )
    return {
        "case_count": case_count,
        "completed_cases": completed,
        "completion_rate": completed / case_count if case_count else 0,
        "code_search_coverage": required_coverage["code_search"],
        "read_project_context_coverage": required_coverage[
            "read_project_context"
        ],
        "code_search_coverage_rate": (
            required_coverage["code_search"] / case_count if case_count else 0
        ),
        "read_project_context_coverage_rate": (
            required_coverage["read_project_context"] / case_count
            if case_count
            else 0
        ),
        "required_tool_coverage": required_coverage,
        "required_tool_coverage_rate": (
            sum(required_coverage.values()) / (len(REQUIRED_TOOLS) * case_count)
            if case_count
            else 0
        ),
        "project_code_evidence_cases": project_code_cases,
        "multi_file_evidence_cases": multi_file_cases,
        "behavior_body_visible_cases": behavior_body_cases,
        "forbidden_tool_calls": forbidden_calls,
        "forbidden_tool_call_rate": (
            forbidden_calls / total_tool_calls if total_tool_calls else 0
        ),
        "non_target_tool_calls": non_target_calls,
        "non_target_tool_call_rate": (
            non_target_calls / total_tool_calls if total_tool_calls else 0
        ),
        "avg_tool_calls": (
            total_tool_calls / case_count if case_count else 0
        ),
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
    }


def _write_report(
    path: Path,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> None:
    lines = [
        "# G11-04 Diagnosis & Config Analysis Run",
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
        "- Tool sequence: semantic contract; no exact sequence is auto-required.",
        "- Diagnosis, root-cause, remediation, and claim grounding require manual Gold review.",
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
                f"- focus path: `{item['focus_path']}`",
                f"- Gold sources: `{', '.join(item['gold_source_paths'])}`",
                f"- status: `{item['status']}`",
                f"- reason/failure: `{item['reason_code']}` / `{item['failure_code']}`",
                f"- provider calls/repair: `{item['provider_calls_total']}` / `{item['repair_attempted']}` / `{item['repair_succeeded']}`",
                f"- tool sequence: `{' -> '.join(item['tool_sequence']) or '(none)'}`",
                f"- evidence shape: `{', '.join(item['evidence_kinds']) or '(none)'}`; multi-file=`{item['multi_file_evidence']}`; behavior-body-visible=`{item['behavior_body_visible']}`",
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
    label: str = "diagnosis-config-transfer-validation",
    knowledge_url: str | None = None,
    project_url: str | None = None,
) -> Path:
    """Run Formal only after all environment and request infrastructure passes.

    No output directory is created until both preflight requests and all four
    case requests have returned valid HTTP JSON objects.  A structured HTTP
    200 Agent result, including status=failed/refused, remains a valid case.
    """

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
        # _post_json raises for connection errors, HTTP errors, invalid JSON,
        # and non-object responses. Those are infrastructure failures and must
        # not be normalized into a synthetic Agent case.
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
        "schema_version": "g11_04_diagnosis_config_manifest_v1",
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
        "workflow_stages": list(WORKFLOW_STAGES),
        "forbidden_tools": list(FORBIDDEN_TOOLS),
        "case_ids": [case["case_id"] for case in CASES],
        "gold_source_paths": {
            case["case_id"]: case["gold_source_paths"] for case in CASES
        },
        "absolute_paths_in_artifact": False,
        "provider_raw_responses_recorded": False,
        "cot_recorded": False,
        "gold_correctness_auto_scored": False,
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
    parser.add_argument("--label", default="diagnosis-config-transfer-validation")
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
    print(
        json.dumps(
            {"output": str(output), "metrics": metrics},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
