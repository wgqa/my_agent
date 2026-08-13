"""G3-DECOMP-04B-02A：Gate 3 Dev Planner 校准 CLI。

run 模式：对公开 Dev 24 Case 运行真实 OpenAI-compatible Planner 并写入
run_config/planner_results/planner_metrics。finalize 模式：在人工语义审查
完成后写 result.json。API Key 只从环境变量读取，不打印。

用法示例：
python scripts/run_gate3_planner_dev.py run \
  --corpus-root "…/02_corpus_candidate" \
  --dev-jsonl "…/gate3/dev/gate3_dev_v1.jsonl" \
  --dev-manifest "…/gate3/dev/dev_manifest_v1.json" \
  --output-root "…/gate3/dev_runs" \
  --provider deepseek --model deepseek-chat \
  --base-url "https://api.deepseek.com/v1" \
  --api-key-env DEEPSEEK_API_KEY \
  --source-commit <commitA>

python scripts/run_gate3_planner_dev.py finalize --run-dir "…/dev_runs/<run_id>"
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from core.query_planning import OpenAICompatibleQueryPlanner
from core.query_planning.prompt import (
    PLANNER_MAX_OUTPUT_TOKENS,
    PLANNER_MAX_RETRIES,
    PLANNER_PROMPT_SHA256,
    PLANNER_PROMPT_VERSION,
    PLANNER_TEMPERATURE,
    PLANNER_TIMEOUT_SECONDS,
)
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.evaluation_set import Gate3EvaluationSet
from evaluation.gate3.planner_dev import (
    PLANNER_DEV_SCHEMA_VERSION,
    ProviderFailFast,
    Gate3PlannerDevConfig,
    Gate3PlannerDevRunner,
    finalize_planner_dev_run,
    write_planner_dev_artifacts,
)

_EXPECTED_CORPUS_ID = "870e5864df67"
_EXPECTED_CORPUS_FILE_COUNT = 37
_EXPECTED_DEV_EVALUATION_SET_ID = "f2144030d754"
_EXPECTED_DEV_CASE_COUNT = 24
_EXPECTED_DEV_JSONL_SHA256 = (
    "0b4bbf5314fee27d965c6ccefd738d71eb5c3925b15517b544c1fdf4f8e94015"
)
_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".py", ".js", ".java"}


def _collect_corpus_files(corpus_root: Path) -> list[str]:
    root = Path(corpus_root).resolve()
    rels = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in _ALLOWED_EXTENSIONS:
            rels.append(p.relative_to(root).as_posix())
    return rels


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_api_key(api_key_env: str) -> str:
    """API Key 只从环境变量读取；缺失时在任何网络调用和 Artifact 写入前失败。"""
    key = os.environ.get(api_key_env, "")
    if not key or not key.strip():
        raise SystemExit(
            f"环境变量 {api_key_env} 未设置；在任何网络调用和 Artifact 写入前失败"
        )
    return key


def _build_planner(provider, model, base_url, api_key) -> OpenAICompatibleQueryPlanner:
    return OpenAICompatibleQueryPlanner(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


def cmd_run(args: argparse.Namespace) -> int:
    # 1) API Key 前置校验（网络/Artifact 之前）
    api_key = _resolve_api_key(args.api_key_env)

    # 2) 冻结 corpus
    corpus_root = Path(args.corpus_root)
    if not corpus_root.is_dir():
        raise SystemExit(f"corpus_root 不存在: {corpus_root}")
    rels = _collect_corpus_files(corpus_root)
    corpus = ExperimentCorpus.build(corpus_root, rels)
    if corpus.corpus_id != _EXPECTED_CORPUS_ID:
        raise SystemExit(
            f"corpus_id 不一致：期望 {_EXPECTED_CORPUS_ID}，实际 {corpus.corpus_id}"
        )
    if len(corpus.entries) != _EXPECTED_CORPUS_FILE_COUNT:
        raise SystemExit(
            f"corpus 文件数不一致：期望 {_EXPECTED_CORPUS_FILE_COUNT}，"
            f"实际 {len(corpus.entries)}"
        )

    # 3) Dev 评测集
    dev_jsonl = Path(args.dev_jsonl)
    dev_jsonl_sha = _sha256_file(dev_jsonl)
    if dev_jsonl_sha != _EXPECTED_DEV_JSONL_SHA256:
        raise SystemExit(
            f"Dev JSONL SHA-256 不一致：期望 {_EXPECTED_DEV_JSONL_SHA256}，"
            f"实际 {dev_jsonl_sha}"
        )
    evaluation_set = Gate3EvaluationSet.load_jsonl(dev_jsonl, corpus)
    if evaluation_set.evaluation_set_id != _EXPECTED_DEV_EVALUATION_SET_ID:
        raise SystemExit(
            "Dev evaluation_set_id 不一致：期望 "
            f"{_EXPECTED_DEV_EVALUATION_SET_ID}，实际 "
            f"{evaluation_set.evaluation_set_id}"
        )
    if len(evaluation_set.cases) != _EXPECTED_DEV_CASE_COUNT:
        raise SystemExit(
            f"Dev case_count 不一致：期望 {_EXPECTED_DEV_CASE_COUNT}，"
            f"实际 {len(evaluation_set.cases)}"
        )

    # 4) 配置
    config = Gate3PlannerDevConfig(
        schema_version=PLANNER_DEV_SCHEMA_VERSION,
        source_commit=args.source_commit,
        corpus_id=corpus.corpus_id,
        evaluation_set_id=evaluation_set.evaluation_set_id,
        dev_jsonl_sha256=dev_jsonl_sha,
        provider=args.provider,
        model=args.model,
        prompt_version=PLANNER_PROMPT_VERSION,
        prompt_sha256=PLANNER_PROMPT_SHA256,
        temperature=PLANNER_TEMPERATURE,
        max_tokens=PLANNER_MAX_OUTPUT_TOKENS,
        timeout=PLANNER_TIMEOUT_SECONDS,
        max_retries=PLANNER_MAX_RETRIES,
    )

    planner = _build_planner(args.provider, args.model, args.base_url, api_key)
    runner = Gate3PlannerDevRunner(config, planner, evaluation_set)

    try:
        result = runner.run(fail_fast_on_provider_error=True)
    except ProviderFailFast as exc:
        # 首条 Case Provider 错误/超时：停止正式运行，不写 Artifact，如实报告。
        print(f"[ABORT] {exc}", file=sys.stderr)
        return 2

    artifact_sha = write_planner_dev_artifacts(result, Path(args.output_root))
    run_dir = Path(args.output_root) / result.run_id
    print(f"run_id: {result.run_id}")
    print(f"run_dir: {run_dir}")
    print(f"case_count: {result.metrics.case_count}")
    print(f"artifact_sha: {artifact_sha}")
    print("下一步：人工审查后执行 finalize 子命令写 result.json。")
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        raise SystemExit(f"run_dir 不存在: {run_dir}")
    sha_map = finalize_planner_dev_run(run_dir)
    print(f"result.json written: {run_dir / 'result.json'}")
    print(f"artifact_sha: {sha_map}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate 3 Dev Planner 校准（真实 OpenAI-compatible 调用）"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    run_p = sub.add_parser("run", help="运行 Dev baseline 并写 3 个 JSON Artifact")
    run_p.add_argument("--corpus-root", required=True)
    run_p.add_argument("--dev-jsonl", required=True)
    run_p.add_argument("--dev-manifest", required=True)
    run_p.add_argument("--output-root", required=True)
    run_p.add_argument("--provider", required=True)
    run_p.add_argument("--model", required=True)
    run_p.add_argument("--base-url", required=True)
    run_p.add_argument("--api-key-env", required=True)
    run_p.add_argument("--source-commit", required=True)
    run_p.set_defaults(func=cmd_run)

    fin_p = sub.add_parser("finalize", help="人工审查后写 result.json")
    fin_p.add_argument("--run-dir", required=True)
    fin_p.set_defaults(func=cmd_finalize)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
