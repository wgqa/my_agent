"""G3-DECOMP-04B-02A + R1：Gate 3 Dev Planner 校准 CLI（v2 + 离线重分析）。

run：真实 OpenAI-compatible 调用（24 Dev Case），写入 run_config/planner_results/
planner_metrics。finalize：写 result.json。reanalyze：基于 R0 Artifact 离线重算 v2
metrics（不调用模型）。finalize-analysis：写 R1 result.json。API Key 只从环境变量读取。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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
    PLANNER_DEV_SCHEMA_VERSION_V1,
    ProviderFailFast,
    Gate3PlannerDevConfig,
    Gate3PlannerDevRunner,
    finalize_analysis,
    finalize_planner_dev_run,
    reanalyze_planner_dev_run,
    write_abort_artifact,
    write_analysis_artifacts,
    write_planner_dev_artifacts,
)

_EXPECTED_CORPUS_ID = "870e5864df67"
_EXPECTED_CORPUS_FILE_COUNT = 37
_EXPECTED_DEV_EVALUATION_SET_ID = "f2144030d754"
_EXPECTED_DEV_CASE_COUNT = 24
_EXPECTED_DEV_JSONL_SHA256 = (
    "0b4bbf5314fee27d965c6ccefd738d71eb5c3925b15517b544c1fdf4f8e94015"
)
_EXPECTED_MANIFEST_SHA256 = (
    "1baeed58d22a71e49c4edb83b7ce156df6a1982ae4c17f0a9aba37fce980ce27"
)
_EXPECTED_FREEZE_ID = "257fa0d0a6d6"
_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".py", ".js", ".java"}

# R0（497808269bdd）五个 Artifact 的冻结 SHA
_R0_SHA256 = {
    "run_config.json": (
        "ca6585052e3ecb206c74233a9853f9032074e7b6ad47bfc173068431b358c6b8"
    ),
    "planner_results.jsonl": (
        "ff3cc51948f4fcc02fb102c28019cab5692ff339a66795f1b4a5a518c4f59cf3"
    ),
    "planner_metrics.json": (
        "4b1ec88b41d67fcbcd94fa0e8993048aea3e1ea0a766fab419f0c766bfdd520a"
    ),
    "planner_semantic_review.md": (
        "3963033e63ae148a3b0c1e654fe1c7369ac7457f1cf7f58b8e61ea55dcedc355"
    ),
    "result.json": (
        "8ff732766f5fff35989b4e3a24e9ba298a94ec5e1794dd350b011ebe781bd922"
    ),
}
_R0_RUN_ID = "497808269bdd"
_R0_SOURCE_COMMIT = "ede4ec6da495e1a3e17142e10b3251c0c0d1d5ee"


def _collect_corpus_files(corpus_root: Path) -> list[str]:
    root = Path(corpus_root).resolve()
    rels = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in _ALLOWED_EXTENSIONS:
            rels.append(p.relative_to(root).as_posix())
    return rels


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    if out.returncode != 0:
        raise SystemExit("无法获取 git HEAD")
    return out.stdout.strip()


def _git_has_tracked_modification() -> bool:
    out = subprocess.run(
        ["git", "status", "--short"], capture_output=True, text=True
    )
    for line in out.stdout.splitlines():
        if line and not line.startswith("??"):
            return True
    return False


def _resolve_api_key(api_key_env: str) -> str:
    key = os.environ.get(api_key_env, "")
    if not key or not key.strip():
        raise SystemExit(
            f"环境变量 {api_key_env} 未设置；在任何网络调用和 Artifact 写入前失败"
        )
    return key


def _validate_manifest(manifest_path: Path) -> tuple[str, str]:
    """真正读取并验证 dev_manifest；返回 (dev_manifest_sha256, gate3_dataset_freeze_id)。"""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise SystemExit(f"dev_manifest 不存在: {manifest_path}")
    manifest_sha = _sha256_file(manifest_path)
    if manifest_sha != _EXPECTED_MANIFEST_SHA256:
        raise SystemExit(
            f"dev_manifest SHA-256 不一致：期望 {_EXPECTED_MANIFEST_SHA256}，"
            f"实际 {manifest_sha}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"dev_manifest 不是合法 JSON: {exc}")
    if not isinstance(manifest, dict):
        raise SystemExit("dev_manifest 必须是 JSON object")

    expected_fields = {
        "schema_version": "gate3_dev_manifest_v1",
        "status": "FROZEN_DEV",
        "gate3_dataset_freeze_id": _EXPECTED_FREEZE_ID,
        "corpus_id": _EXPECTED_CORPUS_ID,
        "corpus_file_count": _EXPECTED_CORPUS_FILE_COUNT,
        "dev_case_count": _EXPECTED_DEV_CASE_COUNT,
        "dev_evaluation_set_id": _EXPECTED_DEV_EVALUATION_SET_ID,
        "dev_jsonl_sha256": _EXPECTED_DEV_JSONL_SHA256,
    }
    for field, expected in expected_fields.items():
        if manifest.get(field) != expected:
            raise SystemExit(
                f"manifest 字段 {field} 不一致：期望 {expected!r}，"
                f"实际 {manifest.get(field)!r}"
            )
    return manifest_sha, manifest["gate3_dataset_freeze_id"]


def _build_planner(provider, model, base_url, api_key) -> OpenAICompatibleQueryPlanner:
    return OpenAICompatibleQueryPlanner(
        provider=provider, model=model, api_key=api_key, base_url=base_url
    )


def _load_corpus_and_eval(corpus_root: Path, dev_jsonl: Path):
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
    dev_jsonl = Path(dev_jsonl)
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
    return corpus, evaluation_set, dev_jsonl_sha


def cmd_run(args: argparse.Namespace) -> int:
    # 1) API Key 前置（网络/Artifact 之前）
    api_key = _resolve_api_key(args.api_key_env)

    # 2) Git 身份：source_commit 必须绑定实际 HEAD，且有 tracked modification 拒绝
    if len(args.source_commit) != 40:
        raise SystemExit("--source-commit 必须是完整 40 位")
    head = _git_head()
    if head != args.source_commit:
        raise SystemExit(
            f"--source-commit ({args.source_commit}) 与 git HEAD ({head}) 不一致"
        )
    if _git_has_tracked_modification():
        raise SystemExit("工作区存在 tracked modification，拒绝正式运行")

    # 3) corpus / Dev / manifest 四者身份
    corpus, evaluation_set, dev_jsonl_sha = _load_corpus_and_eval(
        Path(args.corpus_root), Path(args.dev_jsonl)
    )
    manifest_sha, freeze_id = _validate_manifest(Path(args.dev_manifest))
    if corpus.corpus_id != _EXPECTED_CORPUS_ID:
        raise SystemExit("corpus/manifest corpus_id 不一致")

    # 4) v2 config + run_id，输出目录预检（任何 Planner 调用前）
    config = Gate3PlannerDevConfig(
        schema_version=PLANNER_DEV_SCHEMA_VERSION,
        source_commit=args.source_commit,
        corpus_id=corpus.corpus_id,
        evaluation_set_id=evaluation_set.evaluation_set_id,
        gate3_dataset_freeze_id=freeze_id,
        dev_jsonl_sha256=dev_jsonl_sha,
        dev_manifest_sha256=manifest_sha,
        provider=args.provider,
        model=args.model,
        prompt_version=PLANNER_PROMPT_VERSION,
        prompt_sha256=PLANNER_PROMPT_SHA256,
        temperature=PLANNER_TEMPERATURE,
        max_tokens=PLANNER_MAX_OUTPUT_TOKENS,
        timeout=PLANNER_TIMEOUT_SECONDS,
        max_retries=PLANNER_MAX_RETRIES,
    )
    output_root = Path(args.output_root)
    run_dir = output_root / config.run_id
    if run_dir.exists():
        raise SystemExit(f"输出目录已存在，禁止覆盖: {run_dir}")

    # 5) 构造并调用 Planner（首条 Provider 失败 → abort Artifact）
    planner = _build_planner(args.provider, args.model, args.base_url, api_key)
    runner = Gate3PlannerDevRunner(config, planner, evaluation_set)
    try:
        result = runner.run(fail_fast_on_provider_error=True)
    except ProviderFailFast as exc:
        print(f"[ABORT] {exc}", file=sys.stderr)
        # 使用异常携带的首次 outcome 写脱敏 abort Artifact；严禁再次调用 planner
        try:
            write_abort_artifact(run_dir, config, exc.case_id, exc.outcome)
        except Exception as abort_exc:  # noqa: BLE001 - 尽力保留 abort 信息
            print(f"[ABORT-ARTIFACT-FAIL] {abort_exc}", file=sys.stderr)
        return 2

    artifact_sha = write_planner_dev_artifacts(result, output_root)
    print(f"run_id: {result.run_id}")
    print(f"run_dir: {run_dir}")
    print(f"case_count: {result.metrics.case_count}")
    print(f"artifact_sha: {artifact_sha}")
    print("下一步：人工审查后执行 finalize 子命令写 result.json。")
    return 0


def cmd_reanalyze(args: argparse.Namespace) -> int:
    # 禁止 API Key、禁止构造 Planner、禁止网络
    if getattr(args, "api_key_env", None):
        raise SystemExit("reanalyze 模式禁止 API Key")
    # analysis_source_commit 必须绑定实际 git HEAD，且工作区 tracked clean
    if len(args.analysis_source_commit) != 40:
        raise SystemExit("--analysis-source-commit 必须是完整 40 位 hex")
    head = _git_head()
    if head != args.analysis_source_commit:
        raise SystemExit(
            "--analysis-source-commit "
            f"({args.analysis_source_commit}) 与 git HEAD ({head}) 不一致"
        )
    if _git_has_tracked_modification():
        raise SystemExit("工作区存在 tracked modification，拒绝离线重分析")

    parent_run_dir = Path(args.parent_run_dir)
    if parent_run_dir.name != _R0_RUN_ID:
        raise SystemExit(f"parent run 必须是 {_R0_RUN_ID}")

    corpus, evaluation_set, _ = _load_corpus_and_eval(
        Path(args.corpus_root), Path(args.dev_jsonl)
    )
    manifest_sha, freeze_id = _validate_manifest(Path(args.dev_manifest))

    analysis_result = reanalyze_planner_dev_run(
        parent_run_dir=parent_run_dir,
        expected_r0_sha256=_R0_SHA256,
        evaluation_set=evaluation_set,
        dev_manifest_sha256=manifest_sha,
        gate3_dataset_freeze_id=freeze_id,
        analysis_source_commit=args.analysis_source_commit,
    )
    if len(analysis_result.case_results) != _EXPECTED_DEV_CASE_COUNT:
        raise SystemExit("R0 重算 Case 数不为 24")

    analysis_root = parent_run_dir / "analysis"
    sha_map = write_analysis_artifacts(analysis_result, analysis_root)
    print(f"analysis_id: {analysis_result.analysis_id}")
    print(f"analysis_dir: {analysis_root / analysis_result.analysis_id}")
    print(f"artifact_sha: {sha_map}")
    print("下一步：人工创建 planner_semantic_review.md 后执行 finalize-analysis。")
    return 0


def cmd_finalize_analysis(args: argparse.Namespace) -> int:
    analysis_dir = Path(args.analysis_dir)
    if not analysis_dir.is_dir():
        raise SystemExit(f"analysis_dir 不存在: {analysis_dir}")
    sha_map = finalize_analysis(analysis_dir)
    print(f"result.json written: {analysis_dir / 'result.json'}")
    print(f"artifact_sha: {sha_map}")
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
        description="Gate 3 Dev Planner 校准（v2 + 离线重分析）"
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    run_p = sub.add_parser("run")
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

    re_p = sub.add_parser("reanalyze")
    re_p.add_argument("--corpus-root", required=True)
    re_p.add_argument("--dev-jsonl", required=True)
    re_p.add_argument("--dev-manifest", required=True)
    re_p.add_argument("--parent-run-dir", required=True)
    re_p.add_argument("--analysis-source-commit", required=True)
    re_p.set_defaults(func=cmd_reanalyze)

    fa_p = sub.add_parser("finalize-analysis")
    fa_p.add_argument("--analysis-dir", required=True)
    fa_p.set_defaults(func=cmd_finalize_analysis)

    fin_p = sub.add_parser("finalize")
    fin_p.add_argument("--run-dir", required=True)
    fin_p.set_defaults(func=cmd_finalize)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
