# 评测链路完整性：三类"评测结果不可信"问题

> 2026-08-05 — 169 → 173 passed
> 评测系统审计连续验收后给的三项修复，共同主题：**评测结果必须先可信，再谈指标高低**。
> 一个输出 0.000 的最佳配置、一份不重建索引的对比报告、一次退化 Dense-only 的 Hybrid
> 实验，比没有评测更危险——它们会引导出错误结论。

## 1. 报告字段漂移：hit_rate 与 hit_at_k

**现象**：`Evaluator.run()` 生成的指标字段叫 `hit_at_k`，但 `report.py` 的排序键和
最佳配置展示还在查 `hit_rate`：

```python
sorted_results = sorted(results, key=lambda r: r.get("hit_rate", 0), reverse=True)
report.append(f"- Hit Rate: {best.get('hit_rate', 0):.3f}")
```

查不到字段 → 走默认值 0：排序键恒 0（顺序依赖 Python 稳定排序，纯属巧合）；
最佳配置恒显示 `0.000`。

**根因**：字段名是**跨模块契约**，生成端（evaluator）与消费端（report）分别演进，
没有测试把两端锁在一起。旧测试只断言 `"0.900" in report`——表格里任意位置出现
就算过，测不出排序错、展示错。

**修复**：统一为 `hit_at_k`，展示标签同步 `Hit@K`；测试直接构造 A(0.5)/B(0.8)
断言 `B` 在 `A` 前、`Hit@K: 0.800` 出现、`0.000` 不出现。

**教训**：契约字段要有一端明确"只生成、只消费"的边界测试；"内容存在"断言
（`x in report`）测不出"位置/取值正确"。

## 2. 虚假实验保护：配置改了，组件没重建

**现象**：`Evaluator._apply_config()` 修改 `chunk_strategy` 后没有重新分块、
Embedding、建索引，报告声称比较了不同 Chunker，实际检索的是同一份旧索引。

**设计决策**（按审计要求，先保护不重构）：`run()` 入口检测 `chunk_strategy`
去重后 ≥2 个不同取值，直接抛 `ValueError`——**宁可不跑，不跑假的**：

```python
chunk_strategies = config_grid.get("chunk_strategy")
if chunk_strategies is not None and len(set(chunk_strategies)) > 1:
    raise ValueError("...切分和索引没有重建，对比结果不可信；请等待 ExperimentRunner...")
```

单一值不构成对比，照常运行。

**教训**：评测系统的第一职责是结果可信。在"实验隔离"能力补齐之前，用显式拒绝
代替静默产出误导性数据——这是很好的设计判断（诚实 > 好看）。

## 3. 稀疏索引生命周期：Retriever 重建后 BM25 为空

**现象**：`_apply_config()` 每组实验执行 `pipeline.retriever = pipeline._init_retriever()`，
新建 HybridRetriever 的 BM25 是**空索引**；而 `_rebuild_sparse_index()` 只在
Pipeline **初始化时**调用一次 → 之后所有 Hybrid 实验只剩 Dense 召回。

**根因**：BM25 索引的生命周期挂在 Pipeline 初始化上，而 Retriever 的生命周期
挂在 Evaluator 每轮实验上。组件重建后，依赖它的资源没有跟随重建。

**修复**：在重建 Retriever 之后立即重建稀疏索引（`_rebuild_sparse_index` 自带
`hasattr(..., "build_sparse_index")` 保护，非 Hybrid 安全跳过，无需改动）：

```python
self.pipeline.retriever = self.pipeline._init_retriever()
self.pipeline._rebuild_sparse_index()
```

**测试方法**：事件记录桩（`_FakePipeline` 记 `init_retriever`/`rebuild_sparse_index`，
`_FakeRetriever` 记 `retrieve` 到同一 events 列表），断言相对顺序——把"时序正确"
变成可回归的断言；用 `{"top_k": [3]}` 场景覆盖"仅调 top_k 同样触发重建"。

**教训**：资源重建时机应跟随组件创建点，而不是初始化点；生命周期不一致的组件
要专门写顺序测试，光靠人眼看不出来。

## 三类问题共通的测试设计

| 问题 | 旧测试盲点 | 新测试方法 |
|------|-----------|-----------|
| 字段漂移 | `"0.900" in report` 存在即过 | 断言排序相对位置 + 具体取值 + 默认值不出现 |
| 虚假实验 | 无（没测过 config_grid 校验） | 异常类型 + 异常信息关键字 + 副作用断言（retriever 未被调用） |
| 空 BM25 | 无 | 事件记录数组的 `index()` 相对顺序断言 |

`index()` 相对顺序断言是"调用时序"类 bug 的标准写法：
`events.index(A) < events.index(B)` 明确表达"必须先 A 后 B"。
