# _rebuild_sparse_index 严格模式：评测可信性的最后一道防线

> 2026-08-05 — 173 → 180 passed
> 评测审计的最后一个阻塞项：`_rebuild_sparse_index()` 吞掉所有异常，
> "调用过重建方法" ≠ "BM25 确实重建成功"。Hybrid 评测仍可能静默退化
> 为 Dense-only——只是这次没人知道。

## 问题：容错吞掉了真相

```python
try:
    all_data = self.vector_store.collection.get(...)
    ...
    self.retriever.build_sparse_index(pairs)
except Exception:
    pass   # ← 问题所在
```

ChromaDB 读取失败、元数据异常、`build_sparse_index()` 报错——全部被吞。
普通应用启动时这是合理容错（BM25 失败不应让整个服务崩溃），但**评测场景**
下它把"重建失败"伪装成"重建成功"，实验照跑，指标失真，无人察觉。

**核心矛盾**：同一个方法服务于两个语义完全不同的消费方：
- 普通启动：BM25 是增强项，失败可降级 → 容错
- 评测：BM25 是自变量，失败即失真 → 必须 fail-fast

## 设计：strict 参数的双模式

```python
def _rebuild_sparse_index(self, strict: bool = False) -> int:
```

- 默认 `strict=False`：原有容错不变，`Pipeline.__init__` 照旧调用；
- Evaluator 传 `strict=True`：三种情况抛 `RuntimeError`（信息均含
  "Hybrid 评测已终止……不能生成失真结果"）：
  1. 读取 VectorStore 或构建 BM25 发生异常（`raise ... from exc` 保留根因）；
  2. 向量库有数据（`len(ids) > 0`）但 BM25 文档数为 0；
  3. BM25 文档数 ≠ 可索引 chunk 数（`built != len(pairs)`）。

方法返回实际重建的文档数（`len(pairs)`），避免 Evaluator 直接读
`_bm25.doc_count` 等私有字段；非 Hybrid（无 `build_sparse_index`）返回 0，
不校验、不报错——Simple/MMR 天然安全。

**数量校验的边界语义**：`len(ids) > 0 and built == 0` 与
`built != len(pairs)` 分开写，因为"空库"（ids 为空）不构成失真，
而"有数据但 BM25 空"是明确的静默降级信号。

## 测试方法：委托真实实现，不造第二套逻辑

最关键的测试设计：桩的 `_rebuild_sparse_index` 直接委托**真实的**
`Pipeline._rebuild_sparse_index(self, strict=...)`——Python 允许用
桩实例调用绑定方法：

```python
from core.pipeline import Pipeline

class _FakePipeline:
    def _rebuild_sparse_index(self, strict=False):
        return Pipeline._rebuild_sparse_index(self, strict=strict)
```

桩只需要提供 `vector_store.collection.get()` 和 `retriever`，方法体本身
是真实代码。测的是实现，不是桩的复制品。

- `_FakeCollection.get()`：数据为 None 时抛错 → 模拟"读取失败"；
- `_FakeHybridRetriever(fail_build=...)`：构建抛错 → 模拟"构建失败"；
- `count_after=...`：指定 build 后 BM25 计数 → 模拟"空索引/部分写入"；
- Evaluator 层测试：断言 `retriever.called is False` → 异常发生在
  第一次 `retrieve()` 之前。

## 教训

1. **容错与 fail-fast 的选择取决于消费方语义**：同一个函数服务不同
   调用方时，用参数显式区分，而不是一刀切"吞掉"或"抛出"。
2. **"调用发生"断言 ≠ "结果正确"断言**：E-03 测"重建方法被调用"，
   E-04 测"重建结果正确（数量校验）"——两层缺一不可。
3. **错误信息是契约**：异常必须说出"发生了什么、为什么不继续、谁该
   修"（此处：评测已终止 + 原因 + 不能生成失真结果）。
4. **桩测试委托真实实现**：`Pipeline._rebuild_sparse_index(self)` 直接
   用桩实例调用真实方法，测真实逻辑而非桩的复制品，避免测试与实现
   各自演进（同 37 号笔记的字段漂移教训）。
