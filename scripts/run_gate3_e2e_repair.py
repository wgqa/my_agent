"""G3-E2E-07A-R1-MICRO：纯离线 Evaluation Provenance Repair（独立 source lock）。

复用父 run（如 4172f6cc1d6f）持久化的 generation/Judge 原始结果，用当前
tracked-clean HEAD 对应的 evaluator 重新计算正式指标。不调用任何 LLM/
embedding/retrieval；不修改父 run；不 push。

source lock 为事先冻结的 expected hashes（parent_run_id / run_config_sha256 /
case_results_sha256 / cited_evidence_sha256 / source_answer_judgments_sha256），
本 CLI 只做"实际 vs 冻结"校验，任一 mismatch 立即失败、不生成 repair。

用法（仓库根目录，PYTHONPATH=.）：

  python scripts/run_gate3_e2e_repair.py \
    --parent-run-dir <benchmark_work/gate3/e2e_dev_runs/4172f6cc1d6f> \
    --source-lock <benchmark_work/gate3/e2e_dev_repairs/source_locks/4172.lock.json> \
    --output-root <benchmark_work/gate3/e2e_dev_repairs> \
    --repo <repo> \
    --dev-jsonl <gate3/dev/gate3_dev_v1.jsonl> \
    --frozen-index-manifest <repo>/experiments/dbc497c796d5/.../index_manifest.json \
    --corpus-root <benchmark_work/agent_ai_v1/02_corpus_candidate>
"""

from __future__ import annotations

import argparse
import json
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
        description="G3-E2E-07A-R1 offline evaluation provenance repair (source-locked)"
    )
    parser.add_argument("--parent-run-dir", required=True)
    parser.add_argument("--source-lock", required=True,
                        help="事先冻结的 expected hashes（JSON）")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--dev-jsonl", required=True)
    parser.add_argument("--frozen-index-manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    args = parser.parse_args(argv)

    try:
        check_git_tracked_clean(args.repo)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    source_lock = json.loads(Path(args.source_lock).read_text("utf-8"))
    evaluation_source_commit = _git_head(args.repo)
    print(f"evaluation_source_commit={evaluation_source_commit}")
    result = reevaluate_existing_e2e_run(
        Path(args.parent_run_dir),
        Path(args.output_root),
        evaluation_source_commit=evaluation_source_commit,
        dev_jsonl_path=args.dev_jsonl,
        frozen_index_manifest_path=args.frozen_index_manifest,
        corpus_root=args.corpus_root,
        source_lock=source_lock,
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
    print(f"zero_obligation={a['zero_obligation_case_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
