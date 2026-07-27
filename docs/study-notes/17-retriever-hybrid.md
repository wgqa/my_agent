# File: core/retriever/hybrid.py

## 作用

实现**混合检索**（稠密向量 + BM25 稀疏检索），文件中包含两个类：`BM25`（从零实现的 BM25 算法）和 `HybridRetriever`（融合稠密和稀疏结果）。

## BM25 原理

BM25 是一种基于词袋模型的排序算法，是 TF-IDF 的进阶版本。核心公式：

```
BM25 = IDF(term) × [TF × (k1+1)] / [TF + k1 × (1 - b + b × docLen/avgDocLen)]
```

- **IDF（逆文档频率）**：`log((N - df + 0.5) / (df + 0.5) + 1)` — 这个词有多"罕见"，越罕见权重越高
- **TF（词频）**：这个词在当前文档中出现多少次
- **k1（饱和度参数）**：控制 TF 的增长速度。k1 越大，TF 增长越慢
- **b（长度归一化参数）**：控制文档长度的影响程度。b=1 完全归一化，b=0 不考虑长度

对比向量检索（稠密）：向量检索找"语义相似"（猫→猫咪），BM25 找"词汇匹配"（猫→猫）。两者互补。

## 完整代码（逐行讲解）

### BM25 类

```python
import math
from collections import Counter
from typing import List, Dict
import numpy as np


class BM25:
    """从零实现的 BM25 算法"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs: List[Counter] = []
        self.idf: Dict[str, float] = {}
        self.doc_lens: List[int] = []
        self.avgdl: float = 0.0
        self.corpus_size: int = 0
```

- `k1=1.5` — 经验值。词频超过 k1+1 ≈ 2.5 次后，分数增长明显放缓。
- `b=0.75` — 经验值。文档比平均长度长 10%，分数受约 7.5% 的惩罚。
- `Counter` — Python 标准库的计数工具，等价于 `{word: count}` 字典。

```python
    def fit(self, corpus: List[str]):
        self.doc_freqs = [Counter(doc.split()) for doc in corpus]
        self.doc_lens = [sum(c.values()) for c in self.doc_freqs]
        self.avgdl = sum(self.doc_lens) / max(len(self.doc_lens), 1)
        self.corpus_size = len(corpus)
```

**训练阶段：** 统计语料中每篇文档的词频（TF），计算文档长度和平均长度。

```python
        df = {}
        for counter in self.doc_freqs:
            for term in counter:
                df[term] = df.get(term, 0) + 1
```

**计算文档频率（DF）：** 每个词出现在多少篇不同的文档中。注意和词频（一篇文档中出现多少次）的区别。

```python
        for term, freq in df.items():
            self.idf[term] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)
```

**BM25 的 IDF 公式：** 和传统 TF-IDF 的 `log(N/df)` 不同，这里加了 `+0.5` 平滑和 `+1.0` 保证 IDF 始终为正。

```python
    def score(self, query: str, doc_idx: int) -> float:
        score = 0.0
        doc_len = self.doc_lens[doc_idx]
        doc_freq = self.doc_freqs[doc_idx]

        for term in query.split():
            if term not in self.idf:
                continue
            tf = doc_freq.get(term, 0)
            score += self.idf[term] * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl))

        return score
```

- 对 query 中的每个词，如果 IDF 表中有记录（在训练语料中出现过），计算该词对当前文档的贡献。
- `tf = doc_freq.get(term, 0)` — 这个词在当前文档中出现次数，没出现就是 0。

---

### HybridRetriever 类

```python
class HybridRetriever(BaseRetriever):
    """稠密向量 + BM25 稀疏检索融合"""

    def __init__(
        self,
        embedding: BaseEmbedding,
        vector_store: BaseVectorStore,
        alpha: float = 0.5,
        top_k_initial: int = 20,
    ):
        self.embedding = embedding
        self.vector_store = vector_store
        self.alpha = alpha                # 向量分数权重
        self.top_k_initial = top_k_initial
        self._bm25 = None
        self._corpus_docs: List[Document] = []
```

- `alpha` — 融合权重。最终分数 = `α × 向量分 + (1-α) × BM25 分`。
- `_bm25 = None` — 延迟初始化，第一次调用 retrieve 时才创建。

```python
    def _ensure_bm25(self, docs: List[Document]):
        if self._bm25 is None:
            self._corpus_docs = docs
            self._bm25 = BM25()
            self._bm25.fit([d.content for d in docs])
```

- 用当前候选文档的文本训练 BM25。BM25 的语料 = 向量检索返回的候选集。

```python
    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        query_emb = self.embedding.embed_query(query)
        vec_results = self.vector_store.search(query_emb, top_k=self.top_k_initial)

        all_docs = vec_results
        self._ensure_bm25(all_docs)

        bm25_scores = [self._bm25.score(query, i) for i in range(len(all_docs))]
```

**融合流程：**
1. 向量检索 → 取 top_k_initial 个候选
2. 用候选文档文本训练 BM25（第一次）或复用已有 BM25
3. 对每个候选计算 BM25 分数

```python
        vec_scores_norm = self._normalize([1.0 - d.metadata.get("distance", 0.0) for d in vec_results])
        bm25_scores_norm = self._normalize(bm25_scores)
```

- 向量分数：Chroma 的 distance 是"越小越相关"，所以用 `1.0 - distance` 转换成"越大越相关"。
- 归一化：min-max 归一化到 [0,1]，使两个不同量级的分数可比。

```python
        fused = [
            (self.alpha * vs + (1 - self.alpha) * bs, i)
            for i, (vs, bs) in enumerate(zip(vec_scores_norm, bm25_scores_norm))
        ]
        fused.sort(key=lambda x: x[0], reverse=True)

        return [all_docs[i] for _, i in fused[:top_k]]
```

- 加权融合 → 排序 → 取 top_k。
- `enumerate(zip(vec_norm, bm25_norm))` — `zip` 把两个列表配对，`enumerate` 加上索引。

```python
    def _normalize(self, scores: List[float]) -> List[float]:
        if not scores:
            return scores
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return [0.5] * len(scores)
        return [(s - min_s) / (max_s - min_s) for s in scores]
```

- Min-Max 归一化：`(x-min)/(max-min)`。如果所有分数相同（比如全 0），返回 0.5 作为中性值。

## 重点总结

1. **BM25 从零实现：** 包括 IDF 计算、词频饱和度（k1）、长度归一化（b），约 40 行。
2. **融合策略：** 先向量检索粗筛 → BM25 重打分 → 归一化 → α 加权融合。不是简单的分数相加。
3. **延迟初始化 BM25：** 只在需要时才训练 BM25，语料 = 当前候选集。

## 大厂面试可能问

- **Q: BM25 和 TF-IDF 的核心区别？** — ①BM25 的 IDF 有平滑项（+0.5）；②BM25 有词频饱和（k1），TF 不会无限增长；③BM25 有长度归一化（b），长文档不会天然占优。

- **Q: k1 和 b 参数怎么调？** — k1 越大，TF 增长越慢。对长篇文档（每个词可能出现很多次）用较大的 k1。b 越大，长度惩罚越严格。对长度差异大的语料用较大的 b。

- **Q: alpha 参数的影响？** — α 越大，混合结果越偏向向量检索。如果数据是正式文档（词汇匹配好），可以降低 α 增加 BM25 权重。如果数据是口语化/同义表达多的内容，提高 α 增加语义权重。

- **Q: HybridRetriever 是先向量检索再 BM25，为什么不是同时？** — 向量检索是"召回阶段"，BM25 是"精排阶段"。先向量检索快速召回候选（K=20），再用 BM25 做细粒度排序（复杂度 O(K×|query|) 而不是 O(N×|query|)）。

- **Q: 归一化为什么要用 Min-Max 而不是 Z-score？** — Min-Max 把分数映射到 [0,1]，物理意义明确（0=最低分，1=最高分），适合两个不同量级的分数加权的场景。Z-score 会有负值，加权后解释性差。

- **Q: Python 的 `zip` 函数怎么用？** — `zip([a,b,c], [1,2,3])` 返回 `[(a,1), (b,2), (c,3)]`。用于并行遍历多个列表。



每次 add/remove 全量重算 IDF，文档数量上千后性能显著下降；成熟方案一般增量更新 IDF；
无持久化，程序关闭索引丢失；
没有停用词过滤（“的 / 和” 这类高频虚词会干扰打分，工程上建议加上）；
不支持批量添加文档。

仅 BM25 命中的文档 content=""
传给 LLM 没有文本，相当于无效上下文。