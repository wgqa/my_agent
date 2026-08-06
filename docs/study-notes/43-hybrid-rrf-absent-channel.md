# Gate 1：Hybrid RRF 缺席通道语义——未命中通道贡献必须为 0

> 2026-08-05 — 256 → 260 passed
> RRF 的语义是"对每个命中的排名列表求和"：文档在某个通道缺席时，
> 该通道的贡献就是 0，而不是一个"虚拟的末尾排名"。

## Bug：给缺席通道虚构排名

```python
dense_rank = dense_rank_map.get(doc_id, self.dense_candidate_k + 1)
sparse_rank = sparse_rank_map.get(doc_id, self.sparse_candidate_k + 1)
rrf = 1.0 / (self.rrf_k + dense_rank) + 1.0 / (self.rrf_k + sparse_rank)
```

Dense-only 文档（如 dense rank1）实际得分：

```text
1/(60+1) + 1/(60+candidate_k+1)   # 第二个正分来自缺席的 Sparse 通道
```

这违反 RRF 语义，且会改变最终排序：单通道文档凭空获得另一通道的
正分，双通道融合的优势被稀释。

## 修复：只从实际命中的通道累加

```python
rrf = 0.0
if doc_id in dense_rank_map:
    rrf += 1.0 / (self.rrf_k + dense_rank_map[doc_id])
if doc_id in sparse_rank_map:
    rrf += 1.0 / (self.rrf_k + sparse_rank_map[doc_id])
```

元数据 `dense_rank`/`sparse_rank` 仍用 `map.get(doc_id)`（缺席自然
为 `None`）——元数据与分数分开处理，一个诚实显示缺席，一个不因此
得分。

## 测试：构造排序反转案例的方法

要求"旧算法和正确算法排序不同的案例"。**平局是主要陷阱**：
- 单通道 rank1 文档在正确算法下都是 `1/(rrf_k+1)`（同分）；
- 集合迭代顺序无序，平局会让断言不可测。

所以案例要让 A、B 都是单通道但**排名不同**，且旧算法下 A 的虚拟
加成 > B 的虚拟加成：

```text
dense_candidate_k=2（虚拟 dense rank=3），sparse_candidate_k=9（虚拟 sparse rank=10）
B: dense rank1（dense-only），A: sparse rank2（sparse-only）
旧：A = 1/63 + 1/62 = 0.032002 > B = 1/61 + 1/70 = 0.030679 → A 在前
新：B = 1/61 = 0.016393 > A = 1/62 = 0.016129 → B 在前（反转 ✓）
```

关键规律：**虚拟排名由 candidate_k 决定，与文档实际排名无关**——
所以要反转排序，让"虚拟加成大"的文档（其缺席通道 candidate_k 小）
在正确算法下反而因真实排名靠后而落后。

测试桩设计（不依赖真实 BM25 打分）：

```python
class _FakeBM25Hits:
    def search(self, query, top_k=10): return self._hits[:top_k]   # 预设 [(doc_id, score)]
    def get_text(self, doc_id): return f"text {doc_id}"            # sparse-only 补全

class _DenseHitsVectorStore:
    def search(self, query_emb, top_k=5, where=None): return self._hits[:top_k]
```

Dense/Sparse 通道完全可控，测试只验证 RRF 语义本身。

## 教训

1. **默认值陷阱**：`.get(key, default)` 的 default 若参与计算，就变成
   "伪造数据"——这里应该用 `if key in map` 分支，而不是带默认值的
   取值再无条件使用。
2. **算法语义要先写进测试**：分数字级断言（`rrf == 1/61`）比只断言
   排序更严格——排序可能碰巧一致，分数不会。
3. **排序反转案例要刻意设计**：找到虚拟加成差异与真实排名差异
   方向相反的构造，测试才能真正区分新旧算法（本项目 Gate 1 的
   验收核心）。
