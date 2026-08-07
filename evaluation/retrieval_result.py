"""G2-EVAL-07：正式检索执行结果模型与原子 JSON 快照。

保存逐查询原始 Chunk 命中（hits）与文件级排名（retrieved_files），
并生成与结果内容无关的稳定 retrieval_run_id。
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

RETRIEVAL_RESULT_SCHEMA_VERSION = 1

# 分数白名单：只允许保存这些实际存在的字段，不虚构为 0，
# 不保存完整任意 metadata，不写绝对 source 路径或对象 repr。
SCORE_WHITELIST = frozenset({
    "score",
    "distance",
    "dense_score",
    "sparse_score",
    "rrf_score",
    "mmr_score",
    "rerank_score",
    "dense_rank",
    "sparse_rank",
    "final_rank",
})


@dataclass(frozen=True)
class RetrievalHit:
    """单个 Chunk 的原始检索命中"""

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
class RetrievalCaseResult:
    """单个 Case 的检索结果快照"""

    case_id: str
    query: str
    relevant_files: tuple[str, ...]
    hits: tuple[RetrievalHit, ...]
    retrieved_files: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "relevant_files": list(self.relevant_files),
            "hits": [h.to_dict() for h in self.hits],
            "retrieved_files": list(self.retrieved_files),
        }


@dataclass(frozen=True)
class RetrievalRunResult:
    """一次检索运行的不可变结果快照"""

    schema_version: int = RETRIEVAL_RESULT_SCHEMA_VERSION
    retrieval_run_id: str = ""
    experiment_id: str = ""
    corpus_id: str = ""
    evaluation_set_id: str = ""
    retriever_strategy: str = ""
    top_k: int = 0
    cases: tuple[RetrievalCaseResult, ...] = ()

    @staticmethod
    def compute_run_id(
        *,
        schema_version: int,
        experiment_id: str,
        corpus_id: str,
        evaluation_set_id: str,
        retriever_strategy: str,
        top_k: int,
    ) -> str:
        """稳定 run ID：表示"计划执行的是哪一个检索实验"。

        绑定 schema_version、experiment_id、corpus_id、evaluation_set_id、
        retriever_strategy、top_k；不包含 Workspace 路径、时间、对象地址、
        API Key、耗时或本次返回的分数/内容。
        """
        payload = {
            "schema_version": schema_version,
            "experiment_id": experiment_id,
            "corpus_id": corpus_id,
            "evaluation_set_id": evaluation_set_id,
            "retriever_strategy": retriever_strategy,
            "top_k": top_k,
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
            "retrieval_run_id": self.retrieval_run_id,
            "experiment_id": self.experiment_id,
            "corpus_id": self.corpus_id,
            "evaluation_set_id": self.evaluation_set_id,
            "retriever_strategy": self.retriever_strategy,
            "top_k": self.top_k,
            "cases": [c.to_dict() for c in self.cases],
        }

    def to_json(self) -> str:
        """UTF-8 JSON；sort_keys=True 保证序列化稳定"""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    def write_json(self, path: Union[str, Path]) -> None:
        """原子写入：同目录临时文件 -> flush -> fsync -> close -> os.replace。

        中途失败时清理临时文件并向外传播原异常，绝不留下半成品结果。
        """
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
