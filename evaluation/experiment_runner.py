"""ExperimentRunner：工作区 + 独立 Pipeline 接通（prepare），
以及正式语料入库与索引 Manifest（index_corpus）。

prepare() 将 ExperimentConfig → ExperimentWorkspace（派生配置）→ 独立
Pipeline 接通，并验证 Pipeline 实际使用了派生配置，防止实验跑在
错误配置上。index_corpus() 只负责入库：先完整性校验、再确定性入库、
再做 Dense/BM25 一致性校验，最后原子写入 Manifest；不执行查询与评测。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.experiment_workspace import ExperimentPaths, ExperimentWorkspace
from evaluation.index_manifest import FileIndexRecord, IndexManifest


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
            "chunker_strategy": (cfg.chunker_strategy, config.chunk_strategy),
            "chunk_size": (cfg.chunk_size, config.chunk_size),
            "chunk_overlap": (cfg.chunk_overlap, config.chunk_overlap),
            "retriever_strategy": (cfg.retriever_strategy, config.retriever_strategy),
            "top_k": (cfg.top_k, config.top_k),
            "dense_candidate_k": (cfg.dense_candidate_k, config.dense_candidate_k),
            "sparse_candidate_k": (cfg.sparse_candidate_k, config.sparse_candidate_k),
            "rrf_k": (cfg.rrf_k, config.rrf_k),
        }
        for name, (actual, expected) in checks.items():
            if actual != expected:
                raise RuntimeError(
                    f"Pipeline 配置 {name} 与实验配置不一致："
                    f"actual={actual!r} expected={expected!r}，不能继续实验"
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
        self._validate_corpus_integrity(corpus)

        file_records = []
        total_chunks = 0
        for entry in corpus.entries:
            result = prepared.pipeline.index_file(
                str(corpus.corpus_root / entry.relative_path)
            )
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
    def _validate_corpus_integrity(corpus: ExperimentCorpus) -> None:
        """入库前一次性重读全部语料原始字节并校验。

        校验项：文件存在、仍是普通文件、size_bytes 一致、SHA-256 一致、
        resolve() 后真实路径仍在 corpus_root 内。任一失败立即抛异常，
        且不会静默重算 corpus_id。
        """
        root = Path(corpus.corpus_root).resolve()
        for entry in corpus.entries:
            full = (root / entry.relative_path).resolve()
            if not full.is_relative_to(root):
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
