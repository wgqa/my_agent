# RRF 平局、Python Hash 随机化与可复现实验（G2-DIAG-13-R1）

> 2026-08-08 — 574 → 590 passed
> 一个"排序结果看起来正确"的算法，可能因为一行依赖无序集合的代码
> 而变得跨进程不可复现。修复它的不是加随机种子，而是把平局规则
> 写进算法契约，再让契约本身进入实验身份。

## 1. RRF 是什么

Hybrid 检索有两路候选：

```text
Dense 通道：向量相似度检索，输出自己的排名 dense_rank
Sparse 通道：BM25 词法检索，输出自己的排名 sparse_rank
```

RRF（Reciprocal Rank Fusion）只使用"排名"而不使用原始分数：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

其中 k 是平滑常数（本项目 rrf_k=60）。一个文档 d：

- 只在 Dense 第 r 名：RRF(d) = 1 / (60 + r)
- 只在 Sparse 第 r 名：RRF(d) = 1 / (60 + r)
- 两路都命中：RRF(d) = 1/(60+dense_rank) + 1/(60+sparse_rank)

RRF 不关心 Dense/BM25 的分数量纲，只关心"排第几"，因此两路分数
不需要对齐。

## 2. 为什么两个不同候选会完全同分

真实 q004 中：

```text
candidate A：
  dense_rank = 2
  sparse_rank = 8

candidate B：
  dense_rank = 8
  sparse_rank = 2
```

手工展开：

```text
RRF(A) = 1/(60+2) + 1/(60+8) = 1/62 + 1/68
RRF(B) = 1/(60+8) + 1/(60+2) = 1/68 + 1/62
```

加法交换律成立：

```text
1/62 + 1/68 == 1/68 + 1/62 == 0.0308349...
```

所以两个**完全不同的 chunk** 可以得到**完全相同**的 RRF 分数。
这类"对称排名"平局在 RRF 中很常见，不是个例。

## 3. Python set 为什么会造成跨进程不确定

原实现：

```python
all_ids = set(dense_rank_map.keys()) | set(sparse_rank_map.keys())
rrf_scores.sort(key=lambda x: x[1], reverse=True)
```

`rrf_scores` 的构造顺序来自 `all_ids` 的迭代顺序。Python `set`：

- 用哈希表实现；
- 迭代顺序依赖元素哈希值；
- 字符串哈希值在进程启动时被 `PYTHONHASHSEED` 随机化；
- **set 没有任何排序契约**，同一个集合在不同进程可能以不同顺序
  被遍历。

因此 `all_ids` 迭代顺序跨进程不稳定。

## 4. 为什么 Python sort 稳定反而暴露了问题

Python `list.sort()` 是稳定排序：

```text
同分元素保持输入中的相对顺序
```

对普通业务这是优点。但在 RRF 这里：

```text
同分
→ stable sort 保留输入顺序
→ 输入顺序来自无序 set
→ set 顺序随 hash seed 变化
→ 随机顺序被"稳定地"保留了下来
```

稳定排序没有制造问题，它只是忠实保留了上游的"未定义顺序"。

## 5. 为什么不能用固定 PYTHONHASHSEED 当正式修复

区别：

```text
环境碰巧固定：PYTHONHASHSEED=0 只是让当前环境可复现
算法契约确定：任何环境下，相同输入都产生相同输出
```

固定 seed 的问题：

1. 它依赖运行时环境变量，代码本身没有确定性；
2. 换机器、换 CI、换 Python 版本仍可能改变 set 顺序；
3. 它把"碰巧一致"伪装成"算法正确"；
4. 正式实验身份无法表达"我在依赖 hash seed"这件事。

因此生产逻辑禁止依赖任何固定 hash seed。

## 6. 为什么选择 chunk_id 作为 tie-break

正式契约：

```text
1. rrf_score DESC
2. chunk_id ASC
```

为什么是 chunk_id：

- 不偏 Dense：不把 dense_rank 作为第二键，避免"Dense 通道暗中更重"；
- 不偏 Sparse：不把 sparse_rank 作为第二键；
- 不使用 Dense/BM25 原始分数：分数量纲不同，不能直接比较；
- 不改非平局排序：只有 RRF 完全相同才触发第二键；
- chunk_id 只是 canonical ordering，不代表更高相关性。

实现：

```python
rrf_scores.sort(key=lambda item: (-item[1], item[0]))
```

注意：排序基于完整 float，不能先 `round()` 再排序；
`round(..., 6)` 只用于输出 metadata。

## 7. 为什么 tie-breaker 还必须进入 experiment_id

`rrf_tie_breaker` 改变的是**算法排序契约**，不是"代码实现细节"。

同一个 `experiment_id` 意味着"同一个可复现实验"。如果：

```text
旧排序：平局顺序 = set 迭代（不可复现）
新排序：平局顺序 = chunk_id_asc（可复现）
```

这两个行为在 tie 时可能给出不同 final Top-5，进而改变 MRR/nDCG。
让它们共享同一个 Experiment ID，等于让两份不同契约的实验互相
冒充。所以：

```python
rrf_tie_breaker: str = "chunk_id_asc"
```

必须进入 `to_dict()`，自动进入 `experiment_id`，并出现在
`index_manifest.config` 与 `result.config` 中。

## 8. 对 Retrieval 指标的影响

tie 出现在不同位置时，指标可能变化：

| 指标 | tie 影响 |
|------|---------|
| Hit@K | 通常不变：同一批文档都在 Top-K 内时，命中与否不受顺序影响 |
| Recall@K | 通常不变：集合语义，顺序无关 |
| MRR | **可能变**：第一个相关文档的排名若与 tie 有关，1/rank 会变 |
| nDCG@K | **可能变**：相关性增益按位置折损，位置互换会改变 DCG |

本项目 canonical Baseline 与旧 Baseline 的宏观指标完全相同
（Hit@5=0.92 / Recall@5=0.893333 / MRR=0.786667 / nDCG@5=0.799360），
说明已发生的 tie 没有改变这四个宏观值；但这是结果事实，不是
"必须不变"的保证。

## 9. 真实项目代码链路

```text
Dense Top-N（vector_store.search）
    \
     → dense_rank_map
        → all_ids → rrf_scores
           → sort: (-rrf, chunk_id)   ← G2-DIAG-13-R1 修复点
              → Final Top-K
    /
BM25 Top-N（_bm25.search）
```

关键文件：

- `core/retriever/hybrid.py`：
  - `HybridRetriever.__init__`（持有 `rrf_tie_breaker`）
  - `_internal_retrieve()`（共享一次检索）
  - `_sort_rrf_scores()`（正式排序契约）
  - `retrieve_with_trace()`（诊断通道候选）
- `core/config.py`：读取并校验 `retriever.rrf_tie_breaker`
- `core/pipeline.py`：构造 HybridRetriever 时传入 tie-breaker
- `evaluation/experiment_config.py`：`rrf_tie_breaker` 进入实验身份
- `evaluation/experiment_workspace.py`：派生 config.yaml 写入该字段
- `evaluation/experiment_runner.py`：`_validate_pipeline()` 验证
  pipeline.config 与 HybridRetriever 实际字段都与实验身份一致
- `evaluation/retrieval_diagnostics.py`：channel-level 诊断快照

## 10. 面试追问

### Q：为什么 set 会造成不确定排序？

set 是哈希表，迭代顺序由元素哈希值决定；Python 字符串哈希在进程
启动时被 `PYTHONHASHSEED` 随机化，所以同一个 set 在不同进程可能
以不同顺序被遍历。set 本身没有排序契约。

### Q：Python sort 是不是稳定排序？

是。`list.sort()` 是稳定排序：同分元素保持输入顺序。正因如此，它
会把"来自无序 set 的随机顺序"原样保留到输出。

### Q：RRF 同分怎么办？

定义正式 tie-break：`rrf_score DESC, chunk_id ASC`。只有 RRF 完全
相同才用 chunk_id 做 canonical ordering；不允许用 dense/sparse rank、
原始分数、source path、set 顺序、hash 或随机数。

### Q：为什么不用 Dense score 直接打破平局？

Dense score 只代表 Dense 通道的相似度，用它做平局裁决等于给 Dense
通道额外加权，破坏 RRF 等权融合语义；而且 Dense score 与 BM25 score
量纲不同，无法公平比较。

### Q：为什么不能直接 Dense score + BM25 score？

两路分数量纲和分布不同（余弦距离 vs BM25 权重），直接相加需要
未知的归一化/加权，等于引入隐藏超参；RRF 只用排名就是为了避开
分数对齐问题。

### Q：为什么固定 random seed 不等于算法可复现？

固定 seed 只让当前环境可复现，算法本身仍依赖未定义顺序；换环境、
换 hash 策略或并发执行仍可能不同。可复现要求算法契约在任何环境
下对相同输入给出相同输出。

### Q：为什么排序策略需要进入实验身份？

实验身份（experiment_id）表示"同一个可复现实验"。排序契约不同 =
算法行为不同 = 实验结果可能不同，因此必须换一个 experiment_id；
否则两个不同契约的实验会共享身份，指标无法归因。

### Q：平局为什么可能改变 MRR/nDCG？

MRR 用第一个相关文档的排名倒数；nDCG 用按位置折损的相关性增益。
两个候选（一个相关、一个不相关）在 tie 中互换位置，就会改变
first relevant rank 与位置折损，从而改变 MRR/nDCG；Hit/Recall 只看
集合是否出现，通常不受影响。

## 诊断成果（canonical Baseline）

修复后重新建立 canonical Baseline：

```text
experiment_id     = 3c613202e1ed
retrieval_run_id  = fc228af22f55
metrics_run_id    = 966ed53156e4
result_id         = e27141a2b63e
```

Diagnostic 绑定新 retrieval_run_id，50/50 Final Top-5 exact match 通过；
7 个重点 Case 的通道事实见
`docs/experiments/agent_ai_v1_baseline_analysis.md` 的 DIAG-13-R1 小节。
