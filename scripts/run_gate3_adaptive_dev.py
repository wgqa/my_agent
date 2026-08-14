"""G3-ADAPT-06B：运行 Gate 3 Adaptive Dev 检索对照（CLI）。

用法（仓库根目录，PYTHONPATH=.）：

  python scripts/run_gate3_adaptive_dev.py \
    --dev-jsonl <gate3/dev/gate3_dev_v1.jsonl> \
    --planner-results <dev_runs/497808269bdd/planner_results.jsonl> \
    --planner-result-json <dev_runs/497808269bdd/result.json> \
    --frozen-index-manifest <repo>/experiments/dbc497c796d5/.../index_manifest.json \
    --corpus-root <benchmark_work/agent_ai_v1/02_corpus_candidate> \
    --output-root <benchmark_work/gate3/adaptive_dev_runs>

本 CLI 不读取/设置 LLM API Key；不调用真实 Planner/Generator；不访问
sealed/Holdout；Artifact 写入外部目录，不入 Git。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from core.agent_runtime import DEFAULT_MERGE_RRF_K, SUBQUERY_ROUND_ROBIN_V1
from evaluation.gate3.adaptive_dev import (
    EXPECTED_CORPUS_FILE_COUNT,
    EXPECTED_CORPUS_ID,
    EXPECTED_DEV_CASE_COUNT,
    EXPECTED_DEV_EVALUATION_SET_ID,
    EXPECTED_DEV_JSONL_SHA256,
    EXPECTED_FREEZE_ID,
    EXPECTED_PLANNER_PROMPT_SHA256,
    EXPECTED_PLANNER_RUN_ID,
    Gate3AdaptiveDevConfig,
    check_git_tracked_clean,
    run_adaptive_dev,
)


def _git_head(repo: str) -> str:
    return subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True
    ).strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="G3-ADAPT-06B adaptive dev retrieval comparison"
    )
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--dev-jsonl", required=True)
    parser.add_argument("--planner-results", required=True)
    parser.add_argument("--planner-result-json", required=True)
    parser.add_argument("--frozen-index-manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--merge-policy", default=SUBQUERY_ROUND_ROBIN_V1)
    parser.add_argument("--merge-rrf-k", type=float, default=DEFAULT_MERGE_RRF_K)
    args = parser.parse_args(argv)

    # 绑定到干净源码提交：任何 tracked modification 立即拒绝（untracked 允许），
    # 此时尚未创建任何实验目录。
    try:
        check_git_tracked_clean(args.repo)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

    result_obj = json.loads(Path(args.planner_result_json).read_text("utf-8"))
    recorded = result_obj.get("artifact_sha256", {}).get("planner_results.jsonl")
    if not recorded:
        raise SystemExit("planner result.json 缺少 artifact_sha256.planner_results.jsonl")

    git_head = _git_head(args.repo)
    base = Gate3AdaptiveDevConfig(
        source_commit=git_head,
        corpus_id=EXPECTED_CORPUS_ID,
        corpus_file_count=EXPECTED_CORPUS_FILE_COUNT,
        gate3_dataset_freeze_id=EXPECTED_FREEZE_ID,
        dev_evaluation_set_id=EXPECTED_DEV_EVALUATION_SET_ID,
        dev_case_count=EXPECTED_DEV_CASE_COUNT,
        dev_jsonl_sha256=EXPECTED_DEV_JSONL_SHA256,
        planner_run_id=EXPECTED_PLANNER_RUN_ID,
        planner_prompt_sha256=EXPECTED_PLANNER_PROMPT_SHA256,
        planner_results_sha256=recorded,
        dev_jsonl_path=args.dev_jsonl,
        planner_results_path=args.planner_results,
        planner_result_json_path=args.planner_result_json,
        frozen_index_manifest_path=args.frozen_index_manifest,
        corpus_root=args.corpus_root,
        merge_policy=args.merge_policy,
        merge_rrf_k=args.merge_rrf_k,
    )
    run_dir = Path(args.output_root) / base.run_id
    config = replace(base, output_dir=str(run_dir))

    print(f"run_id={config.run_id}")
    print(f"output_dir={run_dir}")
    result = run_adaptive_dev(config, git_head)
    print(f"result.json written: {run_dir / 'result.json'}")
    print(f"schema_version={result.get('schema_version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
