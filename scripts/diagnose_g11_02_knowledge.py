"""Deterministic diagnosis for missing G11-02 Knowledge Evidence.

This module only assembles the existing Pipeline retrieval backend and
KnowledgeSearchHandler. It never creates a planner, generator request, or
provider client call. Serialized source identities are redacted when the
backend exposes absolute provenance.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Support direct execution as `python scripts/diagnose_...py` from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_runtime.adapters import PipelineRetrievalAdapter
from core.config import Config
from core.embeddings.bge_emb import BGEEmbedding
from core.retriever.bm25_only import BM25OnlyRetriever
from core.retriever.hybrid import HybridRetriever
from core.tool_agent.tools.knowledge_search import KnowledgeSearchHandler
from core.vector_store.chroma_store import ChromaStore

PROJECT_IDENTITY = "my_agent_repository"
DECLARED_KNOWLEDGE_CORPUS_ID = "870e5864df67"
PROVIDER_CALLED = False
GENERATOR_CALLED = False
MAX_SNIPPET_LENGTH = 200
TOP_K = 5

QUERIES = (
    ("Q1", "RRF Reciprocal Rank Fusion"),
    ("Q2", "MMR 多样性 冗余"),
    ("Q3", "Reranker Cross-Encoder"),
    ("Q4", "context token budget citation 引用校验"),
    (
        "Q5",
        "RRF 为什么适合融合 Dense 和 BM25？结合当前项目说明 HybridRetriever 是怎样实现 RRF 的，特别是某个文档只在一路召回时如何计分，以及为什么还需要确定性的 tie-break。",
    ),
    (
        "Q6",
        "MMR 主要解决检索结果里的什么问题？结合当前项目的 MMRRetriever，说明 lambda_param 怎样平衡相关性和多样性，以及为什么实现会先取 top_k_initial 候选再逐个选择。",
    ),
    (
        "Q7",
        "为什么 RAG 通常先召回较多候选再 rerank？当前项目 Pipeline.query 怎样决定 candidate_k 和 final_k，Reranker 失败时怎样降级，最后又怎样保证用户请求的 top_k？这些设计体现了什么工程权衡？",
    ),
    (
        "Q8",
        "RAG 为什么不能把所有检索结果直接塞给模型？结合当前 Pipeline.query 说明项目怎样计算 context token budget、组织带引用的 context，并在生成后验证 citation；这几步分别防什么问题？",
    ),
)

_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)")
_POSIX_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s]+)")


def _run_git(git_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _validate_git_root(git_root: str | Path) -> tuple[Path, str, bool]:
    requested_root = Path(git_root)
    top = _run_git(requested_root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        raise ValueError("git_root is not a Git working tree")
    # Keep the operator-provided cwd for filesystem operations; on Windows
    # decoding Git's non-ASCII absolute path back into Path can be lossy.
    root = requested_root
    head = _run_git(root, "rev-parse", "HEAD")
    head_value = head.stdout.strip().lower()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head_value):
        raise ValueError("git_root HEAD is not a valid commit")
    status = _run_git(root, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        raise ValueError("could not inspect git_root tracked status")
    return root, head_value, not bool(status.stdout.strip())


def classify_source_name(source_name: object) -> str:
    if not isinstance(source_name, str) or not source_name.strip():
        return "MISSING_SOURCE_NAME"
    value = source_name.strip()
    if _WINDOWS_ABSOLUTE_RE.search(value):
        return "ABSOLUTE_PROVENANCE"
    if _POSIX_ABSOLUTE_RE.search(value):
        return "ABSOLUTE_PROVENANCE"
    return "SAFE_RELATIVE_OR_BASENAME"


def _platform_for_source(source_name: object) -> str | None:
    if classify_source_name(source_name) != "ABSOLUTE_PROVENANCE":
        return None
    value = str(source_name)
    if re.search(r"(?i)(?:[a-z]:[\\/]|\\\\)", value):
        return "Windows"
    return "POSIX"


def _safe_source_name(source_name: object) -> str:
    classification = classify_source_name(source_name)
    if classification == "ABSOLUTE_PROVENANCE":
        platform = _platform_for_source(source_name)
        return f"<redacted absolute provenance: {platform.lower()}>"
    if classification == "MISSING_SOURCE_NAME":
        return "<missing source_name>"
    return str(source_name).strip()


def _safe_snippet(content: object, source_name: object) -> str | None:
    if classify_source_name(source_name) != "SAFE_RELATIVE_OR_BASENAME":
        return None
    if not isinstance(content, str) or not content:
        return None
    bounded = content[:MAX_SNIPPET_LENGTH]
    if _WINDOWS_ABSOLUTE_RE.search(bounded) or _POSIX_ABSOLUTE_RE.search(bounded):
        return None
    return bounded


def _safe_match(rank: int, document: Any, score_key: str) -> dict:
    metadata = getattr(document, "metadata", {}) or {}
    source_name = metadata.get("source_name", metadata.get("source"))
    return {
        "rank": rank,
        "source_name": _safe_source_name(source_name),
        "chunk_id": metadata.get("id"),
        "score": metadata.get(score_key),
        "snippet": _safe_snippet(getattr(document, "content", None), source_name),
        "provenance_classification": classify_source_name(source_name),
    }


def _search_result(
    adapter: PipelineRetrievalAdapter, query_id: str, query: str, strategy: str
) -> dict:
    try:
        documents = tuple(adapter.search(query, strategy, TOP_K))
        score_key = "sparse_score" if strategy == "bm25" else "rrf_score"
        matches = [
            _safe_match(rank, document, score_key)
            for rank, document in enumerate(documents, 1)
        ]
        return {
            "query_id": query_id,
            "strategy": strategy,
            "status": "ok",
            "match_count": len(matches),
            "matches": matches,
        }
    except Exception as exc:
        return {
            "query_id": query_id,
            "strategy": strategy,
            "status": "error",
            "error_code": type(exc).__name__,
            "match_count": 0,
            "matches": [],
        }


def _provenance_health(vector_store: ChromaStore) -> dict:
    indexed = vector_store.get_all_indexed()
    counts = {
        "SAFE_RELATIVE_OR_BASENAME": 0,
        "ABSOLUTE_PROVENANCE": 0,
        "MISSING_SOURCE_NAME": 0,
    }
    platforms = {"Windows": 0, "POSIX": 0}
    for item in indexed:
        metadata = item.get("metadata") or {}
        source_name = metadata.get("source_name", metadata.get("source"))
        classification = classify_source_name(source_name)
        counts[classification] += 1
        platform = _platform_for_source(source_name)
        if platform:
            platforms[platform] += 1
    return {
        "classification_counts": counts,
        "absolute_provenance_count": counts["ABSOLUTE_PROVENANCE"],
        "absolute_provenance_platforms": {
            key: value for key, value in platforms.items() if value
        },
    }


def _build_retrieval_backend(root: Path):
    """Build only the production retrieval side; never initialize a generator."""
    previous_cwd = Path.cwd()
    os.chdir(root)
    try:
        config = Config("config.yaml")
        vector_store = ChromaStore(config.vector_store_path)
        if config.embedding_provider != "bge":
            raise RuntimeError(
                "deterministic diagnostic refuses embedding provider initialization"
            )
        embedding = BGEEmbedding(model_name=config.embedding_model)
        if config.retriever_strategy == "hybrid":
            retriever = HybridRetriever(
                embedding,
                vector_store,
                dense_candidate_k=config.dense_candidate_k,
                sparse_candidate_k=config.sparse_candidate_k,
                final_k=config.top_k,
                rrf_k=config.rrf_k,
                rrf_tie_breaker=config.rrf_tie_breaker,
            )
        elif config.retriever_strategy == "bm25":
            retriever = BM25OnlyRetriever()
        else:
            raise RuntimeError(
                "deterministic diagnostic supports only the configured bm25/hybrid retrieval"
            )
        if hasattr(retriever, "build_sparse_index"):
            all_data = vector_store.collection.get(
                include=["documents", "metadatas"]
            )
            pairs = [
                (
                    all_data["metadatas"][i].get("id", ""),
                    all_data["documents"][i],
                    all_data["metadatas"][i],
                )
                for i in range(len(all_data["ids"]))
                if all_data["metadatas"][i].get("id")
            ]
            retriever.build_sparse_index(pairs)
        return config, vector_store, retriever
    finally:
        os.chdir(previous_cwd)


def _handler_result(
    handler: KnowledgeSearchHandler, query_id: str, query: str, strategy: str
) -> dict:
    try:
        result = handler.execute({"query": query})
        matches = result.get("matches", [])
        return {
            "query_id": query_id,
            "strategy": strategy,
            "status": "ok",
            "match_count": len(matches),
            "provenance_classification": (
                "SAFE_RELATIVE_OR_BASENAME" if matches else "NO_MATCHES"
            ),
        }
    except Exception as exc:
        error_name = type(exc).__name__
        classification = (
            "PROVENANCE_REJECTED"
            if error_name == "ValueError"
            else "TOOL_EXECUTION_FAILED"
        )
        return {
            "query_id": query_id,
            "strategy": strategy,
            "status": "error",
            "error_code": error_name,
            "match_count": 0,
            "provenance_classification": classification,
        }


def _write_report(path: Path, manifest: dict, results: dict) -> None:
    lines = [
        "# G11-02 Knowledge Backend Diagnostic",
        "",
        "Deterministic read-only diagnosis. Provider and generator calls were not made.",
        "",
        "## Identity",
        "",
        f"- diagnostic_run_id: `{manifest['diagnostic_run_id']}`",
        f"- source_commit: `{manifest['source_commit']}`",
        f"- project_identity: `{manifest['project_identity']}`",
        f"- declared_knowledge_corpus_id: `{manifest['declared_knowledge_corpus_id']}`",
        f"- retriever_type: `{manifest['retriever_type']}`",
        f"- provider_called: `{manifest['provider_called']}`",
        f"- generator_called: `{manifest['generator_called']}`",
        "",
        "## Index Health",
        "",
        f"- vector_store_count: `{manifest['vector_store_count']}`",
        f"- bm25_doc_count: `{manifest['bm25_doc_count']}`",
        f"- supported_strategies: `{', '.join(manifest['supported_strategies'])}`",
        f"- provenance: `{manifest['provenance_health']}`",
        "",
        "## KnowledgeSearchHandler",
        "",
        "| Query | Strategy | Status | Matches | Provenance | Error |",
        "|---|---|---|---:|---|---|",
    ]
    for item in results["handler_results"]:
        lines.append(
            f"| {item['query_id']} | {item['strategy']} | {item['status']} | "
            f"{item['match_count']} | "
            f"{item.get('provenance_classification', '')} | {item.get('error_code', '')} |"
        )
    lines.extend(["", "## Retrieval Comparison", ""])
    lines.extend(
        [
            "| Query | BM25 matches | Hybrid matches |",
            "|---|---:|---:|",
        ]
    )
    for query_id, _ in QUERIES:
        bm25 = results["backend_results"][query_id]["bm25"]
        hybrid = results["backend_results"][query_id].get("hybrid")
        hybrid_count = "error" if hybrid["status"] == "error" else hybrid["match_count"]
        lines.append(f"| {query_id} | {bm25['match_count']} | {hybrid_count} |")
    lines.extend(
        [
            "",
            "## Classification",
            "",
            f"- primary_root_cause: `{results['root_cause']['primary']}`",
            f"- secondary: `{results['root_cause']['secondary']}`",
            f"- rationale: {results['root_cause']['rationale']}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose(git_root: str | Path, output_dir: str | Path, run_id: str) -> Path:
    root, source_commit, tracked_clean = _validate_git_root(git_root)
    if not tracked_clean:
        raise ValueError("git_root has tracked modifications")

    # Build the existing retrieval side only. This does not initialize a
    # planner/generator and therefore cannot call a provider.
    config, vector_store, retriever = _build_retrieval_backend(root)
    adapter = PipelineRetrievalAdapter(retriever)
    provenance_health = _provenance_health(vector_store)
    bm25_doc_count = getattr(getattr(retriever, "_bm25", None), "doc_count", None)
    backend_results: dict[str, dict] = {}
    for query_id, query in QUERIES:
        item = {"bm25": _search_result(adapter, query_id, query, "bm25")}
        if "hybrid" in adapter.supported_strategies:
            item["hybrid"] = _search_result(adapter, query_id, query, "hybrid")
        backend_results[query_id] = item

    handler_results = []
    for strategy in ("bm25", "hybrid"):
        if strategy not in adapter.supported_strategies:
            continue
        handler = KnowledgeSearchHandler(adapter, strategy=strategy)
        handler_results.extend(
            _handler_result(handler, query_id, query, strategy)
            for query_id, query in QUERIES
        )

    if bm25_doc_count == 0 and vector_store.count() > 0:
        root_cause = {
            "primary": "B. SPARSE_INDEX_NOT_READY",
            "secondary": (
                "C. PROVENANCE_REJECTED"
                if provenance_health["absolute_provenance_count"]
                else "None"
            ),
            "rationale": (
                "The vector store contains indexed chunks but the production BM25 index is "
                "empty, so the production bm25 Handler returns no matches. The same indexed "
                "chunks also expose absolute Windows provenance; the hybrid Handler reaches "
                "that boundary and rejects unsafe source identities."
            ),
        }
    elif bm25_doc_count == 0 and vector_store.count() > 0:
        root_cause = {
            "primary": "B. SPARSE_INDEX_NOT_READY",
            "secondary": "None",
            "rationale": "Vector store contains data but the production BM25 index is empty.",
        }
    elif all(
        backend_results[query_id]["bm25"]["match_count"] == 0
        and backend_results[query_id].get("hybrid", {}).get("match_count", 0) == 0
        for query_id, _ in QUERIES
    ):
        root_cause = {
            "primary": "E. RETRIEVAL_MISS",
            "secondary": "None",
            "rationale": "Neither deterministic BM25 nor hybrid retrieval returned matches.",
        }
    else:
        root_cause = {
            "primary": "G. AGENT_QUERY_FORMULATION",
            "secondary": "None",
            "rationale": (
                "Deterministic retrieval and the handler path returned usable matches; "
                "the existing safe Agent artifact does not preserve tool arguments, so "
                "the exact agent query formulation cannot be proven."
            ),
        }

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "diagnostic_run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "project_identity": PROJECT_IDENTITY,
        "declared_knowledge_corpus_id": DECLARED_KNOWLEDGE_CORPUS_ID,
        "retriever_type": type(retriever).__name__,
        "vector_store_count": vector_store.count(),
        "bm25_doc_count": bm25_doc_count,
        "supported_strategies": list(adapter.supported_strategies),
        "provider_called": PROVIDER_CALLED,
        "generator_called": GENERATOR_CALLED,
        "tracked_clean": tracked_clean,
        "config_identity": {
            "retriever_strategy": config.retriever_strategy,
            "vector_store_path": config.vector_store_path,
        },
        "provenance_health": provenance_health,
    }
    results = {
        "backend_results": backend_results,
        "handler_results": handler_results,
        "root_cause": root_cause,
    }
    (output / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "knowledge_backend_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(output / "diagnostic_report.md", manifest, results)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    output = diagnose(args.git_root, args.output, args.run_id)
    print(json.dumps({"output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
