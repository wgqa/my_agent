from evaluation.metrics import hit_at_k, recall_at_k, mrr, ndcg_at_k


def test_hit_at_k_all_relevant():
    assert hit_at_k(["a", "b", "c"], ["a", "b"]) == 1.0


def test_hit_at_k_partial():
    assert hit_at_k(["a", "b", "c"], ["a", "d"]) == 1.0


def test_hit_at_k_none():
    assert hit_at_k(["a", "b"], ["c"]) == 0.0


def test_hit_at_k_empty_relevant():
    assert hit_at_k(["a", "b"], []) == 0.0


def test_recall_at_k_all():
    assert recall_at_k(["a", "b", "c"], ["a", "b"]) == 1.0


def test_recall_at_k_partial():
    assert recall_at_k(["a", "b", "c"], ["a", "d"]) == 0.5


def test_recall_at_k_none():
    assert recall_at_k(["a", "b"], ["c"]) == 0.0


def test_mrr_first():
    assert mrr(["a", "b", "c"], ["a"]) == 1.0


def test_mrr_second():
    assert mrr(["a", "b", "c"], ["b"]) == 0.5


def test_mrr_not_found():
    assert mrr(["a", "b"], ["c"]) == 0.0


def test_ndcg_perfect():
    assert ndcg_at_k(["a", "b"], ["a", "b"], k=5) == 1.0


def test_ndcg_worst():
    assert ndcg_at_k(["c", "d"], ["a", "b"], k=5) == 0.0
