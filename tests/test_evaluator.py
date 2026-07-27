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
