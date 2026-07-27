# File: core/retriever/mmr.py

## 作用

实现 **MMR（Maximum Marginal Relevance）** 检索，在相关性和多样性之间寻找平衡。避免 top_k 个结果全是同一个话题的重复内容。

## 核心原理

MMR 公式：（来源：Carbonell & Goldstein, 1998）

```
MMR = λ × sim(query, doc) - (1-λ) × max sim(selected_docs, doc)
```

- 第一项：候选文档和 query 的相关性（越大越好）
- 第二项：候选文档和已选中文档的最大相似度（越大表示越冗余）
- λ：平衡参数，λ=1 退化为纯相关排序（=SimpleRetriever），λ=0 只追求多样性
- **贪心算法**：每轮从候选中选 MMR 最高的文档加入结果集，重复直到选够 top_k

## 完整代码（逐行讲解）

```python
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
```

- `lambda_param: float = 0.5` — λ 默认 0.5，相关性和多样性权重相同。
- `top_k_initial: int = 20` — 先从向量库取 20 个候选，再用 MMR 从这 20 个里选出最终的 top_k。原因是 MMR 需要两两计算相似度（O(n²)），不能对整个库做。

```python
    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        query_vec = self.embedding.embed_query(query)
        candidates = self.vector_store.search(query_vec, top_k=self.top_k_initial)
        if len(candidates) <= top_k:
            return candidates
```

- 初筛 top_k_initial 个候选。如果候选本身就不够 top_k，直接返回。

```python
        texts = [c.content for c in candidates]
        candidate_embs = self.embedding.embed(texts)
        query_emb = self.embedding.embed_query(query)
```

- 计算所有候选的 embedding。注意这里用 `embed`（文档编码）而不是 `embed_query`，因为 BGE 对文档和 query 使用不同的 instruction。

```python
        selected = []
        remaining = list(range(len(candidates)))
```

- `selected` 和 `remaining` 维护候选索引。用索引操作比直接用 Document 对象更高效。

```python
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
```

- **核心循环：** 每轮对每个剩余候选计算 MMR 分数。
- `sim_to_selected = max(...)` — 取候选和"所有已选文档"的最大相似度作为冗余度。这是 MMR 的标准实现。
- `default=0.0` — 当 selected 为空时（第一轮），max() 的默认值。

```python
            best_idx = remaining.pop(np.argmax(mmr_scores))
            selected.append(best_idx)

        return [candidates[i] for i in selected]
```

- `np.argmax(mmr_scores)` — MMR 分数最高的候选在列表中的位置。
- `remaining.pop(...)` — 从 remaining 中移除并返回该索引。这里用的是 `list.pop(index)` 而不是默认的 `list.pop()`。

```python
    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        a_arr = np.array(a)
        b_arr = np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
```

- 余弦相似度。`+1e-10` 防止除零。

## 重点总结

1. **贪心选择：** 每轮只选当前最优，不能保证全局最优。但实际效果已经很好了。
2. **λ 调参：** 需要根据场景调整。精确问答（高 λ），多样化推荐（低 λ）。
3. **性能开销：** 多了一次 `embed` 调用（编码所有候选），比 Simple 慢但比 Hybrid 快。

## 大厂面试可能问

- **Q: MMR 的时间复杂度？** — O(k × n)，其中 k=top_k, n=top_k_initial。每轮需要遍历所有剩余候选（n 个），做 k 轮。但 n=20, k=5 时几乎没有性能问题。

- **Q: MMR 和简单去重（如 set）的区别？** — 简单去重只移除完全相同的文档。MMR 能识别"语义上相似但字面上不同"的冗余文档，更精细。

- **Q: 什么场景下 MMR 效果明显好于 Simple？** — 当文档集合中有很多相似的文档时（比如多篇文章都讲 Transformer），MMR 能确保结果覆盖不同方面。而 Simple 可能返回 10 篇都是讲 Transformer 的。

- **Q: `np.argmax` 和 Python 的 `max()` 有什么区别？** — `max(list)` 返回最大值本身。`np.argmax(list)` 返回最大值的索引。这里我们需要索引来操作 `remaining` 列表，所以用 argmax。
