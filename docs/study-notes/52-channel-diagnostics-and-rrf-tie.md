# Hybrid Channel-Level Diagnostic 与 RRF 平局顺序发现（G2-DIAG-13）

> 2026-08-08 — 559 → 574 passed
> 诊断基础设施本身是确定性的，但暴露了正式 Baseline 里一个
> 既有的可复现性缺口：RRF 完全平局时，最终顺序由 Python set
> 迭代顺序（进程 hash seed）决定，跨进程不可复现。

## 诊断能力

`HybridRetriever` 新增：

```python
retrieve_with_trace(query, top_k=5)
```

内部抽出共享 `_internal_retrieve()`：一次 embed + 一次 Dense Search +
一次 BM25 Search，同时得到：

```text
dense_candidates
sparse_candidates
final_results
```

普通 `retrieve()` 行为完全不变（回归测试锁定 chunk 顺序、rrf_score、
dense_rank、sparse_rank）。通道候选通过正式 IndexManifest 的
document mapping 转成 relative_path，写入独立
`retrieval_diagnostics.json`（schema/diagnostic_id 与正式
`retrieval_results.json` 分开）。

## 50/50 验收失败与根因

对冻结 Baseline（experiment_id=874b61d0b5d1）做诊断验证：

- 独立重建索引 → q004 与 Baseline 不一致；
- 复用 Baseline 自身向量索引 → q004 仍不一致（rank 2/3 互换）。

根因是 RRF 精确平局：

```text
chunk A：dense_rank=2、sparse_rank=8 → 1/62 + 1/68 = 0.0308349...
chunk B：dense_rank=8、sparse_rank=2 → 1/68 + 1/62 = 0.0308349...
```

`rrf_scores` 来自 `set` 迭代，`sort()` 稳定，平局顺序 = set 迭代顺序，
随进程 `PYTHONHASHSEED` 变化：

- 同一进程内连续 3 次 retrieve 顺序一致且与 Baseline 一致；
- 另一个进程顺序互换。

因此：`diagnostic != baseline`，按纪律不得用该诊断解释 Baseline，
H1-H4 证据等级不变。

## 教训

1. **“一次检索”不等于“可复现检索”**：只要最终排序存在精确平局且
   平局顺序依赖未定义集合顺序，跨进程执行同一代码也可能得到不同
   顺序。
2. **诊断验收必须严格**：50/50 exact match 不是形式主义——它正是
   用来暴露这种“几乎一致但顺序不稳定”的问题。任何“基本一致”都
   会掩盖可复现性缺口。
3. **先复用索引再下结论**：独立重建索引与复用 Baseline 索引出现
   同一处差异，才把根因锁定在执行层（RRF 平局顺序），而不是索引
   构建。
4. **修复边界要诚实**：给 RRF 增加稳定 tie-break 会改变普通
   retrieve 的平局顺序，属于修改 Retriever 行为；在任务禁止修改
   RRF 时，正确动作是停止并报告，而不是绕道。
