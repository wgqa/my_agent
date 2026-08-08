"""G2-ANALYSIS-14：Chunk-Level Fusion Fragmentation 只读分析单元测试"""

import json

from scripts.analyze_fusion_fragmentation import (
    analyze_payload,
    classify_obligation,
    load_diagnostics,
)


def _candidate(rank, chunk_id, relative_path):
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "document_id": relative_path,
        "relative_path": relative_path,
        "scores": {},
    }


def _case(case_id, relevant_files, dense, sparse, final):
    return {
        "case_id": case_id,
        "query": f"query {case_id}",
        "relevant_files": relevant_files,
        "dense_candidates": dense,
        "sparse_candidates": sparse,
        "final_hits": final,
    }


def _fixture_payload():
    cases = [
        # A: 双通道均无
        _case("cA", ["a.md"], [], [], []),
        # B: 仅 Dense
        _case("cB", ["b.md"], [_candidate(2, "B1", "b.md")], [], []),
        # C: 仅 Sparse
        _case("cC", ["c.md"], [], [_candidate(1, "C1", "c.md")], []),
        # D: 双通道、最佳 chunk 相同，final 命中
        _case("cD", ["d.md"], [
            _candidate(1, "D1", "d.md"),
            _candidate(3, "D2", "d.md"),
        ], [
            _candidate(2, "D1", "d.md"),
        ], [_candidate(1, "D1", "d.md")]),
        # E: 双通道、有共享 chunk 但最佳不同，final 命中
        _case("cE", ["e.md"], [
            _candidate(1, "E1", "e.md"),
            _candidate(4, "E2", "e.md"),
        ], [
            _candidate(2, "E2", "e.md"),
            _candidate(5, "E3", "e.md"),
        ], [_candidate(1, "E1", "e.md")]),
        # F: 双通道、无共享 chunk，final 缺失（q039 模式）
        _case("cF", ["f.md"], [
            _candidate(1, "F1", "f.md"),
        ], [
            _candidate(2, "F2", "f.md"),
        ], []),
    ]
    return {
        "schema_version": 1,
        "diagnostic_id": "diag",
        "cases": cases,
    }


def test_classification_functions():
    assert classify_obligation(False, False, None, None, 0) == (
        "A_no_channel_recall"
    )
    assert classify_obligation(True, False, "A", None, 0) == "B_dense_only"
    assert classify_obligation(False, True, None, "B", 0) == "C_sparse_only"
    assert classify_obligation(True, True, "X", "X", 1) == (
        "D_dual_same_best_chunk"
    )
    assert classify_obligation(True, True, "X", "Y", 1) == (
        "E_dual_shared_chunk"
    )
    assert classify_obligation(True, True, "X", "Y", 0) == (
        "F_dual_different_chunk_only"
    )


def test_analyze_payload_distribution():
    result = analyze_payload(_fixture_payload())
    summary = result["summary"]
    assert summary["total_obligations"] == 6
    assert summary["all"] == {
        "A_no_channel_recall": 1,
        "B_dense_only": 1,
        "C_sparse_only": 1,
        "D_dual_same_best_chunk": 1,
        "E_dual_shared_chunk": 1,
        "F_dual_different_chunk_only": 1,
    }
    assert summary["succeeded"]["count"] == 2
    assert summary["failed"]["count"] == 4
    assert summary["failed"]["dual_different_chunk_only_f"] == 1


def test_f_obligation_fields():
    result = analyze_payload(_fixture_payload())
    f = next(
        o for o in result["obligations"] if o["classification"] == "F_dual_different_chunk_only"
    )
    assert f["relevant_file"] == "f.md"
    assert f["dense_best_chunk_id"] == "F1"
    assert f["sparse_best_chunk_id"] == "F2"
    assert f["best_same_chunk"] is False
    assert f["shared_chunk_count"] == 0
    assert f["shared_chunk_ids"] == []
    assert f["final_document_present"] is False


def test_analyze_is_deterministic():
    payload = _fixture_payload()
    first = analyze_payload(payload)
    second = analyze_payload(json.loads(json.dumps(payload)))
    assert first["obligations"] == second["obligations"]
    assert first["summary"] == second["summary"]


def test_load_diagnostics_rejects_non_object(tmp_path):
    path = tmp_path / "diag.json"
    path.write_text("[]", encoding="utf-8")
    try:
        load_diagnostics(path)
        assert False, "顶层非 object 应拒绝"
    except ValueError:
        pass
