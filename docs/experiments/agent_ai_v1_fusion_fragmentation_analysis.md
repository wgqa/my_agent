# Chunk-Level Fusion Fragmentation Analysis（G2-ANALYSIS-14）

> 2026-08-08
> 只读分析 canonical `retrieval_diagnostics.json`；不重新运行 Retrieval、
> 不修改 Retriever。同一 Artifact 输入由
> `scripts/analyze_fusion_fragmentation.py` 稳定输出相同统计。

## 1. 问题背景

当前 Hybrid RRF 的融合键是 `chunk_id`，而正式 Gold Evaluation 的单位
是 `document relative_path`。G2-DIAG-13-R1 已证明 q039 存在：

```text
Dense  rank1 → Gold document / Chunk A
Sparse rank2 → Gold document / Chunk B
Chunk A != Chunk B
```

因此两个通道虽然都强烈支持同一个 Gold 文档，chunk-level RRF 不会
自动把两路信号合并。本报告验证这种
`same-document / different-chunk channel agreement`
是否是当前 Baseline 的系统性失败模式。

## 2. 粒度差异

- 检索单位：Chunk（Recursive 512/64 切出的片段）；
- 融合单位：chunk_id（RRF 对 chunk 排名求和）；
- Gold 单位：document relative_path；
- 诊断单位：`(case_id, relevant_file)` 的 Gold obligation。

一个 multi-file Case 有 3 个 relevant_files → 3 个 Gold obligations。

## 3. 分类定义（A-F）

| 类别 | 定义 |
|------|------|
| A_no_channel_recall | Dense Top-30 与 Sparse Top-30 都没有 Gold 文档 |
| B_dense_only | 只有 Dense 有 Gold |
| C_sparse_only | 只有 Sparse 有 Gold |
| D_dual_same_best_chunk | 两路都有 Gold，且最佳 Gold chunk 相同 |
| E_dual_shared_chunk | 两路都有 Gold，存在共享 Gold chunk，但最佳 chunk 不同 |
| F_dual_different_chunk_only | 两路都有 Gold，但共享 Gold chunk 为空（最强碎片化证据） |

## 4. 全量统计（58 个 Gold obligations）

```text
总数 = 58
A_no_channel_recall           = 0
B_dense_only                  = 0
C_sparse_only                 = 1
D_dual_same_best_chunk        = 27
E_dual_shared_chunk           = 27
F_dual_different_chunk_only   = 3
```

### 最终成功（final_document_present = true）：51

```text
D_dual_same_best_chunk = 26
E_dual_shared_chunk    = 25
F_dual_different_chunk_only = 0
C_sparse_only          = 0
```

### 最终失败（final_document_present = false）：7

```text
F_dual_different_chunk_only = 3
E_dual_shared_chunk         = 2
D_dual_same_best_chunk      = 1
C_sparse_only               = 1
```

关键回答（Gold obligation 口径）：

```text
Final 失败 7 条中：
E+F（双通道但最佳 chunk 分裂）  = 5 / 7（71.4%）
仅 F（无共享 Gold chunk）       = 3 / 7（42.9%）
双通道任意（D+E+F）             = 6 / 7（85.7%）
```

F 类别 3 条全部最终失败（3/3）；E 类别 27 条中只有 2 条失败（25/27
成功）；D 类别 27 条中只有 1 条失败（26/27 成功）。

## 5. 7 个重点 Case（Gold obligation 级）

| case | Gold 文件 | Dense best rank/chunk | Sparse best rank/chunk | 相同 chunk | shared Gold chunks | Final | 分类 |
|------|-----------|-----------------------|------------------------|-----------|--------------------|-------|------|
| q013 | llm/预训练.md | 3 / 17e91abf… | 10 / fd40fc0d… | 否 | 0 | 否 | F |
| q019 | llm/Transformer架构-03 | absent | 2 / a308d378… | — | 0 | 否 | C |
| q039 | rag/检索与生成.md | 1 / 7f0e0301… | 2 / 23b6e4a3… | 否 | 0 | 否 | F |
| q047 | llm/Transformer架构-04 | 15 / 9451ef18… | 1 / 078bff61… | 否 | 1 | 否 | E |
| q031 | rag/文档处理.md | 2 / 468fead3… | 16 / 468fead3… | 是 | 1 | 否 | D |
| q031 | rag/检索与生成.md | 1 / d3dbe0b0… | 1 / d3dbe0b0… | 是 | 5 | 是 | D |
| q034 | rag/高级RAG.md | 5 / a63be3bb… | 2 / 25e2df22… | 否 | 1 | 否 | E |
| q036 | prompt/提示工程高级技巧.md | 1 / 6cc786bb… | 1 / 6cc786bb… | 是 | 2 | 是 | D |
| q036 | rag/文档处理.md | 11 / abf9618f… | 2 / abf9618f… | 是 | 1 | 是 | D |
| q036 | tool_calling/Function-Calling原理.md | 4 / 943110da… | 20 / 7fdbf870… | 否 | 0 | 否 | F |

（chunk_id 截断展示；完整 id 见 `retrieval_diagnostics.json`。）

## 6. q039 深挖

```text
Gold file: rag/检索与生成.md
Dense  best: rank 1, chunk 7f0e0301d9690995d01e2857371c369f
Sparse best: rank 2, chunk 23b6e4a38bc80b9bd7708d439bc548b5
shared Gold chunks: 空
Final Top-5: absent
分类: F_dual_different_chunk_only
```

确认：q039 的 Dense rank1 与 Sparse rank2 指向同一 Gold 文档中的
**不同 chunk_id**，且两路在该文档上没有共享 Gold chunk。这是
`same-document / different-chunk channel agreement` 的典型样本。

**边界声明**：当前 Gold 是 document-level，没有 chunk-level Gold
Label。因此：

```text
same-document / different-chunk
≠
已经证明两个 chunk 都包含回答 Query 的真正证据。
```

我们只能证明 Retriever 的两路信号落到了同一个 Gold 文件中的不同
Chunk，不能证明这些 Chunk 语义上都正确。

## 7. 已经 supported 的结论

1. **全量不存在 A/B**：58 个 Gold obligations 全部至少被一个通道
   召回（57 个双通道 + 1 个仅 Sparse）。
2. **F 与最终失败强相关**：3/3 的 F 全部 final 失败；Final 失败中
   E+F 占 5/7（71.4%）。
3. **D 与最终成功强相关**：D 类别 26/27 最终成功；F 类别 0/3 成功。
4. **q039 模式确认**：same-document / different-chunk（shared=0）真实
   存在，且 final 缺失。

## 8. 仍未验证

1. chunk-level Gold Label 不存在，无法判断"两路 Gold chunk 是否都
   包含真证据"；
2. 不能证明 document-level fusion 一定更好（本任务禁止宣称）；
3. F 样本仅 3 条，统计意义有限；
4. E 类别 25/27 成功，说明"存在共享 chunk"通常足以让文档进入
   Final Top-5；共享 chunk 与最终命中 chunk 的关系需要进一步检查；
5. q019 属于 C（仅 Sparse），不是碎片化问题。

## 9. 对下一步消融设计的启示

以下只作为**可验证实验假设**，不直接下"应该改成 document-level RRF"
的结论：

- 值得验证：在候选层按 document 聚合通道信号（如 parent-document
  retrieval / document-level scoring）能否减少 F 类最终失败；
- 需要先建立 chunk-level Gold Label，才能区分"碎片化"与"证据本身
  不在被召回 chunk"；
- 设计对比组时应以 D（最佳 chunk 相同）为对照，控制通道排名与
  文档本身的可检索性。

## 数据来源

- `experiments/3c613202e1ed/agent-ai-v1-recursive-hybrid-baseline-001-diagnostics/retrieval_diagnostics.json`
  （diagnostic_id=dfb2316d0163，绑定 retrieval_run_id=fc228af22f55）
