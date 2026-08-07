"""G2-EVAL-09：ExperimentResult 最终实验摘要与原子 result.json。

result.json 是稳定摘要，不复制 Chunk hits、逐 Case raw retrieval、
Corpus 绝对路径、API Key 或对象 repr；详细事实分别存在于
index_manifest.json / retrieval_results.json / retrieval_metrics.json。
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

EXPERIMENT_RESULT_SCHEMA_VERSION = 1

ARTIFACT_FILES = {
    "index_manifest": "index_manifest.json",
    "retrieval_results": "retrieval_results.json",
    "retrieval_metrics": "retrieval_metrics.json",
}


@dataclass(frozen=True)
class ExperimentResult:
    """一次已完成实验的稳定摘要快照"""

    schema_version: int = EXPERIMENT_RESULT_SCHEMA_VERSION
    result_id: str = ""
    experiment_id: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    retrieval_run_id: str = ""
    metrics_run_id: str = ""
    config: dict = field(default_factory=dict)
    chunk_strategy: str = ""
    retriever_strategy: str = ""
    top_k: int = 0
    file_count: int = 0
    total_chunks: int = 0
    case_count: int = 0
    mean_hit_at_k: float = 0.0
    mean_recall_at_k: float = 0.0
    mean_mrr: float = 0.0
    mean_ndcg_at_k: float = 0.0
    artifacts: dict = field(default_factory=dict)

    @staticmethod
    def compute_result_id(
        *,
        schema_version: int,
        experiment_id: str,
        corpus_id: str,
        evaluation_set_id: str,
        retrieval_run_id: str,
        metrics_run_id: str,
    ) -> str:
        """稳定 result_id：哪一个实验 + 哪一份 Corpus + 哪一套评测集 +
        哪一个检索运行 + 哪一种指标定义。

        不包含时间、Workspace 路径、指标实际数值、文件 mtime、repr 或
        API Key。
        """
        payload = {
            "schema_version": schema_version,
            "experiment_id": experiment_id,
            "corpus_id": corpus_id,
            "evaluation_set_id": evaluation_set_id,
            "retrieval_run_id": retrieval_run_id,
            "metrics_run_id": metrics_run_id,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "result_id": self.result_id,
            "experiment_id": self.experiment_id,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "retrieval_run_id": self.retrieval_run_id,
            "metrics_run_id": self.metrics_run_id,
            "config": self.config,
            "chunk_strategy": self.chunk_strategy,
            "retriever_strategy": self.retriever_strategy,
            "top_k": self.top_k,
            "file_count": self.file_count,
            "total_chunks": self.total_chunks,
            "case_count": self.case_count,
            "mean_hit_at_k": self.mean_hit_at_k,
            "mean_recall_at_k": self.mean_recall_at_k,
            "mean_mrr": self.mean_mrr,
            "mean_ndcg_at_k": self.mean_ndcg_at_k,
            "artifacts": dict(self.artifacts),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    def write_json(self, path: Union[str, Path]) -> None:
        """原子写入：临时文件 -> flush -> fsync -> close -> os.replace"""
        target = Path(path)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self.to_json())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
