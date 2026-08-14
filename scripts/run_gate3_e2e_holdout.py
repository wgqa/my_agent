"""G3-HOLDOUT-09A：一次性、Freeze-bound 的 Holdout execution runner。

09A 只允许 --preflight-only（dry-run）。真实 Holdout run 待 09B 授权后进行，
本 CLI 不提供任何性能 override（model/temp/top_k/merge/evidence 全部 frozen）。

用法（仓库根目录，PYTHONPATH=.）：

  python scripts/run_gate3_e2e_holdout.py --preflight-only \
    --repo <repo> --freeze-json <gate3_system_freeze.json> \
    --holdout-jsonl <gate3/sealed/gate3_holdout_v1.jsonl> \
    --private-manifest <gate3/sealed/private_manifest_v1.json> \
    --frozen-index-manifest <repo>/experiments/dbc497c796d5/.../index_manifest.json \
    --corpus-root <benchmark_work/agent_ai_v1/02_corpus_candidate> \
    --output-root <benchmark_work/gate3/holdout_runs> \
    --attempt-ledger <benchmark_work/gate3/holdout_attempt_ledger.json>

本 CLI 在 09A 不读取 holdout-jsonl 内容、不打开 private manifest、不创建
LLM client、不建 index、不创建正式 attempt。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from evaluation.gate3.holdout import (
    _git_head,
    assert_no_forbidden_overrides,
    build_holdout_config_from_freeze,
    execute_holdout,
    preflight_holdout,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="G3-HOLDOUT-09B freeze-bound one-shot holdout runner"
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--freeze-json", required=True)
    parser.add_argument("--holdout-jsonl", required=True)
    parser.add_argument("--private-manifest", required=True)
    parser.add_argument("--frozen-index-manifest", required=True)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--attempt-ledger", required=True)
    # 明确不提供任何性能 override（frozen）。
    args = parser.parse_args(argv)

    assert_no_forbidden_overrides(sys.argv if argv is None else argv)

    if args.execute:
        # 09C 正式执行：需要 Reviewer 显式授权（HOLDOUT_EXECUTION_AUTHORIZED=1）。
        # 09B 不设置该环境变量 → 不会创建正式 attempt。
        if os.getenv("HOLDOUT_EXECUTION_AUTHORIZED") != "1":
            raise SystemExit(
                "Holdout 执行未授权：需 Reviewer 09C 放行 "
                "(HOLDOUT_EXECUTION_AUTHORIZED=1)"
            )
        config = build_holdout_config_from_freeze(
            args.freeze_json,
            actual_execution_source_commit=_git_head(args.repo),
            holdout_jsonl_path=args.holdout_jsonl,
            private_manifest_path=args.private_manifest,
            frozen_index_manifest_path=args.frozen_index_manifest,
            corpus_root=args.corpus_root,
            output_root=args.output_root,
        )
        report = execute_holdout(
            config,
            repo=args.repo,
            freeze_json_path=args.freeze_json,
            output_root=args.output_root,
            attempt_ledger_path=args.attempt_ledger,
            sealed_read_fn=None,  # 09C 注入真实 sealed reader
            run_generation_fn=None,  # 09C 注入真实生成链
            run_evaluation_fn=None,
        )
        for key, value in report.items():
            print(f"{key}={value}")
        return 0

    if not args.preflight_only:
        raise SystemExit(
            "需指定 --preflight-only 或 --execute；09B 只允许 --preflight-only"
        )

    report = preflight_holdout(
        repo=args.repo,
        freeze_json_path=args.freeze_json,
        holdout_jsonl_path=args.holdout_jsonl,
        private_manifest_path=args.private_manifest,
        frozen_index_manifest_path=args.frozen_index_manifest,
        corpus_root=args.corpus_root,
        output_root=args.output_root,
        attempt_ledger_path=args.attempt_ledger,
    )
    for key, value in report.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
