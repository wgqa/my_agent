from support_search.settings import load_result_limit


def search_help(query, retriever):
    limit = load_result_limit()
    return retriever.search(query, limit=limit)
