"""G4-EVAL-06B-01：Gate 4 Tool-Use Dev Runner CLI。

用法：
    python scripts/run_gate4_tool_use_dev.py --preflight-only \
        --output-root <外部输出根> [--corpus-root <语料根>]

    python scripts/run_gate4_tool_use_dev.py --execute \
        --output-root <外部输出根> [--corpus-root <语料根>]

- corpus_root 默认从环境变量 GATE4_KNOWLEDGE_CORPUS_ROOT 读取（正式 Runner 不允许
  fallback / skip；本机路径不会硬编码进代码）。
- --execute 额外要求 GATE4_TOOL_USE_EXECUTION_AUTHORIZED=1，否则 0 model call。
- source_commit 自动绑定 git HEAD（tracked clean 前置），不允许 CLI 手填。

本任务不设置授权变量，因此即使误敲 --execute 也不会真正调用模型。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# scripts/ 下直接运行时，把仓库根加入 sys.path（与 run_gate3_* 一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.gate4.runner import (  # noqa: E402
    FROZEN_MODEL,
    FROZEN_PROVIDER,
    Gate4ToolUseRunner,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "evaluation" / "gate4" / "data" / "tool_use_dev_v1.jsonl"
DEFAULT_MANIFEST = (
    REPO_ROOT / "evaluation" / "gate4" / "data" / "tool_use_dev_manifest_v1.json"
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate 4 Tool-Use Dev Runner")
    parser.add_argument("--dataset-jsonl", default=str(DEFAULT_DATASET))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--corpus-root", default=None,
                        help="冻结语料根目录；默认读 GATE4_KNOWLEDGE_CORPUS_ROOT")
    parser.add_argument("--provider", default=FROZEN_PROVIDER)
    parser.add_argument("--model", default=FROZEN_MODEL)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true",
                      help="只跑 preflight（0 model call）")
    mode.add_argument("--execute", action="store_true",
                      help="正式执行（须 GATE4_TOOL_USE_EXECUTION_AUTHORIZED=1）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    corpus_root = args.corpus_root or os.environ.get("GATE4_KNOWLEDGE_CORPUS_ROOT")
    execution_authorized = (
        os.environ.get("GATE4_TOOL_USE_EXECUTION_AUTHORIZED") == "1"
    )
    mode = "execute" if args.execute else "preflight"

    runner = Gate4ToolUseRunner(
        repo_root=args.repo_root,
        dataset_path=args.dataset_jsonl,
        manifest_path=args.manifest,
        output_root=args.output_root,
        corpus_root=corpus_root,
        mode=mode,
        execution_authorized=execution_authorized,
        provider=args.provider,
        model=args.model,
    )
    result = runner.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
