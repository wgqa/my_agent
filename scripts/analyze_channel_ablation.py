"""G2-ABL-15：Dense vs BM25 vs Hybrid offline channel ablation。

只读取 canonical retrieval_diagnostics.json 中已保存的 channel
candidates 与 final_hits，复用正式 Retrieval Metrics 数学做
post-hoc 消融。不调用 Pipeline/Retriever/Embedding/VectorStore/BM25，
不产生新索引、新 RetrievalRunResult 或新 ExperimentResult。
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from evaluation.retrieval_metrics import compute_case_metrics

ABLATION_SCHEMA_VERSION = 1
TOP_K = 5
METRIC_NAMES = ("hit_at_k", "recall_at_k", "mrr", "ndcg_at_k")


def document_ranking(candidates, top_k=TOP_K):
    """正式 Top-K 语义：先取前 top_k 个 Chunk，再按首次出现顺序去重。"""
    ordered = sorted(candidates, key=lambda c: c["rank"])[:top_k]
    ranking = []
    seen = set()
    for candidate in ordered:
        relative_path = candidate["relative_path"]
        if relative_path not in seen:
            seen.add(relative_path)
            ranking.append(relative_path)
    return ranking


def metrics_for(case_id, retrieved_files, relevant_files, top_k=TOP_K):
    return compute_case_metrics(
        case_id=case_id,
        retrieved_files=retrieved_files,
        relevant_files=relevant_files,
        top_k=top_k,
    )


def classify_case(dense, sparse, hybrid, relevant_count):
    dense_hit = dense.hit_at_k == 1.0
    sparse_hit = sparse.hit_at_k == 1.0
    hybrid_hit = hybrid.hit_at_k == 1.0
    if hybrid_hit and dense_hit and sparse_hit:
        outcome = "all_success"
        subtype = None
    elif hybrid_hit:
        outcome = "hybrid_rescue"
        if dense_hit and not sparse_hit:
            subtype = "rescues_sparse"
        elif sparse_hit and not dense_hit:
            subtype = "rescues_dense"
        else:
            subtype = "rescues_both"
    elif dense_hit or sparse_hit:
        outcome = "fusion_regression"
        subtype = "dense" if dense_hit and not sparse_hit else (
            "sparse" if sparse_hit and not dense_hit else "both"
        )
    else:
        outcome = "all_fail"
        subtype = None
    recall_regression = (
        relevant_count > 1
        and hybrid.recall_at_k
        < max(dense.recall_at_k, sparse.recall_at_k)
    )
    return outcome, subtype, recall_regression


def _metric_dict(metrics, retrieved_files):
    return {
        "hit_at_k": metrics.hit_at_k,
        "recall_at_k": metrics.recall_at_k,
        "mrr": metrics.mrr,
        "ndcg_at_k": metrics.ndcg_at_k,
        "retrieved_files": list(retrieved_files),
        "first_relevant_rank": metrics.first_relevant_rank,
    }


def analyze_payload(payload: dict) -> dict:
    cases = []
    for case in payload["cases"]:
        relevant_files = list(case["relevant_files"])
        dense_ranking = document_ranking(case["dense_candidates"])
        sparse_ranking = document_ranking(case["sparse_candidates"])
        hybrid_ranking = document_ranking(case["final_hits"])

        dense_m = metrics_for(case["case_id"], dense_ranking, relevant_files)
        sparse_m = metrics_for(case["case_id"], sparse_ranking, relevant_files)
        hybrid_m = metrics_for(case["case_id"], hybrid_ranking, relevant_files)
        outcome, subtype, recall_regression = classify_case(
            dense_m, sparse_m, hybrid_m, len(relevant_files)
        )
        cases.append({
            "case_id": case["case_id"],
            "relevant_files": relevant_files,
            "dense": _metric_dict(dense_m, dense_ranking),
            "sparse": _metric_dict(sparse_m, sparse_ranking),
            "hybrid": _metric_dict(hybrid_m, hybrid_ranking),
            "outcome": outcome,
            "outcome_subtype": subtype,
            "recall_regression": recall_regression,
        })

    def _mean(channel, metric):
        return sum(c[channel][metric] for c in cases) / len(cases)

    macro = {
        "dense": {k: _mean("dense", k) for k in METRIC_NAMES},
        "sparse": {k: _mean("sparse", k) for k in METRIC_NAMES},
        "hybrid": {k: _mean("hybrid", k) for k in METRIC_NAMES},
    }

    outcome_counter = Counter(c["outcome"] for c in cases)
    subtype_counter = Counter(
        (c["outcome"], c["outcome_subtype"]) for c in cases
        if c["outcome_subtype"] is not None
    )

    def _net(other_key):
        rescues = sum(
            1
            for c in cases
            if c["hybrid"]["hit_at_k"] == 1.0 and c[other_key]["hit_at_k"] == 0.0
        )
        losses = sum(
            1
            for c in cases
            if c["hybrid"]["hit_at_k"] == 0.0 and c[other_key]["hit_at_k"] == 1.0
        )
        return {"rescue": rescues, "loss": losses}

    summary = {
        "schema_version": ABLATION_SCHEMA_VERSION,
        "source": {
            "diagnostic_id": payload.get("diagnostic_id"),
            "baseline_retrieval_run_id": payload.get("baseline_retrieval_run_id"),
        },
        "method": "offline/counterfactual channel ablation",
        "top_k_chunks": TOP_K,
        "macro": macro,
        "outcomes": {
            "all_success": outcome_counter.get("all_success", 0),
            "hybrid_rescue": outcome_counter.get("hybrid_rescue", 0),
            "fusion_regression": outcome_counter.get("fusion_regression", 0),
            "all_fail": outcome_counter.get("all_fail", 0),
            "subtypes": {
                "rescues_dense": subtype_counter.get(("hybrid_rescue", "rescues_dense"), 0),
                "rescues_sparse": subtype_counter.get(("hybrid_rescue", "rescues_sparse"), 0),
                "rescues_both": subtype_counter.get(("hybrid_rescue", "rescues_both"), 0),
                "regression_dense": subtype_counter.get(("fusion_regression", "dense"), 0),
                "regression_sparse": subtype_counter.get(("fusion_regression", "sparse"), 0),
                "regression_both": subtype_counter.get(("fusion_regression", "both"), 0),
            },
            "recall_regression_count": sum(
                1 for c in cases if c["recall_regression"]
            ),
        },
        "net_value": {
            "hybrid_vs_dense": _net("dense"),
            "hybrid_vs_sparse": _net("sparse"),
        },
        "case_count": len(cases),
    }
    return {"summary": summary, "cases": cases}


def load_diagnostics(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("retrieval_diagnostics.json 顶层不是 object")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="G2-ABL-15 offline channel ablation"
    )
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    payload = load_diagnostics(Path(args.diagnostics))
    result = analyze_payload(payload)
    out = {
        "summary": result["summary"],
        "cases": result["cases"],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
