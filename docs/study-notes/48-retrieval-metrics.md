# 文档级 Retrieval Metrics 与原子指标快照（G2-EVAL-08）

> 2026-08-07 — 442 → 479 passed
> 正式指标的排序单位是"按 Chunk 首次命中顺序去重后的文档排名"
> （retrieved_files），而不是 Chunk 排名；同一个文件命中多个 Chunk
> 绝不能让 Recall 超过 1。

## 数据流

```text
RetrievalRunResult + RetrievalEvaluationSet + 已落盘 retrieval_results.json
→ 磁盘事实快照完整绑定（== retrieval_result.to_dict()）
→ 运行绑定 + 重算 retrieval_run_id
→ Cases 与 EvaluationSet 完整对应（case_id/query/relevant_files）
→ 逐 Case 检索快照不变量（hits <= top_k、rank 连续、Chunk 唯一、
   retrieved_files 与 hits 首次文件顺序一致）
→ 四项文档级指标 + 宏平均
→ 原子 retrieval_metrics.json
```

## 为什么指标输入是 retrieved_files

`hits` 是 Chunk 级原始排名；`retrieved_files` 是同一文件去重后的
文档级排名：

```text
hits：a.md/chunk1、a.md/chunk2、b.md/chunk7
retrieved_files：["a.md", "b.md"]
```

若把 hits 直接交给文档级指标，同一文件的多个 Chunk 会被重复计数，
Recall 可能超过 1。所以必须先验证 `retrieved_files` 与 hits 的首次
文件顺序完全一致，再把它作为唯一指标输入。

## 四项指标定义（K = retrieval_result.top_k）

- Hit@K：retrieved_files 中是否至少出现一个 relevant file → 1.0 / 0.0
- Recall@K：命中的唯一 relevant file 数 / relevant file 总数，范围 [0, 1]
- MRR：第一个相关文件位于文档排名 r → 1 / r，无命中 → 0
- nDCG@K：二元相关性；DCG 基于 retrieved_files 排序，IDCG 按
  `min(K, relevant_files 数量)` 计算

## Macro 聚合

```python
mean_metric = sum(case_metric) / case_count
```

每个 Query 是评测集中的一个独立样本；不按 relevant 数、Chunk 数或
文档数加权。

## metrics_run_id payload

```python
payload = {
    "schema_version": 1,
    "retrieval_run_id": ...,
    "evaluation_set_id": ...,
    "top_k": ...,
    "metric_scope": "document",
    "relevance": "binary",
    "aggregation": "macro",
}
json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

表示"对哪个可信检索快照、用哪个指标 Schema 评测"；不包含时间、
Workspace 路径、实际得分、API Key、repr 或对象地址。

## 完整性校验（与 G2-EVAL-07 同原则）

```text
磁盘事实快照 == 传入内存对象
```

磁盘 `retrieval_results.json` 必须存在、UTF-8 可解析、顶层是 object，
且与 `retrieval_result.to_dict()` 全字段一致；`retrieval_run_id` 必须
由绑定字段重算一致，不信任已存 ID。Cases 必须与 EvaluationSet 数量、
顺序、case_id、query、relevant_files 完全一致，不模糊 join。

## 方案选择

采用方案 A：在 `compute_retrieval_metrics()` 中先严格验证
`retrieved_files` 唯一且与 hits 首次文件顺序一致，再复用现有纯函数
（`hit_at_k`/`recall_at_k`/`mrr`/`ndcg_at_k`），不修改 `metrics.py`
与旧 Evaluator 行为。

## 教训

1. **指标输入必须先验后算**：任何"先算后校验"都会让被篡改的
   retrieved_files 直接操纵结果；不变量校验必须在第一个指标前完成。
2. **快照身份要整份绑定**：只比较 run_id 无法发现 cases/files 被
   人工修改；完整 `to_dict()` 结构比较才是可信绑定。
3. **去重是文档级指标的前提**：Chunk 是检索单位，文档是评测单位；
   两者之间的唯一可信转换是"首次出现顺序去重"。
4. **手算测试要先写对**：MRR 依赖第一个相关文件的排名，测试用例
   的 retrieved 顺序必须与断言一致，避免"实现正确、测试期望写错"。

## R1：快照二次校验收紧为"值 + 类型"（阻塞修复）

原实现用 `actual_ranks == list(range(1, len(hits) + 1))` 校验 rank，
但 Python 中 `True == 1`、`1.0 == 1`，bool/float rank 可以绕过契约；
chunk_id/document_id/relative_path 也只检查 truthy。

修复：

```python
if type(hit.rank) is not int:          # 不用 isinstance：bool 是 int 子类
    raise RuntimeError(...)
```

- rank 必须 `type(...) is int` 且严格等于 1..len(hits)；
- chunk_id / document_id / relative_path 必须
  `type(...) is str and value != ""`，禁止 `str()` 静默转换；
- `retrieved_files` 每项也必须是非空字符串（正式指标输入）；
- `top_k` 绑定同样收紧：`type(retrieval_result.top_k) is int`，
  拒绝 `True == 1` / `1.0 == 1` 绕过。

回归测试覆盖：rank=True、rank=1.0、非字符串 chunk_id / document_id /
relative_path / retrieved_files 项、top_k=True / top_k=1.0 全部拒绝；
正常 rank=1 继续接受。
