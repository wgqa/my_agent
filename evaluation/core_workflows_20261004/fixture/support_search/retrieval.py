def rank_documents(query, documents, limit):
    terms = set(query.lower().split())
    scored = [(sum(word in text.lower().split() for word in terms), text)
              for text in documents]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [text for score, text in scored if score > 0][:limit]
