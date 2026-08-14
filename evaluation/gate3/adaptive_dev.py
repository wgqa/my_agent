"""G3-ADAPT-06B：Dev-only 固定 BM25 vs Adaptive Agentic RAG 真实检索对照。

在公开 Gate 3 Dev 24 Case 上，复用冻结 Planner 输出与冻结 37 文件语料，
对同一份共享索引执行四组真实检索对照：

  A  原问题单次 BM25
  B  原问题单次 Hybrid（Dense+Sparse+RRF）
  C  冻结 QueryPlan + 固定 BM25（不 rescue，bm25-only 能力包装）
  D  冻结 QueryPlan + Adaptive Policy v1 + 最多一次 Hybrid rescue

本模块只评估检索/证据覆盖/路由/调用成本；不调用真实 Planner、不调用
Generator（C/D 用确定性 No-op AnswerPort），不做答案正确性评测。所有
Artifact 写入外部 benchmark_work，不入 Git；不访问 sealed/Holdout。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

from core.adaptive_retrieval import ADAPTIVE_RETRIEVAL_POLICY_VERSION
from core.agent_runtime import (
    AgentRuntime,
    Document as RuntimeDocument,
    EvidenceBundle,
    PipelineRetrievalAdapter,
)
from core.chunker.recursive import RecursiveChunker
from core.domain.models import compute_content_hash, make_document_id
from core.embeddings.bge_emb import BGEEmbedding
from core.loader.text_loader import TextLoader
from core.query_planning import (
    BaseQueryPlanner,
    PlannerOutcome,
    QueryPlan,
)
from core.retriever.hybrid import HybridRetriever
from core.vector_store import ChromaStore
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.evaluation_set import Gate3EvaluationSet

GATE3_ADAPTIVE_DEV_SCHEMA_VERSION = "gate3_adaptive_dev_run_v1"
GATE3_ADAPTIVE_DEV_METRICS_SCHEMA_VERSION = "gate3_adaptive_dev_metrics_v1"
GATE3_ADAPTIVE_DEV_RESULT_SCHEMA_VERSION = "gate3_adaptive_dev_result_v1"
GATE3_ADAPTIVE_DEV_MANIFEST_SCHEMA_VERSION = "gate3_adaptive_dev_index_manifest_v1"
GATE3_ADAPTIVE_DEV_COMPARISON_SCHEMA_VERSION = "gate3_adaptive_dev_comparison_v1"

_HEX = frozenset("0123456789abcdef")
_NOOP_ANSWER = "synthetic-answer-not-evaluated"

# 本任务的冻结身份常量（与公开 freeze 文件一致）。
EXPECTED_CORPUS_ID = "870e5864df67"
EXPECTED_CORPUS_FILE_COUNT = 37
EXPECTED_FREEZE_ID = "257fa0d0a6d6"
EXPECTED_DEV_EVALUATION_SET_ID = "f2144030d754"
EXPECTED_DEV_CASE_COUNT = 24
EXPECTED_DEV_JSONL_SHA256 = (
    "0b4bbf5314fee27d965c6ccefd738d71eb5c3925b15517b544c1fdf4f8e94015"
)
EXPECTED_PLANNER_RUN_ID = "497808269bdd"
EXPECTED_PLANNER_PROMPT_SHA256 = (
    "5b209054f5274fa8f1f88975625c80b78d7e9e2a84569179288fed0c3a3b5c95"
)


def _canonical_json(obj: object) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _safe_rate(num: int, den: int) -> float:
    return num / den if den > 0 else 0.0


def _check_hex(value: object, length: int, label: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} 必须是字符串")
    if len(value) != length or any(c not in _HEX for c in value):
        raise ValueError(f"{label} 必须是 {length} 位小写十六进制，实际 {value!r}")


def _check_nonempty_no_ws(value: object, label: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{label} 必须是字符串")
    if not value.strip():
        raise ValueError(f"{label} 不能为空或只含空白")
    if value != value.strip():
        raise ValueError(f"{label} 首尾不允许空白")


def check_git_tracked_clean(repo: str) -> None:
    """拒绝任何 tracked modification；untracked 文件允许存在。

    实验运行必须绑定到干净源码提交。检查失败 raise RuntimeError，调用方
    必须在构建索引与运行实验之前执行（此时尚未创建实验目录）。
    """
    try:
        out = subprocess.check_output(
            ["git", "-C", repo, "status", "--porcelain"], text=True
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"无法读取 Git 工作区状态: {repo}") from exc
    for line in out.splitlines():
        if not line.startswith("??"):
            raise RuntimeError(f"tracked modification 拒绝运行: {line!r}")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate3AdaptiveDevConfig:
    """一次 Adaptive Dev 检索对照运行的强类型配置；run_id 由身份载荷计算。"""

    schema_version: str = GATE3_ADAPTIVE_DEV_SCHEMA_VERSION
    source_commit: str = ""
    corpus_id: str = ""
    corpus_file_count: int = 0
    gate3_dataset_freeze_id: str = ""
    dev_evaluation_set_id: str = ""
    dev_case_count: int = 0
    dev_jsonl_sha256: str = ""
    planner_run_id: str = ""
    planner_prompt_sha256: str = ""
    planner_results_sha256: str = ""
    # 检索/分块参数
    chunk_strategy: str = "recursive"
    chunk_budget_policy: str = "cl100k_content_v1"
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_provider: str = "bge"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    dense_candidate_k: int = 30
    sparse_candidate_k: int = 30
    rrf_k: float = 60.0
    rrf_tie_breaker: str = "chunk_id_asc"
    top_k: int = 5
    reranker_enabled: bool = False
    merge_policy: str = "subquery_round_robin_v1"
    max_retrieval_calls: int = 4
    max_evidence_items: int = 5
    group_a_policy: str = "original_bm25_v1"
    group_b_policy: str = "original_hybrid_v1"
    group_c_policy: str = "queryplan_bm25_no_rescue_v1"
    group_d_policy: str = ADAPTIVE_RETRIEVAL_POLICY_VERSION
    # 执行路径（不进入 run_id 身份）
    dev_jsonl_path: str = ""
    planner_results_path: str = ""
    planner_result_json_path: str = ""
    frozen_index_manifest_path: str = ""
    corpus_root: str = ""
    output_dir: str = ""

    def __post_init__(self) -> None:
        _check_hex(self.source_commit, 40, "source_commit")
        _check_hex(self.corpus_id, 12, "corpus_id")
        _check_hex(self.gate3_dataset_freeze_id, 12, "gate3_dataset_freeze_id")
        _check_hex(self.dev_evaluation_set_id, 12, "dev_evaluation_set_id")
        _check_hex(self.dev_jsonl_sha256, 64, "dev_jsonl_sha256")
        _check_hex(self.planner_run_id, 12, "planner_run_id")
        _check_hex(self.planner_prompt_sha256, 64, "planner_prompt_sha256")
        _check_hex(self.planner_results_sha256, 64, "planner_results_sha256")
        if type(self.corpus_file_count) is not int or isinstance(
            self.corpus_file_count, bool
        ):
            raise TypeError("corpus_file_count 必须是严格 int")
        if self.corpus_file_count <= 0:
            raise ValueError("corpus_file_count 必须 > 0")
        if type(self.dev_case_count) is not int or isinstance(
            self.dev_case_count, bool
        ):
            raise TypeError("dev_case_count 必须是严格 int")
        if self.dev_case_count <= 0:
            raise ValueError("dev_case_count 必须 > 0")
        for name in ("chunk_size", "chunk_overlap", "dense_candidate_k",
                     "sparse_candidate_k", "top_k", "max_retrieval_calls",
                     "max_evidence_items"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} 必须是整数（不允许 bool）")
            if value <= 0:
                raise ValueError(f"{name} 必须 > 0")
        for label in (
            "chunk_strategy",
            "chunk_budget_policy",
            "embedding_provider",
            "embedding_model",
            "rrf_tie_breaker",
            "merge_policy",
            "group_a_policy",
            "group_b_policy",
            "group_c_policy",
            "group_d_policy",
        ):
            _check_nonempty_no_ws(getattr(self, label), label)
        if type(self.rrf_k) not in (int, float) or isinstance(self.rrf_k, bool):
            raise TypeError("rrf_k 必须是 int 或 float（不允许 bool）")
        if self.rrf_k <= 0:
            raise ValueError("rrf_k 必须 > 0")
        if type(self.reranker_enabled) is not bool:
            raise TypeError("reranker_enabled 必须是严格 bool")

    def identity_payload(self) -> dict:
        """run_id 身份载荷：绑定身份 + 检索参数；不含执行路径。"""
        return {
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "corpus_id": self.corpus_id,
            "corpus_file_count": self.corpus_file_count,
            "gate3_dataset_freeze_id": self.gate3_dataset_freeze_id,
            "dev_evaluation_set_id": self.dev_evaluation_set_id,
            "dev_case_count": self.dev_case_count,
            "dev_jsonl_sha256": self.dev_jsonl_sha256,
            "planner_run_id": self.planner_run_id,
            "planner_prompt_sha256": self.planner_prompt_sha256,
            "planner_results_sha256": self.planner_results_sha256,
            "chunk_strategy": self.chunk_strategy,
            "chunk_budget_policy": self.chunk_budget_policy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "dense_candidate_k": self.dense_candidate_k,
            "sparse_candidate_k": self.sparse_candidate_k,
            "rrf_k": self.rrf_k,
            "rrf_tie_breaker": self.rrf_tie_breaker,
            "top_k": self.top_k,
            "reranker_enabled": self.reranker_enabled,
            "merge_policy": self.merge_policy,
            "max_retrieval_calls": self.max_retrieval_calls,
            "max_evidence_items": self.max_evidence_items,
            "group_a_policy": self.group_a_policy,
            "group_b_policy": self.group_b_policy,
            "group_c_policy": self.group_c_policy,
            "group_d_policy": self.group_d_policy,
        }

    @property
    def run_id(self) -> str:
        return _sha256_bytes(_canonical_json(self.identity_payload()))[:12]

    def to_dict(self) -> dict:
        payload = dict(self.identity_payload())
        payload["run_id"] = self.run_id
        # 执行路径仅以存在性登记，不写入绝对路径字符串。
        for name in ("dev_jsonl_path", "planner_results_path",
                     "planner_result_json_path", "frozen_index_manifest_path",
                     "corpus_root", "output_dir"):
            payload[name] = "set" if getattr(self, name) else ""
        return payload


# ---------------------------------------------------------------------------
# 身份验证
# ---------------------------------------------------------------------------


def validate_identity(config: Gate3AdaptiveDevConfig) -> None:
    """验证冻结身份；任何不一致 fail-fast（在读取任何检索数据前）。"""
    if config.corpus_id != EXPECTED_CORPUS_ID:
        raise ValueError(
            f"corpus_id 必须是 {EXPECTED_CORPUS_ID}，实际 {config.corpus_id}"
        )
    if config.corpus_file_count != EXPECTED_CORPUS_FILE_COUNT:
        raise ValueError(
            f"corpus_file_count 必须是 {EXPECTED_CORPUS_FILE_COUNT}，"
            f"实际 {config.corpus_file_count}"
        )
    if config.gate3_dataset_freeze_id != EXPECTED_FREEZE_ID:
        raise ValueError(
            f"gate3_dataset_freeze_id 必须是 {EXPECTED_FREEZE_ID}，"
            f"实际 {config.gate3_dataset_freeze_id}"
        )
    if config.dev_evaluation_set_id != EXPECTED_DEV_EVALUATION_SET_ID:
        raise ValueError(
            f"dev_evaluation_set_id 必须是 {EXPECTED_DEV_EVALUATION_SET_ID}，"
            f"实际 {config.dev_evaluation_set_id}"
        )
    if config.dev_case_count != EXPECTED_DEV_CASE_COUNT:
        raise ValueError(
            f"dev_case_count 必须是 {EXPECTED_DEV_CASE_COUNT}，"
            f"实际 {config.dev_case_count}"
        )
    if config.dev_jsonl_sha256 != EXPECTED_DEV_JSONL_SHA256:
        raise ValueError(
            f"dev_jsonl_sha256 必须是 {EXPECTED_DEV_JSONL_SHA256}，"
            f"实际 {config.dev_jsonl_sha256}"
        )
    if config.planner_run_id != EXPECTED_PLANNER_RUN_ID:
        raise ValueError(
            f"planner_run_id 必须是 {EXPECTED_PLANNER_RUN_ID}，"
            f"实际 {config.planner_run_id}"
        )
    if config.planner_prompt_sha256 != EXPECTED_PLANNER_PROMPT_SHA256:
        raise ValueError(
            f"planner_prompt_sha256 必须是 {EXPECTED_PLANNER_PROMPT_SHA256}，"
            f"实际 {config.planner_prompt_sha256}"
        )

    # dev jsonl 实际 SHA 校验。
    actual_dev_sha = _sha256_file(Path(config.dev_jsonl_path))
    if actual_dev_sha != config.dev_jsonl_sha256:
        raise ValueError(
            f"dev jsonl 实际 SHA {actual_dev_sha} 与配置 {config.dev_jsonl_sha256} "
            "不一致"
        )

    # planner_results.jsonl 的 SHA 必须从原始 result.json 读取并验证。
    result_obj = json.loads(Path(config.planner_result_json_path).read_text("utf-8"))
    recorded = result_obj.get("artifact_sha256", {}).get("planner_results.jsonl")
    if not recorded:
        raise ValueError("planner result.json 缺少 artifact_sha256.planner_results.jsonl")
    actual_planner_sha = _sha256_file(Path(config.planner_results_path))
    if recorded != config.planner_results_sha256:
        raise ValueError(
            f"planner_results_sha256 配置 {config.planner_results_sha256} 与 "
            f"result.json 记录 {recorded} 不一致"
        )
    if actual_planner_sha != config.planner_results_sha256:
        raise ValueError(
            f"planner_results.jsonl 实际 SHA {actual_planner_sha} 与记录 "
            f"{config.planner_results_sha256} 不一致"
        )


# ---------------------------------------------------------------------------
# 语料 / Dev / Planner 快照
# ---------------------------------------------------------------------------


def load_corpus(corpus_root: str, relative_paths: Sequence[str]) -> dict:
    """basename -> canonical relative_path 映射；basename 唯一，未知来源将失败。"""
    root = Path(corpus_root)
    mapping: dict[str, str] = {}
    seen_base: dict[str, str] = {}
    for rp in relative_paths:
        base = PurePosixPath(rp).name
        if base in seen_base:
            raise ValueError(f"basename 冲突: {base}（{seen_base[base]} vs {rp}）")
        seen_base[base] = rp
        full = root / rp
        if not full.is_file():
            raise ValueError(f"语料文件缺失: {rp}")
        mapping[base] = rp
    return mapping


def load_dev_set(dev_jsonl_path: str, corpus: ExperimentCorpus) -> Gate3EvaluationSet:
    """加载 Dev 评测集（外部 JSONL，绑定冻结 corpus）。"""
    return Gate3EvaluationSet.load_jsonl(dev_jsonl_path, corpus)


def load_planner_snapshot(
    planner_results_path: str, dev_set: Gate3EvaluationSet
) -> dict:
    """从冻结 planner_results.jsonl 重建内存 QueryPlan 快照并严格校验。

    返回 {case_id: {"outcome": PlannerOutcome, "query": str}}。
    C/D 共用同一份快照；不重新调用 Planner。
    """
    case_map = {c.case_id: c for c in dev_set.cases}
    expected_ids = set(case_map.keys())
    query_by_id = {c.case_id: c.query for c in dev_set.cases}
    snapshot: dict[str, dict] = {}
    actual_ids = set()
    seen_ids: set[str] = set()
    with open(planner_results_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            case_id = rec["case_id"]
            if case_id in seen_ids:
                raise ValueError(f"Planner 快照重复 case_id: {case_id}")
            seen_ids.add(case_id)
            actual_ids.add(case_id)
            plan = QueryPlan.from_dict(rec["plan"])
            if plan.original_query != rec["query"]:
                raise ValueError(f"{case_id} plan.original_query 与记录 query 不一致")
            if rec["query"] != query_by_id.get(case_id):
                raise ValueError(f"{case_id} query 与 Dev 不一致")
            pred = rec["predicted"]
            if pred != {
                "action": plan.action,
                "query_type": plan.query_type,
                "reason_code": plan.reason_code,
                "retrieval_required": plan.retrieval_required,
            }:
                raise ValueError(f"{case_id} predicted 与重建 QueryPlan 不一致")
            outcome = PlannerOutcome(
                plan=plan,
                fallback_used=rec["fallback_used"],
                failure_code=rec["failure_code"],
            )
            snapshot[case_id] = {"outcome": outcome, "query": rec["query"]}
    if actual_ids != expected_ids:
        raise ValueError(
            f"Planner 快照 case_id 集合与 Dev 不一致："
            f"多 {sorted(actual_ids - expected_ids)} "
            f"缺 {sorted(expected_ids - actual_ids)}"
        )
    return snapshot


# ---------------------------------------------------------------------------
# 共享索引（复用现有 Loader/Chunker/Embedding/VectorStore/Retriever）
# ---------------------------------------------------------------------------


@dataclass
class SharedIndex:
    retriever: HybridRetriever
    vector_store: ChromaStore
    total_chunks: int
    vector_count: int
    sparse_count: int
    build_manifest: dict


def build_shared_index(
    corpus_root: str,
    relative_paths: Sequence[str],
    vector_store_path: str,
    *,
    embedding=None,
    chunker=None,
) -> SharedIndex:
    """用现有组件构建共享 Hybrid 索引（Dense 与 BM25 同一批 chunks）。

    分块参数固定：recursive / cl100k_content_v1 / 512 / 64；默认 BGE embedding；
    HybridRetriever（dense 30 / sparse 30 / rrf 60 / chunk_id_asc）。
    不构建 Generator；不访问任何 API Key。embedding/chunker 可注入（测试用
    Fake，避免加载真实 bge 模型）。
    """
    root = Path(corpus_root)
    if Path(vector_store_path).exists():
        raise FileExistsError(
            f"向量库目录已存在，禁止覆盖重建: {vector_store_path}"
        )
    embedding = embedding or BGEEmbedding(model_name="BAAI/bge-small-zh-v1.5")
    vector_store = ChromaStore(path=vector_store_path)
    chunker = chunker or RecursiveChunker(chunk_size=512, chunk_overlap=64)
    retriever = HybridRetriever(
        embedding,
        vector_store,
        dense_candidate_k=30,
        sparse_candidate_k=30,
        final_k=5,
        rrf_k=60.0,
        rrf_tie_breaker="chunk_id_asc",
    )
    loader = TextLoader()
    total_chunks = 0
    for rp in relative_paths:
        full = root / rp
        if not full.is_file():
            raise ValueError(f"语料文件缺失: {rp}")
        source_name = PurePosixPath(rp).name
        document_id = make_document_id(source_name)
        docs = loader.load(str(full))
        full_text = "".join(d.content for d in docs)
        content_hash = compute_content_hash(full_text)
        chunks = chunker.chunk(docs)
        texts = [c.content for c in chunks]
        embeddings = embedding.embed(texts)
        for c in chunks:
            c.metadata["document_id"] = document_id
            c.metadata["content_hash"] = content_hash
        vector_store.upsert(chunks, embeddings)
        retriever.build_sparse_index(
            [(c.metadata["id"], c.content, c.metadata) for c in chunks]
        )
        total_chunks += len(chunks)

    vector_count = vector_store.count()
    sparse_count = retriever._bm25.doc_count
    if vector_count != total_chunks or sparse_count != vector_count:
        raise RuntimeError(
            f"索引数量不一致: total={total_chunks} vector={vector_count} "
            f"sparse={sparse_count}"
        )
    build_manifest = {
        "schema_version": GATE3_ADAPTIVE_DEV_MANIFEST_SCHEMA_VERSION,
        "corpus_id": EXPECTED_CORPUS_ID,
        "file_count": len(relative_paths),
        "chunk_strategy": "recursive",
        "chunk_budget_policy": "cl100k_content_v1",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "embedding_provider": "bge",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "retriever_strategy": "hybrid",
        "dense_candidate_k": 30,
        "sparse_candidate_k": 30,
        "rrf_k": 60.0,
        "rrf_tie_breaker": "chunk_id_asc",
        "top_k": 5,
        "reranker_enabled": False,
        "total_chunks": total_chunks,
        "vector_store_count": vector_count,
        "sparse_index_count": sparse_count,
        "shared_across_groups": ["A", "B", "C", "D"],
    }
    return SharedIndex(
        retriever=retriever,
        vector_store=vector_store,
        total_chunks=total_chunks,
        vector_count=vector_count,
        sparse_count=sparse_count,
        build_manifest=build_manifest,
    )


# ---------------------------------------------------------------------------
# No-op AnswerPort / Snapshot Planner（C/D 禁止真实生成 / 真实 Planner）
# ---------------------------------------------------------------------------


class DeterministicNoopAnswerPort:
    """确定性 No-op AnswerPort：返回固定 synthetic 答案，不做真实生成。"""

    answer_generation = "not_evaluated"
    answer_adapter = "deterministic_noop"

    def answer(self, question: str, evidence_bundle: EvidenceBundle, mode: str) -> str:
        return _NOOP_ANSWER


class SnapshotPlanner(BaseQueryPlanner):
    """从冻结 Planner 快照返回 Plan；不调用真实 Planner。"""

    def __init__(self, snapshot: dict):
        self._snapshot = snapshot

    def plan(self, original_query: str) -> PlannerOutcome:
        for case_id, item in self._snapshot.items():
            if item["query"] == original_query:
                return item["outcome"]
        raise ValueError("快照中找不到该 query 对应的冻结计划")


class BM25OnlyCapabilityAdapter(PipelineRetrievalAdapter):
    """evaluation-only 能力包装：只向 Runtime 声明 ("bm25",)（C 组，禁 Hybrid/rescue）。"""

    @property
    def supported_strategies(self) -> tuple[str, ...]:
        return ("bm25",)


class _RecordingAdapter:
    """记录每次 search 返回结果的 RetrievalPort 包装（用于 C/D 候选覆盖）。"""

    def __init__(self, inner, sink: list):
        self._inner = inner
        self._sink = sink

    @property
    def supported_strategies(self) -> tuple[str, ...]:
        return self._inner.supported_strategies

    def search(self, query: str, strategy: str, top_k: int):
        docs = self._inner.search(query, strategy, top_k)
        self._sink.append({"query": query, "strategy": strategy, "docs": list(docs)})
        return docs


def canonical_paths_from_documents(documents, basename_map: dict) -> list[str]:
    """把检索结果（RuntimeDocument 或 EvidenceItem）映射为去重 canonical 路径。

    未知来源立即失败；不允许模糊匹配或手工映射。
    """
    result: list[str] = []
    seen: set[str] = set()
    for d in documents:
        src = getattr(d, "source_name", None) or (
            (d.metadata or {}).get("source_name") if hasattr(d, "metadata") else None
        )
        if src not in basename_map:
            raise ValueError(f"未知检索来源，禁止模糊匹配: {src!r}")
        rp = basename_map[src]
        if rp not in seen:
            seen.add(rp)
            result.append(rp)
    return result


# ---------------------------------------------------------------------------
# 四组执行
# ---------------------------------------------------------------------------


def run_group_original(
    group: str,
    retriever: HybridRetriever,
    cases: Sequence[Gate3Case],
    top_k: int,
    basename_map: dict,
) -> list[dict]:
    """A（bm25）与 B（hybrid）：原问题单次检索，不使用 QueryPlan。"""
    adapter = PipelineRetrievalAdapter(retriever)
    strategy = "bm25" if group == "A" else "hybrid"
    records = []
    for case in sorted(cases, key=lambda c: c.case_id):
        docs = adapter.search(case.query, strategy, top_k)
        canonical = canonical_paths_from_documents(docs, basename_map)
        records.append(
            {
                "case_id": case.case_id,
                "group": group,
                "strategy": strategy,
                "status": "completed",
                "route": "original_single",
                "retrieval_call_count": 1,
                "retrieved_canonical_paths": canonical,
                "retrieved_count": len(canonical),
            }
        )
    return records


def run_group_queryplan(
    group: str,
    retriever: HybridRetriever,
    cases: Sequence[Gate3Case],
    snapshot: dict,
    top_k: int,
    basename_map: dict,
    adaptive: bool,
) -> list[dict]:
    """C（bm25 不 rescue）与 D（adaptive）：冻结 QueryPlan + Runtime。"""
    records = []
    for case in sorted(cases, key=lambda c: c.case_id):
        sink: list[dict] = []
        if adaptive:
            base_adapter = PipelineRetrievalAdapter(retriever)
        else:
            base_adapter = BM25OnlyCapabilityAdapter(retriever)
        recording = _RecordingAdapter(base_adapter, sink)
        runtime = AgentRuntime(
            planner=SnapshotPlanner(snapshot),
            retrieval_port=recording,
            answer_port=DeterministicNoopAnswerPort(),
        )
        result = runtime.run(case.query, top_k=top_k)

        candidates = canonical_paths_from_documents(
            [d for entry in sink for d in entry["docs"]], basename_map
        )
        final_docs = result.evidence_bundle.items if result.evidence_bundle else ()
        final_paths = canonical_paths_from_documents(final_docs, basename_map)
        strategies: dict[str, int] = {}
        for entry in sink:
            strategies[entry["strategy"]] = strategies.get(entry["strategy"], 0) + 1

        verification = result.verification
        records.append(
            {
                "case_id": case.case_id,
                "group": group,
                "plan_id": (
                    result.planner_outcome.plan.plan_id
                    if result.planner_outcome is not None
                    and result.planner_outcome.plan is not None
                    else None
                ),
                "status": result.status,
                "route": (
                    result.route_decision.route
                    if result.route_decision is not None
                    else None
                ),
                "verification_reason": (
                    verification.reason_code if verification is not None else None
                ),
                "coverage_complete": (
                    verification.coverage_complete if verification is not None else None
                ),
                "fallback_used": (
                    result.planner_outcome.fallback_used
                    if result.planner_outcome is not None
                    else None
                ),
                "failure_code": (
                    result.planner_outcome.failure_code
                    if result.planner_outcome is not None
                    else None
                ),
                "retrieval_call_count": len(sink),
                "strategy_distribution": strategies,
                "evidence_count": len(final_docs),
                "upgrade_attempted": (
                    verification.upgrade_attempted if verification is not None else False
                ),
                "upgrade_used": (
                    verification.upgrade_used if verification is not None else False
                ),
                "candidate_canonical_paths": candidates,
                "retrieved_canonical_paths": final_paths,
                "retrieved_count": len(final_paths),
            }
        )
    return records


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


def _ndcg_at_k(retrieved: Sequence[str], gold: set, k: int) -> float:
    rel = [1.0 if r in gold else 0.0 for r in retrieved[:k]]
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal > 0 else 0.0


def compute_document_metrics(
    records_by_case: dict, cases: Sequence[Gate3Case]
) -> dict:
    """document Hit@5 / Recall@5 / MRR / nDCG@5（仅 answerable cases）。"""
    answerable = [c for c in cases if c.answerability == "answerable"]
    per_case = []
    hit_count = 0
    recall_sum = 0.0
    full_recall_count = 0
    mrr_sum = 0.0
    ndcg_sum = 0.0
    for case in answerable:
        rec = records_by_case[case.case_id]
        retrieved = rec["retrieved_canonical_paths"]
        gold = set(case.relevant_files)
        hit = 1 if any(r in gold for r in retrieved) else 0
        recall = (
            len(set(retrieved) & gold) / len(gold) if gold else 0.0
        )
        mrr = 0.0
        for i, r in enumerate(retrieved, 1):
            if r in gold:
                mrr = 1.0 / i
                break
        ndcg = _ndcg_at_k(retrieved, gold, 5)
        hit_count += hit
        recall_sum += recall
        if recall >= 1.0:
            full_recall_count += 1
        mrr_sum += mrr
        ndcg_sum += ndcg
        per_case.append(
            {
                "case_id": case.case_id,
                "hit": hit,
                "recall": recall,
                "mrr": mrr,
                "ndcg": ndcg,
                "gold_count": len(gold),
                "retrieved_count": len(retrieved),
            }
        )
    n = len(answerable)
    return {
        "denominator_case_count": n,
        "hit_at_5": _safe_rate(hit_count, n),
        "recall_at_5": (recall_sum / n) if n else 0.0,
        "mrr": (mrr_sum / n) if n else 0.0,
        "ndcg_at_5": (ndcg_sum / n) if n else 0.0,
        "hit_count": hit_count,
        "full_recall_count": full_recall_count,
        "per_case": per_case,
    }


def compute_obligation_metrics(
    records_by_case: dict, cases: Sequence[Gate3Case], *, candidate_key: str
) -> dict:
    """obligation 覆盖（answerable cases）。candidate_key 决定用最终检索集或候选集。"""
    answerable = [c for c in cases if c.answerability == "answerable"]
    total_obligations = 0
    covered_obligations = 0
    full_cases = 0
    cases_with_obligations = 0
    multi_total = 0
    multi_complete = 0
    per_case = []
    for case in answerable:
        rec = records_by_case[case.case_id]
        retrieved = set(rec[candidate_key])
        obl_list = case.evidence_obligations
        if not obl_list:
            continue
        cases_with_obligations += 1
        covered = 0
        for obl in obl_list:
            total_obligations += 1
            if retrieved & set(obl.relevant_files):
                covered += 1
        covered_obligations += covered
        complete = covered == len(obl_list)
        if complete:
            full_cases += 1
        if len(obl_list) > 1:
            multi_total += 1
            if complete:
                multi_complete += 1
        per_case.append(
            {
                "case_id": case.case_id,
                "obligation_count": len(obl_list),
                "covered_count": covered,
                "complete": complete,
            }
        )
    return {
        "case_count": cases_with_obligations,
        "obligation_total": total_obligations,
        "obligation_covered": covered_obligations,
        "obligation_coverage_rate": _safe_rate(covered_obligations, total_obligations),
        "full_coverage_case_count": full_cases,
        "full_coverage_rate": _safe_rate(full_cases, cases_with_obligations),
        "multi_obligation_case_count": multi_total,
        "multi_obligation_complete_count": multi_complete,
        "multi_obligation_complete_rate": _safe_rate(multi_complete, multi_total),
        "per_case": per_case,
    }


def compute_group_metrics(
    records: list[dict],
    cases: Sequence[Gate3Case],
    *,
    candidate_key: str = "retrieved_canonical_paths",
) -> dict:
    records_by_case = {r["case_id"]: r for r in records}
    doc = compute_document_metrics(records_by_case, cases)
    obl = compute_obligation_metrics(
        records_by_case, cases, candidate_key=candidate_key
    )
    total_calls = sum(r.get("retrieval_call_count", 0) for r in records)
    metrics = {
        "schema_version": GATE3_ADAPTIVE_DEV_METRICS_SCHEMA_VERSION,
        "document": doc,
        "obligation": obl,
        "retrieval_call_count_total": total_calls,
    }
    # C/D 额外：merge-drop / refused / evidence / rescue / strategy / fallback
    group = records[0]["group"] if records else ""
    if group in ("C", "D"):
        metrics.update(_compute_cd_extras(records, cases, obl))
    return metrics


def _compute_cd_extras(
    records: list[dict], cases: Sequence[Gate3Case], obl: dict
) -> dict:
    """候选覆盖、merge-drop、refused、evidence、rescue、fallback、策略分布。"""
    answerable = [c for c in cases if c.answerability == "answerable"]
    records_by_case = {r["case_id"]: r for r in records}
    cand_obl = compute_obligation_metrics(
        records_by_case, answerable, candidate_key="candidate_canonical_paths"
    )
    final_covered = obl["obligation_covered"]
    cand_covered = cand_obl["obligation_covered"]
    refused = sum(1 for r in records if r["status"] == "refused")
    evidence_total = sum(r.get("evidence_count", 0) for r in records)
    rescue_attempted = sum(1 for r in records if r.get("upgrade_attempted"))
    rescue_used = sum(1 for r in records if r.get("upgrade_used"))
    fallback = sum(1 for r in records if r.get("fallback_used"))
    strategy_dist: dict[str, int] = {}
    for r in records:
        for strategy, count in r.get("strategy_distribution", {}).items():
            strategy_dist[strategy] = strategy_dist.get(strategy, 0) + count
    return {
        "candidate_obligation_covered": cand_covered,
        "candidate_obligation_coverage_rate": cand_obl["obligation_coverage_rate"],
        "merge_drop_obligation_count": max(0, cand_covered - final_covered),
        "merge_drop_rate": _safe_rate(
            max(0, cand_covered - final_covered), cand_covered
        ),
        "refused_count": refused,
        "evidence_count_total": evidence_total,
        "rescue_attempted_count": rescue_attempted,
        "rescue_used_count": rescue_used,
        "fallback_count": fallback,
        "strategy_distribution_total": strategy_dist,
    }


# ---------------------------------------------------------------------------
# 分层指标
# ---------------------------------------------------------------------------


def compute_stratified(records: list[dict], cases: Sequence[Gate3Case]) -> dict:
    """按 query_type 与 decomposition_expected 分层（count + 原始分子/分母）。"""
    by_id = {c.case_id: c for c in cases}
    by_type: dict[str, dict] = {}
    by_decomp: dict[str, dict] = {}
    for r in records:
        case = by_id[r["case_id"]]
        for bucket, key in ((by_type, case.query_type), (by_decomp, case.decomposition_expected)):
            b = bucket.setdefault(
                key, {"case_count": 0, "covered_obligations": 0, "total_obligations": 0,
                      "hit": 0, "answerable": 0, "full_coverage": 0, "obligation_cases": 0}
            )
            b["case_count"] += 1
            if case.answerability == "answerable":
                b["answerable"] += 1
                gold = set(case.relevant_files)
                retrieved = set(r["retrieved_canonical_paths"])
                if retrieved & gold:
                    b["hit"] += 1
                if case.evidence_obligations:
                    b["obligation_cases"] += 1
                    covered = sum(
                        1
                        for obl in case.evidence_obligations
                        if retrieved & set(obl.relevant_files)
                    )
                    b["covered_obligations"] += covered
                    b["total_obligations"] += len(case.evidence_obligations)
                    if covered == len(case.evidence_obligations):
                        b["full_coverage"] += 1
    return {
        "by_query_type": by_type,
        "by_decomposition_expected": by_decomp,
    }


# ---------------------------------------------------------------------------
# 对照结论
# ---------------------------------------------------------------------------


def build_comparison_report(metrics: dict) -> str:
    """A/B/C/D 对照 markdown；样本过少时展示 count + 原始分子/分母。"""
    lines = ["# G3-ADAPT-06B 对照报告（Dev 真实检索）", ""]
    oblig_keys = [
        ("obligation_coverage_rate", "obligation 覆盖"),
        ("full_coverage_rate", "full coverage"),
        ("multi_obligation_complete_rate", "multi-obligation 完整覆盖"),
    ]
    doc_keys = [
        ("hit_at_5", "Hit@5"),
        ("recall_at_5", "Recall@5"),
        ("mrr", "MRR"),
        ("ndcg_at_5", "nDCG@5"),
    ]
    lines.append("## 核心指标（A/B/C/D）")
    lines.append("")
    lines.append("指标 | " + " | ".join(metrics.keys()))
    lines.append("--- | " + " | ".join(["---"] * len(metrics)))
    for metric_key, label in oblig_keys:
        row = [label] + [
            f"{m['obligation'][metric_key]:.4f}" for m in metrics.values()
        ]
        lines.append(" | ".join(row))
    for metric_key, label in doc_keys:
        row = [label] + [
            f"{m['document'][metric_key]:.4f}" for m in metrics.values()
        ]
        lines.append(" | ".join(row))
    lines.append("")
    lines.append("## 调用成本")
    lines.append("")
    lines.append("组 | 检索调用总数")
    lines.append("--- | ---")
    for name, m in metrics.items():
        lines.append(f"{name} | {m.get('retrieval_call_count_total', 0)}")
    lines.append("")
    lines.append("## 分组详情（count + 原始分子/分母）")
    for name, m in metrics.items():
        obl = m["obligation"]
        lines.append(
            f"- **{name}**：obligation {obl['obligation_covered']}/"
            f"{obl['obligation_total']}（{obl['obligation_coverage_rate']:.4f}）；"
            f"full {obl['full_coverage_case_count']}/{obl['case_count']}；"
            f"multi 完整 {obl['multi_obligation_complete_count']}/"
            f"{obl['multi_obligation_case_count']}；调用 {m.get('retrieval_call_count_total', 0)}"
        )
        if name in ("C", "D"):
            lines.append(
                f"  - C/D 额外：candidate 覆盖 "
                f"{m.get('candidate_obligation_coverage_rate', 0.0):.4f}、"
                f"merge-drop {m.get('merge_drop_obligation_count', 0)}、"
                f"refused {m.get('refused_count', 0)}、"
                f"rescue used {m.get('rescue_used_count', 0)}、"
                f"fallback {m.get('fallback_count', 0)}"
            )
    lines.append("")
    lines.append("> 说明：本报告为 Dev-only 真实检索对照；answer_generation=not_evaluated，"
                 "不做答案正确性评测；未运行 Holdout。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Artifact 写入
# ---------------------------------------------------------------------------


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_adaptive_dev_artifacts(
    run_dir: Path,
    config: Gate3AdaptiveDevConfig,
    index_manifest: dict,
    case_records: dict,
    metrics: dict,
    comparison_report: str,
) -> None:
    if run_dir.exists():
        raise FileExistsError(f"输出目录已存在，禁止覆盖: {run_dir}")
    run_dir.mkdir(parents=True)
    write_text_atomic(
        run_dir / "run_config.json",
        _canonical_json(config.to_dict()).decode("utf-8"),
    )
    write_text_atomic(
        run_dir / "index_manifest.json",
        _canonical_json(index_manifest).decode("utf-8"),
    )
    case_lines = "\n".join(
        _canonical_json(r).decode("utf-8")
        for group in ("A", "B", "C", "D")
        for r in case_records[group]
    )
    write_text_atomic(run_dir / "case_results.jsonl", case_lines + "\n")
    write_text_atomic(
        run_dir / "retrieval_metrics.json",
        _canonical_json(metrics).decode("utf-8"),
    )
    write_text_atomic(run_dir / "comparison_report.md", comparison_report)


def finalize_adaptive_dev(run_dir: Path, config: Gate3AdaptiveDevConfig,
                          metrics: dict) -> dict:
    """写 result.json（防覆盖、不自引用自身 SHA、无绝对路径/Key/正文）。"""
    result_path = run_dir / "result.json"
    if result_path.exists():
        raise FileExistsError(f"result.json 已存在，禁止覆盖: {result_path}")
    result = {
        "schema_version": GATE3_ADAPTIVE_DEV_RESULT_SCHEMA_VERSION,
        "run_id": config.run_id,
        "config": config.to_dict(),
        "answer_generation": "not_evaluated",
        "answer_adapter": "deterministic_noop",
        "metrics": metrics,
    }
    write_text_atomic(result_path, _canonical_json(result).decode("utf-8"))
    return result


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------


def run_adaptive_dev(config: Gate3AdaptiveDevConfig, git_head: str) -> dict:
    """主入口：身份验证 → 快照 → 共享索引 → 四组 → 指标 → 写入外部 Artifact。"""
    if config.source_commit != git_head:
        raise ValueError(
            f"source_commit {config.source_commit} 与 git HEAD {git_head} 不一致"
        )
    validate_identity(config)

    corpus_path = Path(config.corpus_root)
    frozen_manifest = json.loads(
        Path(config.frozen_index_manifest_path).read_text("utf-8")
    )
    relative_paths = [
        entry["relative_path"]
        for entry in frozen_manifest.get("corpus_entries", [])
    ]
    if len(relative_paths) != config.corpus_file_count:
        raise ValueError(
            f"冻结索引 corpus_entries 数量 {len(relative_paths)} 与 "
            f"config.corpus_file_count {config.corpus_file_count} 不一致"
        )
    corpus = ExperimentCorpus.build(str(corpus_path), relative_paths)
    if corpus.corpus_id != config.corpus_id:
        raise ValueError(
            f"重建 corpus_id {corpus.corpus_id} 与配置 {config.corpus_id} 不一致"
        )
    basename_map = load_corpus(str(corpus_path), relative_paths)

    dev_set = load_dev_set(config.dev_jsonl_path, corpus)
    if len(dev_set.cases) != config.dev_case_count:
        raise ValueError(
            f"Dev 实际 case 数 {len(dev_set.cases)} 与配置 "
            f"{config.dev_case_count} 不一致"
        )
    snapshot = load_planner_snapshot(config.planner_results_path, dev_set)

    run_dir = Path(config.output_dir)
    workspace = run_dir.parent / "workspaces" / config.run_id
    vector_store_path = workspace / "vector_store"
    index = build_shared_index(
        str(corpus_path), relative_paths, str(vector_store_path)
    )
    index_manifest = dict(index.build_manifest)
    index_manifest["index_sha256"] = _sha256_bytes(
        _canonical_json(index_manifest)
    )

    records_a = run_group_original("A", index.retriever, dev_set.cases,
                                   config.top_k, basename_map)
    records_b = run_group_original("B", index.retriever, dev_set.cases,
                                   config.top_k, basename_map)
    records_c = run_group_queryplan("C", index.retriever, dev_set.cases,
                                    snapshot, config.top_k, basename_map,
                                    adaptive=False)
    records_d = run_group_queryplan("D", index.retriever, dev_set.cases,
                                    snapshot, config.top_k, basename_map,
                                    adaptive=True)

    case_records = {"A": records_a, "B": records_b, "C": records_c, "D": records_d}
    metrics = {
        name: compute_group_metrics(recs, dev_set.cases)
        for name, recs in case_records.items()
    }
    for name in ("A", "B", "C", "D"):
        metrics[name]["stratified"] = compute_stratified(
            case_records[name], dev_set.cases
        )

    comparison = build_comparison_report(metrics)
    write_adaptive_dev_artifacts(
        run_dir, config, index_manifest, case_records, metrics, comparison
    )
    result = finalize_adaptive_dev(run_dir, config, metrics)
    return result
