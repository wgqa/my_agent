from support_search.service import search_help
from support_search.settings import load_result_limit


class RecordingRetriever:
    def search(self, query, *, limit):
        return {"query": query, "limit": limit}


def test_search_help_passes_default_limit(monkeypatch):
    monkeypatch.delenv("SUPPORT_RESULT_LIMIT", raising=False)
    result = search_help("account", RecordingRetriever())
    assert result == {"query": "account", "limit": 4}


def test_search_help_passes_environment_limit(monkeypatch):
    monkeypatch.setenv("SUPPORT_RESULT_LIMIT", "9")
    result = search_help("account", RecordingRetriever())
    assert result["limit"] == 9


def test_invalid_result_limit_is_rejected(monkeypatch):
    monkeypatch.setenv("SUPPORT_RESULT_LIMIT", "21")
    import pytest
    with pytest.raises(ValueError, match="between 1 and 20"):
        load_result_limit()
