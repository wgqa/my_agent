"""G4-EVAL-06B-03：Gate 4 Tool-Agent Dev baseline 离线封档（0 DeepSeek，纯只读）。

从既有 run artifact 独立复算并验证，证明 committed baseline JSON 不是人工抄错。

用法：
    python scripts/seal_gate4_tool_use_dev.py \
        --run-dir <external_root>/fa4ab9aa5f13

只读操作：不调模型、不建索引、不执行、不修改任何 artifact / dataset / Gold。
产出 seal JSON（默认 docs/experiments/gate4_tool_use_dev_seal.json）。

本脚本不硬编码本机路径；run-dir 由 --run-dir 显式传入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.gate4 import (  # noqa: E402
    FROZEN_EVALUATION_SET_ID,
    Gate4ToolUseEvaluationSet,
)
from evaluation.gate4.evaluator import CaseScore, compute_metrics  # noqa: E402
from evaluation.gate4.runner_models import Gate4ToolUseRunConfig  # noqa: E402

SEAL_SCHEMA_VERSION = "gate4_tool_use_dev_seal_v1"
EXPECTED_RUN_ID = "fa4ab9aa5f13"
ARTIFACT_NAMES = (
    "run_config.json",
    "execution_results.jsonl",
    "case_scores.jsonl",
    "metrics.json",
    "result.json",
    "report.md",
    "artifact_manifest.json",
)
# Gold-only 字段（execution artifact 不得出现）
GOLD_ONLY_KEYS = {
    "category",
    "expected_terminal",
    "expected_first_action",
    "expected_first_tool",
    "expected_first_tools",
    "required_tools",
    "allowed_tool_sequences",
    "forbidden_tools",
    "completion_assertions",
    "allowed_refuse_reason_codes",
    "knowledge_gold",
    "rationale",
    "tags",
}
SECRET_MARKERS = (
    "api_key",
    "Authorization",
    "reasoning_content",
    "raw_output",
    "system_prompt",
    "traceback",
)


class SealError(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def git_head(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise SealError("无法读取 git HEAD")
    return proc.stdout.strip()


def _case_score_from_dict(d: dict) -> CaseScore:
    return CaseScore(
        case_id=d["case_id"],
        category=d["category"],
        expected_terminal=d["expected_terminal"],
        expected_first_action=d["expected_first_action"],
        expected_first_tool=d["expected_first_tool"],
        expected_first_tools=tuple(d["expected_first_tools"]),
        required_tools=tuple(d["required_tools"]),
        forbidden_tools=tuple(d["forbidden_tools"]),
        allowed_tool_sequences=tuple(
            tuple(s) for s in d["allowed_tool_sequences"]
        ),
        actual_first_action=d["actual_first_action"],
        actual_first_tool=d["actual_first_tool"],
        executed_tool_sequence=tuple(d["executed_tool_sequence"]),
        required_tools_hit=d["required_tools_hit"],
        required_tools_total=d["required_tools_total"],
        forbidden_tool_used=d["forbidden_tool_used"],
        unnecessary_tool_call_count=d["unnecessary_tool_call_count"],
        assertions_passed=d["assertions_passed"],
        terminal_correct=d["terminal_correct"],
        termination_correct=d["termination_correct"],
        allowed_sequence_match=d["allowed_sequence_match"],
        status=d["status"],
        reason_code=d["reason_code"],
        failure_code=d["failure_code"],
        iterations=d["iterations"],
        tool_calls=d["tool_calls"],
        tool_errors=d["tool_errors"],
    )


def seal(run_dir: Path, repo_root: Path) -> dict:
    run_dir = run_dir.resolve()
    for name in ARTIFACT_NAMES:
        if not (run_dir / name).is_file():
            raise SealError(f"artifact 缺失: {run_dir / name}")

    baseline_path = (
        repo_root / "docs" / "experiments" / "gate4_tool_use_dev_baseline.json"
    )
    baseline = load_json(baseline_path)
    dataset_path = repo_root / "evaluation" / "gate4" / "data" / "tool_use_dev_v1.jsonl"

    # ---- 3. 独立 SHA 校验 ----
    artifact_hashes = {
        name: {
            "sha256": sha256_bytes((run_dir / name).read_bytes()),
            "size_bytes": (run_dir / name).stat().st_size,
        }
        for name in ARTIFACT_NAMES
    }
    baseline_hashes = baseline["artifacts"]
    mismatch = [
        name
        for name in ARTIFACT_NAMES
        if artifact_hashes[name] != baseline_hashes.get(name)
    ]
    if mismatch:
        raise SealError(f"artifact SHA/size 与 baseline 不一致: {mismatch}")
    artifact_verification_passed = True

    # ---- 4. RunConfig 身份重算 ----
    run_config = load_json(run_dir / "run_config.json")
    cfg_fields = {k: v for k, v in run_config.items() if k != "run_id"}
    cfg = Gate4ToolUseRunConfig(**cfg_fields)
    recomputed_run_id = cfg.compute_run_id()
    run_identity_ok = (
        recomputed_run_id == EXPECTED_RUN_ID
        and run_config.get("run_id") == EXPECTED_RUN_ID
    )
    if not run_identity_ok:
        raise SealError(f"run_id 重算不符: {recomputed_run_id}")
    identity_checks = {
        "source_commit": (cfg.source_commit == run_config["source_commit"]),
        "evaluation_set_id": (
            cfg.evaluation_set_id == FROZEN_EVALUATION_SET_ID
            == baseline["run"]["evaluation_set_id"]
        ),
        "dataset_jsonl_sha256": (
            cfg.dataset_jsonl_sha256 == baseline["run"]["dataset_jsonl_sha256"]
        ),
        "knowledge_corpus_id": (
            cfg.knowledge_corpus_id == baseline["run"]["knowledge_corpus_id"]
        ),
        "knowledge_corpus_file_count": (
            cfg.knowledge_corpus_file_count
            == baseline["run"]["knowledge_corpus_file_count"]
        ),
        "provider_model": (
            cfg.provider == "deepseek" and cfg.model == "deepseek-chat"
        ),
        "prompt": (cfg.prompt_version and len(cfg.prompt_sha256) == 64),
        "toolset": len(cfg.toolset_sha256) == 64,
        "budget": (cfg.max_agent_iterations == 5 and cfg.max_tool_calls == 4
                   and cfg.max_tool_errors == 2),
        "knowledge": (cfg.knowledge_strategy == "bm25"
                      and cfg.knowledge_top_k == 5),
        "chunk": (cfg.chunk_strategy == "recursive" and cfg.chunk_size == 512
                  and cfg.chunk_overlap == 64),
        "temp": cfg.temperature == 0,
        "max_tokens": cfg.max_tokens == 600,
        "retry": cfg.max_retries == 0,
        "timeout": cfg.timeout_seconds == 20.0,
    }
    if not all(identity_checks.values()):
        raise SealError(f"身份字段校验失败: {identity_checks}")
    run_identity_recomputed = True

    # ---- 5. 行数 / case 集合 ----
    execution = load_jsonl(run_dir / "execution_results.jsonl")
    case_scores = load_jsonl(run_dir / "case_scores.jsonl")
    frozen = Gate4ToolUseEvaluationSet.load_jsonl(dataset_path)
    frozen_ids = {c.case_id for c in frozen.cases}
    exec_ids = {r["case_id"] for r in execution}
    score_ids = {s["case_id"] for s in case_scores}
    case_set_ok = (
        len(execution) == 24
        and len(case_scores) == 24
        and exec_ids == score_ids == frozen_ids
    )
    if not case_set_ok:
        raise SealError("行数或 case 集合不一致")
    case_set_verified = True

    # ---- 6. 独立复算 15 指标 ----
    scores = [_case_score_from_dict(s) for s in case_scores]
    recomputed_metrics = compute_metrics(scores)
    metrics_json = load_json(run_dir / "metrics.json")["metrics"]
    result_json = load_json(run_dir / "result.json")
    baseline_metrics = baseline["metrics"]
    metric_consistent = (
        recomputed_metrics == metrics_json
        == result_json["metrics"]
        == baseline_metrics
    )
    if not metric_consistent:
        raise SealError("15 指标四方不一致")
    metrics_recomputed = True

    # ---- 7. 调用统计 ----
    decision_calls = sum(r["provider"]["decision_call_count"] for r in execution)
    iterations = sum(r["iterations_used"] for r in execution)
    tool_calls = sum(r["tool_calls_used"] for r in execution)
    tool_errors = sum(r["tool_errors_used"] for r in execution)
    tokens_in = [r["provider"]["input_tokens"] for r in execution]
    tokens_out = [r["provider"]["output_tokens"] for r in execution]
    has_full_tokens = all(t is not None for t in tokens_in) and all(
        t is not None for t in tokens_out
    )
    input_tokens = sum(tokens_in) if has_full_tokens else None
    output_tokens = sum(tokens_out) if has_full_tokens else None
    latency = round(
        sum(r["provider"]["total_latency_ms"] for r in execution), 1
    )
    stats_ok = (
        decision_calls == 41
        and iterations == 41
        and tool_calls == 17
        and tool_errors == 0
        and input_tokens == 38443
        and output_tokens == 1317
        and latency == baseline["run"]["latency_ms_total"]
    )
    if not stats_ok:
        raise SealError(
            f"调用统计不一致: calls={decision_calls} iter={iterations} "
            f"tcalls={tool_calls} terr={tool_errors} in={input_tokens} "
            f"out={output_tokens} lat={latency}"
        )
    provider_totals_recomputed = True

    # ---- 8. Case summary 重算 ----
    status_counts = Counter(s["status"] for s in case_scores)
    codes = Counter()
    for s in case_scores:
        if s["reason_code"]:
            codes[s["reason_code"]] += 1
        if s["failure_code"]:
            codes[s["failure_code"]] += 1
    non_complete = sorted(
        s["case_id"]
        for s in case_scores
        if not (s["terminal_correct"] and s["assertions_passed"])
    )
    multi_seq = {
        s["case_id"]: {
            "executed_tool_sequence": s["executed_tool_sequence"],
            "allowed_sequence_match": s["allowed_sequence_match"],
        }
        for s in case_scores
        if s["category"] == "multi_step"
    }
    expected_summary = {
        "completed": 16,
        "refused": 6,
        "failed": 2,
        "ACTION_PARSE_FAILED": 2,
        "AGENT_BUDGET_EXCEEDED": 1,
        "non_complete": ["g4q013", "g4q018", "g4q019", "g4q020"],
    }
    summary_ok = (
        status_counts["completed"] == 16
        and status_counts["refused"] == 6
        and status_counts["failed"] == 2
        and codes.get("ACTION_PARSE_FAILED") == 2
        and codes.get("AGENT_BUDGET_EXCEEDED") == 1
        and non_complete == expected_summary["non_complete"]
        and multi_seq == baseline["case_summary"]["multi_step_executed_sequences"]
    )
    if not summary_ok:
        raise SealError(f"case summary 不一致: {summary_ok}")
    case_summary = {
        "status_counts": dict(status_counts),
        "code_counts": dict(codes),
        "non_task_completion_case_ids": non_complete,
        "multi_step_executed_sequences": multi_seq,
    }

    # ---- 9. Secret / Gold 泄漏扫描 ----
    gold_leak = []
    secret_leak = []
    for i, rec in enumerate(execution):
        leak_keys = set(rec.keys()) & GOLD_ONLY_KEYS
        if leak_keys:
            gold_leak.append((i, sorted(leak_keys)))
        serialized = json.dumps(rec, ensure_ascii=False)
        for marker in SECRET_MARKERS:
            if marker.lower() in serialized.lower():
                secret_leak.append((i, marker))
    if gold_leak or secret_leak:
        raise SealError(f"泄漏: gold={gold_leak} secret={secret_leak}")
    gold_leakage_check = True
    secret_check = True

    return {
        "schema_version": SEAL_SCHEMA_VERSION,
        "run_id": EXPECTED_RUN_ID,
        "baseline_source_commit": baseline["run"]["source_commit"],
        "baseline_record_commit": git_head(repo_root),
        "verification_commit": git_head(repo_root),
        "artifact_verification_passed": artifact_verification_passed,
        "run_identity_recomputed": run_identity_recomputed,
        "case_set_verified": case_set_verified,
        "metrics_recomputed": metrics_recomputed,
        "provider_totals_recomputed": provider_totals_recomputed,
        "gold_leakage_check": gold_leakage_check,
        "secret_check": secret_check,
        "artifact_hashes": artifact_hashes,
        "headline_metrics": recomputed_metrics,
        "case_summary": case_summary,
        "verdict": "valid_public_dev_baseline",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Gate 4 Tool-Agent Dev baseline seal")
    parser.add_argument("--run-dir", required=True,
                        help="既有 run artifact 目录（外部路径，不硬编码）")
    parser.add_argument("--seal-out", default=None,
                        help="seal JSON 输出路径（默认仓库 docs/experiments）")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    repo_root = Path(__file__).resolve().parents[1]
    seal_out = Path(args.seal_out) if args.seal_out else (
        repo_root / "docs" / "experiments" / "gate4_tool_use_dev_seal.json"
    )

    try:
        result = seal(Path(args.run_dir), repo_root)
    except SealError as exc:
        print(f"SEAL FAIL: {exc}")
        return 1

    seal_out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"SEAL PASS: verdict={result['verdict']} run_id={result['run_id']}")
    print(f"seal written: {seal_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
