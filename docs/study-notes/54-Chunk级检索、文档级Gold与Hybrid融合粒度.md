# Chunk 级检索、文档级 Gold 与 Hybrid 融合粒度（G2-ANALYSIS-14）

> 2026-08-08 — 只读分析任务（590 → 595 tests）
> RAG 里最常见的一个"粒度错位"：检索和融合在 Chunk 层，标注和
> 评价在 Document 层。理解这个错位，才能读懂为什么"两个通道都
> 找到同一篇文档"不等于"RRF 获得双路加分"。

## 1. 为什么 RAG 实际检索单位通常是 Chunk

长文档不能整篇嵌入：

- 向量维度固定，整篇文档太长会稀释语义；
- 需要控制送入 Generator 的上下文预算；
- 精确引用需要定位到"哪一段"而不是"哪个文件"。

因此 RAG 通常把文档切成 Chunk：检索返回 Chunk，证据引用也落在
Chunk 上。Chunk 是检索单位，也是引用单位。

## 2. 为什么我们的 Gold 是 document-level

构建评测集时，标注者标记的是"这道题应该看哪个文件"：

```text
relevant_files: ["rag/检索与生成.md", "rag/文档处理.md"]
```

原因：

- 文件路径是跨 Chunk 策略稳定的身份（Fixed/Recursive 的 chunk_id
  完全不同）；
- 人工标注 Chunk 太细、且随切分参数变化；
- 文档级标注允许同一文件多个 Chunk 命中只算一个相关文件。

所以：**检索单位是 Chunk，评价单位是 Document**。

## 3. chunk_id 与 document_id 的区别

```text
document_id：文件身份（由 basename 派生）
chunk_id：  切分后的片段身份（document_id + content 的哈希）
```

同一个 document_id 可以有多个 chunk_id；不同 chunk 策略下同一
文档的 chunk_id 完全不同，document_id 不变。IndexManifest 保存
document_id → relative_path 映射，用于把 Chunk 命中还原成文件。

## 4. RRF 当前到底融合什么

RRF 融合的是**Chunk 的通道排名**：

```text
RRF(chunk) = 1/(k + dense_rank) + 1/(k + sparse_rank)
```

它给"在某个通道排名靠前的 chunk"加分。两个 chunk 即使属于同一
文档，也被当成两个独立的融合单元。

## 5. “两个通道都找到同一文档”为什么不等于“RRF 获得双路加分”

假设：

```text
Dense  找到 文档X 的 chunk A
Sparse 找到 文档X 的 chunk B
A != B
```

RRF 计算：

```text
RRF(A) = 1/(k + dense_rank_A) + 0        # B 的 sparse 分不归 A
RRF(B) = 0 + 1/(k + sparse_rank_B)       # A 的 dense 分不归 B
```

两路信号各自落在不同的 chunk 上，**没有在同一个 chunk 上叠加**。
如果 A、B 单独都不够强，文档 X 就可能掉出 Final Top-5。

这就是 G2-ANALYSIS-14 说的 fusion fragmentation。

## 6. q039 完整示例

```text
Gold: rag/检索与生成.md

Dense  Top-30: chunk A (7f0e0301...)，dense rank 1
Sparse Top-30: chunk B (23b6e4a3...)，sparse rank 2
shared Gold chunks: 空

RRF(A) = 1/61 + 0
RRF(B) = 0 + 1/62
Final Top-5: 文档未出现
分类: F_dual_different_chunk_only
```

两个通道都非常强地支持同一文档，但因为落在不同 chunk，chunk-level
RRF 无法合并，最终文档没有进入 Top-5。

## 7. chunk-level fusion 与 document-level fusion 的 trade-off

Chunk-level fusion：

- 优点：与检索/引用单位一致；定位精确；
- 缺点：同一文档的跨通道信号无法聚合，碎片化会损失文档级召回。

Document-level fusion（把同一文档所有 chunk 的通道信号合并后再排序）：

- 优点：能聚合碎片化信号；
- 缺点：需要先定义"文档得分怎么从 chunk 得分推导"，可能引入
  隐藏加权；最终仍要回到 chunk 才能引用。

这是假设层面的 trade-off；G2-ANALYSIS-14 只提供事实，不宣称
document-level 一定更好。

## 8. 为什么不能直接把同一文档所有 Chunk 分数相加

直接相加的问题：

- 长文档 chunk 多，天然得分高（长度偏置）；
- 同文档多个 chunk 可能是重复/冗余内容，相加会重复计权；
- dense/sparse 分数量纲不同，相加前要未知的归一化；
- 一个文档只要有一个强 chunk 就足以支持答案，总和反而稀释决策。

所以任何 document-level 聚合都需要明确契约（max / first / weighted
sum），不能简单相加。

## 9. 与 diversification / dedup / parent-document retrieval 的关系

- dedup：避免同一文档多个 chunk 占据 Top-K；
- diversification：让 Top-K 覆盖更多文档；
- parent-document retrieval：检索到 chunk 后回填父文档，再按文档
  组织证据；
- document-level fusion：在融合阶段就把同一文档的通道信号合并。

它们都是"如何从 chunk 信号还原文档级决策"的不同手段；本项目当前
的 `retrieved_files` 去重只是**结果展示层**的文档去重，不是融合层
的文档聚合。

## 10. 大厂面试可能怎么追问

### Q：检索单位为什么是 chunk 而不是 document？

为了语义密度、上下文预算和精确引用；document 级嵌入会稀释长文档
语义。

### Q：Gold 是 document 级，指标为什么还可靠？

指标用去重后的文档排名（retrieved_files）计算，Chunk 命中先映射回
文件再判相关；可靠性来自"Chunk → document"的映射是确定性的，
但代价是丢失了 chunk 层的正确性信息。

### Q：两个通道命中同一文档的不同 chunk，RRF 会给双路分吗？

不会。RRF 只对同一 chunk_id 的排名求和；不同 chunk 各自计算，
跨通道信号无法在 chunk 层合并。

### Q：怎么证明 fragmentation 是失败原因？

需要对比：同一文档在两路的最佳 chunk 是否相同、是否有共享 chunk；
以及最终是否进入 Top-K。G2-ANALYSIS-14 用六分类
（A/B/C/D/E/F）把每个 Gold obligation 归入事实类别。

### Q：document-level fusion 一定能提升指标吗？

不一定。它改变排序语义，可能让长文档/多 chunk 文档受益，也可能
引入新的偏置；必须作为可验证实验假设，用固定 Baseline 对比。

### Q：为什么不能直接对同一文档所有 chunk 求和？

长度偏置、重复计权、跨通道量纲不一致、以及"一个强 chunk 就够"
的决策本质。

## 事实结论（本任务）

- 58 个 Gold obligations：A=0、B=0、C=1、D=27、E=27、F=3；
- Final 失败 7 条：F=3、E=2、D=1、C=1；E+F 占 5/7；
- F（无共享 Gold chunk）3/3 最终失败；D（最佳 chunk 相同）26/27
  成功；
- q039 确认 same-document / different-chunk（shared=0）。

边界：无 chunk-level Gold Label，不能宣称被召回的两个 chunk 都
包含真正证据。
