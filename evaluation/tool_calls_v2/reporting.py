"""Readable reports retain automatic verdicts and separate review decisions."""
from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _rate(metric: dict) -> str:
    return (f"{metric['rate']:.1%} ({metric['numerator']}/{metric['denominator']})" if metric["rate"] is not None else "N/A (0 个观察机会)")


def review_queue(cases: list[dict], scores: list[dict]) -> list[dict]:
    by_id = {c["id"]: c for c in cases}
    # All disputed/failed/invalid cases plus reproducible PASS samples per group.
    sampled = set()
    reviews = []
    for score in scores:
        key = (score["split"], score["group"], score["focus_tool"])
        needed = score["verdict"] != "PASS" or score["group"] == "boundary" or key not in sampled
        if not needed:
            continue
        sampled.add(key)
        reviews.append({"case_id": score["case_id"], "query": by_id[score["case_id"]]["query"], "automatic_verdict": score["verdict"],
                        "automatic_failures": score["failures"], "review_status": "pending", "reviewer_type": None,
                        "reviewer_name": None, "decision": None, "reason": None, "source_references": []})
    return reviews


def validate_reviews(reviews: list[dict], scores: list[dict]) -> None:
    """Do not silently replace mechanical scores with a claimed human judgment."""
    by_id, seen = {s["case_id"]: s for s in scores}, set()
    for review in reviews:
        case_id = review["case_id"]
        if case_id in seen or case_id not in by_id or review["automatic_verdict"] != by_id[case_id]["verdict"]:
            raise ValueError("Review identity/automatic verdict mismatch")
        seen.add(case_id)
        if review["review_status"] == "pending":
            continue
        if (review["review_status"] != "reviewed" or review["reviewer_type"] not in ("developer_assistant", "project_owner", "other_reviewer")
                or review["decision"] not in ("PASS", "PARTIAL", "FAIL", "INVALID") or not review["reason"]
                or not review["reviewer_name"] or not review["source_references"]):
            raise ValueError("Reviewed decision requires reviewer identity, reason and source references")


def write_report(directory: Path, manifest: dict, cases: list[dict], scores: list[dict], summary: dict) -> None:
    write_json(directory / "scores.json", scores)
    write_json(directory / "summary.json", summary)
    write_json(directory / "reviews.json", review_queue(cases, scores))
    labels = {"gold_proof": "离线 Gold 可达性检查（工具实际执行，无模型）", "scripted": "当前产品装配脚本回放（无模型）", "live": "真实模型工具过程评测"}
    lines = [f"# {manifest['run_id']}", "", labels[summary["mode"]], "",
             f"代码 HEAD：`{manifest['code_head']}`；实际业务 SHA：`{manifest['business']['sha256']}`。",
             f"计划 {summary['planned_requests']} 题，已记录 {summary['recorded_requests']} 题，有效 {summary['valid_records']} 题，无效 {summary['invalid_records']} 题，未运行 {len(summary['not_run'])} 题。", "",
             "原始状态与自动判分分别保存。复核队列尚未人工裁决；不能把自动 PASS 称作独立人工验收。", "",
             "| 指标 | 结果 / 分母 |", "|---|---|"]
    metric_names = {"material_coverage": "必需材料获取", "all_goals": "整题材料齐全", "required_tool_coverage": "不可替代工具义务",
                    "first_action": "合理首步", "target_correct": "已解析执行调用的目标正确", "initial_parse_valid": "首次动作解析有效",
                    "after_repair_parse_valid": "修复后动作解析有效", "parse_repair_success": "解析修复成功",
                    "multistep": "多材料过程", "recovery": "已触发故障的恢复", "terminal_behavior": "停止行为"}
    lines.extend(f"| {label} | {_rate(summary['metrics'][key])} |" for key, label in metric_names.items())
    cost = summary["cost"]
    lines += ["", f"Provider 调用已知数量：{cost['provider_calls_known']}；缺 metadata 的逻辑调用：{cost['metadata_missing_logical_calls']}。",
              f"已知 input/output token：{cost['input_tokens_known']} / {cost['output_tokens_known']}；缺 usage 的实际调用数：{cost['input_usage_missing_calls']} / {cost['output_usage_missing_calls']}。",
              f"工具执行：{cost['tool_calls']} 次；不当尝试 {summary['metrics']['unsafe_attempts']} 次，护栏拦截涉及 {summary['metrics']['guard_blocked_unsafe_cases']} 题。", "",
              "## 逐题自动结果", "", "| 题号 | 集合 / 任务组 | 判分 | 原始停止状态 | 缺口 |", "|---|---|---|---|---|"]
    for score in scores:
        failures = ", ".join(score["record_problems"] + score["failures"]) or ("需源码复核其他合法路径" if score["review_required"] else "—")
        lines.append(f"| {score['case_id']} | {score['split']} / {score['group']} | {score['verdict']} | {score['original_status']} / {score['original_reason'] or '—'} | {failures} |")
    lines += ["", "## 分组与限制", ""]
    for dimension, groups in summary["breakdown"].items():
        for name, counts in groups.items():
            lines.append(f"- {dimension}={name}：计划 {counts['planned']}，记录 {counts['recorded']}，{counts['verdicts']}。")
    lines += ["", *[f"- {limitation}" for limitation in summary["limitations"]], "",
              "原始事实见 calls.jsonl，冻结题目见 cases.jsonl，自动分见 scores.json，复核意见单独填写 reviews.json。", ""]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
