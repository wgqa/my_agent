"""Run the fixed G11-02 Theory <-> Code cases against a local API.

The runner stores only the public response contract and safe trace fields. It
does not capture provider responses, prompts, credentials, or local paths.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_IDENTITY = "my_agent_repository"
KNOWLEDGE_CORPUS_ID = "870e5864df67"
TOOLSET_SHA256 = "9b846d9e72e8d5536c2b3de8730f61433a96d7ff59f557a70f07c6a0c33bb85f"
KNOWN_PROMPT_IDENTITIES = {
    "tool_agent_decision_prompt_v3": "a6092bffdfee3236575ae0f801985e6c8d6aecedba339672bde838f1daed1dc1",
    "engineering_agent_decision_prompt_v1": "aa99e543d2bfbd3315113842e5377bf52bff7dcf50fc843840785ddee34dfa0a",
    "engineering_agent_decision_prompt_v2": "14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107",
}
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_PROMPT_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
REQUIRED_TOOLS = ("knowledge_search", "code_search", "read_project_context")
FORBIDDEN_TOOLS = ("changed_files", "git_diff", "find_tests", "calculator")
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

CASES = (
    {
        "case_id": "TC01",
        "question": "RRF 为什么适合融合 Dense 和 BM25？结合当前项目说明 HybridRetriever 是怎样实现 RRF 的，特别是某个文档只在一路召回时如何计分，以及为什么还需要确定性的 tie-break。",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": [
            {"id": "K1", "description": "RRF 基于 rank 融合，而不是直接比较 Dense/BM25 不同尺度的 raw score。"},
            {"id": "K2", "description": "核心形式为各通道 1/(k + rank) 累加，k 是平滑常数。"},
            {"id": "C1", "description": "HybridRetriever 分别构建 dense_rank_map / sparse_rank_map。"},
            {"id": "C2", "description": "all_ids 是两路命中 ID 的 union。"},
            {"id": "C3", "description": "文档没在某一路命中时，该通道贡献为 0，不给虚拟排名。"},
            {"id": "C4", "description": "最终存在 deterministic RRF tie-break，当前策略为 chunk_id_asc。"},
        ],
    },
    {
        "case_id": "TC02",
        "question": "MMR 主要解决检索结果里的什么问题？结合当前项目的 MMRRetriever，说明 lambda_param 怎样平衡相关性和多样性，以及为什么实现会先取 top_k_initial 候选再逐个选择。",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": [
            {"id": "K1", "description": "MMR 平衡 query relevance 与结果之间的 diversity/redundancy。"},
            {"id": "K2", "description": "使用 MMR 需要评估是否因为追求多样性损失关键证据。"},
            {"id": "C1", "description": "项目先从 vector store 获取 top_k_initial candidates。"},
            {"id": "C2", "description": "对每个剩余候选计算 query similarity。"},
            {"id": "C3", "description": "同时计算候选与已选择集合的最大 similarity。"},
            {"id": "C4", "description": "当前公式为 lambda * relevance - (1-lambda) * redundancy。"},
            {"id": "C5", "description": "迭代选择直到 top_k。"},
        ],
    },
    {
        "case_id": "TC03",
        "question": "为什么 RAG 通常先召回较多候选再 rerank？当前项目 Pipeline.query 怎样决定 candidate_k 和 final_k，Reranker 失败时怎样降级，最后又怎样保证用户请求的 top_k？这些设计体现了什么工程权衡？",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": [
            {"id": "K1", "description": "Retriever 以较低成本扩大 recall；reranker 用 query-document interaction 提升候选排序质量。"},
            {"id": "K2", "description": "Reranker 更贵，因此一般只作用在较小候选集合。"},
            {"id": "K3", "description": "是否使用 reranker 应结合 Recall、MRR/nDCG、答案质量、延迟和成本评估。"},
            {"id": "C1", "description": "candidate_k 优先读取 reranker_candidate_k，否则使用 max(config.top_k * 3, k * 3)。"},
            {"id": "C2", "description": "final_k 优先 reranker_final_k，否则 k。"},
            {"id": "C3", "description": "reranker_enabled 时才执行 rerank。"},
            {"id": "C4", "description": "reranker 异常时保留已有 retrieval results 并降级继续。"},
            {"id": "C5", "description": "后续仍执行 retrieved[:k]，保证用户最终请求数量上限。"},
        ],
    },
    {
        "case_id": "TC04",
        "question": "RAG 为什么不能把所有检索结果直接塞给模型？结合当前 Pipeline.query 说明项目怎样计算 context token budget、组织带引用的 context，并在生成后验证 citation；这几步分别防什么问题？",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": [
            {"id": "K1", "description": "Context 受模型窗口/token budget 限制，不应无界拼接。"},
            {"id": "K2", "description": "过多或重复证据会增加噪音并存在 Lost in the Middle 等风险。"},
            {"id": "K3", "description": "稳定 source/citation 编号便于应用层验证。"},
            {"id": "K4", "description": "模型输出引用字符串本身不等于引用正确，需要应用层校验。"},
            {"id": "C1", "description": "Pipeline 调用 generator.available_context_tokens(question) 得到 evidence context 可用预算。"},
            {"id": "C2", "description": "使用 ContextAssembler(max_context_tokens=budget)。"},
            {"id": "C3", "description": "assemble 后的 blocks 进入 generator。"},
            {"id": "C4", "description": "生成后使用 CitationValidator.validate(answer, blocks)。"},
            {"id": "C5", "description": "API/source result 保存 citation_id 和 invalid citation 信息。"},
        ],
    },
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
    """Validate the declared commit against the actual tested checkout."""
    if type(value) is not str or not _COMMIT_RE.fullmatch(value):
        raise ValueError("source_commit must be exactly 40 hexadecimal characters")
    normalized = value.lower()

    requested_root = Path(git_root)
    top_level = _run_git(requested_root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0 or not top_level.stdout.strip():
        raise ValueError("git_root is not a Git working tree")
    # Keep the operator-provided cwd for subsequent Git calls. On Windows
    # this avoids re-encoding a non-ASCII path returned by Git.
    checkout_root = requested_root

    actual_head = _run_git(checkout_root, "rev-parse", "HEAD")
    actual_head_value = actual_head.stdout.strip().lower()
    if actual_head.returncode != 0 or not _COMMIT_RE.fullmatch(actual_head_value):
        raise ValueError("git_root HEAD is not a valid commit")
    if actual_head_value != normalized:
        raise ValueError("declared source_commit does not match git_root HEAD")

    verified = _run_git(checkout_root, "cat-file", "-e", f"{normalized}^{{commit}}")
    if verified.returncode != 0:
        raise ValueError("source_commit is not a valid commit object")

    status = _run_git(checkout_root, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        raise ValueError("could not inspect git_root tracked status")
    if status.stdout.strip():
        raise ValueError("git_root has tracked modifications")
    return normalized


def validate_prompt_identity(version: object, sha256: object) -> tuple[str, str]:
    if type(version) is not str or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("prompt_version must be a bounded non-empty identifier")
    if version not in KNOWN_PROMPT_IDENTITIES:
        raise ValueError("prompt_version is not a supported G11-02 identity")
    if type(sha256) is not str or not _SHA256_RE.fullmatch(sha256):
        raise ValueError("prompt_sha256 must be exactly 64 hexadecimal characters")
    normalized_sha = sha256.lower()
    expected_sha = KNOWN_PROMPT_IDENTITIES.get(version)
    if expected_sha is not None and expected_sha != normalized_sha:
        raise ValueError("prompt_version and prompt_sha256 do not match")
    return version, normalized_sha


def _post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {body[:200]}") from exc


def _get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {body[:200]}") from exc


def _knowledge_url(query_url: str) -> str:
    parsed = urllib.parse.urlsplit(query_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("engineering query URL must be an absolute HTTP URL")
    path = parsed.path.rstrip("/")
    suffix = "/engineering/query"
    if not path.endswith(suffix):
        raise ValueError("engineering query URL must end with /engineering/query")
    knowledge_path = path[: -len(suffix)] + "/engineering/knowledge"
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, knowledge_path, "", "")
    )


def validate_knowledge_backend(status: object) -> dict:
    """Require the service's verified backend identity before any query call."""

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
    for field, value in expected.items():
        if status.get(field) != value:
            raise ValueError(
                f"Engineering Knowledge status mismatch: {field}={status.get(field)!r}"
            )
    return {field: status[field] for field in expected}


def _safe_trace(trace: object) -> list[dict]:
    if not isinstance(trace, list):
        return []
    return [
        {key: event[key] for key in SAFE_TRACE_KEYS if key in event}
        for event in trace
        if isinstance(event, dict)
    ]


def _tool_sequence(trace: list[dict]) -> list[str]:
    return [
        event["tool_name"]
        for event in trace
        if event.get("event_type") == "tool_observation"
        and isinstance(event.get("tool_name"), str)
    ]


def _evidence_kinds(response: dict) -> list[str]:
    return [
        item["kind"]
        for item in response.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    ]


def _normalize_case(case: dict, response: dict, elapsed_ms: float) -> dict:
    trace = _safe_trace(response.get("trace"))
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
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "status": response.get("status"),
        "answer": response.get("answer"),
        "reason_code": response.get("reason_code"),
        "failure_code": response.get("failure_code"),
        "iterations_used": response.get("iterations_used"),
        "tool_calls_used": response.get("tool_calls_used"),
        "tool_errors_used": response.get("tool_errors_used"),
        "provider_calls_total": provider_calls,
        "repair_attempted": repair_attempted,
        "repair_succeeded": repair_succeeded,
        "initial_parse_categories": parse_categories,
        "latency_ms": round(elapsed_ms, 2),
        "trace": trace,
        "tool_sequence": sequence,
        "evidence": response.get("evidence", []),
        "evidence_kinds": _evidence_kinds(response),
        "required_tools": list(case["required"]),
        "forbidden_tools": list(case["forbidden"]),
        "gold_obligations": case["obligations"],
    }


def _metrics(cases: list[dict]) -> dict:
    completed = sum(item.get("status") == "completed" for item in cases)
    cross_source = sum(
        {"knowledge", "project_code"}.issubset(set(item["evidence_kinds"]))
        for item in cases
    )
    required_coverage = {
        tool: sum(tool in item["tool_sequence"] for item in cases)
        for tool in REQUIRED_TOOLS
    }
    forbidden_calls = sum(
        any(tool in FORBIDDEN_TOOLS for tool in item["tool_sequence"])
        for item in cases
    )
    return {
        "case_count": len(cases),
        "completed_cases": completed,
        "completion_rate": completed / len(cases) if cases else 0,
        "cross_source_cases": cross_source,
        "cross_source_evidence_rate": cross_source / len(cases) if cases else 0,
        "required_tool_coverage": required_coverage,
        "required_tool_coverage_rate": (
            sum(required_coverage.values()) / (len(REQUIRED_TOOLS) * len(cases))
            if cases
            else 0
        ),
        "forbidden_tool_calls": forbidden_calls,
        "forbidden_tool_call_rate": forbidden_calls / len(cases) if cases else 0,
        "avg_tool_calls": (
            sum(item["tool_calls_used"] or 0 for item in cases) / len(cases)
            if cases
            else 0
        ),
        "avg_iterations": (
            sum(item["iterations_used"] or 0 for item in cases) / len(cases)
            if cases
            else 0
        ),
        "evidence_count": sum(len(item.get("evidence", [])) for item in cases),
        "refused_cases": sum(item.get("status") == "refused" for item in cases),
        "failed_cases": sum(item.get("status") == "failed" for item in cases),
        "provider_calls_total": sum(item["provider_calls_total"] for item in cases),
        "repair_attempted_cases": sum(item["repair_attempted"] for item in cases),
        "repair_succeeded_cases": sum(item["repair_succeeded"] for item in cases),
        "parse_failure_cases": sum(
            bool(item["initial_parse_categories"]) for item in cases
        ),
        "initial_parse_categories": [
            category
            for item in cases
            for category in item["initial_parse_categories"]
        ],
    }


def _write_report(path: Path, manifest: dict, cases: list[dict], metrics: dict) -> None:
    lines = [
        "# G11-02 Theory <-> Code Run",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- source_commit: `{manifest['source_commit']}`",
        f"- endpoint: `{manifest['endpoint']}`",
        f"- prompt_version: `{manifest['prompt_version']}`",
        f"- prompt_sha256: `{manifest['prompt_sha256']}`",
        f"- knowledge_corpus_id: `{manifest['knowledge_corpus_id']}`",
        f"- knowledge_backend: `{json.dumps(manifest['knowledge_backend'], ensure_ascii=False, sort_keys=True)}`",
        "- correctness: not automatically scored; Gold obligations are provided for manual audit.",
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
                f"- status: `{item['status']}`",
                f"- reason_code: `{item['reason_code']}`",
                f"- failure_code: `{item['failure_code']}`",
                f"- provider calls/repair attempted/succeeded: `{item['provider_calls_total']}/{item['repair_attempted']}/{item['repair_succeeded']}`",
                f"- tool sequence: `{' -> '.join(item['tool_sequence']) or '(none)'}`",
                f"- iterations/tool calls/errors: `{item['iterations_used']}/{item['tool_calls_used']}/{item['tool_errors_used']}`",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/engineering/query")
    parser.add_argument(
        "--knowledge-url",
        default=None,
        help="Optional backend status URL; defaults to /engineering/knowledge on --url host",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--git-root",
        required=True,
        help="Git checkout root of the API server being evaluated",
    )
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--prompt-sha256", required=True)
    args = parser.parse_args()

    source_commit = validate_source_commit(args.source_commit, git_root=args.git_root)
    prompt_version, prompt_sha256 = validate_prompt_identity(
        args.prompt_version, args.prompt_sha256
    )
    knowledge_status = validate_knowledge_backend(
        _get_json(args.knowledge_url or _knowledge_url(args.url))
    )
    output = Path(args.output_root).resolve() / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": args.run_id,
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
        "toolset_sha256": TOOLSET_SHA256,
        "budget": {"max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2},
        "case_ids": [case["case_id"] for case in CASES],
        "absolute_paths_in_artifact": False,
        "provider_raw_responses_recorded": False,
        "cot_recorded": False,
    }
    cases: list[dict] = []
    for case in CASES:
        started = time.perf_counter()
        response = _post_json(args.url, {"question": case["question"]})
        cases.append(_normalize_case(case, response, (time.perf_counter() - started) * 1000))

    metrics = _metrics(cases)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "case_results.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    (output / "summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_report(output / "run_report.md", manifest, cases, metrics)
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
