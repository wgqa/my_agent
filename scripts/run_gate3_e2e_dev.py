"""G3-E2E-07A：运行 Gate 3 真实 E2E 答案评测（Generation / Evaluation 两阶段）。

用法（仓库根目录，PYTHONPATH=.）：

  1) Generation stage（真实 Planner→Retrieval→merge v2→真实 Generator→Answer）：
     python scripts/run_gate3_e2e_dev.py --phase generate \
       --repo <repo> --dev-jsonl <gate3/dev/gate3_dev_v1.jsonl> \
       --frozen-index-manifest <repo>/experiments/dbc497c796d5/.../index_manifest.json \
       --corpus-root <benchmark_work/agent_ai_v1/02_corpus_candidate> \
       --output-root <benchmark_work/gate3/e2e_dev_runs> \
       [--planner-model deepseek-chat] [--generator-model deepseek-v4-flash] \
       [--judge-model deepseek-chat] [--merge-policy subquery_rrf_merge_v2] [--merge-rrf-k 60.0]

  2) Evaluation stage（离线读 Dev Gold + LLM Judge，聚合 answer 指标）：
     python scripts/run_gate3_e2e_dev.py --phase evaluate \
       --run-dir <e2e_dev_runs/<run_id>> \
       --dev-jsonl <gate3/dev/gate3_dev_v1.jsonl> \
       --frozen-index-manifest <repo>/.../index_manifest.json \
       --corpus-root <corpus> [--judge-model deepseek-chat]

本 CLI 不读取/搜索 sealed/Holdout；API Key 只来自环境变量 DEEPSEEK_API_KEY；
不 push；不调参；Artifact 写入外部目录，不入 Git。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from core.agent_runtime import DEFAULT_MERGE_RRF_K, SUBQUERY_RRF_MERGE_V2
from core.query_planning.prompt import PLANNER_PROMPT_SHA256
from evaluation.gate3.e2e import (
    EXPECTED_CORPUS_FILE_COUNT,
    EXPECTED_CORPUS_ID,
    EXPECTED_DEV_CASE_COUNT,
    EXPECTED_DEV_EVALUATION_SET_ID,
    EXPECTED_DEV_JSONL_SHA256,
    EXPECTED_FREEZE_ID,
    GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    Gate3E2EConfig,
    check_git_tracked_clean,
    run_e2e_evaluation,
    run_e2e_generation,
)


def _git_head(repo: str) -> str:
    return subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True
    ).strip()


def _base_config(args, planner_prompt_sha: str) -> Gate3E2EConfig:
    return Gate3E2EConfig(
        source_commit="",  # generate 阶段由 git_head 填充
        corpus_id=EXPECTED_CORPUS_ID,
        corpus_file_count=EXPECTED_CORPUS_FILE_COUNT,
        gate3_dataset_freeze_id=EXPECTED_FREEZE_ID,
        dev_evaluation_set_id=EXPECTED_DEV_EVALUATION_SET_ID,
        dev_case_count=EXPECTED_DEV_CASE_COUNT,
        dev_jsonl_sha256=EXPECTED_DEV_JSONL_SHA256,
        planner_prompt_sha256=planner_prompt_sha,
        judge_prompt_sha256=GATE3_ANSWER_JUDGE_PROMPT_SHA256,
        planner_model=args.planner_model,
        generator_model=args.generator_model,
        judge_model=args.judge_model,
        merge_policy=args.merge_policy,
        merge_rrf_k=args.merge_rrf_k,
        dev_jsonl_path=args.dev_jsonl,
        frozen_index_manifest_path=args.frozen_index_manifest,
        corpus_root=args.corpus_root,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="G3-E2E-07A gate3 real E2E answer evaluation"
    )
    parser.add_argument("--phase", required=True, choices=("generate", "evaluate"))
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--dev-jsonl", required=True)
    parser.add_argument("--frozen-index-manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=False)
    parser.add_argument("--run-dir", required=False)
    parser.add_argument("--planner-model", default="deepseek-chat")
    parser.add_argument("--generator-model", default="deepseek-v4-flash")
    parser.add_argument("--judge-model", default="deepseek-chat")
    parser.add_argument("--merge-policy", default=SUBQUERY_RRF_MERGE_V2)
    parser.add_argument("--merge-rrf-k", type=float, default=DEFAULT_MERGE_RRF_K)
    args = parser.parse_args(argv)

    if args.phase == "generate":
        if not args.output_root:
            raise SystemExit("--phase generate 需要 --output-root")
        try:
            check_git_tracked_clean(args.repo)
        except RuntimeError as exc:
            raise SystemExit(str(exc))
        git_head = _git_head(args.repo)
        base = _base_config(args, PLANNER_PROMPT_SHA256)
        run_dir = Path(args.output_root) / base.run_id
        config = replace(base, source_commit=git_head, output_dir=str(run_dir))
        print(f"run_id={config.run_id}")
        print(f"output_dir={run_dir}")
        summary = run_e2e_generation(config, git_head)
        print(f"case_count={summary['case_count']}")
        print(f"status_counts={summary['status_counts']}")
        return 0

    if args.phase == "evaluate":
        if not args.run_dir:
            raise SystemExit("--phase evaluate 需要 --run-dir")
        run_dir = Path(args.run_dir)
        if not run_dir.is_dir():
            raise SystemExit(f"run-dir 不存在: {run_dir}")
        run_config = json.loads((run_dir / "run_config.json").read_text("utf-8"))
        fields = {
            k: v for k, v in run_config.items()
            if k in Gate3E2EConfig.__dataclass_fields__
        }
        base = Gate3E2EConfig(**fields)
        config = replace(
            base,
            judge_model=args.judge_model,
            dev_jsonl_path=args.dev_jsonl,
            frozen_index_manifest_path=args.frozen_index_manifest,
            corpus_root=args.corpus_root,
            output_dir=str(run_dir),
        )
        print(f"run_id={config.run_id}")
        metrics = run_e2e_evaluation(config, run_dir)
        a = metrics["answer"]
        print(
            f"answer_obligation={a['answer_obligation_covered']}/"
            f"{a['answer_obligation_total']} "
            f"({a['answer_obligation_coverage_rate']:.4f})"
        )
        print(
            f"answer_pass={a['answer_pass_case_count']}/"
            f"{a['answerable_case_count']} ({a['answer_pass_rate']:.4f})"
        )
        print(
            f"citation_valid={a['citation_valid_case_count']}/"
            f"{a['answerable_case_count']} ({a['citation_valid_case_rate']:.4f})"
        )
        return 0

    raise SystemExit("未知 phase")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
