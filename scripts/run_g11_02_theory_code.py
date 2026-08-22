"""Run the fixed G11-02 Theory <-> Code cases against a local API.

The runner stores only the public response contract and safe trace fields. It
does not capture provider responses, prompts, credentials, or local paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SOURCE_COMMIT = "540b9bc674a76f535947179329bee572fdb4148"
PROJECT_IDENTITY = "my_agent_repository"
KNOWLEDGE_CORPUS_ID = "870e5864df67"
PROMPT_VERSION = "tool_agent_decision_prompt_v3"
PROMPT_SHA256 = "a6092bffdfee3236575ae0f801985e6c8d6aecedba339672bde838f1daed1dc1"
TOOLSET_SHA256 = "9b846d9e72e8d5536c2b3de8730f61433a96d7ff59f557a70f07c6a0c33bb85f"
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
    }
)

CASES = (
    {
        "case_id": "TC01",
        "question": "RRF 为什么适合融合 Dense 和 BM25？结合当前项目说明 HybridRetriever 是怎样实现 RRF 的，特别是某个文档只在一路召回时如何计分，以及为什么还需要确定性的 tie-break。",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": ["K1", "K2", "C1", "C2", "C3", "C4"],
    },
    {
        "case_id": "TC02",
        "question": "MMR 主要解决检索结果里的什么问题？结合当前项目的 MMRRetriever，说明 lambda_param 怎样平衡相关性和多样性，以及为什么实现会先取 top_k_initial 候选再逐个选择。",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": ["K1", "K2", "C1", "C2", "C3", "C4", "C5"],
    },
    {
        "case_id": "TC03",
        "question": "为什么 RAG 通常先召回较多候选再 rerank？当前项目 Pipeline.query 怎样决定 candidate_k 和 final_k，Reranker 失败时怎样降级，最后又怎样保证用户请求的 top_k？这些设计体现了什么工程权衡？",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": ["K1", "K2", "K3", "C1", "C2", "C3", "C4", "C5"],
    },
    {
        "case_id": "TC04",
        "question": "RAG 为什么不能把所有检索结果直接塞给模型？结合当前 Pipeline.query 说明项目怎样计算 context token budget、组织带引用的 context，并在生成后验证 citation；这几步分别防什么问题？",
        "required": REQUIRED_TOOLS,
        "forbidden": FORBIDDEN_TOOLS,
        "obligations": ["K1", "K2", "K3", "K4", "C1", "C2", "C3", "C4", "C5"],
    },
)


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
                f"- tool sequence: `{' -> '.join(item['tool_sequence']) or '(none)'}`",
                f"- iterations/tool calls/errors: `{item['iterations_used']}/{item['tool_calls_used']}/{item['tool_errors_used']}`",
                f"- evidence kinds: `{', '.join(item['evidence_kinds']) or '(none)'}`",
                f"- Gold obligations: `{', '.join(item['gold_obligations'])}`",
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
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--prompt-version", default=PROMPT_VERSION)
    parser.add_argument("--prompt-sha256", default=PROMPT_SHA256)
    args = parser.parse_args()

    output = Path(args.output_root).resolve() / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": args.run_id,
        "label": args.label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": args.url,
        "source_commit": SOURCE_COMMIT,
        "project_identity": PROJECT_IDENTITY,
        "knowledge_corpus_id": KNOWLEDGE_CORPUS_ID,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "prompt_version": args.prompt_version,
        "prompt_sha256": args.prompt_sha256,
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
    _write_report(output / "comparison_report.md", manifest, cases, metrics)
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
