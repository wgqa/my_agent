from support_search.retrieval import rank_documents


def test_rank_documents_returns_only_matching_results():
    assert rank_documents("account", ["account help", "billing"], 4) == ["account help"]
