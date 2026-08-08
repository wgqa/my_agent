"""G2-DIAG-13：Hybrid Dense/BM25 Channel-Level Diagnostic 运行入口。

独立诊断 Workspace：prepare + index_corpus（复用正式阶段），然后
run_retrieval_diagnostics() 生成 retrieval_diagnostics.json，并强制
Final Top-5 与冻结 Baseline 完全一致。
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment
from evaluation.experiment_workspace import ExperimentWorkspace
from evaluation.index_manifest import FileIndexRecord, IndexManifest
from evaluation.retrieval_evaluation_set import RetrievalEvaluationSet
from scripts.run_retrieval_experiment import build_config, discover_markdown


FOCUS_CASES = ["q013", "q019", "q039", "q047", "q031", "q034", "q036"]


def _load_baseline_manifest(path: Path) -> IndexManifest:
    """从冻结 Baseline Workspace 读取并重建 IndexManifest（只读）。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return IndexManifest(
        schema_version=payload["schema_version"],
        experiment_id=payload["experiment_id"],
        corpus_id=payload["corpus_id"],
        chunk_strategy=payload["chunk_strategy"],
        retriever_strategy=payload["retriever_strategy"],
        config=payload["config"],
        corpus_entries=tuple(dict(e) for e in payload["corpus_entries"]),
        files=tuple(FileIndexRecord(**f) for f in payload["files"]),
        file_count=payload["file_count"],
        total_chunks=payload["total_chunks"],
        vector_store_count=payload["vector_store_count"],
        sparse_index_count=payload["sparse_index_count"],
    )


def _copy_baseline_index(src: Path, dst: Path) -> None:
    """把冻结 Baseline 的向量索引复制到独立诊断 Workspace。

    复用同一份索引可保证 Dense 通道与 Baseline 完全一致；
    只写诊断 Workspace，不修改 Baseline Workspace。
    """
    if not src.is_dir():
        raise RuntimeError(f"Baseline vector_store 不存在：{src}")
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _channel_facts(candidates, gold_files):
    """对每个 Gold 文件返回 (present, first_rank)"""
    facts = {}
    for rel in gold_files:
        present = False
        first_rank = None
        for c in candidates:
            if c.relative_path == rel:
                present = True
                first_rank = c.rank
                break
        facts[rel] = (present, first_rank)
    return facts


def run(args) -> dict:
    corpus_root = Path(args.corpus_root)
    corpus = ExperimentCorpus.build(corpus_root, discover_markdown(corpus_root))
    evaluation_set = RetrievalEvaluationSet.load_jsonl(
        Path(args.evaluation), corpus
    )
    config = build_config()
    runner = ExperimentRunner(args.base_config, args.workspace_root)
    workspace = ExperimentWorkspace(
        args.base_config, args.workspace_root, config, args.run_id
    )
    paths = workspace.prepare()
    baseline_ws = Path(args.baseline_results).parent
    manifest = _load_baseline_manifest(baseline_ws / "index_manifest.json")
    _copy_baseline_index(baseline_ws / "vector_store", paths.vector_store_path)
    manifest.write_json(paths.index_manifest_path)
    pipeline = runner._pipeline_factory(paths.config_path)
    prepared = PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=pipeline
    )
    snapshot = runner.run_retrieval_diagnostics(
        prepared,
        manifest,
        evaluation_set,
        baseline_retrieval_run_id=args.baseline_run_id,
        baseline_results_path=args.baseline_results,
    )

    facts = {}
    for case_id in FOCUS_CASES:
        case_obj = next(c for c in snapshot.cases if c.case_id == case_id)
        gold = case_obj.relevant_files
        dense = _channel_facts(case_obj.dense_candidates, gold)
        sparse = _channel_facts(case_obj.sparse_candidates, gold)
        final = _channel_facts(case_obj.final_hits, gold)
        facts[case_id] = {
            rel: {
                "dense_present": dense[rel][0],
                "dense_first_rank": dense[rel][1],
                "sparse_present": sparse[rel][0],
                "sparse_first_rank": sparse[rel][1],
                "final_present": final[rel][0],
            }
            for rel in gold
        }

    return {
        "diagnostic_id": snapshot.diagnostic_id,
        "baseline_retrieval_run_id": snapshot.baseline_retrieval_run_id,
        "experiment_id": snapshot.experiment_id,
        "corpus_id": snapshot.corpus_id,
        "evaluation_set_id": snapshot.evaluation_set_id,
        "case_count": len(snapshot.cases),
        "final_match_baseline": "50/50 exact match",
        "focus_cases": facts,
        "diagnostic_json": str(
            Path(args.workspace_root)
            / config.experiment_id
            / args.run_id
            / "retrieval_diagnostics.json"
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="运行 Hybrid Channel-Level Diagnostic（G2-DIAG-13）"
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline-results", required=True)
    parser.add_argument("--baseline-run-id", required=True)
    args = parser.parse_args(argv)
    facts = run(args)
    print(json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
