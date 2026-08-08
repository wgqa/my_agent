"""G2-DIAG-13：Hybrid Dense/BM25 Channel-Level Diagnostic Snapshot。

诊断 Artifact 与正式 retrieval_results.json 分开，不修改
RetrievalRunResult schema；只用于解释已冻结 Baseline 的通道内部事实。
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION = 1

_REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "diagnostic_id",
    "experiment_id",
    "corpus_id",
    "evaluation_set_id",
    "baseline_retrieval_run_id",
    "dense_candidate_k",
    "sparse_candidate_k",
    "cases",
)


@dataclass(frozen=True)
class ChannelCandidate:
    """单个通道候选或最终命中的可序列化事实"""

    rank: int
    chunk_id: str
    document_id: str
    relative_path: str
    scores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "relative_path": self.relative_path,
            "scores": dict(self.scores),
        }


@dataclass(frozen=True)
class DiagnosticCase:
    """单个 Case 的通道级诊断快照"""

    case_id: str
    query: str
    relevant_files: tuple[str, ...]
    dense_candidates: tuple[ChannelCandidate, ...]
    sparse_candidates: tuple[ChannelCandidate, ...]
    final_hits: tuple[ChannelCandidate, ...]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "relevant_files": list(self.relevant_files),
            "dense_candidates": [c.to_dict() for c in self.dense_candidates],
            "sparse_candidates": [c.to_dict() for c in self.sparse_candidates],
            "final_hits": [c.to_dict() for c in self.final_hits],
        }


@dataclass(frozen=True)
class RetrievalDiagnosticSnapshot:
    """一次诊断运行的不可变快照，绑定 Baseline retrieval_run_id"""

    schema_version: int = RETRIEVAL_DIAGNOSTICS_SCHEMA_VERSION
    diagnostic_id: str = ""
    experiment_id: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    baseline_retrieval_run_id: str = ""
    dense_candidate_k: int = 0
    sparse_candidate_k: int = 0
    cases: tuple = ()

    @staticmethod
    def compute_diagnostic_id(
        *,
        schema_version: int,
        experiment_id: str,
        corpus_id: str,
        evaluation_set_id: str,
        baseline_retrieval_run_id: str,
        dense_candidate_k: int,
        sparse_candidate_k: int,
    ) -> str:
        """稳定 diagnostic_id：只绑定 schema 与稳定实验/基线事实。

        不包含时间、Workspace 路径、对象地址或检索内容。
        """
        payload = {
            "schema_version": schema_version,
            "experiment_id": experiment_id,
            "corpus_id": corpus_id,
            "evaluation_set_id": evaluation_set_id,
            "baseline_retrieval_run_id": baseline_retrieval_run_id,
            "dense_candidate_k": dense_candidate_k,
            "sparse_candidate_k": sparse_candidate_k,
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
            "diagnostic_id": self.diagnostic_id,
            "experiment_id": self.experiment_id,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "baseline_retrieval_run_id": self.baseline_retrieval_run_id,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "cases": [c.to_dict() for c in self.cases],
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


def load_diagnostic_snapshot(path: Union[str, Path]) -> dict:
    """严格读取诊断 Artifact：合法 JSON、顶层 object、必需字段齐全。

    非法 JSON / 顶层非 object / 缺字段均拒绝，与既有快照风格一致。
    """
    snapshot_path = Path(path)
    try:
        with snapshot_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"retrieval_diagnostics.json 无法解析：{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            "retrieval_diagnostics.json 顶层不是 JSON object"
        )
    missing = [key for key in _REQUIRED_TOP_LEVEL_KEYS if key not in payload]
    if missing:
        raise RuntimeError(
            f"retrieval_diagnostics.json 缺少字段：{', '.join(missing)}"
        )
    return payload
