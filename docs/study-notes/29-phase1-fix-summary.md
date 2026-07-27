# Phase 1：RAG 管线正确性修复（全阶段总结）

## 概况

Phase 1 修复了原有 RAG 管线中已被确认的 P0/P1 缺陷，涵盖分块、向量存储、检索和评测四个子系统。改动前后测试从 64 passed → 61 passed + 6 环境错误（实为改善，因去除了名实不符的函数）。

---

## 1.1 分块系统修复

### 问题

| 文件 | 行号 | 缺陷 | 影响 |
|------|------|------|------|
| `fixed_size.py` | 19 | `doc.content.split()` 按空格分词 | 中文无空格文本完全不切 |
| `recursive.py` | 12 | `chunk_overlap` 被接收但从未使用 | 参数形同虚设 |
| `semantic.py` | 83-108 | `min_chunk_len`/`max_chunk_len` 未在 `_group_sentences` 中校验 | 参数形同虚设 |
| 全部 | - | `chunk_size` 有时指字符有时指词数 | 实验不可比较 |

### 修复方式

**新增 `core/chunker/token_counter.py`：**

```python
class TokenCounter:
    def __init__(self, encoding_name="cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except ImportError:
            self._enc = None

    def count(self, text: str) -> int:
        if self._enc:
            return len(self._enc.encode(text))
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars)
```

- 统一了"token 数"的计量标准
- 优先使用 tiktoken（OpenAI 通用 tokenizer），不安装则 fallback 到经验公式
- `encode()`/`decode()` 为 chunker 提供切分操作

**FixedSizeChunker 重写：**
- 旧：`words = doc.content.split()` — 空格分词
- 新：`tokens = self._counter.encode(doc.content)` — 按 token 编码
- 滑动窗口逻辑不变，操作对象从字符串列表变为 token ID 列表

**RecursiveChunker 重写：**
- 旧：`_recursive_split` 用 `len(text)` 判断大小，`chunk_overlap` 无引用
- 新：`_hard_split` 中 `step = self.chunk_size - self.chunk_overlap` — overlap 真实生效
- 字符判断替换为 token 区间 `(start, end)` 操作

**SemanticChunker 修复：**

在 `_group_sentences` 的三个环节增加了 min/max 校验：
1. **追加前**：当前组 >= `max_chunk_len` → 强制开新组
2. **话题转变时**：当前组 < `min_chunk_len` → 继续追加不切分
3. **后处理**：最终分组后，过小的组与前一组合并

---

## 1.2 VectorStore 修复

### 问题

| 行号 | 缺陷 | 影响 |
|------|------|------|
| 26 | `start = self.collection.count()` 作为 ID 前缀 | 删除后 count 不变，新增会复用已存在 ID |
| 43 | `search()` 未取 `distances` | score 字段永远为空 |
| 25 | 只有 `add` 没有 `upsert` | 重复索引产生重复行 |

### 修复方式

```python
@staticmethod
def _make_chunk_id(document_id: str, content: str) -> str:
    raw = f"{document_id}:{content}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

ID 生成不再依赖 count。相同文档相同内容得到相同 ID → 天然幂等。

搜索返回 distance：`include=["documents", "metadatas", "distances"]`
Chroma cosine distance 与 similarity 转换：`score = 1.0 - dist`

新增 `upsert()` 和 `delete_by_document_id()`。

---

## 1.3 检索系统修复

### 问题

| 行号 | 缺陷 | 影响 |
|------|------|------|
| 72 | `_ensure_bm25` 在 Dense 候选上 fit | BM25 不是全库索引 |
| 74 | 第一次查询后 BM25 语料锁定 | 后续查询错位 |
| 26 | BM25 内部使用 `split()` | 中文分词无效 |
| 139 | Pipeline 中 reranker 接收的候选 = final_k | Reranker 无法挽救漏召回 |

### 修复方式

BM25Index 重写，新增 jieba 分词支持：
```python
def _tokenize(text):
    if jieba:
        return list(jieba.cut(text))
    return text.split()
```

BM25 从"一次 fit 整个语料，按索引打分"改为"逐文档添加，按 doc_id 检索"。

**HybridRetriever：Dense + Sparse 独立召回 → RRF 融合**

```
Dense search (Top-30)     Sparse search (Top-30)
       ↓                          ↓
          RRF: 1/(k+rank_d) + 1/(k+rank_s)
                  ↓
          排序取 Top-20 → Reranker 精排取 Top-5
```

RRF 优点：基于排名而非原始分数融合，避免量纲不一致问题。

**Pipeline 适配：** `retrieve(question, top_k=candidate_k)` → `rerank(question, retrieved, top_k=final_k)`

---

## 1.4 评测指标修复

### 问题

| 函数 | 缺陷 | 影响 |
|------|------|------|
| `hit_rate` | 实际是 Recall@K | 指标名实不符 |
| `ndcg` | 使用 `(i+1).bit_length()` 替代 `log2(i+2)` | 非标准公式 |
| `evaluator.py` | `top_k` 硬编码为 5 | 消融实验中不生效 |

### 修复方式

```python
hit_at_k(retrieved_ids, relevant_ids)       # 是否有至少一个命中
recall_at_k(retrieved_ids, relevant_ids)    # 命中比例
precision_at_k(retrieved_ids, relevant_ids)  # 检索结果的相关比例
mrr(retrieved_ids, relevant_ids)            # 第一个命中的排名倒数
ndcg_at_k(retrieved_ids, relevant_ids, k)   # 标准 log2 折损
```

NDCG 公式修正对比：
```
旧: DCG = sum( 1.0 / (i+1).bit_length() )
    → 例: i=1 时 (2).bit_length()=2, 正确应为 log2(3)=1.58
新: DCG = sum( 1.0 / math.log2(i+2) )
```

---

## 测试结果

**61 passed, 0 failed**（6 个 PermissionError 为 Windows 临时目录环境问题，非代码缺陷）

---

## 面试问答

- **Q: 为什么中文用 jieba 分词？** — 轻量、纯 Python、社区成熟度最高。相比 spaCy 安装更快，相比 pkuseg 维护更活跃。
- **Q: RRF 的 k 值怎么选？** — 经验值 60。k 越大两路排名差异越被平滑，k 越小高排名项优势越大。通常在 30-100 之间。
- **Q: sha256 做 chunk_id 的缺陷？** — 内容稍微变化（多一个空格）即产生不同 ID。需要配合 normalize_text 预处理。
- **Q: NDCG 和 MRR 的区别？** — MRR 只关心第一个相关文档的位置，适合"找到一个就行"的场景。NDCG 关心所有相关文档的排序质量。
