"""ExperimentRunner 第三步：最小版 Runner——工作区 + 独立 Pipeline 接通。

prepare() 将 ExperimentConfig → ExperimentWorkspace（派生配置）→ 独立
Pipeline 接通，并验证 Pipeline 实际使用了派生配置，防止实验跑在
错误配置上。不执行索引、检索与评测。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_workspace import ExperimentPaths, ExperimentWorkspace


@dataclass(frozen=True)
class PreparedExperiment:
    """一次已准备就绪的实验：配置、工作区路径与独立 Pipeline"""

    experiment_config: ExperimentConfig
    paths: ExperimentPaths
    pipeline: object


class ExperimentRunner:
    """准备工作区并用派生配置创建独立 Pipeline"""

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
