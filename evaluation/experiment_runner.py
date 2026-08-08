"""ExperimentRunner：工作区 + 独立 Pipeline 接通（prepare），
以及正式语料入库与索引 Manifest（index_corpus）。

prepare() 将 ExperimentConfig → ExperimentWorkspace（派生配置）→ 独立
Pipeline 接通，并验证 Pipeline 实际使用了派生配置，防止实验跑在
错误配置上。index_corpus() 只负责入库：先完整性校验、再确定性入库、
再做 Dense/BM25 一致性校验，最后原子写入 Manifest；不执行查询与评测。
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.experiment_result import (
    ARTIFACT_FILES,
    EXPERIMENT_RESULT_SCHEMA_VERSION,
    ExperimentResult,
)
from evaluation.experiment_workspace import ExperimentPaths, ExperimentWorkspace
from evaluation.index_manifest import FileIndexRecord, IndexManifest
from evaluation.retrieval_evaluation_set import RetrievalCase, RetrievalEvaluationSet
from evaluation.retrieval_result import (
    RETRIEVAL_RESULT_SCHEMA_VERSION,
    SCORE_WHITELIST,
    RetrievalCaseResult,
    RetrievalHit,
    RetrievalRunResult,
)
from evaluation.retrieval_diagnostics import (
    RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION,
    ChannelCandidate,
    DiagnosticCase,
    RetrievalDiagnosticSnapshot,
)
from evaluation.retrieval_metrics import (
    AGGREGATION,
    METRICS_SCHEMA_VERSION,
    METRIC_SCOPE,
    RELEVANCE,
    RetrievalMetricsResult,
    compute_case_metrics,
)


@dataclass(frozen=True)
class PreparedExperiment:
    """一次已准备就绪的实验：配置、工作区路径与独立 Pipeline"""

    experiment_config: ExperimentConfig
    paths: ExperimentPaths
    pipeline: object


class ExperimentRunner:
    """准备工作区、创建独立 Pipeline，并执行可复现语料入库"""

    def __init__(
        self,
        base_config_path: Union[str, Path],
        workspace_root: Union[str, Path],
        pipeline_factory: Callable[[Path], object] | None = None,
    ):
        self.base_config_path = Path(base_config_path)
        self.workspace_root = Path(workspace_root)
        self._pipeline_factory = pipeline_factory or self._default_pipeline_factory

    @staticmethod
    def _default_pipeline_factory(config_path: Path):
        from core.pipeline import Pipeline
        return Pipeline(str(config_path))

    def prepare(self, config: ExperimentConfig, run_id: str) -> PreparedExperiment:
        workspace = ExperimentWorkspace(
            self.base_config_path, self.workspace_root, config, run_id
        )
        paths = workspace.prepare()
        pipeline = self._pipeline_factory(paths.config_path)
        self._validate_pipeline(pipeline, config, paths)
        return PreparedExperiment(
            experiment_config=config, paths=paths, pipeline=pipeline
        )

    def _validate_pipeline(self, pipeline, config: ExperimentConfig, paths: ExperimentPaths):
        """Pipeline 必须实际使用派生配置；不一致立即终止，不产生半成品结果"""
        cfg = pipeline.config
        checks = {
            "embedding_provider": (
                cfg.embedding_provider,
                config.embedding_provider,
            ),
            "embedding_model": (
                cfg.embedding_model,
                config.embedding_model,
            ),
            "chunker_strategy": (cfg.chunker_strategy, config.chunk_strategy),
            "chunk_size": (cfg.chunk_size, config.chunk_size),
            "chunk_overlap": (cfg.chunk_overlap, config.chunk_overlap),
            "retriever_strategy": (cfg.retriever_strategy, config.retriever_strategy),
            "top_k": (cfg.top_k, config.top_k),
            "dense_candidate_k": (cfg.dense_candidate_k, config.dense_candidate_k),
            "sparse_candidate_k": (cfg.sparse_candidate_k, config.sparse_candidate_k),
            "rrf_k": (cfg.rrf_k, config.rrf_k),
            "rrf_tie_breaker": (
                cfg.rrf_tie_breaker,
                config.rrf_tie_breaker,
            ),
        }
        for name, (actual, expected) in checks.items():
            if actual != expected:
                raise RuntimeError(
                    f"Pipeline 配置 {name} 与实验配置不一致："
                    f"actual={actual!r} expected={expected!r}，不能继续实验"
                )
        if config.retriever_strategy == "hybrid":
            actual_breaker = getattr(
                getattr(pipeline, "retriever", None),
                "rrf_tie_breaker",
                None,
            )
            if actual_breaker != config.rrf_tie_breaker:
                raise RuntimeError(
                    "HybridRetriever.rrf_tie_breaker 与实验配置不一致："
                    f"actual={actual_breaker!r} expected={config.rrf_tie_breaker!r}，"
                    "不能继续实验"
                )
        vs_actual = Path(cfg.vector_store_path).resolve()
        if vs_actual != paths.vector_store_path.resolve():
            raise RuntimeError(
                f"Pipeline vector_store.path 与实验工作区不一致："
                f"actual={vs_actual} expected={paths.vector_store_path}，"
                "不能继续实验"
            )

    def index_corpus(
        self, prepared: PreparedExperiment, corpus: ExperimentCorpus
    ) -> IndexManifest:
        """正式语料入库：完整性校验 -> 确定性入库 -> 数量一致性 -> 原子 Manifest。

        失败时绝不生成成功 Manifest；正式 Manifest 已存在时在入库前拒绝。
        """
        manifest_path = prepared.paths.index_manifest_path
        if manifest_path.exists():
            raise FileExistsError(
                f"实验工作区已存在 index_manifest.json，禁止重复入库或覆盖："
                f"{manifest_path}"
            )

        # 必须先验证全部文件，再开始第一个文件入库，避免后面文件损坏时
        # 前面文件已经被部分写入。
        validated_paths = self._validate_corpus_integrity(corpus)

        file_records = []
        total_chunks = 0
        for entry, file_path in zip(corpus.entries, validated_paths):
            result = prepared.pipeline.index_file(str(file_path))
            status = result.get("status")
            if status != "create":
                raise RuntimeError(
                    f"实验索引可能被污染、重复执行或 Workspace 不再干净："
                    f"{entry.relative_path} 期望 status='create'，实际 {status!r}；"
                    "不得生成正式 Manifest"
                )
            file_records.append(FileIndexRecord(
                relative_path=entry.relative_path,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                document_id=result.get("document_id"),
                chunks=result.get("chunks"),
                status=status,
            ))
            total_chunks += result.get("chunks")

        vector_store_count = prepared.pipeline.vector_store.count()
        if vector_store_count != total_chunks:
            raise RuntimeError(
                f"向量库实际数量 {vector_store_count} 与入库 chunks 总和 "
                f"{total_chunks} 不一致，不得生成正式 Manifest"
            )

        sparse_index_count = None
        if prepared.experiment_config.retriever_strategy == "hybrid":
            sparse_index_count = self._validate_hybrid_sparse_index(
                prepared, vector_store_count
            )

        config = prepared.experiment_config
        manifest = IndexManifest(
            schema_version=1,
            experiment_id=config.experiment_id,
            corpus_id=corpus.corpus_id,
            chunk_strategy=config.chunk_strategy,
            retriever_strategy=config.retriever_strategy,
            config=config.to_dict(),
            corpus_entries=tuple(
                {
                    "relative_path": e.relative_path,
                    "sha256": e.sha256,
                    "size_bytes": e.size_bytes,
                }
                for e in corpus.entries
            ),
            files=tuple(file_records),
            file_count=len(file_records),
            total_chunks=total_chunks,
            vector_store_count=vector_store_count,
            sparse_index_count=sparse_index_count,
        )
        manifest.write_json(manifest_path)
        return manifest

    @staticmethod
    def _validate_corpus_integrity(corpus: ExperimentCorpus) -> tuple[Path, ...]:
        """入库前一次性重读全部语料原始字节并校验，返回已验证的规范文件路径。

        corpus_root 本身是 ExperimentCorpus.build() 时 resolve 过的不可变锚点，
        不能再次 resolve 后当作新可信根；否则整个根被替换成指向外部的
        junction/symlink 时会把外部目标误认为可信根。

        校验项：锚点仍存在、仍是目录、resolve 后没有变成与构建时不同的目标；
        每个文件 resolve 后仍在锚点内、是普通文件、size_bytes 一致、SHA-256 一致。
        任一失败立即抛异常，且不会静默重算 corpus_id。
        """
        anchor = Path(corpus.corpus_root)
        if not anchor.exists():
            raise FileNotFoundError(
                f"corpus_root 在构建后被删除或替换：{anchor}"
            )
        if not anchor.is_dir():
            raise ValueError(
                f"corpus_root 在构建后不再是目录：{anchor}"
            )
        resolved_anchor = anchor.resolve()
        if resolved_anchor != anchor:
            raise ValueError(
                f"corpus_root 在构建后被重定向或替换（resolve 与构建时锚点不同）："
                f"{anchor} -> {resolved_anchor}"
            )

        validated_paths = []
        for entry in corpus.entries:
            full = (anchor / entry.relative_path).resolve()
            if not full.is_relative_to(anchor):
                raise ValueError(
                    f"语料路径逃逸 corpus_root（符号链接/junction 指向外部）："
                    f"{entry.relative_path}"
                )
            if not full.exists():
                raise FileNotFoundError(
                    f"语料文件已不存在：{entry.relative_path}"
                )
            if not full.is_file():
                raise ValueError(
                    f"语料路径不再是普通文件：{entry.relative_path}"
                )
            data = full.read_bytes()
            if len(data) != entry.size_bytes:
                raise ValueError(
                    f"语料文件 size_bytes 不一致：{entry.relative_path} "
                    f"期望 {entry.size_bytes} 实际 {len(data)}"
                )
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != entry.sha256:
                raise ValueError(
                    f"语料文件 SHA-256 不一致：{entry.relative_path} "
                    f"期望 {entry.sha256[:12]}... 实际 {actual_sha[:12]}..."
                )
            validated_paths.append(full)
        return tuple(validated_paths)

    def run_retrieval(
        self,
        prepared: PreparedExperiment,
        index_manifest: IndexManifest,
        evaluation_set: RetrievalEvaluationSet,
    ) -> RetrievalRunResult:
        """正式检索执行：绑定校验 -> 逐 Case 直接调用 Retriever -> 原子快照。

        只允许调用 retriever.retrieve(case.query, top_k=config.top_k)；
        不调用 Pipeline.query/Generator/Reranker/旧 Evaluator/指标/报告。
        """
        result_path = prepared.paths.retrieval_results_path
        if result_path.exists():
            raise FileExistsError(
                f"实验工作区已存在 retrieval_results.json，禁止重复运行或覆盖："
                f"{result_path}"
            )
        if not prepared.paths.index_manifest_path.is_file():
            raise FileNotFoundError(
                f"实验工作区缺少 index_manifest.json，必须先完成正式入库："
                f"{prepared.paths.index_manifest_path}"
            )

        self._validate_persisted_manifest(
            prepared.paths.index_manifest_path, index_manifest
        )
        self._validate_retrieval_binding(prepared, index_manifest, evaluation_set)
        document_map = self._build_document_map(index_manifest)

        config = prepared.experiment_config
        top_k = config.top_k
        case_results = []
        for case in evaluation_set.cases:
            retrieved = prepared.pipeline.retriever.retrieve(case.query, top_k=top_k)
            case_results.append(
                self._snapshot_case_result(case, retrieved, top_k, document_map)
            )

        run_id = RetrievalRunResult.compute_run_id(
            schema_version=RETRIEVAL_RESULT_SCHEMA_VERSION,
            experiment_id=config.experiment_id,
            corpus_id=index_manifest.corpus_id,
            evaluation_set_id=evaluation_set.evaluation_set_id,
            retriever_strategy=config.retriever_strategy,
            top_k=top_k,
        )
        result = RetrievalRunResult(
            schema_version=RETRIEVAL_RESULT_SCHEMA_VERSION,
            retrieval_run_id=run_id,
            experiment_id=config.experiment_id,
            corpus_id=index_manifest.corpus_id,
            evaluation_set_id=evaluation_set.evaluation_set_id,
            retriever_strategy=config.retriever_strategy,
            top_k=top_k,
            cases=tuple(case_results),
        )
        result.write_json(result_path)
        return result

    def compute_retrieval_metrics(
        self,
        prepared: PreparedExperiment,
        retrieval_result: RetrievalRunResult,
        evaluation_set: RetrievalEvaluationSet,
    ) -> RetrievalMetricsResult:
        """文档级指标：磁盘事实快照绑定 -> Case 对应 -> 不变量 -> 指标 -> 原子快照。

        不重新调用 Retriever/Pipeline/Generator/Reranker/旧 Evaluator；
        正式指标只基于 retrieved_files 与 relevant_files。
        """
        metrics_path = prepared.paths.retrieval_metrics_path
        if metrics_path.exists():
            raise FileExistsError(
                f"实验工作区已存在 retrieval_metrics.json，禁止重复计算或覆盖："
                f"{metrics_path}"
            )
        results_path = prepared.paths.retrieval_results_path
        if not results_path.is_file():
            raise FileNotFoundError(
                f"实验工作区缺少 retrieval_results.json，必须先完成正式检索："
                f"{results_path}"
            )

        self._validate_persisted_retrieval_results(results_path, retrieval_result)
        self._validate_retrieval_metrics_binding(
            prepared, retrieval_result, evaluation_set
        )
        self._validate_case_correspondence(retrieval_result, evaluation_set)

        case_metrics = []
        for run_case, eval_case in zip(
            retrieval_result.cases, evaluation_set.cases
        ):
            self._validate_case_snapshot(run_case, retrieval_result.top_k)
            case_metrics.append(compute_case_metrics(
                case_id=run_case.case_id,
                retrieved_files=run_case.retrieved_files,
                relevant_files=eval_case.relevant_files,
                top_k=retrieval_result.top_k,
            ))

        case_count = len(case_metrics)
        means = {}
        for name in ("hit_at_k", "recall_at_k", "mrr", "ndcg_at_k"):
            means[name] = sum(
                getattr(c, name) for c in case_metrics
            ) / case_count

        metrics_run_id = RetrievalMetricsResult.compute_metrics_run_id(
            schema_version=METRICS_SCHEMA_VERSION,
            retrieval_run_id=retrieval_result.retrieval_run_id,
            evaluation_set_id=retrieval_result.evaluation_set_id,
            top_k=retrieval_result.top_k,
            metric_scope=METRIC_SCOPE,
            relevance=RELEVANCE,
            aggregation=AGGREGATION,
        )
        result = RetrievalMetricsResult(
            schema_version=METRICS_SCHEMA_VERSION,
            metrics_run_id=metrics_run_id,
            experiment_id=retrieval_result.experiment_id,
            corpus_id=retrieval_result.corpus_id,
            evaluation_set_id=retrieval_result.evaluation_set_id,
            retrieval_run_id=retrieval_result.retrieval_run_id,
            retriever_strategy=retrieval_result.retriever_strategy,
            top_k=retrieval_result.top_k,
            case_count=case_count,
            cases=tuple(case_metrics),
            mean_hit_at_k=means["hit_at_k"],
            mean_recall_at_k=means["recall_at_k"],
            mean_mrr=means["mrr"],
            mean_ndcg_at_k=means["ndcg_at_k"],
        )
        result.write_json(metrics_path)
        return result

    def finalize_result(
        self,
        prepared: PreparedExperiment,
        index_manifest: IndexManifest,
        retrieval_result: RetrievalRunResult,
        metrics_result: RetrievalMetricsResult,
        evaluation_set: RetrievalEvaluationSet,
    ) -> ExperimentResult:
        """单实验结果收口：三份落盘事实快照绑定 -> 跨阶段校验 -> 原子 result.json。

        不重新调用 index_file/Retriever/Generator/指标计算/旧 Evaluator。
        """
        result_path = prepared.paths.result_path
        if result_path.exists():
            raise FileExistsError(
                f"实验工作区已存在 result.json，禁止重复收口或覆盖："
                f"{result_path}"
            )

        self._validate_persisted_manifest(
            prepared.paths.index_manifest_path, index_manifest
        )
        self._validate_persisted_retrieval_results(
            prepared.paths.retrieval_results_path, retrieval_result
        )
        self._validate_persisted_retrieval_metrics(
            prepared.paths.retrieval_metrics_path, metrics_result
        )
        self._validate_experiment_binding(
            prepared,
            index_manifest,
            retrieval_result,
            metrics_result,
            evaluation_set,
        )
        self._validate_experiment_quantities(
            index_manifest,
            retrieval_result,
            metrics_result,
            evaluation_set,
            prepared.experiment_config.retriever_strategy,
        )

        config = prepared.experiment_config
        result_id = ExperimentResult.compute_result_id(
            schema_version=EXPERIMENT_RESULT_SCHEMA_VERSION,
            experiment_id=config.experiment_id,
            corpus_id=index_manifest.corpus_id,
            evaluation_set_id=evaluation_set.evaluation_set_id,
            retrieval_run_id=retrieval_result.retrieval_run_id,
            metrics_run_id=metrics_result.metrics_run_id,
        )
        result = ExperimentResult(
            schema_version=EXPERIMENT_RESULT_SCHEMA_VERSION,
            result_id=result_id,
            experiment_id=config.experiment_id,
            corpus_id=index_manifest.corpus_id,
            evaluation_set_id=evaluation_set.evaluation_set_id,
            retrieval_run_id=retrieval_result.retrieval_run_id,
            metrics_run_id=metrics_result.metrics_run_id,
            config=config.to_dict(),
            chunk_strategy=config.chunk_strategy,
            retriever_strategy=config.retriever_strategy,
            top_k=config.top_k,
            file_count=index_manifest.file_count,
            total_chunks=index_manifest.total_chunks,
            case_count=metrics_result.case_count,
            mean_hit_at_k=metrics_result.mean_hit_at_k,
            mean_recall_at_k=metrics_result.mean_recall_at_k,
            mean_mrr=metrics_result.mean_mrr,
            mean_ndcg_at_k=metrics_result.mean_ndcg_at_k,
            artifacts=dict(ARTIFACT_FILES),
        )
        result.write_json(result_path)
        return result

    def run_experiment(
        self,
        config: ExperimentConfig,
        run_id: str,
        corpus: ExperimentCorpus,
        evaluation_set: RetrievalEvaluationSet,
    ) -> ExperimentResult:
        """唯一高层入口：prepare -> index_corpus -> run_retrieval ->
        compute_retrieval_metrics -> finalize_result。

        只做编排，不复制任何阶段内部逻辑；原异常向外传播、不重试、
        不清理 Workspace、不做隐式 Resume。run_id 必须由调用方显式提供。
        """
        if evaluation_set.corpus_id != corpus.corpus_id:
            raise ValueError(
                f"evaluation_set.corpus_id={evaluation_set.corpus_id!r} 与 "
                f"corpus.corpus_id={corpus.corpus_id!r} 不一致，禁止运行实验"
            )

        prepared = self.prepare(config, run_id)
        manifest = self.index_corpus(prepared, corpus)
        retrieval_result = self.run_retrieval(prepared, manifest, evaluation_set)
        metrics_result = self.compute_retrieval_metrics(
            prepared, retrieval_result, evaluation_set
        )
        return self.finalize_result(
            prepared,
            manifest,
            retrieval_result,
            metrics_result,
            evaluation_set,
        )

    def run_retrieval_diagnostics(
        self,
        prepared: PreparedExperiment,
        index_manifest: IndexManifest,
        evaluation_set: RetrievalEvaluationSet,
        baseline_retrieval_run_id: str,
        baseline_results_path: Union[str, Path],
    ) -> RetrievalDiagnosticSnapshot:
        """通道级诊断：一次检索暴露 Dense/Sparse 候选与最终命中，
        并强制 Final Top-5 与 Baseline retrieval_results.json 完全一致。

        不重新实现检索/RRF；只读取 retrieve_with_trace() 的单次执行结果，
        通过 IndexManifest 映射 relative_path，原子写入独立诊断 Artifact。
        """
        diagnostic_path = prepared.paths.retrieval_diagnostics_path
        if diagnostic_path.exists():
            raise FileExistsError(
                f"实验工作区已存在 retrieval_diagnostics.json，禁止重复覆盖："
                f"{diagnostic_path}"
            )

        self._validate_persisted_manifest(
            prepared.paths.index_manifest_path, index_manifest
        )
        document_map = self._build_document_map(index_manifest)
        config = prepared.experiment_config

        baseline = self._load_baseline_retrieval_results(baseline_results_path)
        baseline_cases = {c["case_id"]: c for c in baseline.get("cases", [])}
        if len(baseline_cases) != len(evaluation_set.cases):
            raise RuntimeError(
                f"Baseline retrieval_results Case 数量 {len(baseline_cases)} "
                f"与 EvaluationSet {len(evaluation_set.cases)} 不一致"
            )

        top_k = config.top_k
        diagnostic_cases = []
        for case in evaluation_set.cases:
            baseline_case = baseline_cases.get(case.case_id)
            if baseline_case is None:
                raise RuntimeError(
                    f"Baseline retrieval_results 缺少 Case {case.case_id}"
                )
            expected_final_ids = [
                hit["chunk_id"] for hit in baseline_case.get("hits", [])
            ]
            retriever = prepared.pipeline.retriever
            if not hasattr(retriever, "retrieve_with_trace"):
                raise RuntimeError(
                    f"case_id={case.case_id}：Retriever 缺少 "
                    "retrieve_with_trace() 诊断接口"
                )
            trace = retriever.retrieve_with_trace(case.query, top_k=top_k)

            dense_candidates = self._map_channel_candidates(
                trace["dense_candidates"],
                document_map,
                case.case_id,
                "dense",
                ("score", "distance"),
            )
            sparse_candidates = self._map_channel_candidates(
                trace["sparse_candidates"],
                document_map,
                case.case_id,
                "sparse",
                ("sparse_score",),
            )
            final_hits = self._map_final_hits(
                trace["final_results"], document_map, case.case_id
            )

            actual_final_ids = [h.chunk_id for h in final_hits]
            if actual_final_ids != expected_final_ids:
                raise RuntimeError(
                    "diagnostic != baseline："
                    f"case_id={case.case_id} "
                    f"expected={expected_final_ids} actual={actual_final_ids}"
                )

            diagnostic_cases.append(DiagnosticCase(
                case_id=case.case_id,
                query=case.query,
                relevant_files=case.relevant_files,
                dense_candidates=dense_candidates,
                sparse_candidates=sparse_candidates,
                final_hits=final_hits,
            ))

        diagnostic_id = RetrievalDiagnosticSnapshot.compute_diagnostic_id(
            schema_version=RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION,
            experiment_id=config.experiment_id,
            corpus_id=index_manifest.corpus_id,
            evaluation_set_id=evaluation_set.evaluation_set_id,
            baseline_retrieval_run_id=baseline_retrieval_run_id,
            dense_candidate_k=config.dense_candidate_k,
            sparse_candidate_k=config.sparse_candidate_k,
        )
        snapshot = RetrievalDiagnosticSnapshot(
            schema_version=RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION,
            diagnostic_id=diagnostic_id,
            experiment_id=config.experiment_id,
            corpus_id=index_manifest.corpus_id,
            evaluation_set_id=evaluation_set.evaluation_set_id,
            baseline_retrieval_run_id=baseline_retrieval_run_id,
            dense_candidate_k=config.dense_candidate_k,
            sparse_candidate_k=config.sparse_candidate_k,
            cases=tuple(diagnostic_cases),
        )
        snapshot.write_json(diagnostic_path)
        return snapshot

    @staticmethod
    def _load_baseline_retrieval_results(path: Union[str, Path]) -> dict:
        """严格读取 Baseline retrieval_results.json（UTF-8 + object）"""
        baseline_path = Path(path)
        try:
            with baseline_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Baseline retrieval_results.json 无法解析：{exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                "Baseline retrieval_results.json 顶层不是 JSON object"
            )
        return payload

    @staticmethod
    def _map_channel_candidates(
        candidates,
        document_map: dict,
        case_id: str,
        channel: str,
        score_keys: tuple,
    ) -> tuple:
        """把 trace 通道候选映射为可序列化 ChannelCandidate。"""
        mapped = []
        for item in candidates:
            rank = item.get("rank")
            chunk_id = item.get("chunk_id")
            document_id = item.get("document_id")
            if type(rank) is not int:
                raise RuntimeError(
                    f"case_id={case_id}：{channel} 候选 rank 必须是严格 int，"
                    f"实际 {type(rank).__name__}（{rank!r}）"
                )
            if type(chunk_id) is not str or not chunk_id:
                raise RuntimeError(
                    f"case_id={case_id}：{channel} 候选 chunk_id 必须是非空字符串"
                )
            if type(document_id) is not str or not document_id:
                raise RuntimeError(
                    f"case_id={case_id}：{channel} 候选 document_id 必须是非空字符串"
                )
            if document_id not in document_map:
                raise RuntimeError(
                    f"case_id={case_id}：{channel} 候选未知 document_id "
                    f"{document_id!r}（不在 IndexManifest 映射中）"
                )
            scores = {
                key: item[key]
                for key in score_keys
                if key in item
            }
            mapped.append(ChannelCandidate(
                rank=rank,
                chunk_id=chunk_id,
                document_id=document_id,
                relative_path=document_map[document_id],
                scores=scores,
            ))
        return tuple(mapped)

    @staticmethod
    def _map_final_hits(docs, document_map: dict, case_id: str) -> tuple:
        """把 trace 最终 Document 映射为 ChannelCandidate（白名单分数）。"""
        mapped = []
        for rank, doc in enumerate(docs, 1):
            metadata = doc.metadata or {}
            chunk_id = metadata.get("id")
            document_id = metadata.get("document_id")
            if type(chunk_id) is not str or not chunk_id:
                raise RuntimeError(
                    f"case_id={case_id}：最终命中 chunk_id 必须是非空字符串"
                )
            if type(document_id) is not str or not document_id:
                raise RuntimeError(
                    f"case_id={case_id}：最终命中 document_id 必须是非空字符串"
                )
            if document_id not in document_map:
                raise RuntimeError(
                    f"case_id={case_id}：最终命中未知 document_id "
                    f"{document_id!r}"
                )
            scores = {
                name: metadata[name]
                for name in SCORE_WHITELIST
                if name in metadata
            }
            mapped.append(ChannelCandidate(
                rank=rank,
                chunk_id=chunk_id,
                document_id=document_id,
                relative_path=document_map[document_id],
                scores=scores,
            ))
        return tuple(mapped)

    @staticmethod
    def _validate_experiment_binding(
        prepared: PreparedExperiment,
        index_manifest: IndexManifest,
        retrieval_result: RetrievalRunResult,
        metrics_result: RetrievalMetricsResult,
        evaluation_set: RetrievalEvaluationSet,
    ) -> None:
        """跨阶段绑定：ID 链、top_k、策略、Config，并重算两个 run ID。"""
        config = prepared.experiment_config

        if type(config.top_k) is not int:
            raise RuntimeError(
                f"ExperimentConfig.top_k 必须是严格 int，"
                f"实际 {type(config.top_k).__name__}（{config.top_k!r}）"
            )
        if type(retrieval_result.top_k) is not int:
            raise RuntimeError(
                f"retrieval_result.top_k 必须是严格 int，"
                f"实际 {type(retrieval_result.top_k).__name__} "
                f"（{retrieval_result.top_k!r}）"
            )
        if type(metrics_result.top_k) is not int:
            raise RuntimeError(
                f"metrics_result.top_k 必须是严格 int，"
                f"实际 {type(metrics_result.top_k).__name__} "
                f"（{metrics_result.top_k!r}）"
            )

        ids = (
            config.experiment_id,
            index_manifest.experiment_id,
            retrieval_result.experiment_id,
            metrics_result.experiment_id,
        )
        if len(set(ids)) != 1:
            raise RuntimeError("experiment_id 跨阶段不一致")

        corpus_ids = (
            index_manifest.corpus_id,
            retrieval_result.corpus_id,
            metrics_result.corpus_id,
            evaluation_set.corpus_id,
        )
        if len(set(corpus_ids)) != 1:
            raise RuntimeError("corpus_id 跨阶段不一致")

        eval_set_ids = (
            retrieval_result.evaluation_set_id,
            metrics_result.evaluation_set_id,
            evaluation_set.evaluation_set_id,
        )
        if len(set(eval_set_ids)) != 1:
            raise RuntimeError("evaluation_set_id 跨阶段不一致")

        if retrieval_result.retrieval_run_id != metrics_result.retrieval_run_id:
            raise RuntimeError("retrieval_run_id 跨阶段不一致")

        if not (
            retrieval_result.top_k == metrics_result.top_k == config.top_k
        ):
            raise RuntimeError("top_k 跨阶段不一致")

        strategies = (
            index_manifest.retriever_strategy,
            retrieval_result.retriever_strategy,
            metrics_result.retriever_strategy,
            config.retriever_strategy,
        )
        if len(set(strategies)) != 1:
            raise RuntimeError("retriever_strategy 跨阶段不一致")

        if index_manifest.config != config.to_dict():
            raise RuntimeError("index_manifest.config 与 ExperimentConfig 不一致")

        if index_manifest.chunk_strategy != config.chunk_strategy:
            raise RuntimeError("chunk_strategy 与 ExperimentConfig 不一致")

        recomputed_run_id = RetrievalRunResult.compute_run_id(
            schema_version=retrieval_result.schema_version,
            experiment_id=retrieval_result.experiment_id,
            corpus_id=retrieval_result.corpus_id,
            evaluation_set_id=retrieval_result.evaluation_set_id,
            retriever_strategy=retrieval_result.retriever_strategy,
            top_k=retrieval_result.top_k,
        )
        if recomputed_run_id != retrieval_result.retrieval_run_id:
            raise RuntimeError(
                "retrieval_run_id 与绑定字段重算结果不一致："
                f"stored={retrieval_result.retrieval_run_id!r} "
                f"recomputed={recomputed_run_id!r}"
            )

        recomputed_metrics_id = RetrievalMetricsResult.compute_metrics_run_id(
            schema_version=metrics_result.schema_version,
            retrieval_run_id=metrics_result.retrieval_run_id,
            evaluation_set_id=metrics_result.evaluation_set_id,
            top_k=metrics_result.top_k,
            metric_scope=METRIC_SCOPE,
            relevance=RELEVANCE,
            aggregation=AGGREGATION,
        )
        if recomputed_metrics_id != metrics_result.metrics_run_id:
            raise RuntimeError(
                "metrics_run_id 与绑定字段重算结果不一致："
                f"stored={metrics_result.metrics_run_id!r} "
                f"recomputed={recomputed_metrics_id!r}"
            )

    @staticmethod
    def _validate_experiment_quantities(
        index_manifest: IndexManifest,
        retrieval_result: RetrievalRunResult,
        metrics_result: RetrievalMetricsResult,
        evaluation_set: RetrievalEvaluationSet,
        retriever_strategy: str,
    ) -> None:
        """只验证可信快照之间的数量关系，不访问真实 Vector Store / BM25。

        retriever_strategy 来自已通过四阶段绑定校验的 ExperimentConfig；
        Hybrid 判定以可信实验配置为准，不允许通过修改 Manifest 顶层
        字段跳过 sparse/vector 数量校验。
        """
        if index_manifest.file_count != len(index_manifest.files):
            raise RuntimeError(
                f"index_manifest file_count={index_manifest.file_count} "
                f"与 files 数量 {len(index_manifest.files)} 不一致"
            )
        if index_manifest.total_chunks != index_manifest.vector_store_count:
            raise RuntimeError(
                f"index_manifest total_chunks={index_manifest.total_chunks} "
                f"与 vector_store_count={index_manifest.vector_store_count} 不一致"
            )
        if retriever_strategy == "hybrid":
            if index_manifest.sparse_index_count != index_manifest.vector_store_count:
                raise RuntimeError(
                    f"Hybrid sparse_index_count="
                    f"{index_manifest.sparse_index_count} 与 vector_store_count="
                    f"{index_manifest.vector_store_count} 不一致"
                )
        if metrics_result.case_count != len(metrics_result.cases):
            raise RuntimeError(
                f"metrics_result case_count={metrics_result.case_count} "
                f"与 cases 数量 {len(metrics_result.cases)} 不一致"
            )
        if metrics_result.case_count != len(evaluation_set.cases):
            raise RuntimeError(
                f"metrics_result case_count={metrics_result.case_count} "
                f"与 EvaluationSet cases 数量 {len(evaluation_set.cases)} 不一致"
            )
        if len(retrieval_result.cases) != len(evaluation_set.cases):
            raise RuntimeError(
                f"retrieval_result cases 数量 {len(retrieval_result.cases)} "
                f"与 EvaluationSet cases 数量 {len(evaluation_set.cases)} 不一致"
            )

    @staticmethod
    def _validate_persisted_json_snapshot(
        snapshot_path: Path,
        expected: dict,
        display_name: str,
        mismatch_message: str,
    ) -> None:
        """通用落盘事实快照校验：UTF-8 + 合法 JSON + 顶层 object + 全结构比较。"""
        try:
            with snapshot_path.open("r", encoding="utf-8") as f:
                disk_payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Workspace 中已落盘的 {display_name} 无法解析：{exc}"
            ) from exc
        if not isinstance(disk_payload, dict):
            raise RuntimeError(
                f"Workspace 中已落盘的 {display_name} 顶层不是 JSON object"
            )
        if disk_payload != expected:
            raise RuntimeError(mismatch_message)

    @staticmethod
    def _validate_persisted_manifest(
        manifest_path: Path,
        index_manifest: IndexManifest,
    ) -> None:
        """强制证明 Workspace 中落盘的 index_manifest.json 与传入对象是
        同一份完整业务快照。

        使用 UTF-8 + json.loads 读取磁盘内容；磁盘内容必须是 JSON object；
        然后与 index_manifest.to_dict() 做全字段结构比较（含 config、
        corpus_entries、files 等，而不仅是顶层 ID 与数量）。
        """
        ExperimentRunner._validate_persisted_json_snapshot(
            manifest_path,
            index_manifest.to_dict(),
            "index_manifest.json",
            "传入 IndexManifest 与 Workspace 中已落盘的 "
            "index_manifest.json 不一致",
        )

    @staticmethod
    def _validate_persisted_retrieval_results(
        results_path: Path,
        retrieval_result: RetrievalRunResult,
    ) -> None:
        """强制证明 Workspace 中落盘的 retrieval_results.json 与传入对象
        是同一份完整业务快照（与 Manifest 绑定原则一致）。"""
        ExperimentRunner._validate_persisted_json_snapshot(
            results_path,
            retrieval_result.to_dict(),
            "retrieval_results.json",
            "传入 RetrievalRunResult 与 Workspace 中已落盘的 "
            "retrieval_results.json 不一致",
        )

    @staticmethod
    def _validate_persisted_retrieval_metrics(
        metrics_path: Path,
        metrics_result: RetrievalMetricsResult,
    ) -> None:
        """强制证明 Workspace 中落盘的 retrieval_metrics.json 与传入对象
        是同一份完整业务快照。"""
        ExperimentRunner._validate_persisted_json_snapshot(
            metrics_path,
            metrics_result.to_dict(),
            "retrieval_metrics.json",
            "传入 RetrievalMetricsResult 与 Workspace 中已落盘的 "
            "retrieval_metrics.json 不一致",
        )

    @staticmethod
    def _validate_retrieval_metrics_binding(
        prepared: PreparedExperiment,
        retrieval_result: RetrievalRunResult,
        evaluation_set: RetrievalEvaluationSet,
    ) -> None:
        """指标运行绑定校验，并重算 retrieval_run_id（不信任已存 ID）。"""
        config = prepared.experiment_config
        if type(retrieval_result.top_k) is not int:
            raise RuntimeError(
                f"指标绑定校验失败：top_k 必须是严格 int，"
                f"实际 {type(retrieval_result.top_k).__name__} "
                f"（{retrieval_result.top_k!r}）"
            )
        if type(config.top_k) is not int:
            raise RuntimeError(
                f"指标绑定校验失败：ExperimentConfig.top_k 必须是严格 int，"
                f"实际 {type(config.top_k).__name__}（{config.top_k!r}）"
            )
        checks = {
            "experiment_id": (retrieval_result.experiment_id, config.experiment_id),
            "corpus_id": (retrieval_result.corpus_id, evaluation_set.corpus_id),
            "evaluation_set_id": (
                retrieval_result.evaluation_set_id,
                evaluation_set.evaluation_set_id,
            ),
            "retriever_strategy": (
                retrieval_result.retriever_strategy,
                config.retriever_strategy,
            ),
            "top_k": (retrieval_result.top_k, config.top_k),
        }
        for name, (actual, expected) in checks.items():
            if actual != expected:
                raise RuntimeError(
                    f"指标绑定校验失败：{name} 不一致 "
                    f"actual={actual!r} expected={expected!r}"
                )
        recomputed = RetrievalRunResult.compute_run_id(
            schema_version=retrieval_result.schema_version,
            experiment_id=retrieval_result.experiment_id,
            corpus_id=retrieval_result.corpus_id,
            evaluation_set_id=retrieval_result.evaluation_set_id,
            retriever_strategy=retrieval_result.retriever_strategy,
            top_k=retrieval_result.top_k,
        )
        if recomputed != retrieval_result.retrieval_run_id:
            raise RuntimeError(
                f"指标绑定校验失败：retrieval_run_id 与绑定字段重算结果不一致 "
                f"stored={retrieval_result.retrieval_run_id!r} "
                f"recomputed={recomputed!r}"
            )

    @staticmethod
    def _validate_case_correspondence(
        retrieval_result: RetrievalRunResult,
        evaluation_set: RetrievalEvaluationSet,
    ) -> None:
        """Cases 必须与 EvaluationSet 按规范顺序完整对应。"""
        run_cases = retrieval_result.cases
        eval_cases = evaluation_set.cases
        if len(run_cases) != len(eval_cases):
            raise RuntimeError(
                f"检索结果 Case 数量 {len(run_cases)} 与 EvaluationSet "
                f"Case 数量 {len(eval_cases)} 不一致"
            )
        for index, (run_case, eval_case) in enumerate(
            zip(run_cases, eval_cases), 1
        ):
            if run_case.case_id != eval_case.case_id:
                raise RuntimeError(
                    f"第 {index} 个 Case 的 case_id 不一致："
                    f"{run_case.case_id!r} != {eval_case.case_id!r}"
                )
            if run_case.query != eval_case.query:
                raise RuntimeError(
                    f"第 {index} 个 Case（{run_case.case_id}）的 query 不一致"
                )
            if run_case.relevant_files != eval_case.relevant_files:
                raise RuntimeError(
                    f"第 {index} 个 Case（{run_case.case_id}）的 relevant_files "
                    "快照与 EvaluationSet 不一致"
                )

    @staticmethod
    def _validate_case_snapshot(case_result: RetrievalCaseResult, top_k: int) -> None:
        """重新验证单个 Case 的检索快照不变量，不信任 retrieved_files。"""
        hits = case_result.hits
        if len(hits) > top_k:
            raise RuntimeError(
                f"case_id={case_result.case_id}：hits 数量 {len(hits)} "
                f"超过 top_k={top_k}"
            )
        expected_ranks = list(range(1, len(hits) + 1))
        actual_ranks = []
        for hit in hits:
            if type(hit.rank) is not int:
                raise RuntimeError(
                    f"case_id={case_result.case_id}：Hit rank 必须是严格 int，"
                    f"实际 {type(hit.rank).__name__}（{hit.rank!r}）"
                )
            actual_ranks.append(hit.rank)
        if actual_ranks != expected_ranks:
            raise RuntimeError(
                f"case_id={case_result.case_id}：Hit rank 必须严格为 "
                f"1..{len(hits)}，实际 {actual_ranks}"
            )
        seen_chunk_ids = set()
        for hit in hits:
            if type(hit.chunk_id) is not str or hit.chunk_id == "":
                raise RuntimeError(
                    f"case_id={case_result.case_id}：Hit chunk_id 必须是"
                    f"非空字符串，实际 {type(hit.chunk_id).__name__} "
                    f"（{hit.chunk_id!r}）"
                )
            if type(hit.document_id) is not str or hit.document_id == "":
                raise RuntimeError(
                    f"case_id={case_result.case_id}：Hit document_id 必须是"
                    f"非空字符串，实际 {type(hit.document_id).__name__} "
                    f"（{hit.document_id!r}）"
                )
            if type(hit.relative_path) is not str or hit.relative_path == "":
                raise RuntimeError(
                    f"case_id={case_result.case_id}：Hit relative_path 必须是"
                    f"非空字符串，实际 {type(hit.relative_path).__name__} "
                    f"（{hit.relative_path!r}）"
                )
            if hit.chunk_id in seen_chunk_ids:
                raise RuntimeError(
                    f"case_id={case_result.case_id}：重复 Chunk ID "
                    f"{hit.chunk_id!r}"
                )
            seen_chunk_ids.add(hit.chunk_id)

        for path in case_result.retrieved_files:
            if type(path) is not str or path == "":
                raise RuntimeError(
                    f"case_id={case_result.case_id}：retrieved_files 每项必须"
                    f"是非空字符串，实际 {type(path).__name__}（{path!r}）"
                )
        expected_files = []
        for hit in hits:
            if hit.relative_path not in expected_files:
                expected_files.append(hit.relative_path)
        if tuple(expected_files) != case_result.retrieved_files:
            raise RuntimeError(
                f"case_id={case_result.case_id}：retrieved_files 与 hits "
                f"首次文件顺序不一致：{case_result.retrieved_files!r} != "
                f"{tuple(expected_files)!r}"
            )
        if len(set(case_result.retrieved_files)) != len(case_result.retrieved_files):
            raise RuntimeError(
                f"case_id={case_result.case_id}：retrieved_files 包含重复文件"
            )

    @staticmethod
    def _validate_retrieval_binding(
        prepared: PreparedExperiment,
        index_manifest: IndexManifest,
        evaluation_set: RetrievalEvaluationSet,
    ) -> None:
        """第一次 retrieve 前完成全部绑定校验；任一不一致立即失败。"""
        config = prepared.experiment_config
        checks = {
            "experiment_id": (index_manifest.experiment_id, config.experiment_id),
            "config": (index_manifest.config, config.to_dict()),
            "corpus_id": (index_manifest.corpus_id, evaluation_set.corpus_id),
            "retriever_strategy": (
                index_manifest.retriever_strategy,
                config.retriever_strategy,
            ),
            "chunk_strategy": (
                index_manifest.chunk_strategy,
                config.chunk_strategy,
            ),
        }
        for name, (actual, expected) in checks.items():
            if actual != expected:
                raise RuntimeError(
                    f"检索绑定校验失败：{name} 不一致 "
                    f"actual={actual!r} expected={expected!r}，不能执行检索"
                )
        if index_manifest.file_count != len(index_manifest.files):
            raise RuntimeError(
                f"检索绑定校验失败：manifest file_count={index_manifest.file_count} "
                f"与 files 数量 {len(index_manifest.files)} 不一致"
            )
        if index_manifest.total_chunks != index_manifest.vector_store_count:
            raise RuntimeError(
                f"检索绑定校验失败：total_chunks={index_manifest.total_chunks} "
                f"与 vector_store_count={index_manifest.vector_store_count} 不一致"
            )
        if config.retriever_strategy == "hybrid":
            if index_manifest.sparse_index_count != index_manifest.vector_store_count:
                raise RuntimeError(
                    f"检索绑定校验失败：Hybrid sparse_index_count="
                    f"{index_manifest.sparse_index_count} 与 vector_store_count="
                    f"{index_manifest.vector_store_count} 不一致"
                )

    @staticmethod
    def _build_document_map(index_manifest: IndexManifest) -> dict:
        """document_id -> relative_path 映射，只来自 index_manifest.files。"""
        mapping = {}
        for file_record in index_manifest.files:
            document_id = file_record.document_id
            if not isinstance(document_id, str) or not document_id:
                raise RuntimeError(
                    f"Manifest 存在空 document_id：{file_record.relative_path}"
                )
            previous = mapping.get(document_id)
            if previous is not None and previous != file_record.relative_path:
                raise RuntimeError(
                    f"document_id={document_id!r} 映射到多个文件："
                    f"{previous} 与 {file_record.relative_path}"
                )
            mapping[document_id] = file_record.relative_path
        return mapping

    @staticmethod
    def _snapshot_case_result(
        case: RetrievalCase,
        retrieved,
        top_k: int,
        document_map: dict,
    ) -> RetrievalCaseResult:
        """把 Retriever 返回值立即转为不可变内存快照。

        稳定策略：超过 top_k 只保留前 top_k；同一 Case 内重复 Chunk ID 拒绝。
        """
        hits = []
        seen_chunk_ids = set()
        retrieved_files = []
        seen_files = set()
        for rank, doc in enumerate(retrieved[:top_k], 1):
            metadata = doc.metadata or {}
            chunk_id = metadata.get("id")
            document_id = metadata.get("document_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise RuntimeError(
                    f"case_id={case.case_id}：Chunk 缺失非空 metadata['id']"
                )
            if not isinstance(document_id, str) or not document_id:
                raise RuntimeError(
                    f"case_id={case.case_id}：Chunk {chunk_id!r} 缺失非空 "
                    "metadata['document_id']"
                )
            if chunk_id in seen_chunk_ids:
                raise RuntimeError(
                    f"case_id={case.case_id}：重复 Chunk ID {chunk_id!r}"
                )
            seen_chunk_ids.add(chunk_id)
            if document_id not in document_map:
                raise RuntimeError(
                    f"case_id={case.case_id}：未知 document_id {document_id!r}"
                    "（不在 IndexManifest 映射中）"
                )
            relative_path = document_map[document_id]
            scores = {
                name: metadata[name]
                for name in SCORE_WHITELIST
                if name in metadata
            }
            hits.append(RetrievalHit(
                rank=rank,
                chunk_id=chunk_id,
                document_id=document_id,
                relative_path=relative_path,
                scores=scores,
            ))
            if relative_path not in seen_files:
                seen_files.add(relative_path)
                retrieved_files.append(relative_path)
        return RetrievalCaseResult(
            case_id=case.case_id,
            query=case.query,
            relevant_files=case.relevant_files,
            hits=tuple(hits),
            retrieved_files=tuple(retrieved_files),
        )

    @staticmethod
    def _validate_hybrid_sparse_index(
        prepared: PreparedExperiment, vector_store_count: int
    ) -> int:
        """Hybrid 模式：调用现有严格 BM25 重建，并校验 Sparse 数量与向量库一致。

        不允许 Hybrid 实验以 Dense-only 状态完成；数量不一致立即失败。
        """
        pipeline = prepared.pipeline
        rebuild = getattr(pipeline, "_rebuild_sparse_index", None)
        if rebuild is None:
            raise RuntimeError(
                "Hybrid 实验缺少严格 BM25 重建接口 _rebuild_sparse_index，"
                "不能以 Dense-only 状态完成"
            )
        rebuild(strict=True)
        bm25 = getattr(getattr(pipeline, "retriever", None), "_bm25", None)
        if bm25 is None:
            raise RuntimeError(
                "Hybrid 实验 BM25 索引缺失，不得生成正式 Manifest"
            )
        sparse_count = bm25.doc_count
        if sparse_count != vector_store_count:
            raise RuntimeError(
                f"Sparse/BM25 数量 {sparse_count} 与向量库数量 "
                f"{vector_store_count} 不一致，不得生成正式 Manifest"
            )
        return sparse_count
