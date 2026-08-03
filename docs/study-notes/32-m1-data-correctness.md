# M1：入库与数据正确性（全记录）

> 2026-07-29 — T1~T5 完成，95 passed, 0 failed

## 概览

| 任务 | 目标 | 提交 |
|------|------|------|
| M1-T1 | 稳定领域模型（DocumentRecord/ChunkRecord） | `d7d9e20` |
| M1-T2 | 修复 ChromaStore 契约（校验/距离/过滤/维度） | `164c3d5` |
| M1-T3 | 统一 Token 计数与分块单位（补充） | `1d5dbfe` |
| M1-T4 | 修复 Recursive/Semantic Chunker | `844718f` |
| M1-T5 | Loader 元数据与文件安全 | `058d907` |
| M1-T6 | 幂等增量入库服务 | `3873fdf` |

---

## M1-T1：稳定领域模型

### 问题

之前所有数据都只有 `Document(content, metadata)` 两个字段，没有**业务身份**：
- 没有 document_id → 无法区分"这个 chunk 属于哪个文档"
- 没有 version → 文档更新后无法知道新旧版本
- 没有 content_hash → 无法判断文件是否变化

### 新增 `core/domain/models.py`

**三个工具函数：**

```python
def compute_content_hash(content: str) -> str:
    """文本内容 → sha256 前 32 字符"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

def make_document_id(source_name: str) -> str:
    """文件名 → 稳定 document_id（16 字符）"""
    raw = f"doc:{source_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def make_chunk_id(document_id: str, chunk_index: int, content: str) -> str:
    """document_id + 序号 + 内容 → 稳定 chunk_id（32 字符）"""
    raw = f"{document_id}:{chunk_index}:{compute_content_hash(content)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
```

**关键设计：chunk_id 包含内容 hash。** 内容不变 ID 不变（幂等）；内容一改 ID 全变（可检测更新）；不同文档相同文本 ID 不同（不误合并）。

**DocumentRecord（文档级身份）：**

```python
@dataclass
class DocumentRecord:
    document_id: str
    source_name: str        # 用户看到的文件名
    source_uri: str         # 文件真实路径
    content_hash: str       # 原始文件 hash
    file_type: str          # txt/md/pdf/py/java
    version: str = ""       # 内容版本，默认等于 content_hash
    status: str = "indexing"  # indexing/active/failed/deleted
    created_at: datetime = field(default_factory=utc_now)  # UTC 时间
    updated_at: datetime = field(default_factory=utc_now)
```

**ChunkRecord（块级身份）：**

```python
@dataclass
class ChunkRecord:
    chunk_id: str
    document_id: str
    document_version: str
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    page_number: int | None = None   # PDF 页码
    title_path: list = []            # Markdown 标题路径
    start_offset / end_offset        # token 偏移
    metadata: dict = {}              # 纯数据，可被 Chroma 序列化
```

### 测试验证（11 个）

- 相同内容 → 相同 hash ✓
- 相同 document/chunk → 相同 ID ✓
- 内容变了 → ID 变 ✓
- 不同文档相同文本 → ID 不同 ✓
- metadata 可 JSON 序列化 ✓

---

## M1-T2：修复 ChromaStore 契约

### 改了什么

**1. 输入校验（新增 `_validate_batch`）：**
```python
if len(docs) != len(embs):
    raise ValueError(f"documents {len(docs)} 与 embeddings {len(embs)} 数量不一致")
# 记录首个维度，后续批次维度不一致直接报错
```

**2. 空批次明确处理：** `add([], [])` 返回 `[]`，不炸不写。

**3. 查询返回 rank（`meta["rank"] = i + 1`）**，配合已有的 distance/score。

**4. where 元数据过滤：**
```python
def search(self, query_emb, top_k=5, where=None):
    if where:
        kwargs["where"] = where   # 如 {"document_id": "doc_a"}
```

**5. collection 名称包含模型名：**
```python
if model_name:
    safe = f"{collection_name}_{model_name.replace('/', '_')}"
# BGE 和 OpenAI 的向量不能混在一个 collection 里
```

**6. `list_ids(limit)` 方法**：列出所有 ID，供调试/全量重建用。

### 测试验证（8 个新增）

- 幂等 upsert（同一 chunk 两次 upsert count 不变）✓
- 删除后重加不冲突 ✓
- 搜索返回 distance + rank ✓
- score 排序语义正确 ✓
- delete_by_document 只删目标文档 ✓
- where 过滤生效 ✓
- 维度不一致报错 ✓
- 空批次显式处理 ✓

---

## M1-T3：统一 Token 计数与分块单位（补充）

Phase 1 已做了大部分。本任务补了三块：

**1. FixedSize 的 chunk_index 按文档重置：**
```python
for doc in documents:
    chunk_index = 0   # ← 每个文档从 0 开始（旧版全局递增）
```

**2. 空文档/纯空白跳过：**
```python
if total == 0 or not doc.content.strip():
    continue   # 不生成空块
```

**3. 新增 4 个测试：**
- 700 字中文按预算切分 ✓
- chunk_index 跨文档重置 ✓
- 空/空白文档不生成块 ✓
- 分块重组后内容不丢失 ✓

---

## M1-T4：修复 Recursive 与 Semantic Chunker

### Recursive 修了什么

**问题：超长 segment 没有硬切。** 一个段落本身超过 chunk_size（无分隔符可切）时，合并循环直接单独开组，产出超限 chunk。

```python
# 修复后
if seg_len > self.chunk_size:
    seg_tokens = self._counter.encode(seg)
    seg_start, seg_end = pos, pos + seg_len
    merged.extend(self._hard_split(tokens, seg_start, seg_end))  # ← 硬切
    pos = seg_end
    acc_segs, acc_tokens = [], 0
```

**空文档跳过：** `if not tokens or not doc.content.strip(): continue`

### Semantic 修了什么

**问题：embedding 失败直接炸。**

```python
try:
    embeddings = self.embedding_fn(sentences)
except Exception as e:
    warnings.warn(f"SemanticChunker embedding 失败，降级 Recursive: {type(e).__name__}")
    return RecursiveChunker(...).chunk(documents)   # 降级 + 记录 warning
```

### 新增测试

- 无分隔符超长段必须被硬切（每块 ≤ chunk_size）✓
- 空文档不生成空块 ✓

---

## M1-T5：Loader 元数据与文件安全

### TextLoader

```python
# 旧：filename = source.split("/")[-1]  ← Windows 反斜杠路径取不到文件名
# 新：filename = os.path.basename(source) ← 兼容两种路径分隔符
```
metadata 增加 `source_name`（稳定文件名）。

### PDFLoader

```python
# 旧：doc = fitz.open(source) ... doc.close()  ← 中途报错泄漏文件句柄
# 新：with fitz.open(source) as doc:  ← 上下文管理，异常也保证关闭

# 新增加密 PDF 检测
if doc.is_encrypted:
    return [Document(content="", metadata={"status": "encrypted"})]
```

### CodeLoader

```python
# 旧：.py/.js/.java 全部走 _split_python（Python 正则）← 名实不符
# 新：只有 python 走结构正则；java/js 返回整文件
if self.language == "python":
    return self._split_python(source, content)
return [Document(content=content, metadata={..., "language": self.language})]
```

### 连带测试修复

M1-T2 改了 search 签名后两个测试挂了：
- `test_api.py`：mock 的 config 从 dict 改成 SimpleNamespace（适配 Config 属性访问）
- `test_retrievers.py`：MockVectorStore.search 增加 `where=None` 参数

### 意外收获：解决 Windows 权限问题

Loader 测试一直有 8 个 PermissionError。发现用 `--basetemp=.tmp_pytest` 绕过。

**全量测试从 87 passed + 8 errors 变成 95 passed, 0 failed。**

---

## M1-T6：幂等增量入库服务

### 问题

旧 `index_file` 每次上传都重新切分 + 重新写入：
- 相同文件传两次 → 向量库出现两份重复数据
- 文件更新 → 旧 chunk 残留
- 无法判断"这是新文档还是更新"

### 新流程

```
index_file(file_path)
  → document_id = make_document_id(文件名)
  → content_hash = compute_content_hash(全文)   # fingerprint
  → decide：
      无记录        → create
      有记录且 hash 相同 → no_change（直接返回，不重复入库）
      有记录且 hash 不同 → update（先删旧 chunk 再入库）
  → 分块 → embedding → upsert → 同步 BM25
```

### 关键代码

```python
def index_file(self, file_path: str) -> dict:
    source_name = os.path.basename(file_path)
    document_id = make_document_id(source_name)

    existing = self.vector_store.get_by_document_id(document_id)

    if existing:
        old_hash = existing[0]["metadata"].get("content_hash", "")
        if old_hash == content_hash:
            return {"status": "no_change", "document_id": document_id, "chunks": 0}

    # update 路径：先删旧 chunk 再入库
    if existing:
        old_ids = [c["id"] for c in existing]
        self.vector_store.delete(old_ids)
        for cid in old_ids:
            self.retriever._bm25.remove_document(cid)

    # 新版本入库（用 upsert 而非 add：内容重复时幂等）
    ids = self.vector_store.upsert(chunks, embeddings)
```

### 返回格式变化

```python
# 旧：返回 int（chunk 数）
# 新：返回 dict
{"status": "create" | "update" | "no_change", "document_id": "...", "chunks": n}
```

API 端点 `/index/file` 同步适配，`IndexResponse` 增加 `status` 字段。

### ChromaStore 配套改动

**1. 新增 `get_by_document_id`：** 按 document_id 查全部 chunk（id/content/metadata），用于 decide 判断和删除。

**2. 批次内去重（`_batch`）：** 相同内容 chunk 生成相同 ID，ChromaDB 拒绝同批次重复 ID。`_batch` 对重复 ID 跳过，并同步过滤 embeddings：
```python
seen = set()
for d, emb in zip(docs, embs):
    cid = self._make_chunk_id(doc_id, d.content)
    if cid in seen:
        continue        # 去重
    seen.add(cid)
    ...
    filtered_embs.append(emb)   # embeddings 也过滤
```

### delete_document 同步清理

```python
def delete_document(self, document_id: str) -> int:
    chunks = self.vector_store.get_by_document_id(document_id)
    for c in chunks:
        self.retriever._bm25.remove_document(c["id"])  # BM25 同步删
    self.vector_store.delete_by_document_id(document_id)
```

### 新增测试（4 个）

- 新文件 → create ✓
- 相同文件重复上传 → no_change，count 不变 ✓
- 内容变更 → update，count 等于新版本 chunk 数 ✓
- 删除 → 向量库清空 ✓

### 踩坑记录

**坑 1：测试文本高度重复导致 chunk_id 冲突。** "内容"×20 切出来的块内容完全相同 → 相同 chunk_id → ChromaDB 报 DuplicateIDError。修复：`_batch` 去重。

**坑 2：Windows 下 `write_text` 默认 GBK 编码。** 测试写中文文件必须 `encoding="utf-8"`，否则 TextLoader（UTF-8 读）报 UnicodeDecodeError。

---

## 当前测试总览

```
99 passed, 0 failed, 4 warnings
```

| 模块 | 测试数 |
|------|--------|
| domain models | 11 |
| vector store | 11 |
| fixed_size chunker | 7 |
| recursive chunker | 5 |
| semantic chunker | 3 |
| loaders | 6 |
| pipeline | 9 |
| metrics/evaluator | 13 |
| retrievers | 5 |
| generators | 3 |
| api | 14 |
