from evaluation.report import generate_report


def test_generate_report_empty():
    assert generate_report([]) == "No results."


def test_generate_report_basic():
    results = [
        {"chunk": "fixed", "hit_at_k": 0.8, "mrr": 0.6, "recall_at_k": 0.7},
        {"chunk": "recursive", "hit_at_k": 0.9, "mrr": 0.7, "recall_at_k": 0.8},
    ]
    report = generate_report(results)
    assert "评估对比报告" in report
    assert "0.900" in report
    assert "recursive" in report


def test_report_sorts_by_hit_at_k_and_shows_best():
    """报告按 hit_at_k 排序（B 在前），最佳配置显示 0.8 而非默认 0"""
    results = [
        {"chunk": "A", "hit_at_k": 0.5, "mrr": 0.3, "ndcg": 0.2},
        {"chunk": "B", "hit_at_k": 0.8, "mrr": 0.6, "ndcg": 0.5},
    ]
    report = generate_report(results)
    assert report.index("B") < report.index("A"), "B 必须排在 A 前面"
    assert "Hit@K: 0.800" in report, "最佳配置必须显示 0.8"
    assert "Hit Rate: 0.000" not in report and "Hit@K: 0.000" not in report
