"""G4-EVAL-06B-01：Gate 4 正式 Dev Runner（preflight gates + 两阶段 Gold 隔离 +
15 项冻结指标 + artifact + 原子 finalize）。

正式执行纪律：
- tracked clean 绑定 source_commit（禁止 CLI 手填）；
- 冻结 benchmark preflight（evaluation_set_id / jsonl_sha256 / 24 case / 六类各 4 /
  manifest 冻结常量），任一不符 → 0 model call fail-fast；
- 正式 corpus provenance hard gate（GATE4_KNOWLEDGE_CORPUS_ROOT，不允许 fallback /
  skip）；
- code Gold intact（git diff 91627bb..HEAD -- core/tool_agent core/agent_runtime 为空）；
- output no-overwrite；<run_id>.partial → 原子 finalize；
- --execute 必须 GATE4_TOOL_USE_EXECUTION_AUTHORIZED=1，否则 0 model call；
- 未知异常 abort 保留现场；不自动 retry / resume / overwrite；
- total decision calls ≤ 120。

本任务只跑 Fake / Scripted Provider + real Tool wiring + real corpus preflight，
0 real LLM。依赖通过构造参数注入（git_context / corpus_verifier / retrieval_port /
provider_factory），便于 0-LLM harness 测试。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional, Sequence

from core.agent_runtime.adapters import PipelineRetrievalAdapter
from core.chunker.recursive import RecursiveChunker
from core.loader.text_loader import TextLoader
from core.retriever.bm25_only import BM25OnlyRetriever
from core.tool_agent import (
    ToolAgentBudget,
    ToolAgentRuntime,
    build_readonly_tool_registry,
)
from core.tool_agent.decision_prompt import (
    DECISION_PROMPT_SHA256,
    DECISION_PROMPT_VERSION,
    compute_toolset_sha256,
)
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate4.schema import (
    CATEGORIES,
    CATEGORY_COUNT_PER_TYPE,
    CODE_REFERENCE_COMMIT,
    KNOWLEDGE_CORPUS_FILE_COUNT,
    KNOWLEDGE_CORPUS_ID,
    Gate4ToolUseEvaluationSet,
)
from evaluation.gate4.evaluator import (
    compute_metrics,
    evaluate_case,
)
from evaluation.gate4.runner_models import (
    FROZEN_CHUNK_OVERLAP,
    FROZEN_CHUNK_SIZE,
    FROZEN_CHUNK_STRATEGY,
    FROZEN_KNOWLEDGE_STRATEGY,
    FROZEN_KNOWLEDGE_TOP_K,
    FROZEN_MAX_AGENT_ITERATIONS,
    FROZEN_MAX_TOOL_CALLS,
    FROZEN_MAX_TOOL_ERRORS,
    FROZEN_MODEL,
    FROZEN_PROVIDER,
    Gate4ExecutionResult,
    Gate4ToolUseRunConfig,
    RecordingDecisionProvider,
)

# 冻结 benchmark 身份（protocol §7 / 卡片 §7）
FROZEN_EVALUATION_SET_ID = "5639ca57b09a"
FROZEN_DATASET_JSONL_SHA256 = (
    "93a32e64130d79a4133fb01d1c84a3103940f286bacece5d2711c38add39e8af"
)
FROZEN_CASE_COUNT = 24
FROZEN_TOTAL_DECISION_CALLS_CAP = 120

PREFLIGHT_SCHEMA_VERSION = "gate4_tool_use_preflight_v1"
RESULT_SCHEMA_VERSION = "gate4_tool_use_result_v1"
METRICS_SCHEMA_VERSION = "gate4_tool_use_metrics_v1"
ARTIFACT_MANIFEST_SCHEMA_VERSION = "gate4_tool_use_artifact_manifest_v1"

ARTIFACT_FILENAMES = (
    "run_config.json",
    "execution_results.jsonl",
    "case_scores.jsonl",
    "metrics.json",
    "result.json",
    "report.md",
    "artifact_manifest.json",
)


class RunnerAbort(Exception):
    """正式 run 中止（任一 gate 失败 / 基础设施错误）。执行现场保留。"""


# ---------------------------------------------------------------------- #
# Git 上下文（生产用真实 git；测试可注入 fake）
# ---------------------------------------------------------------------- #


class GitContext:
    def __init__(self, repo_root: str | os.PathLike) -> None:
        self._repo = Path(repo_root)

    def source_commit(self) -> str:
        return self._git(["rev-parse", "HEAD"]).strip()

    def is_tracked_clean(self) -> bool:
        out = self._git(["status", "--porcelain"])
        tracked = [
            line
            for line in out.splitlines()
            if line and not line.startswith("??")
        ]
        return not tracked

    def code_gold_diff_ok(self, code_reference_commit: str) -> bool:
        out = self._git(
            [
                "diff",
                "--name-only",
                f"{code_reference_commit}...HEAD",
                "--",
                "core/tool_agent",
                "core/agent_runtime",
            ]
        )
        return not out.strip()

    def _git(self, args: Sequence[str]) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self._repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RunnerAbort(
                f"git {' '.join(args)} 失败：{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout


# ---------------------------------------------------------------------- #
# Preflight 纯函数
# ---------------------------------------------------------------------- #


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_dataset_identity(
    set_obj: Gate4ToolUseEvaluationSet,
    dataset_sha: str,
    manifest: dict,
) -> None:
    """冻结 benchmark preflight（卡片 §7）；任一不符 → RunnerAbort。"""
    if set_obj.evaluation_set_id != FROZEN_EVALUATION_SET_ID:
        raise RunnerAbort(
            f"evaluation_set_id 不符：期望 {FROZEN_EVALUATION_SET_ID}，"
            f"实际 {set_obj.evaluation_set_id}"
        )
    if dataset_sha != FROZEN_DATASET_JSONL_SHA256:
        raise RunnerAbort(
            f"dataset jsonl_sha256 不符：期望 {FROZEN_DATASET_JSONL_SHA256[:12]}…，"
            f"实际 {dataset_sha[:12]}…"
        )
    if set_obj.case_count != FROZEN_CASE_COUNT:
        raise RunnerAbort(
            f"case_count 不符：期望 {FROZEN_CASE_COUNT}，实际 {set_obj.case_count}"
        )
    for cat in CATEGORIES:
        if set_obj.category_counts.get(cat) != CATEGORY_COUNT_PER_TYPE:
            raise RunnerAbort(
                f"category {cat} 数量不符：期望 {CATEGORY_COUNT_PER_TYPE}，"
                f"实际 {set_obj.category_counts.get(cat)}"
            )
    manifest_expected = {
        "code_reference_commit": CODE_REFERENCE_COMMIT,
        "knowledge_corpus_id": KNOWLEDGE_CORPUS_ID,
        "knowledge_corpus_file_count": KNOWLEDGE_CORPUS_FILE_COUNT,
        "evaluation_set_id": FROZEN_EVALUATION_SET_ID,
        "jsonl_sha256": FROZEN_DATASET_JSONL_SHA256,
    }
    for key, expected in manifest_expected.items():
        actual = manifest.get(key)
        if actual != expected:
            raise RunnerAbort(f"manifest {key} 不符：期望 {expected}，实际 {actual}")


def collect_corpus_relative_paths(corpus_root: str | os.PathLike) -> tuple[str, ...]:
    root = Path(corpus_root)
    if not root.is_dir():
        raise RunnerAbort(f"语料根目录不存在：{root}")
    paths = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*.md")
        if p.is_file()
    )
    if not paths:
        raise RunnerAbort(f"语料根目录下没有 .md 文件：{root}")
    return tuple(paths)


def verify_knowledge_gold_provenance(
    corpus_root: str | os.PathLike,
    set_obj: Gate4ToolUseEvaluationSet,
) -> None:
    """逐条验证 knowledge_gold：source 存在 + evidence_phrase 连续 substring。

    独立函数便于单独测试 evidence mismatch（corpus_id 校验前置由
    verify_corpus_provenance 负责）。
    """
    root = Path(corpus_root)
    for case in set_obj.cases:
        if case.knowledge_gold is None:
            continue
        source_name = case.knowledge_gold.source_name
        posix = PurePosixPath(source_name).as_posix()
        src = (root / posix).resolve()
        if not src.is_file():
            raise RunnerAbort(f"{case.case_id} source 文件不存在：{source_name}")
        text = src.read_text(encoding="utf-8")
        if case.knowledge_gold.evidence_phrase not in text:
            raise RunnerAbort(
                f"{case.case_id} evidence_phrase 不是 {source_name} 的连续 substring"
            )


def verify_corpus_provenance(
    corpus_root: str | os.PathLike,
    set_obj: Gate4ToolUseEvaluationSet,
) -> tuple[str, int, tuple[str, ...]]:
    """正式 corpus provenance hard gate（卡片 §8，不允许 skip）。

    用 ExperimentCorpus 同一 identity 机制（relative path + raw SHA + size，
    含路径逃逸 / 符号链接防护）验证 corpus；再逐条验证 knowledge_gold
    source existence + evidence 连续 substring。
    返回 (corpus_id, file_count, relative_paths)。
    """
    relative_paths = collect_corpus_relative_paths(corpus_root)
    corpus = ExperimentCorpus.build(corpus_root, relative_paths)
    if corpus.corpus_id != KNOWLEDGE_CORPUS_ID:
        raise RunnerAbort(
            f"corpus_id 不符：期望 {KNOWLEDGE_CORPUS_ID}，实际 {corpus.corpus_id}"
        )
    if len(corpus.entries) != KNOWLEDGE_CORPUS_FILE_COUNT:
        raise RunnerAbort(
            f"corpus file_count 不符：期望 {KNOWLEDGE_CORPUS_FILE_COUNT}，"
            f"实际 {len(corpus.entries)}"
        )
    verify_knowledge_gold_provenance(corpus_root, set_obj)
    return corpus.corpus_id, len(corpus.entries), relative_paths


def build_bm25_retrieval_port(
    corpus_root: str | os.PathLike,
    relative_paths: Sequence[str],
    *,
    chunk_size: int = FROZEN_CHUNK_SIZE,
    chunk_overlap: int = FROZEN_CHUNK_OVERLAP,
):
    """冻结 knowledge tool 链：frozen corpus → loader/chunker → BM25OnlyRetriever
    → PipelineRetrievalAdapter。不调用 Embedding / 不联网。"""
    root = Path(corpus_root)
    loader = TextLoader()
    chunker = RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    retriever = BM25OnlyRetriever()
    chunk_tuples: list[tuple] = []
    for rp in relative_paths:
        full = root / rp
        if not full.is_file():
            raise RunnerAbort(f"语料文件缺失: {rp}")
        docs = loader.load(str(full))
        chunks = chunker.chunk(docs)
        source_name = PurePosixPath(rp).as_posix()
        for c in chunks:
            c.metadata["source_name"] = source_name
            chunk_tuples.append((c.metadata["id"], c.content, c.metadata))
    retriever.build_sparse_index(chunk_tuples)
    return PipelineRetrievalAdapter(retriever)


def build_run_config(
    *,
    source_commit: str,
    set_obj: Gate4ToolUseEvaluationSet,
    dataset_sha: str,
    toolset_sha256: str,
    provider: str,
    model: str,
) -> Gate4ToolUseRunConfig:
    return Gate4ToolUseRunConfig(
        source_commit=source_commit,
        evaluation_set_id=set_obj.evaluation_set_id,
        dataset_jsonl_sha256=dataset_sha,
        code_reference_commit=CODE_REFERENCE_COMMIT,
        knowledge_corpus_id=KNOWLEDGE_CORPUS_ID,
        knowledge_corpus_file_count=KNOWLEDGE_CORPUS_FILE_COUNT,
        provider=provider,
        model=model,
        prompt_version=DECISION_PROMPT_VERSION,
        prompt_sha256=DECISION_PROMPT_SHA256,
        toolset_sha256=toolset_sha256,
    )


# ---------------------------------------------------------------------- #
# Runner
# ---------------------------------------------------------------------- #


class Gate4ToolUseRunner:
    """正式 Runner；依赖经构造参数注入，便于 0-LLM harness 测试。"""

    def __init__(
        self,
        *,
        repo_root: str | os.PathLike,
        dataset_path: str | os.PathLike,
        manifest_path: str | os.PathLike,
        output_root: str | os.PathLike,
        corpus_root: str | os.PathLike | None,
        mode: str,
        execution_authorized: bool,
        git_context: Any = None,
        corpus_verifier: Callable = verify_corpus_provenance,
        retrieval_port: Any = None,
        provider_factory: Callable | None = None,
        provider: str = FROZEN_PROVIDER,
        model: str = FROZEN_MODEL,
    ) -> None:
        if mode not in ("preflight", "execute"):
            raise ValueError(f"mode 必须是 preflight/execute，实际 {mode!r}")
        self.repo_root = Path(repo_root)
        self.dataset_path = Path(dataset_path)
        self.manifest_path = Path(manifest_path)
        self.output_root = Path(output_root)
        self.corpus_root = Path(corpus_root) if corpus_root else None
        self.mode = mode
        self.execution_authorized = bool(execution_authorized)
        self.git = git_context or GitContext(repo_root)
        self.corpus_verifier = corpus_verifier
        self._retrieval_port = retrieval_port
        self._provider_factory = provider_factory
        self.provider = provider
        self.model = model

    # ---- preflight ---------------------------------------------------- #

    def preflight(self) -> dict:
        """全部 gate；成功返回 preflight 事实，并设置内部 state。"""
        if not self.git.is_tracked_clean():
            raise RunnerAbort("tracked 有未提交修改：拒绝运行（必须 tracked clean）")
        if self.mode == "execute" and not self.execution_authorized:
            raise RunnerAbort(
                "execute 模式必须设置 GATE4_TOOL_USE_EXECUTION_AUTHORIZED=1"
            )

        source_commit = self.git.source_commit()
        set_obj = Gate4ToolUseEvaluationSet.load_jsonl(self.dataset_path)
        dataset_sha = sha256_bytes(self.dataset_path.read_bytes())
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        verify_dataset_identity(set_obj, dataset_sha, manifest)

        if not self.git.code_gold_diff_ok(CODE_REFERENCE_COMMIT):
            raise RunnerAbort(
                "code Gold 核心代码面已变化（core/tool_agent 或 core/agent_runtime "
                "在 benchmark code reference commit 之后被改）：不得继续用旧 benchmark"
            )

        if self.corpus_root is None:
            raise RunnerAbort("缺少 GATE4_KNOWLEDGE_CORPUS_ROOT（不允许 fallback）")
        corpus_id, corpus_file_count, relative_paths = self.corpus_verifier(
            self.corpus_root, set_obj
        )

        if self._retrieval_port is not None:
            port = self._retrieval_port
        else:
            port = build_bm25_retrieval_port(
                self.corpus_root, relative_paths,
                chunk_size=FROZEN_CHUNK_SIZE, chunk_overlap=FROZEN_CHUNK_OVERLAP,
            )
        registry = build_readonly_tool_registry(
            self.repo_root,
            port,
            knowledge_strategy=FROZEN_KNOWLEDGE_STRATEGY,
            knowledge_top_k=FROZEN_KNOWLEDGE_TOP_K,
        )
        toolset_sha256 = compute_toolset_sha256(registry.list_specs())

        config = build_run_config(
            source_commit=source_commit,
            set_obj=set_obj,
            dataset_sha=dataset_sha,
            toolset_sha256=toolset_sha256,
            provider=self.provider,
            model=self.model,
        )
        run_id = config.compute_run_id()
        run_dir = self.output_root / run_id
        if run_dir.exists():
            raise FileExistsError(
                f"{run_id}/ 已存在，禁止覆盖（不 rm / overwrite / resume）"
            )

        self._set_obj = set_obj
        self._registry = registry
        self._config = config
        self._run_id = run_id
        self._relative_paths = relative_paths

        return {
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "source_commit": source_commit,
            "evaluation_set_id": set_obj.evaluation_set_id,
            "jsonl_sha256": dataset_sha,
            "corpus_id": corpus_id,
            "corpus_file_count": corpus_file_count,
            "toolset_sha256": toolset_sha256,
            "run_id": run_id,
            "preflight": "PASS",
            "model_calls": 0,
        }

    # ---- execution（Phase A） ------------------------------------------ #

    def _execute(self) -> tuple[Gate4ExecutionResult, ...]:
        provider = RecordingDecisionProvider(self._build_provider())
        runtime = ToolAgentRuntime(
            registry=self._registry,
            provider=provider,
            budget=ToolAgentBudget(
                max_agent_iterations=FROZEN_MAX_AGENT_ITERATIONS,
                max_tool_calls=FROZEN_MAX_TOOL_CALLS,
                max_tool_errors=FROZEN_MAX_TOOL_ERRORS,
            ),
        )
        results: list[Gate4ExecutionResult] = []
        for case in sorted(self._set_obj.cases, key=lambda c: c.case_id):
            start = provider.call_count
            try:
                run_result = runtime.run(case.query)
            except RunnerAbort:
                raise
            except Exception as exc:  # 基础设施错误 → abort 保留现场
                raise RunnerAbort(
                    f"case {case.case_id} 基础设施异常：{type(exc).__name__}"
                ) from exc
            end = provider.call_count
            decisions = provider.slice_decisions(start, end)
            agg = RecordingDecisionProvider.aggregate(decisions)
            results.append(
                Gate4ExecutionResult(
                    case_id=case.case_id,
                    status=run_result.status,
                    answer=run_result.answer,
                    reason_code=run_result.reason_code,
                    failure_code=run_result.failure_code,
                    iterations_used=run_result.iterations_used,
                    tool_calls_used=run_result.tool_calls_used,
                    tool_errors_used=run_result.tool_errors_used,
                    trace=tuple(e.to_dict() for e in run_result.trace),
                    decisions=decisions,
                    decision_call_count=agg["decision_call_count"],
                    input_tokens=agg["input_tokens"],
                    output_tokens=agg["output_tokens"],
                    total_latency_ms=agg["total_latency_ms"],
                    prompt_version=agg["prompt_version"],
                    prompt_sha256=agg["prompt_sha256"],
                    toolset_sha256=agg["toolset_sha256"],
                )
            )
        if provider.call_count > FROZEN_TOTAL_DECISION_CALLS_CAP:
            raise RunnerAbort(
                f"total decision calls {provider.call_count} > "
                f"{FROZEN_TOTAL_DECISION_CALLS_CAP}"
            )
        return tuple(results)

    def _build_provider(self):
        if self._provider_factory is not None:
            return self._provider_factory(self._registry)
        from core.tool_agent.openai_compatible import (
            OpenAICompatibleAgentDecisionProvider,
        )

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RunnerAbort("缺少 DEEPSEEK_API_KEY（execute 模式需要）")
        return OpenAICompatibleAgentDecisionProvider(
            provider=FROZEN_PROVIDER,
            model=FROZEN_MODEL,
            api_key=api_key,
            temperature=0,
            max_tokens=600,
            max_retries=0,
            timeout=20.0,
        )

    # ---- evaluation（Phase B） + artifact ------------------------------ #

    def _run_pipeline(self, partial_dir: Path) -> dict:
        results = self._execute()
        self._write_jsonl(
            partial_dir / "execution_results.jsonl",
            [r.to_dict() for r in results],
        )

        exec_ids = {r.case_id for r in results}
        gold_ids = {c.case_id for c in self._set_obj.cases}
        if exec_ids != gold_ids or len(exec_ids) != FROZEN_CASE_COUNT:
            raise RunnerAbort(
                "execution case_id set != Gold case_id set（多/少/重复全部 fail）"
            )

        gold_by_id = {c.case_id: c for c in self._set_obj.cases}
        scores = [
            evaluate_case(gold_by_id[r.case_id], r) for r in results
        ]
        metrics = compute_metrics(scores)

        self._write_json(partial_dir / "run_config.json", self._config.to_dict())
        self._write_jsonl(
            partial_dir / "case_scores.jsonl", [s.to_dict() for s in scores]
        )
        self._write_json(
            partial_dir / "metrics.json",
            {
                "schema_version": METRICS_SCHEMA_VERSION,
                "run_id": self._run_id,
                "evaluation_set_id": FROZEN_EVALUATION_SET_ID,
                "metrics": metrics,
            },
        )
        result_obj = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "run_id": self._run_id,
            "config": self._config.to_dict(),
            "metrics": metrics,
            "status": "completed",
            "decision_call_count": sum(r.decision_call_count for r in results),
        }
        self._write_json(partial_dir / "result.json", result_obj)
        self._write_report(partial_dir / "report.md", result_obj, scores)
        self._write_artifact_manifest(partial_dir)
        return result_obj

    # ---- 对外 run() ---------------------------------------------------- #

    def run(self) -> dict:
        """preflight → preflight-only 报告 / execute 全流程。"""
        facts = self.preflight()
        if self.mode == "preflight":
            return facts

        partial_dir = self.output_root / f"{self._run_id}.partial"
        partial_dir.mkdir(parents=True, exist_ok=False)
        try:
            result_obj = self._run_pipeline(partial_dir)
        except BaseException:
            # 保留 partial 现场交给 Reviewer；不自动 cleanup
            raise
        final_dir = self.output_root / self._run_id
        if final_dir.exists():
            raise FileExistsError(f"{self._run_id} 已存在（finalize 前被占用）")
        partial_dir.rename(final_dir)
        return result_obj

    # ---- 写盘 helper ---------------------------------------------------- #

    @staticmethod
    def _write_json(path: Path, obj: dict) -> None:
        path.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_jsonl(path: Path, objs: Sequence[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(o, ensure_ascii=False) for o in objs) + "\n",
            encoding="utf-8",
        )

    def _write_report(
        self, path: Path, result_obj: dict, scores: Sequence[Any]
    ) -> None:
        lines = [
            "# Gate 4 Tool-Use Dev Run",
            "",
            f"- run_id: `{result_obj['run_id']}`",
            f"- status: {result_obj['status']}",
            "",
            "## Metrics",
            "",
        ]
        for name, entry in result_obj["metrics"].items():
            lines.append(
                f"- {name}: value={entry['value']} "
                f"(numerator={entry['numerator']}, denominator={entry['denominator']})"
            )
        lines += ["", "## Case scores", ""]
        for s in scores:
            lines.append(
                f"- {s.case_id} [{s.category}] status={s.status} "
                f"first_action={s.actual_first_action} first_tool={s.actual_first_tool} "
                f"seq={list(s.executed_tool_sequence)} "
                f"assertions={s.assertions_passed} term={s.termination_correct}"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_artifact_manifest(self, partial_dir: Path) -> None:
        entries = {}
        for name in ARTIFACT_FILENAMES:
            p = partial_dir / name
            if not p.is_file():
                continue
            data = p.read_bytes()
            entries[name] = {
                "sha256": sha256_bytes(data),
                "size_bytes": len(data),
            }
        self._write_json(
            partial_dir / "artifact_manifest.json",
            {
                "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
                "run_id": self._run_id,
                "files": entries,
            },
        )


__all__ = [
    "FROZEN_EVALUATION_SET_ID",
    "FROZEN_DATASET_JSONL_SHA256",
    "FROZEN_CASE_COUNT",
    "FROZEN_TOTAL_DECISION_CALLS_CAP",
    "PREFLIGHT_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "METRICS_SCHEMA_VERSION",
    "ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "ARTIFACT_FILENAMES",
    "RunnerAbort",
    "GitContext",
    "sha256_bytes",
    "verify_dataset_identity",
    "collect_corpus_relative_paths",
    "verify_corpus_provenance",
    "verify_knowledge_gold_provenance",
    "build_bm25_retrieval_port",
    "build_run_config",
    "Gate4ToolUseRunner",
]
