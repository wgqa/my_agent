from typing import List
import numpy as np

from core.loader.base import Document
from core.retriever.base import BaseRetriever
from core.embeddings.base import BaseEmbedding
from core.vector_store.base import BaseVectorStore


class MMRRetriever(BaseRetriever):

    def __init__(
        self,
        embedding: BaseEmbedding,
        vector_store: BaseVectorStore,
        lambda_param: float = 0.5,
        top_k_initial: int = 20,
    ):
        self.embedding = embedding
        self.vector_store = vector_store
        self.lambda_param = lambda_param
        self.top_k_initial = top_k_initial

    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        # 先多取一些候选
        query_vec = self.embedding.embed_query(query)
        candidates = self.vector_store.search(query_vec, top_k=self.top_k_initial)
        if len(candidates) <= top_k:
            return candidates

        # 计算所有候选向量的 embedding
        texts = [c.content for c in candidates]
        candidate_embs = self.embedding.embed(texts)
        query_emb = query_vec

        selected = []
        mmr_scores_selected = {}
        remaining = list(range(len(candidates)))

        while len(selected) < top_k and remaining:
            mmr_scores = []
            for i in remaining:
                sim_to_query = self._cosine_sim(query_emb, candidate_embs[i])
                sim_to_selected = max(
                    [self._cosine_sim(candidate_embs[i], candidate_embs[j]) for j in selected],
                    default=0.0,
                )
                mmr = self.lambda_param * sim_to_query - (1 - self.lambda_param) * sim_to_selected
                mmr_scores.append(mmr)

            best_idx = remaining.pop(np.argmax(mmr_scores))
            selected.append(best_idx)
            mmr_scores_selected[best_idx] = max(mmr_scores)

        result = []
        for i in selected:
            doc = candidates[i]
            doc.metadata["mmr_score"] = round(mmr_scores_selected[i], 6)
            result.append(doc)

        return result

    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        a_arr = np.array(a)
        b_arr = np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
