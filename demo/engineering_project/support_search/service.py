from support_search.settings import load_result_limit


def search_help(query, retriever):
    return retriever.search(query, limit=load_result_limit())
