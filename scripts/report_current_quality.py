"""Offline quality/cost report from recorded requests; never calls a provider.

Scores are the archived whole-answer manual reviews, not inferred from status.
Historical files remain untouched. A current-code comparison prevents presenting
old live results as acceptance of a later working tree.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = "evaluation/core_workflows_20261004"
PHASE_LABELS = {
    "development-ready": "原开发基线",
    "development-candidate": "提示词候选（未晋升）",
    "development-reader": "旧 Reader 候选（未晋升）",
    "development-planner": "Planner 候选（未晋升）",
    "confirmation": "恢复原主线的检查",
    "guided": "早期明确输入入口",
    "acquisition/development": "对象 Reader：原六题",
    "acquisition/confirmation": "对象 Reader：新输入检查",
    "acquisition/entry_confirmation": "文本匹配修订后入口",
    "acquisition/change_entry_confirmation": "变更路径入口修订",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_json(path: Path, expected_sha256: str):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Archive SHA mismatch: {path.name}")
    return json.loads(raw)


def scores(items) -> dict:
    counts = Counter(item["score"] for item in items)
    return {label: counts[label] for label in ("PASS", "PARTIAL", "FAIL")}


def request_usage(row: dict) -> dict:
    result = {"planner_calls": 0, "decision_calls": 0, "input_tokens": 0, "output_tokens": 0}
    identities = set()
    for event in row["observations"]:
        stage = event["stage"]
        if stage not in {"planner", "decision_metadata"}:
            continue
        metadata = event["call_metadata"] if stage == "planner" else event["metadata"]
        if not isinstance(metadata, dict):
            raise ValueError("Provider usage metadata missing")
        for key in ("call_count", "input_tokens", "output_tokens"):
            if type(metadata.get(key)) is not int or metadata[key] < 0:
                raise ValueError(f"Provider usage missing/invalid: {key}")
        result["planner_calls" if stage == "planner" else "decision_calls"] += metadata["call_count"]
        result["input_tokens"] += metadata["input_tokens"]
        result["output_tokens"] += metadata["output_tokens"]
        identities.add(tuple(metadata.get(key) for key in ("provider", "model", "prompt_version", "prompt_sha256")))
    if not result["planner_calls"] or not result["decision_calls"]:
        raise ValueError("Request is missing Planner or Decision observations")
    result["provider_calls"] = result["planner_calls"] + result["decision_calls"]
    result["provider_identities"] = [dict(zip(("provider", "model", "prompt_version", "prompt_sha256"), item)) for item in sorted(identities)]
    return result


def summarize_phase(rows: list[dict], reviews: list[dict]) -> dict:
    by_id = {item["id"]: item for item in reviews}
    if len(by_id) != len(reviews) or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate case ID")
    if set(by_id) != {row["id"] for row in rows} or not rows:
        raise ValueError("Raw/review case IDs disagree or phase is empty")
    cases = []
    for row in rows:
        review, output = by_id[row["id"]], row["public_response"]
        if review["score"] not in {"PASS", "PARTIAL", "FAIL"} or type(review["boundary_control"]) is not bool:
            raise ValueError("Invalid recorded review")
        if not row["transport_ok"]:
            raise ValueError("Transport failure must be reviewed before reporting")
        for key, limit in (("iterations_used", 5), ("tool_calls_used", 4), ("tool_errors_used", 2)):
            if type(output.get(key)) is not int or not 0 <= output[key] <= limit:
                raise ValueError(f"Runtime budget violation: {key}")
        elapsed = row["elapsed_seconds"]
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid recorded elapsed time")
        if "conversations/" in row["path"] and row.get("persistence_ok") is not True:
            raise ValueError("Conversation persistence mismatch")
        cases.append({
            "id": row["id"], "project": row["project"], "cohort": row["cohort"],
            "score": review["score"], "review_reason": review["reason"],
            "boundary_control": review["boundary_control"], "status": output["status"],
            "reason_code": output.get("reason_code"), "failure_code": output.get("failure_code"),
            "elapsed_seconds": elapsed, "tool_calls": output["tool_calls_used"],
            **request_usage(row),
        })
    elapsed = sorted(case["elapsed_seconds"] for case in cases)
    return {
        "requests": len(cases), "core_scores": scores(case for case in cases if not case["boundary_control"]),
        "boundary_scores": scores(case for case in cases if case["boundary_control"]),
        "statuses": dict(Counter(case["status"] for case in cases)),
        "stop_codes": dict(Counter(case["reason_code"] or case["failure_code"] for case in cases if case["reason_code"] or case["failure_code"])),
        **{key: sum(case[key] for case in cases) for key in ("planner_calls", "decision_calls", "provider_calls", "input_tokens", "output_tokens", "tool_calls")},
        "p50_elapsed_seconds": round(statistics.median(elapsed), 3),
        "p95_elapsed_seconds": round(elapsed[math.ceil(len(elapsed) * .95) - 1], 3),
        "cases": cases,
    }


def current_identity(repo_root: Path, live_hashes: dict) -> dict:
    recorded = {name: value for name, value in live_hashes.items() if name.startswith(("api/", "core/", "ui/")) or name == "config.yaml"}
    actual_paths = [path for part in ("api", "core", "ui") for path in (repo_root / part).rglob("*.py")]
    if (repo_root / "config.yaml").is_file():
        actual_paths.append(repo_root / "config.yaml")
    current = {path.relative_to(repo_root).as_posix(): digest(path) for path in sorted(actual_paths)}
    changed = sorted(name for name, value in recorded.items() if name in current and current[name] != value)
    missing, unrecorded = sorted(set(recorded) - set(current)), sorted(set(current) - set(recorded))
    return {
        "matches_last_live_product_files": not (changed or missing or unrecorded),
        "changed_since_last_live": changed, "missing_since_last_live": missing,
        "new_unrecorded_product_files": unrecorded, "current_product_sha256": current,
        "current_product_fingerprint": hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest(),
    }


def build_report(repo_root: Path = REPO_ROOT) -> dict:
    archive = repo_root / ARCHIVE
    seal_path = archive / "acquisition/archive_manifest.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    frozen = seal["files_sha256"]
    # Verify historical evidence only. Later production edits are a version
    # difference, not corruption of the previous evaluation archive.
    checked = {name: value for name, value in frozen.items() if name.startswith(ARCHIVE + "/")}
    for name, value in checked.items():
        if digest(repo_root / name) != value:
            raise ValueError(f"Archive SHA mismatch: {name}")
    phases, raw_phases, manifests = {}, {}, {}
    for relative in ("", "acquisition"):
        base = archive / relative
        review = verified_json(base / "manual_review.json", frozen[(base / "manual_review.json").relative_to(repo_root).as_posix()])
        for phase, data in review["phases"].items():
            key = f"{relative}/{phase}" if relative else phase
            raw_path, manifest_path = base / "raw" / phase / "live_results.jsonl", base / "raw" / phase / "run_manifest.json"
            raw_hash = frozen[raw_path.relative_to(repo_root).as_posix()]
            if data.get("results_sha256", raw_hash) != raw_hash:
                raise ValueError("Review and sealed raw hash disagree")
            rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
            manifest = verified_json(manifest_path, frozen[manifest_path.relative_to(repo_root).as_posix()])
            if manifest["planned_requests"] != len(rows):
                raise ValueError("Manifest request count disagrees")
            phases[key] = {
                "label": PHASE_LABELS[key], **summarize_phase(rows, data["reviews"]),
                "raw_path": raw_path.relative_to(repo_root).as_posix(), "raw_sha256": raw_hash,
                "manifest_sha256": frozen[manifest_path.relative_to(repo_root).as_posix()],
                "started_utc": manifest["started_utc"], "code_head": manifest["code_head"],
            }
            raw_phases[key], manifests[key] = rows, manifest
    if set(phases) != set(PHASE_LABELS):
        raise ValueError("Unexpected phase set")
    old, new = "development-ready", "acquisition/development"
    old_rows, new_rows = {r["id"]: r for r in raw_phases[old]}, {r["id"]: r for r in raw_phases[new]}
    if set(old_rows) != set(new_rows) or any(old_rows[key]["question"] != new_rows[key]["question"] for key in old_rows) or manifests[old]["projects"] != manifests[new]["projects"]:
        raise ValueError("Development comparison has different questions or source identities")
    latest_cases = [case for case in phases["acquisition/entry_confirmation"]["cases"] if case["id"] in {"E-C", "E-D"}]
    latest_cases += phases["acquisition/change_entry_confirmation"]["cases"]
    last = manifests["acquisition/change_entry_confirmation"]
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True)
    return {
        "schema_version": "current_quality_report_v1", "independent_acceptance": False,
        "review_method": "Archived same-developer whole-answer source review; no rejudging or provider calls.",
        "archive_seal_sha256": digest(seal_path), "historical_files_verified": len(checked),
        "runtime_budget": {"decisions": 5, "tool_calls": 4, "tool_errors": 2},
        "current_code_head": git.stdout.strip(), "last_live_code_head": last["code_head"],
        "last_live_started_utc": last["started_utc"], **current_identity(repo_root, last["input_sha256"]),
        "same_input_development": {"baseline": old, "object_reader": new, "runs_per_case_per_version": 1},
        "latest_three_entries": {"selection": "Latest recorded configuration/document entries plus revised changed-path input; earlier failed input remains in phases.", "scores": scores(latest_cases), "cases": latest_cases},
        "experimental_usage_totals": {key: sum(phase[key] for phase in phases.values()) for key in ("requests", "planner_calls", "decision_calls", "provider_calls", "input_tokens", "output_tokens")},
        "phases": phases,
        "limitations": [
            "No merged success rate: candidate arms, changed inputs, revisions and boundary controls differ.",
            "completed, source fidelity and answer correctness are separate measurements.",
            "p95 uses nearest rank on small sequential samples; not load testing, an SLA or independent acceptance.",
            "Token usage includes Planner and Decision repair calls; money/cache discounts are not inferred.",
            "Later production changes have offline checks only unless new live evidence is explicitly recorded.",
        ],
    }


def render_markdown(report: dict) -> str:
    def triplet(value):
        return " / ".join(str(value[k]) for k in ("PASS", "PARTIAL", "FAIL"))
    totals = report["experimental_usage_totals"]
    comparison = report["same_input_development"]
    baseline_scores = report["phases"][comparison["baseline"]]["core_scores"]
    object_scores = report["phases"][comparison["object_reader"]]["core_scores"]
    lines = [
        "# 当前版本质量、调用成本与基线索引", "",
        "由 `scripts/report_current_quality.py` 离线生成，保留历史原始结果及负实验。内容评分沿用同一开发助手的完整答案审查，非独立验收。第一项核心可靠性仍 OPEN。", "",
        f"记录共 **{totals['requests']} 个请求 / {totals['provider_calls']} 次实际 provider 调用**（Planner {totals['planner_calls']}、Decision 含解析修复 {totals['decision_calls']}）；输入 {totals['input_tokens']:,}、输出 {totals['output_tokens']:,} tokens。这是整个开发实验的消耗，不能当单版本产品成本或账单金额。", "",
        "## 版本与证据", "",
        f"最近真实检查：`{report['last_live_started_utc']}`；Git HEAD `{report['current_code_head']}`。工作区代码以 JSON 内逐文件 SHA 和 fingerprint 绑定，HEAD 相同不代表代码相同。",
        f"历史材料校验 {report['historical_files_verified']} 文件；封档索引 SHA `{report['archive_seal_sha256']}`。", "",
    ]
    if report["matches_last_live_product_files"]:
        lines.append("当前生产文件与最近真实检查记录一致。")
    else:
        paths = report["changed_since_last_live"] + report["missing_since_last_live"] + report["new_unrecorded_product_files"]
        lines.append("**当前工作区与最近真实检查有差异；下表属于已记录版本，不代表修改后代码经过新一轮付费验收。** 差异文件：" + "、".join(f"`{path}`" for path in paths) + "。")
    lines += ["", "## 同题开发基线与当前入口", "",
        f"原六道开发题的完整答案：旧版 **{triplet(baseline_scores)}** → 对象 Reader **{triplet(object_scores)}**（PASS / PARTIAL / FAIL）。相同问题与被调查源码身份已经校验；每版各一次，不能解释为稳定成功率。",
        f"最后三个修订入口：**{triplet(report['latest_three_entries']['scores'])}**；配置和变更答案仍有未读语义推断，文档核对 PASS。输入有调整，旧拒答保留，不能与原题当作公平 A/B。", "",
        "## 各阶段质量与资源", "",
        "核心任务与预期边界拒答分开计数；P / 部 / F 分别为 PASS / PARTIAL / FAIL。耗时为单请求 HTTP/SSE 总耗时的观测值。", "",
        "| 阶段 | 请求 | 核心 P / 部 / F | 边界 P / 部 / F | provider | 输入 / 输出 tokens | p50 / p95 秒 |",
        "|---|---:|---|---|---:|---:|---:|",
    ]
    for phase in report["phases"].values():
        lines.append(f"| {phase['label']} | {phase['requests']} | {triplet(phase['core_scores'])} | {triplet(phase['boundary_scores'])} | {phase['provider_calls']} | {phase['input_tokens']:,} / {phase['output_tokens']:,} | {phase['p50_elapsed_seconds']:.3f} / {phase['p95_elapsed_seconds']:.3f} |")
    lines += ["", "p95 按 nearest rank 计算；样本很小、顺序执行，不能当并发压测或 SLA。完整 JSON 保存各题 stop code、工具调用数、人工理由、prompt 身份与原始材料 SHA；不会从 completed 自动推导正确。", "",
        "## 离线复核", "", "```powershell",
        "python scripts/report_current_quality.py --output-prefix docs/validation/2026-10-04-quality-baseline", "```", "",
        "零模型、零检索、零 embedding 调用；仅读取已归档数据并生成 Markdown/JSON。发现 hash、分母、预算或 usage 缺失时退出失败，避免把缺失成本记成零。",
        "原实验细节见 [核心任务检查](2026-10-04-core-workflows.md)。历史 Gate 2/3/4 的冻结结果继续保持原版本身份，不能替代当前 Engineering 的质量结论。", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-prefix", type=Path)
    args = parser.parse_args()
    report = build_report()
    if args.output_prefix:
        prefix = args.output_prefix
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        prefix.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
