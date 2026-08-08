"""G2-ANALYSIS-14：Chunk-Level Fusion Fragmentation 只读分析。

只读取 retrieval_diagnostics.json 与其中保存的 relevant_files，
不调用 Pipeline / Retriever / Embedding / Vector Store / BM25。
同一 Artifact 输入必须得到稳定相同输出。
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

CLASS_ORDER = (
    "A_no_channel_recall",
    "B_dense_only",
    "C_sparse_only",
    "D_dual_same_best_chunk",
    "E_dual_shared_chunk",
    "F_dual_different_chunk_only",
)


def classify_obligation(dense_present, sparse_present, dense_best_chunk,
                        sparse_best_chunk, shared_chunk_count):
    """按 G2-ANALYSIS-14 定义把 Gold obligation 归入 A-F。"""
    if not dense_present and not sparse_present:
        return "A_no_channel_recall"
    if dense_present and not sparse_present:
        return "B_dense_only"
    if not dense_present and sparse_present:
        return "C_sparse_only"
    if dense_best_chunk == sparse_best_chunk:
        return "D_dual_same_best_chunk"
    if shared_chunk_count > 0:
        return "E_dual_shared_chunk"
    return "F_dual_different_chunk_only"


def analyze_payload(payload: dict) -> dict:
    """从诊断 payload 计算全部 Gold obligations 与统计。"""
    obligations = []
    for case in payload["cases"]:
        dense_by_file = {}
        for candidate in case["dense_candidates"]:
            dense_by_file.setdefault(candidate["relative_path"], []).append(candidate)
        sparse_by_file = {}
        for candidate in case["sparse_candidates"]:
            sparse_by_file.setdefault(candidate["relative_path"], []).append(candidate)
        final_files = set(hit["relative_path"] for hit in case["final_hits"])
        final_chunks_by_file = {}
        for hit in case["final_hits"]:
            final_chunks_by_file.setdefault(hit["relative_path"], []).append(
                hit["chunk_id"]
            )

        for rel in case["relevant_files"]:
            dense_cands = sorted(
                dense_by_file.get(rel, []), key=lambda c: c["rank"]
            )
            sparse_cands = sorted(
                sparse_by_file.get(rel, []), key=lambda c: c["rank"]
            )
            dense_chunk_ids = [c["chunk_id"] for c in dense_cands]
            sparse_chunk_ids = [c["chunk_id"] for c in sparse_cands]
            shared_chunk_ids = sorted(
                set(dense_chunk_ids) & set(sparse_chunk_ids)
            )
            dense_present = bool(dense_cands)
            sparse_present = bool(sparse_cands)
            dense_best = dense_cands[0] if dense_present else None
            sparse_best = sparse_cands[0] if sparse_present else None
            final_present = rel in final_files
            obligations.append({
                "case_id": case["case_id"],
                "relevant_file": rel,
                "dense_present": dense_present,
                "dense_best_rank": dense_best["rank"] if dense_best else None,
                "dense_best_chunk_id": (
                    dense_best["chunk_id"] if dense_best else None
                ),
                "dense_all_gold_chunk_ids": dense_chunk_ids,
                "sparse_present": sparse_present,
                "sparse_best_rank": sparse_best["rank"] if sparse_best else None,
                "sparse_best_chunk_id": (
                    sparse_best["chunk_id"] if sparse_best else None
                ),
                "sparse_all_gold_chunk_ids": sparse_chunk_ids,
                "shared_chunk_ids": shared_chunk_ids,
                "shared_chunk_count": len(shared_chunk_ids),
                "best_same_chunk": bool(
                    dense_best
                    and sparse_best
                    and dense_best["chunk_id"] == sparse_best["chunk_id"]
                ),
                "final_document_present": final_present,
                "final_gold_chunk_ids": final_chunks_by_file.get(rel, []),
                "classification": classify_obligation(
                    dense_present,
                    sparse_present,
                    dense_best["chunk_id"] if dense_best else None,
                    sparse_best["chunk_id"] if sparse_best else None,
                    len(shared_chunk_ids),
                ),
            })

    def _counts(items):
        counter = Counter(item["classification"] for item in items)
        return {name: counter.get(name, 0) for name in CLASS_ORDER}

    total = len(obligations)
    succeeded = [o for o in obligations if o["final_document_present"]]
    failed = [o for o in obligations if not o["final_document_present"]]
    failed_dual_split = sum(
        1
        for o in failed
        if o["classification"] in ("E_dual_shared_chunk", "F_dual_different_chunk_only")
    )
    failed_f = sum(
        1 for o in failed if o["classification"] == "F_dual_different_chunk_only"
    )
    summary = {
        "total_obligations": total,
        "all": _counts(obligations),
        "succeeded": {
            "count": len(succeeded),
            "distribution": _counts(succeeded),
        },
        "failed": {
            "count": len(failed),
            "distribution": _counts(failed),
            "dual_split_e_plus_f": failed_dual_split,
            "dual_different_chunk_only_f": failed_f,
        },
    }
    return {"obligations": obligations, "summary": summary}


def load_diagnostics(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("retrieval_diagnostics.json 顶层不是 object")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="G2-ANALYSIS-14 只读融合碎片化分析"
    )
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--focus", default="q013,q019,q039,q047,q031,q034,q036")
    args = parser.parse_args(argv)
    payload = load_diagnostics(Path(args.diagnostics))
    result = analyze_payload(payload)
    focus_ids = [c.strip() for c in args.focus.split(",") if c.strip()]
    focus = [
        o for o in result["obligations"] if o["case_id"] in focus_ids
    ]
    print(json.dumps({
        "summary": result["summary"],
        "focus_obligations": focus,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
