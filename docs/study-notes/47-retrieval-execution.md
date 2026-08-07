# 正式检索执行与原始结果快照（G2-EVAL-07）

> 2026-08-07 — 396 → 435 passed
> 检索评测的第一个可信产物是"逐查询原始 Chunk 命中 + 文件级排名"
> 的不可变快照，而不是直接算出的指标——指标可以在快照上重算，
> 快照本身必须能被审计。

## 数据流

```text
PreparedExperiment + IndexManifest + RetrievalEvaluationSet
→ 运行前绑定校验（第一次 retrieve 前全部完成）
→ document_id → relative_path 映射（只来自 index_manifest.files）
→ 逐 Case 直接调用 retriever.retrieve(case.query, top_k=config.top_k)
→ 立即转为不可变内存快照（hits + retrieved_files）
→ 原子生成 retrieval_results.json
```

只允许调用 Retriever；不调用 Pipeline.query、Generator、
ContextAssembler、CitationValidator、Reranker、旧 Evaluator、
指标或报告生成器。

## 运行前绑定校验

- `index_manifest.json` 必须已存在；
- `experiment_id`、`config`、`corpus_id`、`retriever_strategy`、
  `chunk_strategy` 与当前 ExperimentConfig / EvaluationSet 一致；
- `file_count == len(files)`、`total_chunks == vector_store_count`；
- Hybrid 模式 `sparse_index_count == vector_store_count`；
- `retrieval_results.json` 已存在时拒绝重复运行。

任一不一致都在第一次 retrieve 前失败，Retriever 调用次数为 0。

## document_id → relative_path 映射

映射只来自 `index_manifest.files`：

```text
document_id → relative_path
```

禁止用 `source_name` basename、`metadata["source"]` 绝对路径、
字符串截断、当前工作目录或模糊文件名匹配。Manifest 的 document_id
必须非空、不得映射到两个不同文件；Retriever 返回的每个 Chunk 必须
有非空 `metadata["id"]` 与 `metadata["document_id"]`，且 document_id
必须存在于映射中，否则 fail-fast。

## Chunk Hit 与 retrieved_files 的区别

`hits` 保存原始 Chunk 排名（诊断用），`retrieved_files` 是文件级
排名（后续 Hit/Recall/MRR/nDCG 用）：

```text
Chunk 排名：1. a.md/chunk-1  2. a.md/chunk-2  3. b.md/chunk-7
retrieved_files：1. a.md  2. b.md
```

同一文件只按首次命中出现一次；不能把所有 Chunk 的 relative_path
直接交给文档级指标，否则同一文件的多个 Chunk 会被重复计数。

## 分数白名单

只保存实际存在的白名单字段，不虚构 0、不保存完整 metadata：

```text
score / distance / dense_score / sparse_score / rrf_score /
mmr_score / rerank_score / dense_rank / sparse_rank / final_rank
```

绝对 source 路径、API Key、对象 repr、内存地址一律不写入结果。

## retrieval_run_id payload

```python
payload = {
    "schema_version": 1,
    "experiment_id": ...,
    "corpus_id": ...,
    "evaluation_set_id": ...,
    "retriever_strategy": ...,
    "top_k": ...,
}
json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

该 ID 表示"计划执行的是哪一个检索实验"，不是结果内容哈希；不包含
Workspace 路径、时间、对象地址、API Key、耗时或本次分数。

## 原子写入与失败语义

同目录临时文件 → flush → fsync → close → os.replace；中途失败清理
临时文件、原异常向外传播、不留下正式结果文件。已完成 Case 只保留
在内存，不得伪装成成功运行。

## 测试要点

- 稳定策略：Retriever 返回超过 top_k 时只保留前 top_k；
- 同一 Case 内重复 Chunk ID 拒绝；
- 少于 top_k 合法；中间 Case 抛异常时不生成文件；
- 全部使用 FakeRetriever / FakePipeline / 内存评测集，不加载真实模型、
  不调用网络、不调用旧 Evaluator。

## 教训

1. **可信映射只能有一个来源**：文件身份只能来自 Manifest 的
   document_id 映射，任何 basename / source / 截断猜测都会把"标注
   身份"换成"检索产物的巧合文本"。
2. **先固化绑定，再执行副作用**：所有绑定校验必须发生在第一次
   retrieve 之前，否则一次错误的实验运行会污染 Workspace。
3. **原始结果与派生指标分层**：快照保存 Chunk 与文件两级排名，
   指标以后再算——分层让"结果可重算"与"快照可审计"同时成立。
4. **分数要白名单而不是黑名单**：只放行已知语义字段，避免
   metadata 中任意字段（含绝对路径/密钥）悄悄进入正式结果。
