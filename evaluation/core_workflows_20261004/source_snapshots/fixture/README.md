# Support Search

The default result limit is 4. Set SUPPORT_RESULT_LIMIT to override it.
Allowed result limits are integers from 1 through 20, inclusive.
search_help forwards the configured limit to the retriever.

The retriever counts matching query words, removes zero-score documents,
and returns at most limit results. It does not implement BM25 or embeddings.

Suggested local test command: python -m pytest tests/test_service.py
