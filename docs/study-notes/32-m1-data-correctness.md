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

## 当前测试总览

```
95 passed, 0 failed, 4 warnings
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
