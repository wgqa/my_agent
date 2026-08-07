# 单实验端到端 Orchestrator（G2-EXP-10）

> 2026-08-07 — 526 → 537 passed
> 高层入口的价值不是"再实现一遍"，而是"把已经各自可信的阶段
> 按固定顺序串成一次完整实验，并保证失败时的事实状态可诊断"。

## 公共接口

```python
runner.run_experiment(
    config: ExperimentConfig,
    run_id: str,
    corpus: ExperimentCorpus,
    evaluation_set: RetrievalEvaluationSet,
) -> ExperimentResult
```

run_id 必须由调用方显式提供；不自动生成、不使用当前时间、不删除或
覆盖旧 Workspace。

## 五阶段调用顺序

```text
prepare
→ index_corpus
→ run_retrieval
→ compute_retrieval_metrics
→ finalize_result
```

前一个阶段的返回值原样传给下一个阶段，每个阶段恰好调用一次。
成功只返回 `ExperimentResult`，不新增 CombinedResult；详细事实仍由
四个 JSON 文件承载。

## Corpus/EvaluationSet 预绑定

创建 Workspace 前必须满足：

```python
evaluation_set.corpus_id == corpus.corpus_id
```

不一致直接抛 ValueError，`prepare` 调用 0 次、不创建 Workspace；
不重新实现 EvaluationSet 内部 Case 校验。

## 失败语义

任一阶段异常原样向外传播，后续阶段不执行、不重试、不 try/except
伪装成功、不自动清理 Workspace。已落盘的前置事实快照保留用于诊断：

```text
index 成功、retrieval 失败 → index_manifest.json 存在，
  retrieval_results.json / retrieval_metrics.json / result.json 不存在
metrics 失败 → index_manifest.json / retrieval_results.json 存在，
  retrieval_metrics.json / result.json 不存在
```

## 为什么不实现 Resume

第一版 `run_experiment()` 只允许"从全新 Workspace 完整执行一次"。
部分 Artifact 已存在时，由各阶段自身的拒绝逻辑失败；"从哪一步继续"
是独立能力，需要先定义每份快照的幂等与续跑契约，当前不做。

## 测试策略

- spy 测试：monkeypatch 五个阶段方法，断言调用顺序、恰好一次、
  返回对象透传、显式 run_id 透传、各阶段失败时后续不调用、
  原始异常类型与信息保留、失败后不删除 Workspace；
- 轻量集成：真实五阶段 + FakePipeline（含 config/vector_store/
  retriever/_rebuild_sparse_index）跑完一次实验，断言四个 Artifact
  文件全部存在且 result.json 摘要正确。

## 教训

1. **编排层要"薄"**：任何被复制的阶段内部逻辑都会变成第二套实现，
   后续修复只改一处时另一处必然漂移；run_experiment 只做顺序与透传。
2. **失败也是一种状态**：前置快照保留 + 后续文件缺失，本身就是
   可诊断的实验状态机，而不是需要被清理的"错误残留"。
3. **预绑定放在副作用之前**：Corpus/EvaluationSet 不匹配必须在
   prepare（创建 Workspace）之前失败，避免留下无意义的工作区。
4. **spy 与集成互补**：spy 固定"编排契约"，轻量集成固定"真实
   五阶段 + 落盘产物"，两者缺一不可。
