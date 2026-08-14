"""G3-E2E-07A-R1：纯离线 Evaluation Provenance Repair。

复用父 run（如 4172f6cc1d6f）持久化的 generation/Judge 原始结果，用当前
tracked-clean HEAD 对应的 evaluator 重新计算正式指标。不调用任何 LLM/
embedding/retrieval；不修改父 run；不 push。

用法（仓库根目录，PYTHONPATH=.）：

  python scripts/run_gate3_e2e_repair.py \
    --parent-run-dir <benchmark_work/gate3/e2e_dev_runs/4172f6cc1d6f> \
    --output-root <benchmark_work/gate3/e2e_dev_repairs> \
    --repo <repo> \
    --dev-jsonl <gate3/dev/gate3_dev_v1.jsonl> \
    --frozen-index-manifest <repo>/experiments/dbc497c796d5/.../index_manifest.json \
    --corpus-root <benchmark_work/agent_ai_v1/02_corpus_candidate> \
    [--judge-model deepseek-chat]
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from evaluation.gate3.e2e import (
    check_git_tracked_clean,
    reevaluate_existing_e2e_run,
)


def _git_head(repo: str) -> str:
    return subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True
    ).strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="G3-E2E-07A-R1 offline evaluation provenance repair"
    )
    parser.add_argument("--parent-run-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--dev-jsonl", required=True)
    parser.add_argument("--frozen-index-manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--judge-model", default="deepseek-chat")
    args = parser.parse_args(argv)

    try:
        check_git_tracked_clean(args.repo)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    evaluation_source_commit = _git_head(args.repo)
    print(f"evaluation_source_commit={evaluation_source_commit}")
    result = reevaluate_existing_e2e_run(
        Path(args.parent_run_dir),
        Path(args.output_root),
        evaluation_source_commit=evaluation_source_commit,
        dev_jsonl_path=args.dev_jsonl,
        frozen_index_manifest_path=args.frozen_index_manifest,
        corpus_root=args.corpus_root,
        judge_model=args.judge_model,
    )
    a = result["metrics"]["answer"]
    print(f"repair_id={result['repair_id']}")
    print(f"reusable_judgments={result['reusable_judgments']}")
    print(f"input_mismatch={result['input_mismatch']}")
    print(f"answer_obligation={a['answer_obligation_covered']}/"
          f"{a['answer_obligation_total']} "
          f"({a['answer_obligation_coverage_rate']:.4f})")
    print(f"answer_pass={a['answer_pass_case_count']}/"
          f"{a['answerable_case_count']} ({a['answer_pass_rate']:.4f})")
    print(f"citation_valid={a['citation_valid_case_count']}/"
          f"{a['citation_valid_denominator']} "
          f"({a['citation_valid_case_rate']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
