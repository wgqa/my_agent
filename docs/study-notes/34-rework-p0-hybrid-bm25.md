# REWORK-P0：外部评审驱动的两轮修复（Hybrid 候选链路 + BM25 统计）

> 2026-08-04/05 — 139 → 141 → 147 passed
> 背景：项目推上 GitHub 后请外部 LLM 按远程仓库审计，逐条核验后修复。
> 提交：`0b34074`+`d849e4b`（P0-01）、`36300da`+`069d3c4`（P0-02）

## 概览

| 任务 | 问题 | 提交 |
|------|------|------|
| REWORK-P0-01 | candidate_k 被内部 final_k 截断，reranker 收不到候选 | `0b34074` |
| REWORK-P0-02 | BM25 重复入库统计膨胀 + zip 配对错位 | `36300da` |
| 附带 | 增量 idf 陈旧值（既有 bug） | `36300da` |

---

## REWORK-P0-01：Hybrid Candidate→Rerank→Final 链路

### Bug：candidate_k 形同虚设

pipeline 初始化 Hybrid 时显式传参：

```python
HybridRetriever(..., final_k=self.config.top_k)   # 默认 5
```

Hybrid 内部检索又执行 `rrf_scores[:self.final_k]`，**先截断到 5 条**。
于是即使 `candidate_k=20`，Reranker 最多也只收到 5 条——配置了等于没配置。

> 教训：第一轮评审说"Hybrid 截断"，我当时只看了 hybrid.py 的默认值
> （final_k=20）就判定不属实，没查 pipeline 的**显式传参**。查 bug 要沿调用链，
> 不能只看单文件默认值。

### 修复

```python
# hybrid.py：内部池取两者较大者，不再吞候选
for doc_id, rrf in rrf_scores[:max(self.final_k, top_k)]:

# pipeline.py：语义明确定义 + reranker 关闭也严格截断
k = top_k or self.config.top_k                      # 请求 top_k：最终答案数上限
candidate_k = config.reranker_candidate_k or k*3    # 喂给检索器的候选池
final_k = config.reranker_final_k or k              # reranker 输出数
...
retrieved = retrieved[:k]                           # 无论 reranker 开关都截断
```

语义：**请求 top_k 是最终答案数上限；candidate_k 决定候选池；final_k 决定 rerank 输出**。

### 测试设计要点

集成测试必须用**真实 HybridRetriever + FakeEmbedding/FakeVectorStore**
（10 条候选 → candidate=7 → reranker 收到 7 → final=2 → 返回 2），
只用 FakeRetriever 只能证明"参数传出去了"，证明不了链路真的通了。

---

## REWORK-P0-02：BM25 重复入库统计膨胀

### Bug 1：add_document 不是 upsert

```python
def add_document(self, doc_id, text):
    self._doc_freqs[doc_id] = Counter(tokens)   # 覆盖
    for term in ...:
        self._df[term] += 1                      # ← 但没撤销旧统计！
    self._total_docs += 1                        # ← 同上
```

同一 ID 再入库（内容不变的部分 chunk）→ 字典里只有一份文档，`total_docs`/`df`
却重复累计。文档多次更新后 BM25 的 IDF 逐渐失真。这是"先写后删"改动引入的回归：
旧代码先删全部旧 ID 再重建，不会重复；新代码保留同 ID chunk 后直接重建。

**修复**：同 ID 先 `remove_document` 撤销旧统计再写入，保持不变式：

```python
_total_docs == len(_doc_freqs) == len(_doc_lens) == len(_texts)
```

### Bug 2（顺带发现）：增量 idf 陈旧值

审计要求"相同语料 build_sparse_index 两次，分数不变"——第一次跑就红了。
对比内部状态发现两次 build 后 `_doc_freqs/_df/_total_docs` 全一样，但**分数变了**。
根因：`_recompute_affected_idf` 只重算新增文档的词项。当总文档数 N 从 1 变 2 时，
不在新文档词表里的词（如 sat）的 idf 还停留在 N=1 时的值。

**修复**：总文档数变化影响所有词项，改为全量 `_recompute_idf()`（每文档 O(词表)，
对本项目语料规模可接受）。

> 教训：幂等测试不是形式主义——它抓到了"最终状态看起来一致，但中间计算缓存
> 陈旧"这类测试一次执行根本暴露不了的问题。

### Bug 3：zip(ids, texts) 配对错位

`_batch` 按内容去重（同内容同 chunk_id），返回的 `ids` 比输入 docs 少。
pipeline 用 `zip(ids, texts)` 配对 → 中间有重复 chunk 时，**去重之后的 id 与正文错位**
（idC 配到了 A 的正文上）。

**修复**两层：
1. `_batch` 给**所有**输入 doc 写回 `metadata["id"]`（含被去重的，重复内容同 id）
2. pipeline 改用 `[(c.metadata["id"], c.content) for c in chunks]`，不再 zip

---

## 其他（审计非阻塞项）

- README 出现重复"启动服务"段落（恢复 UI 段落时造成）→ 删除旧段
- status.md 不再维护提交哈希（提交本身会让哈希过期）→ 改为"最近验收基线"

## 验证

- 新增 9 个测试（P0-01 ×2 + P0-02 ×6 + store 对齐 ×1）
- 139 → 141 → **147 passed**，全量套件无回归
- 验收命令：`python -m pytest tests/test_retrievers.py tests/test_pipeline.py --basetemp=.tmp_pytest`

## 面试可讲

1. **外部评审流程**：远程仓库审计 → 逐条对代码核验（评审也会错，要自己验）→ 按任务卡修复 → 复审
2. **沿调用链查参**：默认值 vs 显式传参的差异（final_k 的坑）
3. **幂等测试的价值**：重复执行必须结果不变，才能暴露缓存陈旧类 bug
4. **去重后的 ID 对齐**：批量操作里"去重"和"顺序"是两个容易打架的约束
