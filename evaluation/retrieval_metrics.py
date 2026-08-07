"""G2-EVAL-08：文档级 Retrieval Metrics 与原子指标快照。

正式指标输入是 retrieval_results 中已按 Chunk 首次命中顺序去重的
retrieved_files 与 EvaluationSet 的 relevant_files；本模块依赖上游
已完成的唯一性校验（方案 A：复用现有纯函数），不直接接收重复
retrieved 输入，也不使用 Chunk ID 或 hits 数量计算文档级指标。
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

from evaluation.metrics import (
    hit_at_k as _hit_at_k,
    recall_at_k as _recall_at_k,
    mrr as _mrr,
    ndcg_at_k as _ndcg_at_k,
)

METRICS_SCHEMA_VERSION = 1
METRIC_SCOPE = "document"
RELEVANCE = "binary"
AGGREGATION = "macro"


@dataclass(frozen=True)
class RetrievalCaseMetrics:
    """单个 Case 的文档级指标"""

    case_id: str
    hit_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    relevant_file_count: int
    retrieved_file_count: int
    first_relevant_rank: Optional[int]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "hit_at_k": self.hit_at_k,
            "recall_at_k": self.recall_at_k,
            "mrr": self.mrr,
            "ndcg_at_k": self.ndcg_at_k,
            "relevant_file_count": self.relevant_file_count,
            "retrieved_file_count": self.retrieved_file_count,
            "first_relevant_rank": self.first_relevant_rank,
        }


@dataclass(frozen=True)
class RetrievalMetricsResult:
    """一次检索评测的指标快照（宏平均）"""

    schema_version: int = METRICS_SCHEMA_VERSION
    metrics_run_id: str = ""
    experiment_id: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    retrieval_run_id: str = ""
    retriever_strategy: str = ""
    top_k: int = 0
    case_count: int = 0
    cases: tuple = ()
    mean_hit_at_k: float = 0.0
    mean_recall_at_k: float = 0.0
    mean_mrr: float = 0.0
    mean_ndcg_at_k: float = 0.0

    @staticmethod
    def compute_metrics_run_id(
        *,
        schema_version: int,
        retrieval_run_id: str,
        evaluation_set_id: str,
        top_k: int,
        metric_scope: str,
        relevance: str,
        aggregation: str,
    ) -> str:
        """稳定 metrics_run_id：对哪个可信检索快照、用哪个指标 Schema 评测。

        绑定 metrics schema_version、retrieval_run_id、evaluation_set_id、
        top_k、metric_scope、relevance、aggregation；不包含时间、路径、
        实际得分、API Key、repr 或对象地址。
        """
        payload = {
            "schema_version": schema_version,
            "retrieval_run_id": retrieval_run_id,
            "evaluation_set_id": evaluation_set_id,
            "top_k": top_k,
            "metric_scope": metric_scope,
            "relevance": relevance,
            "aggregation": aggregation,
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
            "metrics_run_id": self.metrics_run_id,
            "experiment_id": self.experiment_id,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "retrieval_run_id": self.retrieval_run_id,
            "retriever_strategy": self.retriever_strategy,
            "top_k": self.top_k,
            "case_count": self.case_count,
            "cases": [c.to_dict() for c in self.cases],
            "mean_hit_at_k": self.mean_hit_at_k,
            "mean_recall_at_k": self.mean_recall_at_k,
            "mean_mrr": self.mean_mrr,
            "mean_ndcg_at_k": self.mean_ndcg_at_k,
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


def compute_case_metrics(
    case_id: str,
    retrieved_files: Sequence[str],
    relevant_files: Sequence[str],
    top_k: int,
) -> RetrievalCaseMetrics:
    """计算单个 Case 的文档级指标。

    前置契约：retrieved_files 必须已经按 Chunk 首次命中顺序去重且
    len(retrieved_files) <= top_k（由 ExperimentRunner 校验）；相关文件
    集合非空（RetrievalEvaluationSet 保证）。此处直接复用现有纯函数。
    """
    retrieved = list(retrieved_files)
    relevant = list(relevant_files)
    relevant_set = set(relevant)

    hit = _hit_at_k(retrieved, relevant)
    recall = _recall_at_k(retrieved, relevant)
    reciprocal = _mrr(retrieved, relevant)
    ndcg = _ndcg_at_k(retrieved, relevant, k=top_k)
    first_rank = next(
        (i for i, f in enumerate(retrieved, 1) if f in relevant_set),
        None,
    )
    return RetrievalCaseMetrics(
        case_id=case_id,
        hit_at_k=float(hit),
        recall_at_k=float(recall),
        mrr=float(reciprocal),
        ndcg_at_k=float(ndcg),
        relevant_file_count=len(relevant_set),
        retrieved_file_count=len(retrieved),
        first_relevant_rank=first_rank,
    )
