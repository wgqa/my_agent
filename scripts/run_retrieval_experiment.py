"""G2-REAL-11：真实 Retrieval 实验薄执行入口。

只负责：接受路径参数 -> 发现 Corpus 文件 -> 构造 ExperimentCorpus ->
加载 RetrievalEvaluationSet -> 构造本次固定 ExperimentConfig ->
创建 ExperimentRunner -> 调用 run_experiment() -> 打印最终事实结果。

不包含新的 Retrieval / Metrics / Manifest / Gold 逻辑。
"""

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.experiment_runner import ExperimentRunner
from evaluation.retrieval_evaluation_set import RetrievalEvaluationSet


def build_config(
    retriever_strategy: str = "hybrid",
    chunk_strategy: str = "recursive",
) -> ExperimentConfig:
    """冻结参数：512/64 + top5（不得调参）；支持 fixed/recursive 与 simple/hybrid/bm25。"""
    if retriever_strategy not in ("simple", "hybrid", "bm25"):
        raise ValueError(
            f"未知 retriever_strategy: {retriever_strategy}，"
            "CLI 只允许 simple/hybrid/bm25"
        )
    if chunk_strategy not in ("fixed", "recursive"):
        raise ValueError(
            f"未知 chunk_strategy: {chunk_strategy}，CLI 只允许 fixed/recursive"
        )
    return ExperimentConfig(
        embedding_provider="bge",
        embedding_model="BAAI/bge-small-zh-v1.5",
        chunk_strategy=chunk_strategy,
        chunk_size=512,
        chunk_overlap=64,
        retriever_strategy=retriever_strategy,
        top_k=5,
        dense_candidate_k=30,
        sparse_candidate_k=30,
        rrf_k=60.0,
        rrf_tie_breaker="chunk_id_asc",
    )


def discover_markdown(corpus_root: Path):
    """递归发现全部 .md，返回相对于 Corpus Root 的 POSIX relative path"""
    return sorted(
        p.relative_to(corpus_root).as_posix()
        for p in corpus_root.rglob("*.md")
        if p.is_file()
    )


def run(args) -> dict:
    corpus_root = Path(args.corpus_root)
    corpus = ExperimentCorpus.build(corpus_root, discover_markdown(corpus_root))
    evaluation_set = RetrievalEvaluationSet.load_jsonl(
        Path(args.evaluation), corpus
    )
    config = build_config(args.retriever_strategy, args.chunk_strategy)
    runner = ExperimentRunner(args.base_config, args.workspace_root)
    result = runner.run_experiment(config, args.run_id, corpus, evaluation_set)
    return {
        "corpus_id": corpus.corpus_id,
        "evaluation_set_id": evaluation_set.evaluation_set_id,
        "experiment_id": config.experiment_id,
        "retrieval_run_id": result.retrieval_run_id,
        "metrics_run_id": result.metrics_run_id,
        "result_id": result.result_id,
        "file_count": result.file_count,
        "total_chunks": result.total_chunks,
        "case_count": result.case_count,
        "top_k": result.top_k,
        "mean_hit_at_k": result.mean_hit_at_k,
        "mean_recall_at_k": result.mean_recall_at_k,
        "mean_mrr": result.mean_mrr,
        "mean_ndcg_at_k": result.mean_ndcg_at_k,
        "result_json": str(
            Path(args.workspace_root)
            / config.experiment_id
            / args.run_id
            / "result.json"
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="运行一次正式 Retrieval 实验（G2-REAL-11）"
    )
    parser.add_argument("--corpus-root", required=True, help="Benchmark Corpus Root")
    parser.add_argument("--evaluation", required=True, help="Gold evaluation.jsonl")
    parser.add_argument("--base-config", required=True, help="项目 config.yaml")
    parser.add_argument("--workspace-root", required=True, help="实验 Workspace Root")
    parser.add_argument("--run-id", required=True, help="显式 run_id")
    parser.add_argument(
        "--retriever-strategy", default="hybrid",
        choices=["simple", "hybrid", "bm25"],
        help="正式实验策略：simple=Dense-only，bm25=BM25-only，hybrid=RRF 融合",
    )
    parser.add_argument(
        "--chunk-strategy", default="recursive",
        choices=["fixed", "recursive"],
        help="分块策略：fixed=固定 token 窗口，recursive=语义边界优先",
    )
    args = parser.parse_args(argv)
    facts = run(args)
    print(json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
