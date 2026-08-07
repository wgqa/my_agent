# ExperimentResult 最终实验摘要与事实快照绑定（G2-EVAL-09）

> 2026-08-07 — 488 → 522 passed
> result.json 是"一次已完成实验"的稳定摘要，而不是新的事实来源；
> 详细事实仍由 index_manifest.json / retrieval_results.json /
> retrieval_metrics.json 三份专用快照承载。

## 数据流

```text
IndexManifest + RetrievalRunResult + RetrievalMetricsResult
+ RetrievalEvaluationSet + 三份已落盘事实快照
→ 三份磁盘快照完整绑定（== 对应对象 to_dict()）
→ 跨阶段 ID / top_k / 策略 / Config 绑定 + 重算两个 run ID
→ 数量关系校验（不访问真实 Vector Store / BM25）
→ 稳定 ExperimentResult（指标摘要直接复制自 Metrics 快照）
→ 原子 result.json
```

本任务不重新调用 index_file / Retriever / Pipeline.query / Generator /
指标计算 / 旧 Evaluator。

## 三份落盘快照如何绑定

复用统一私有校验：

```python
_validate_persisted_json_snapshot(path, expected, display_name, mismatch_message)
```

- UTF-8 + `json.loads()`，合法 JSON，顶层必须是 object；
- 与 `index_manifest.to_dict()` / `retrieval_result.to_dict()` /
  `metrics_result.to_dict()` 做全结构比较；
- 任一文件缺失、非法、被人工修改或与传入对象不同 → 立即失败，
  不生成 result.json。

## 跨阶段 ID 如何验证

```text
experiment_id：Config == Manifest == Retrieval == Metrics
corpus_id：    Manifest == Retrieval == Metrics == EvaluationSet
evaluation_set_id：Retrieval == Metrics == EvaluationSet
retrieval_run_id：  Retrieval == Metrics，且按绑定字段重算一致
metrics_run_id：    按 metrics schema/run/eval/top_k/scope/relevance/aggregation 重算一致
top_k / retriever_strategy：Retrieval == Metrics == Config
chunk_strategy：Manifest == Config；config 与 index_manifest.config 完全一致
```

不信任对象中已存的 ID；两个 run ID 都必须重新计算并比对。

## result_id payload

```python
payload = {
    "schema_version": 1,
    "experiment_id": ...,
    "corpus_id": ...,
    "evaluation_set_id": ...,
    "retrieval_run_id": ...,
    "metrics_run_id": ...,
}
json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

表示"哪一个实验 + 哪一份 Corpus + 哪一套评测集 + 哪一个检索运行 +
哪一种指标定义"；不包含时间、Workspace 路径、指标数值、mtime、
repr 或 API Key。相同事实链得到相同 result_id。

## 为什么不重新计算指标

mean_hit_at_k / mean_recall_at_k / mean_mrr / mean_ndcg_at_k /
case_count 直接复制自已经过磁盘绑定验证的 RetrievalMetricsResult。
重新计算会让"被篡改的指标快照"与"摘要"出现两套真相，且引入
不必要的计算路径。

## 原子写入与失败语义

result.json 已存在时在任何收口工作前拒绝；只有全部绑定成功后
临时文件 → flush → fsync → close → os.replace；失败时清理临时文件、
原异常传播、不留下 result.json，已有三份事实快照保持不动。

## 教训

1. **摘要不是新事实**：result.json 只是三份专用快照的稳定投影；
   若摘要需要重算，说明事实快照本身不可信。
2. **绑定要整链验证**：单点 ID 校验无法发现"检索阶段换了评测集"
   这类跨阶段错配，必须让 Config / Manifest / Retrieval / Metrics /
   EvaluationSet 的 ID 链与数量关系同时闭合。
3. **通用校验收敛重复代码**：三份快照共用
   `_validate_persisted_json_snapshot`，各自只保留业务文件名与
   不一致消息，避免三套解析逻辑漂移。
