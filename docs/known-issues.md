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

### SemanticChunker

#### Bug 7：超长单句无兜底硬切
- **位置：** `semantic.py` `_group_sentences`
- **现象：** 单句本身 token > max_chunk_len 时，代码不做处理，产生超上限 chunk
- **原因：** 没有对超长单句做 token 级硬切

### HybridRetriever / BM25Index

#### Bug 8：IDF 全量重算
- **位置：** `hybrid.py` `BM25Index.add_document` / `remove_document`
- **现象：** 每次 add/remove 全量重算 IDF，文档上千后性能显著下降
- **原因：** 没有增量更新 IDF 的机制

#### Bug 9：BM25 无持久化
- **位置：** `hybrid.py` `BM25Index`
- **现象：** 程序重启后 BM25 索引丢失，与 Chroma 持久化数据不一致
- **原因：** BM25 索引仅存在内存中，没有保存到磁盘

#### Bug 10：没有停用词过滤
- **位置：** `hybrid.py` `BM25Index`
- **现象：** "的""和"等高频虚词干扰 BM25 打分
- **原因：** 分词后没有过滤停用词

### Generator

#### Bug 11：没有最大上下文长度限制
- **位置：** `deepseek_gen.py` / `openai_gen.py` / `base.py`
- **现象：** context_docs 太多时拼接超长，触发模型截断或超限报错
- **原因：** `_build_prompt` 没有对 context token 数量做预算控制

#### Bug 12：缺少异常捕获
- **位置：** `deepseek_gen.py` `generate`
- **现象：** 网络波动、API 限额、key 错误、接口超时会直接抛异常
- **原因：** 没有 try-except 和重试逻辑

### Pipeline

#### Bug 13：BM25 索引与 Chroma 不一致
- **位置：** `pipeline.py`
- **现象：** 服务重启后 BM25 清空但 Chroma 磁盘持久化还在，两边数据不同步
- **原因：** 启动时没有从 Chroma 重建 BM25 稀疏索引

#### Bug 14：没有文档删除接口
- **位置：** `pipeline.py`
- **现象：** 文件更新后旧 chunk 残留在向量库和 BM25 中
- **原因：** Pipeline 只实现了新增索引，没有删除/清空方法
