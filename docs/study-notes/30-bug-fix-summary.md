# Bug 修复总结（2026-07-24）

## 修复清单

| Bug | 文件 | 根因 | 修复方式 |
|------|------|------|----------|
| Bug 1 | `recursive.py` | overlap 只在 `_hard_split` 里实现，主路径不走 | 在 `_split_tokens` 合并后统一加 overlap |
| Bug 2 | `recursive.py` | `_find_split_boundaries` 用字符比例映射 token 位置 | 删除该函数，每个 segment 单独 encode 跟踪真实位置 |
| Bug 3 | `recursive.py` | 与 Bug 2 同根因 | 与 Bug 2 一并修复 |
| Bug 4 | `mmr.py` | MMR 排序后不写分数到 metadata | 在选中每个文档时记录 mmr_score，返回前写回 |
| Bug 5 | `chroma_store.py` | add() 生成了 chunk_id 但不写回 doc.metadata | `meta["id"] = chunk_id` + `doc.metadata = meta` |
| Bug 6 | `hybrid.py` | BM25Index.search 只返回 (id, score)，不返文本 | BM25Index 存 `_texts` 字典，Hybrid 通过 `get_text` 补全 |
| Bug 7 | `semantic.py` | 单句 > max_chunk_len 时无兜底处理 | 分组前对超长单句做 token 硬切 |
| Bug 8 | `hybrid.py` | 每次 add/remove 全量重算 IDF | 增量更新 DF + 只重算受影响的词 |
| Bug 9 | `hybrid.py` | BM25Index 无持久化 | 新增 save/load 方法，JSON 磁盘持久化 |
| Bug 10 | `generator/base.py` | `_build_prompt` 无 token 预算控制 | 加 limit + 逐块截断 |
| Bug 11 | `generator/deepseek_gen.py` | generate 无异常捕获 | try-except + 返回错误信息 |
| Bug 12 | `pipeline.py` | 重启后 BM25 丢失，与 Chroma 不一致 | 启动时从 Chroma 全量重建 BM25 |
| Bug 13 | `pipeline.py` | 没有文档删除接口 | 新增 `delete_document` 方法 |
| Bug 14 | `mmr.py` | query embedding 重复计算两次 | 复用 `query_vec`，删除冗余 `embed_query` 调用 |

---

## 详细修复说明

### Bug 1-3：RecursiveChunker（overlap 未生效 + 边界映射错误 + 空块）

**旧代码做了什么：**

```
_split_tokens
  → decode tokens 成文本
  → _split_by_separator（按 \n\n、\n、。等递归切分文本）
    → _find_split_boundaries（用字符位置比例估算 token 位置）
  → 超长的块走 _hard_split（带 overlap）
  → 不超长的块直接返回（不带 overlap）
```

**三个问题：**

1. 按分隔符切完后，不超长的块头尾相接（`[0:40)`, `[40:66)`, `[66:71)`...），overlap = 0。
2. `_find_split_boundaries` 用 `字符位置 / 总字符数 ≈ token 位置 / 总 token 数` 的线性映射。中英文混排时比例不稳定，切出大量碎片。
3. 映射歪到同一个位置时产生空块 `[192:192)`。

**修复方式：**

删掉 `_split_by_separator` 和 `_find_split_boundaries`。改为：

```
_split_tokens
  → decode tokens 成文本
  → _split_text（递归按分隔符切分文本，得到 text segment 列表）
  → 每个 text segment 单独 encode，得到精确 token 长度
  → 按 chunk_size 合并 segment（追踪真实 token 位置）
  → 相邻块向后扩展 overlap 大小
```

`_split_text` 的职责是**只在字符层面按分隔符切**，返回文本片段。分隔符附到片段末尾：
```
"段落1\n\n段落2\n\n段落3"
  → ["段落1\n\n", "段落2\n\n", "段落3"]
```

`_split_tokens` 对每个片段调用 `self._counter.encode(seg)` 得到精确的 token 数量，在 token 层面合并。合并时检查是否超过 `chunk_size`，超过就开新块。最后在相邻块之间加 overlap——后一块的起始位置向前扩展 `chunk_overlap` 个 token。

**关键改动：** 从"字符比例估算"改为"每个片段单独编码后累积真实 token 长度"。不再有估算误差，不再有空块。overlap 统一在最后加，不再依赖 `_hard_split`。

---

### Bug 4 + Bug 14：MMR（分数不写回 + 冗余 embedding 调用）

**旧代码：**
```python
query_vec = self.embedding.embed_query(query)  # 算一次
...
query_emb = self.embedding.embed_query(query)  # 又算一次，完全冗余
...
return [candidates[i] for i in selected]  # 只返回 Document，没写分数
```

**修复：**
```python
query_emb = query_vec  # 复用第一次算的
...
mmr_scores_selected[best_idx] = max(mmr_scores)  # 记录每轮最高 MMR 分
...
doc.metadata["mmr_score"] = round(mmr_scores_selected[i], 6)  # 写回 metadata
```

**效果：** 省一次 embed_query 调用。调用方可以通过 `doc.metadata["mmr_score"]` 看到 MMR 重新排序后的真实打分。

---

### Bug 5：VectorStore.add() 不写回 ID

**旧代码：**
```python
meta = dict(doc.metadata)
meta["document_id"] = doc_id
metadatas.append(meta)
# doc.metadata 没有被更新！
```

**修复：** 在 append 之后加两行：
```python
meta["id"] = chunk_id       # 存 chunk_id 到 meta
doc.metadata = meta          # 写回原来的 Document 对象
```

**效果：** 调用 `store.add(chunks, vectors)` 之后，`chunks[0].metadata["id"]` 直接可用。不再需要：
```python
for chunk, cid in zip(chunks, ids):
    chunk.metadata["id"] = cid  # 这一行现在不需要了
```

---

### Bug 6：HybridRetriever BM25 命中但 content 为空

**旧代码：**
```python
# BM25Index.search() 返回 [(chunk_id, score), ...]
# Hybrid 对 Dense 未召回但 Sparse 命中的文档构造空 Document：
Document(content="", metadata={"id": chunk_id, ...})
```

`content=""` 的原因：BM25Index 存了分词后的 `_doc_freqs` 但没有保留原始文本。

**修复（两步）：**

第一步，BM25Index 新增 `_texts` 字典：
```python
class BM25Index:
    def __init__(self):
        ...
        self._texts: Dict[str, str] = {}  # 新增：存文本

    def add_document(self, doc_id, text):
        ...
        self._texts[doc_id] = text  # 存原文

    def get_text(self, doc_id) -> str:
        return self._texts.get(doc_id, "")
```

第二步，HybridRetriever 用 `get_text` 补全：
```python
text = self._bm25.get_text(chunk_id)
result_map[chunk_id] = Document(
    content=text,  # 不再为空
    metadata={"id": chunk_id, "sparse_score": round(s_score, 4)},
)
```

---

### Bug 7：SemanticChunker 超长单句

**问题场景：** 如果一个句子本身超过了 `max_chunk_len`（比如一段不含句号的超长日志），`_group_sentences` 不会处理它，直接当作一个句子加入分组。最终产出一个超过 `max_chunk_len` 的 chunk。

**修复：** 在 `_group_sentences` 开头的循环中加预处理：
```python
for s in sentences:
    n = self._counter.count(s)
    if n > self.max_chunk_len:
        tokens = self._counter.encode(s)
        for t in range(0, len(tokens), self.max_chunk_len):
            seg = self._counter.decode(tokens[t:t + self.max_chunk_len])
            if seg:
                safe_sentences.append(seg)
    else:
        safe_sentences.append(s)
```

**效果：** 任何单一输入文本片段，都不会超过 `max_chunk_len` token。超长的被切成多个子句后再进入语义分组。

---

### Bug 8：BM25Index IDF 全量重算

**旧代码：**
```python
def add_document(self, doc_id, text):
    ...
    self._total_docs += 1
    self._recompute_idf()  # 遍历所有文档所有词，重算所有词 IDF

def remove_document(self, doc_id):
    ...
    self._total_docs -= 1
    self._recompute_idf()  # 同上
```

文档数量上千后，每次 add/remove 扫全库重算 IDF，性能 O(N*V) 其中 N=文档数、V=词汇量。

**修复：** 维护全局 `_df` 字典（每个词在多少篇文档中出现过）：
```python
# add 时增量更新
for term in self._doc_freqs[doc_id]:
    self._df[term] = self._df.get(term, 0) + 1
self._recompute_affected_idf(affected_terms)

# remove 时增量更新
for term in affected:
    self._df[term] = self._df.get(term, 0) - 1
    if self._df[term] <= 0:
        self._df.pop(term, None)
self._recompute_affected_idf(affected_terms)
```

`_recompute_affected_idf` 只重算受影响的词：
```python
def _recompute_affected_idf(self, terms):
    for term in terms:
        freq = self._df.get(term, 0)
        if freq <= 0:
            self._idf.pop(term, None)
        else:
            self._idf[term] = math.log(...)
```

**效果：** add/remove 从 O(N*V) 降到 O(V_affected)，V_affected 是单篇文档的词汇量（通常远小于总词汇量）。

---

### Bug 9：BM25Index 无持久化

**旧代码：** BM25Index 所有数据只存内存，程序重启全部丢失。

**修复：** 新增 `save` 和 `load` 方法，使用 JSON 序列化：

```python
def save(self, path):
    """保存 BM25 索引到磁盘（JSON）"""
    data = {
        "doc_freqs": {k: dict(v) for k, v in self._doc_freqs.items()},
        "df": self._df,
        "doc_lens": self._doc_lens,
        "texts": self._texts,
        "total_docs": self._total_docs,
    }
    json.dump(data, f, ensure_ascii=False)

@classmethod
def load(cls, path) -> "BM25Index":
    """从磁盘加载 BM25 索引"""
    idx = cls()
    data = json.load(f)
    idx._doc_freqs = {k: Counter(v) for k, v in data["doc_freqs"].items()}
    idx._df = data["df"]
    ...
    idx._recompute_idf()  # 从加载的 DF 重建 IDF
    return idx
```

---

### Bug 10：Generator 无上下文长度限制

**旧代码：**
```python
def _build_prompt(self, query, context_docs):
    context = "\n\n".join([...])  # 不管多少文档，全部拼进去
```

如果用户搜一个宽泛的关键词，Retriever 返回很多文档，`context` 可能远超 LLM 的上下文窗口，导致截断或报错。

**修复：** 加入 token 预算控制 + 逐块截断：
```python
MAX_CONTEXT_TOKENS = 3000

for d in context_docs:
    block_tokens = counter.count(block)
    if used + block_tokens > limit:
        # 最后一块做 token 级截断
        if used < limit:
            remaining = limit - used
            tokens = counter.encode(block)
            parts.append(counter.decode(tokens[:remaining]))
        break
    parts.append(block)
    used += block_tokens
```

**效果：** 无论传入多少 context_docs，最终拼接的 context 不超过 3000 token。超出的文档被丢弃，最后一块被截断。

---

### Bug 11：Generator 无异常捕获

**旧代码：**
```python
resp = self.client.chat.completions.create(...)  # 网络波动、API 限额直接炸
return resp.choices[0].message.content
```

**修复：**
```python
try:
    resp = self.client.chat.completions.create(...)
    return resp.choices[0].message.content
except Exception as e:
    return f"[生成失败: {type(e).__name__}] {str(e)[:300]}"
```

**效果：** 网络波动、API 限额、key 错误等不会导致整个请求崩溃，而是返回可读的错误信息。调用方可以根据 `[生成失败: ...]` 前缀识别错误。

---

### Bug 12：Pipeline BM25 索引与 Chroma 不一致

**问题：** 服务重启后，ChromaDB 从磁盘恢复向量数据，但 BM25Index 是纯内存的——没了。两边数据不同步。用户搜同样的查询，重启前 Hybrid 能命中 BM25 的专有名词匹配，重启后 BM25 空库，退化成了纯 Dense 检索。

**修复：** 在 Pipeline `__init__` 末尾调用 `_rebuild_sparse_index()`：
```python
def _rebuild_sparse_index(self):
    all_data = self.vector_store.collection.get(
        include=["documents", "metadatas"]
    )
    pairs = [
        (meta["id"], content)
        for i, (meta, content) in enumerate(zip(all_data["metadatas"], all_data["documents"]))
        if meta.get("id")
    ]
    if pairs:
        self.retriever.build_sparse_index(pairs)
```

**效果：** Pipeline 初始化时自动从 ChromaDB 读取所有文档，重建 BM25 索引。两边数据保持一致。

---

### Bug 13：Pipeline 无文档删除接口

**旧代码：** Pipeline 只有 `index_file`（新增），没有删除方法。文件更新后旧 chunk 残留在向量库。

**修复：** 新增 `delete_document` 方法：
```python
def delete_document(self, document_id: str) -> int:
    self.vector_store.delete_by_document_id(document_id)
    return self.vector_store.count()
```

**已知限制：** 当前实现只清理 ChromaDB。BM25 索引里的 chunk_id 粒度和 document_id 不匹配，暂不清理 BM25。后续需要为 BM25 增加按 document_id 清理的能力。

---

## 测试结果

30 passed, 0 failed。覆盖模块：metrics、retrievers、vector_store、recursive_chunker、semantic_chunker、generators。
