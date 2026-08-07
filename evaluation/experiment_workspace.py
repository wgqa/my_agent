"""ExperimentRunner 第二步：独立实验工作区与派生配置。

为一次实验运行准备 `<workspace_root>/<experiment_id>/<run_id>/` 目录、
独立向量库路径和覆盖实验字段后的派生 config.yaml，避免不同实验或
重复运行共享旧索引。
"""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import yaml

from evaluation.experiment_config import ExperimentConfig

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ExperimentPaths:
    """一次实验运行的工作区路径；不可变"""

    workspace_path: Path
    config_path: Path
    vector_store_path: Path
    result_path: Path
    index_manifest_path: Path
    retrieval_results_path: Path
    retrieval_metrics_path: Path


class ExperimentWorkspace:
    """创建独立实验工作区并生成派生配置"""

    def __init__(
        self,
        base_config_path: Union[str, Path],
        workspace_root: Union[str, Path],
        config: ExperimentConfig,
        run_id: str,
    ):
        self.base_config_path = Path(base_config_path)
        self.workspace_root = Path(workspace_root).resolve()
        self.config = config
        self.run_id = self._validate_run_id(run_id)

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id 必须是非空字符串")
        if not _RUN_ID_RE.match(run_id):
            raise ValueError(
                f"run_id 只允许字母/数字/-/_（防路径穿越），当前: {run_id!r}"
            )
        return run_id

    def _workspace_path(self) -> Path:
        candidate = (
            self.workspace_root / self.config.experiment_id / self.run_id
        ).resolve()
        # 真正的路径语义归属校验（不是字符串前缀）：符号链接/junction
        # 若把路径引到 root 外，在创建任何目录之前拒绝
        if not candidate.is_relative_to(self.workspace_root):
            raise RuntimeError(
                f"实验工作区路径逃逸 workspace_root（可能因符号链接指向外部）："
                f"{candidate}"
            )
        return candidate

    def prepare(self) -> ExperimentPaths:
        ws = self._workspace_path()
        if ws.exists():
            raise FileExistsError(
                f"实验工作区已存在，禁止复用旧向量库或覆盖旧结果: {ws}"
            )
        ws.mkdir(parents=True, exist_ok=False)

        with open(self.base_config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # 覆盖实验字段（仅读基础文件，不修改它）
        # Embedding 身份由 ExperimentConfig 决定，不能作为隐式参数
        raw.setdefault("embedding", {})
        raw["embedding"]["provider"] = self.config.embedding_provider
        raw["embedding"]["model"] = self.config.embedding_model
        raw.setdefault("chunker", {})
        raw["chunker"]["strategy"] = self.config.chunk_strategy
        raw["chunker"]["size_tokens"] = self.config.chunk_size
        raw["chunker"]["overlap_tokens"] = self.config.chunk_overlap
        raw.setdefault("retriever", {})
        raw["retriever"]["strategy"] = self.config.retriever_strategy
        raw["retriever"]["top_k"] = self.config.top_k
        raw["retriever"]["dense_candidate_k"] = self.config.dense_candidate_k
        raw["retriever"]["sparse_candidate_k"] = self.config.sparse_candidate_k
        raw["retriever"]["rrf_k"] = self.config.rrf_k

        # 向量库路径指向工作区内（绝对路径），杜绝共享旧索引
        vs_path = (ws / "vector_store").resolve()
        vs_path.mkdir(parents=True, exist_ok=False)
        raw.setdefault("vector_store", {})
        raw["vector_store"]["path"] = str(vs_path)

        config_path = ws / "config.yaml"
        self._atomic_write_yaml(config_path, raw)

        return ExperimentPaths(
            workspace_path=ws,
            config_path=config_path,
            vector_store_path=vs_path,
            result_path=ws / "result.json",
            index_manifest_path=ws / "index_manifest.json",
            retrieval_results_path=ws / "retrieval_results.json",
            retrieval_metrics_path=ws / "retrieval_metrics.json",
        )

    @staticmethod
    def _atomic_write_yaml(path: Path, data: dict):
        """临时文件 + os.replace 原子替换，避免写出半个 YAML"""
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
