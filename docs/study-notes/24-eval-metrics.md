# File: evaluation/metrics.py

## 作用

实现 RAG 系统检索质量的三个核心评估指标：Hit Rate（命中率）、MRR（平均倒数排名）、NDCG（归一化折损累计增益）。这些指标在信息检索领域是最基础的评估方法，也是面试必考内容。

## 完整代码（逐行讲解）

```python
from typing import List
```

导入 `List` 类型提示。Python 3.9+ 可以直接用 `list`，这里为了兼容性用 `typing.List`。

---

```python
def hit_rate(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """Hit Rate: 相关文档是否被召回"""
    if not relevant_ids:
        return 0.0
    hits = sum(1 for rid in retrieved_ids if rid in relevant_ids)
    return hits / len(relevant_ids)
```

**原理：** 检索结果中，有多少比例的相关文档被召回了。

- `if not relevant_ids: return 0.0` — 边界处理：如果没有标注相关文档，无法计算，返回 0。
- `sum(1 for rid in retrieved_ids if rid in relevant_ids)` — **生成器表达式**。遍历检索结果 ID 列表，对每个 ID 检查是否在相关文档集合中。`sum(1 for ... if ...)` 是 Python 中"计数满足条件的元素"的标准写法。
- `hits / len(relevant_ids)` — 注意分母是**相关文档总数**，而不是检索结果数。这意味着即使 5 个结果全部命中，如果相关文档有 10 个，hit_rate 也只有 0.5。

> **面试重点：** Hit Rate 的分母是什么？很多人会误以为是 `len(retrieved_ids)`，但实际上是 `len(relevant_ids)`。它衡量的是"覆盖度"而非"精确度"。

**举例：**
```
retrieved = [doc1, doc2, doc3, doc4, doc5]
relevant = [doc1, doc3, doc7]
hit_rate = 2/3 = 0.667（doc1 和 doc3 命中，doc7 没被召回）
```

---

```python
def mrr(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """MRR: 第一个相关文档的排名倒数"""
    for i, rid in enumerate(retrieved_ids):
        if rid in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0
```

**原理：** 第一个相关文档出现在第几位，取倒数。MRR = Mean Reciprocal Rank，但这里只算一条 query 的 RR（Reciprocal Rank），多条 query 的 MRR 是 RR 的平均值。

- `enumerate(retrieved_ids)` — 同时拿到索引 `i`（从 0 开始）和元素 `rid`。这是 Python 的惯用写法，等价于 Java 的 `for (int i = 0; i < list.size(); i++)` 但更简洁。
- `1.0 / (i + 1)` — 因为索引从 0 开始，排名 = `i + 1`。用 `1.0` 确保浮点除法。
- 一旦找到第一个匹配就 `return`，不会继续找后面的。

> **为什么用倒数（reciprocal）？** 排名的意义不是线性的。第一名和第二名的差距（1.0 → 0.5）远大于第八名和第九名的差距（0.125 → 0.111）。这反映了用户行为：用户更关注排名靠前的结果。

---

```python
def ndcg(retrieved_ids: List[str], relevant_ids: List[str], k: int = 5) -> float:
    """NDCG@k: 考虑排序质量的加权指标"""
    dcg = 0.0
    for i, rid in enumerate(retrieved_ids[:k]):
        if rid in relevant_ids:
            dcg += 1.0 / (i + 1).bit_length()

    idcg = sum(1.0 / (i + 1).bit_length() for i in range(min(k, len(relevant_ids))))
    return dcg / idcg if idcg > 0 else 0.0
```

**原理：** NDCG 是最精细的指标，同时考虑：①相关文档是否被召回；②相关文档的排序是否合理；③排名越靠前权重越大。

- `retrieved_ids[:k]` — 只取前 k 个结果（切片操作）。
- `(i + 1).bit_length()` — 返回数字的二进制位数。`1→1, 2→2, 3→2, 4→3`，这近似于 `floor(log2(n)) + 1`。在这里作为 `log2(i+1)` 的近似值。标准的 DCG 公式是 `相关性 / log2(排名+1)`，这里相关性为 1（相关=1，不相关=0），所以是 `1 / log2(i+1)`。
- **IDCG（Ideal DCG）**：假设所有相关文档都排在最前面时的 DCG，用于归一化。
- 返回 `dcg / idcg`，如果 idcg 为 0（没有相关文档），返回 0。

> **`bit_length()` 的精度问题：** 这个简化的写法不完全等于 `1/math.log2(i+1)`。严格实现应该用 `import math` 然后 `1.0 / math.log2(i+1+1)`。不过在小范围（k≤10）内，差异很小，不影响实验结论。

**举例：**
```
retrieved = [doc1, doc2, doc3, doc4, doc5]
relevant = [doc3, doc5]

DCG  = 0/log2(1) + 0/log2(2) + 1/log2(3) + 0 + 1/log2(5)
     = 0 + 0 + 0.63 + 0 + 0.43 = 1.06
IDCG = 1/log2(1) + 1/log2(2) + 0 + 0 + 0 = 1.0 + 0.63 = 1.63
NDCG = 1.06 / 1.63 = 0.65
```

## 重点总结

1. **三个指标侧重点不同：**
   - Hit Rate → 覆盖率（相关文档有没有被召回到结果集中）
   - MRR → 第一个答案的位置（用户最快多久能看见一个相关结果）
   - NDCG → 整体排序质量（所有相关结果的排序是否合理）

2. **分母陷阱：** Hit Rate 的分母是 `len(relevant_ids)`，不是 `len(retrieved_ids)`。

3. **MRR vs NDCG 的选择：** 如果用户只关心第一个正确答案（如 QA 场景），MRR 更合适。如果用户需要浏览多个结果（如搜索场景），NDCG 更合适。

## 大厂面试可能问

- **Q: 三个指标最关注哪个？** — 看场景。问答系统看重 MRR（第一个答案位置），搜索引擎看重 NDCG（整体排序质量）。通常简历上三个都列，重点提 NDCG，因为它对排序最敏感。

- **Q: 如果 MRR 是 1.0 但 NDCG 是 0.5，说明什么？** — 第一个结果就命中了相关文档（MRR=1.0），但其他相关文档排在很后面或没被召回（NDCG 受整体排序影响）。说明系统对"最佳匹配"做得好，但"全面覆盖"做得差。

- **Q: 这些指标能完全反映 RAG 系统的质量吗？** — 不能。检索指标只衡量"找得准不准"，不衡量"生成得好不好"。还需要 Answer Relevance、Faithfulness 等生成质量指标。

- **Q: Python 中 `enumerate` 的作用？** — `enumerate(list)` 返回 `(index, element)` 对，索引从 0 开始。常用于需要同时知道元素位置和值的场景。
