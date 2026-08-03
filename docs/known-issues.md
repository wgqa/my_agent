# 已知 Bug

> ✅ 2026-07-24 — Bug 1-6 已修复（26 passed）
> ✅ 2026-07-24 — Bug 7-14 已修复（30 passed）
> 修复详情见 `docs/study-notes/30-bug-fix-summary.md`

## RecursiveChunker

### Bug 1：overlap 未生效
- **位置：** `_split_by_separator` 主路径
- **现象：** `chunk_overlap=10` 传入但所有块头尾相接，无重叠
- **原因：** overlap 只写在 `_hard_split` 中，`_split_by_separator` 提前切好就不走硬切

### Bug 2：`_find_split_boundaries` 线性映射不准
- **位置：** `_find_split_boundaries` 第 110 行
- **现象：** 切出大量 1-5 token 的碎片，边界不准
- **原因：** 字符位置占比 ≈ token 位置占比的假设在中英文混排下不成立

### Bug 3：空块
- **位置：** `_split_by_separator` 切分逻辑
- **现象：** 出现 token_start == token_end 的空块
- **原因：** 边界映射定位到同一个位置

## MMRRetriever

### Bug 4：metadata 未记录 MMR 打分
- **位置：** `mmr.py` 排序逻辑
- **现象：** score 是向量库原始分数，不是 MMR 重新排序后的分数
- **原因：** MMR 排序后没有把 mmr_score 写回 metadata

## VectorStore

### Bug 5：add() 不写回 chunk_id
- **位置：** `chroma_store.py` add 方法
- **现象：** Document metadata 里没有 id，下游需要手动补
- **原因：** add 生成并返回了 chunk_id，但没有写回 doc.metadata

## HybridRetriever

### Bug 6：BM25 命中但 content 为空
- **位置：** `hybrid.py` 第 154-156 行
- **现象：** BM25 命中的文档 content=""，传给 LLM 无效上下文
- **原因：** BM25Index.search() 只返回 (id, score)，不返回文本

---

## 待修复（未修复）

### HybridRetriever / BM25Index

#### Bug 15：没有停用词过滤（增强级）
- **位置：** `hybrid.py` `BM25Index`
- **现象：** "的""和"等高频虚词干扰 BM25 打分
- **原因：** 分词后没有过滤停用词
- **优先级：** 增强级，可延后
