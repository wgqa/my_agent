"""G2-ABL-15：Dense vs BM25 vs Hybrid offline channel ablation 纯数据测试"""

import json

import pytest

from scripts.analyze_channel_ablation import (
    analyze_payload,
    document_ranking,
    load_diagnostics,
)


def _c(rank, chunk_id, relative_path):
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "document_id": relative_path,
        "relative_path": relative_path,
        "scores": {},
    }


def _case(case_id, relevant, dense, sparse, final):
    return {
        "case_id": case_id,
        "query": f"query {case_id}",
        "relevant_files": list(relevant),
        "dense_candidates": dense,
        "sparse_candidates": sparse,
        "final_hits": final,
    }


def _fixture_payload():
    return {
        "schema_version": 1,
        "diagnostic_id": "diag-1",
        "baseline_retrieval_run_id": "run-1",
        "cases": [
            _case("c_rank", ["a.md", "b.md", "c.md"], [
                _c(1, "A1", "a.md"),
                _c(2, "A2", "a.md"),
                _c(3, "A3", "a.md"),
                _c(4, "B1", "b.md"),
                _c(5, "B2", "b.md"),
                _c(6, "C1", "c.md"),
            ], [], []),
            _case("c_hit", ["a.md"], [
                _c(1, "A1", "a.md"),
            ], [
                _c(2, "A2", "a.md"),
            ], [
                _c(1, "A1", "a.md"),
            ]),
            _case("c_regression_dense", ["a.md"], [
                _c(1, "X1", "x.md"),
                _c(2, "A1", "a.md"),
            ], [], [
                _c(1, "X1", "x.md"),
            ]),
            _case("c_rescue_both", ["a.md"], [
                _c(1, "X1", "x.md"),
            ], [
                _c(1, "Y1", "y.md"),
            ], [
                _c(1, "A1", "a.md"),
            ]),
            _case("c_recall_regression", ["a.md", "b.md"], [
                _c(1, "A1", "a.md"),
                _c(2, "B1", "b.md"),
            ], [
                _c(1, "B1", "b.md"),
            ], [
                _c(1, "A1", "a.md"),
            ]),
            _case("c_all_fail", ["a.md"], [
                _c(1, "X1", "x.md"),
            ], [
                _c(1, "Y1", "y.md"),
            ], [
                _c(1, "Z1", "z.md"),
            ]),
        ],
    }


def test_document_ranking_first_top5_chunks_then_dedup():
    """先取前 5 个 Chunk 再去重；不得先按文档去重再取 Top-5 文档。"""
    candidates = [
        _c(1, "A1", "a.md"),
        _c(2, "A2", "a.md"),
        _c(3, "A3", "a.md"),
        _c(4, "B1", "b.md"),
        _c(5, "B2", "b.md"),
        _c(6, "C1", "c.md"),
    ]
    ranking = document_ranking(candidates)
    assert ranking == ["a.md", "b.md"]
    assert "c.md" not in ranking, "前 5 Chunk 之外的文件不得进入 ranking"


def test_dense_and_sparse_top5_semantics():
    payload = _fixture_payload()
    cases = {c["case_id"]: c for c in analyze_payload(payload)["cases"]}
    assert cases["c_rank"]["dense"]["retrieved_files"] == ["a.md", "b.md"]
    assert cases["c_rank"]["sparse"]["retrieved_files"] == []


def test_hit_recall_mrr_ndcg_values():
    payload = _fixture_payload()
    cases = {c["case_id"]: c for c in analyze_payload(payload)["cases"]}
    hit = cases["c_hit"]
    assert hit["dense"]["hit_at_k"] == 1.0
    assert hit["dense"]["recall_at_k"] == 1.0
    assert hit["dense"]["mrr"] == 1.0
    assert hit["dense"]["ndcg_at_k"] == 1.0
    regression = cases["c_regression_dense"]
    assert regression["dense"]["mrr"] == 0.5
    assert regression["dense"]["ndcg_at_k"] < 1.0


def test_multi_file_recall():
    payload = _fixture_payload()
    cases = {c["case_id"]: c for c in analyze_payload(payload)["cases"]}
    multi = cases["c_recall_regression"]
    assert multi["dense"]["recall_at_k"] == 1.0
    assert multi["hybrid"]["recall_at_k"] == 0.5
    assert multi["recall_regression"] is True


def test_hybrid_rescue_classification():
    payload = _fixture_payload()
    cases = {c["case_id"]: c for c in analyze_payload(payload)["cases"]}
    assert cases["c_rescue_both"]["outcome"] == "hybrid_rescue"
    assert cases["c_rescue_both"]["outcome_subtype"] == "rescues_both"


def test_fusion_regression_classification():
    payload = _fixture_payload()
    cases = {c["case_id"]: c for c in analyze_payload(payload)["cases"]}
    assert cases["c_regression_dense"]["outcome"] == "fusion_regression"
    assert cases["c_regression_dense"]["outcome_subtype"] == "dense"


def test_all_fail_and_all_success():
    payload = _fixture_payload()
    cases = {c["case_id"]: c for c in analyze_payload(payload)["cases"]}
    assert cases["c_all_fail"]["outcome"] == "all_fail"
    assert cases["c_hit"]["outcome"] == "all_success"


def test_deterministic_output():
    first = analyze_payload(_fixture_payload())
    second = analyze_payload(json.loads(json.dumps(_fixture_payload())))
    assert first["summary"] == second["summary"]
    assert first["cases"] == second["cases"]


def test_load_rejects_non_object(tmp_path):
    path = tmp_path / "diag.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="顶层不是 object"):
        load_diagnostics(path)
