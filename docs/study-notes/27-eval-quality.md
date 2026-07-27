# File: evaluation/quality.py

## 作用

对分块结果进行质量控制检查，衡量分块质量的稳定性和一致性。这是工程化 RAG 系统中容易被忽略但很重要的一环。

## 完整代码（逐行讲解）

```python
from typing import List
import numpy as np

from core.loader.base import Document


def check_chunk_quality(chunks: List[Document]) -> dict:
    """质控检查：分块一致性、空块、长度分布"""
    lengths = [len(c.content) for c in chunks]
    return {
        "length_cv": float(np.std(lengths) / max(np.mean(lengths), 1)),
        "empty_chunks": sum(1 for c in chunks if not c.content.strip()),
        "min_len": min(lengths) if lengths else 0,
        "max_len": max(lengths) if lengths else 0,
        "total_chunks": len(chunks),
    }
```

---

**核心指标：`length_cv`（变异系数，Coefficient of Variation）**

变异系数 = 标准差 / 平均值。它衡量数据的**相对离散程度**。

- **公式：** `CV = σ / μ`
- **意义：** 与标准差的区别是 CV 消除了量纲影响。长度 100±20（CV=0.2）和长度 1000±200（CV=0.2）的"不一致程度"是一样的。

**各 chunker 的预期 CV：**
- **FixedSizeChunker：** CV ≈ 0.05–0.15（非常稳定，只有最后一个 chunk 可能偏短）
- **RecursiveChunker：** CV ≈ 0.1–0.3（比较稳定，按自然边界分割）
- **SemanticChunker：** CV ≈ 0.3–0.8+（不稳定，按语义边界分组，组大小差异大）

---

**`empty_chunks`（空块检测）：**

- `sum(1 for c in chunks if not c.content.strip())` — 统计内容为空（全是空白字符）的 chunk 数量。
- `.strip()` 去除首尾空格，如果结果是空字符串则视为空块。
- 正常情况应该为 0。如果有空块，说明分块逻辑有 bug。

---

**`min_len / max_len`（长度极值）：**

- `min(lengths) if lengths else 0` — 如果列表非空返回最小值，否则返回 0（边界处理）。
- 用于快速诊断：如果 min_len = 0 或 max_len 是 chunk_size 的几十倍，说明分块有问题。

---

**`total_chunks`（总块数）：**

- 简单计数，用于估算后续的 token 消耗和存储成本。

## 重点总结

1. **变异系数是最重要的质控指标：** 它量化了分块的一致性，直接影响下游检索效果。
2. **空块检测是质量底线：** 不应该有任何空块，如果出现了说明分块策略有边界情况未处理。
3. **质控是工程化的标志：** 只有跑通代码是不够的，需要能自动检测分块质量。

## 大厂面试可能问

- **Q: 为什么分块一致性很重要？** — ①chunk 太短缺乏上下文，太长引入噪音；②不一致的分块导致 embedding 质量不稳定；③影响向量检索的 recall（短文本容易被长文本"淹没"）。

- **Q: Token 利用率和 chunk_cv 的关系？** — 如果 chunk 长短不均（CV 大），表示很多 chunk 没有充分利用上下文窗口，token 利用率低。理想情况是所有 chunk 接近 chunk_size。

- **Q: 如何判断一个 chunker 的好坏？** — 结合三个维度：①检索质量（Hit Rate/MRR/NDCG）；②分块质量（CV、空块率）；③工程成本（延迟、存储）。
