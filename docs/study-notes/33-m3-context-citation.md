# M3：上下文组装与引用验证（T1 + T3）

> 2026-07-29 — 116 passed, 0 failed

## 概览

| 子任务 | 目标 | 提交 |
|--------|------|------|
| M3-T1 | ContextAssembler（预算/去重/引用编号） | `51bd80d` |
| M3-T3 | 引用验证（答案 [Cx] 可追溯） | `51bd80d` |

---

## M3-T1：ContextAssembler

### 问题

之前 `_build_prompt` 直接把检索结果拼进去：
- 无去重（同一内容可能重复出现）
- 无 token 预算（Bug 10 只做了简单截断）
- 无引用编号（答案无法标注"这句话来自哪块"）
- 无单文档占比限制（一个文档可能垄断上下文）

### 新增 `core/context/assembler.py`

**ContextBlock 数据结构：**
```python
@dataclass
class ContextBlock:
    citation_id: str        # [C1], [C2]...
    chunk_id: str           # 来源块 ID
    source_name: str        # 文件名
    page_number: Optional[int]
    content: str            # 内容
    token_count: int
    retrieval_scores: dict  # 分数/排名
```

**ContextAssembler.assemble() 四步流水线：**

```python
def assemble(self, hits: List[Document]) -> List[ContextBlock]:
    # 1. 按检索分数排序（score 高在前）
    ordered = sorted(hits, key=lambda d: d.metadata.get("score", 0.0), reverse=True)

    # 2. 去重 + 分配引用编号
    for d in ordered:
        if d.content in seen_content:
            continue                      # 相同内容只留一个
        citation_id = f"[C{len(blocks) + 1}]"   # 稳定编号

    # 3. 单文档占比限制
    blocks = self._limit_doc_share(blocks)

    # 4. token 预算截断
    blocks = self._truncate_to_budget(blocks)
```

### 三个关键设计

**1. 引用编号分配：** 按排序后的顺序给 [C1]、[C2]...。编号稳定 = 引用可验证的基础。

**2. 单文档占比限制（_limit_doc_share）：**
```python
cap = int(max_context_tokens * max_doc_ratio)   # 例：3000 * 0.5 = 1500
if doc_used == 0:
    # 该文档第一块：无论多大都保留（否则整个文档消失）
    ...
elif doc_used + b.token_count > cap:
    continue    # 超上限的块被跳过
```

**3. token 预算截断（_truncate_to_budget）：** 最后一块按 token 截断，不整块丢弃：
```python
remaining = max_context_tokens - used
tokens = counter.encode(b.content)
truncated = counter.decode(tokens[:remaining])
```

---

## M3-T3：引用验证

### 问题

答案里的引用完全不可验证。LLM 可能：
- 引用不存在的块（幻觉引用）
- 引用错误的来源

### 新增 `core/generator/citation.py`

```python
@dataclass
class CitationCheck:
    citation_id: str
    valid: bool
    chunk_id: str = ""
    source_name: str = ""
    reason: str = ""

@dataclass
class CitationValidation:
    valid: List[CitationCheck]
    invalid: List[CitationCheck]

    @property
    def validity_rate(self) -> float:
        """引用有效率 = 有效引用 / 总引用"""
        ...

class CitationValidator:
    PATTERN = re.compile(r"\[C(\d+)\]")

    def validate(self, answer: str, blocks: List[ContextBlock]) -> CitationValidation:
        # 1. 从答案中提取所有 [C1] [C2]
        cited_ids = sorted({int(m) for m in self.PATTERN.findall(answer)})

        # 2. 检查每个引用是否存在于本次 Context
        block_map = {b.citation_id: b for b in blocks}
        for n in cited_ids:
            block = block_map.get(f"[C{n}]")
            if block is None:
                invalid.append(...)   # 引用不存在
            else:
                valid.append(...)     # 引用有效，记录 chunk_id + source
```

### 集成进 Pipeline.query

```
检索 → 重排 → ContextAssembler 组装（带引用编号）
  → Generator 生成（prompt 要求用 [Cx] 标注）
  → CitationValidator 验证
  → 返回 {answer, sources, citation_validation}
```

返回结构新增：
```python
"citation_validation": {
    "valid_count": 2,
    "invalid_count": 1,
    "validity_rate": 0.67,
    "invalid_ids": ["[C5]"],
}
```

---

## Generator._build_prompt 兼容两种输入

```python
# ContextBlock 和 Document 都能传给 generate
citation = getattr(d, "citation_id", "")     # ContextBlock 有，Document 没有
source = getattr(d, "source_name", None) or d.metadata.get("source", "unknown")

if citation:
    block = f"{citation} [来源: {source}]\n{d.content}"   # [C1] [来源: redis.md]
else:
    block = f"[来源: {source}]\n{d.content}"
```

prompt 增加引用规则：
```
引用规则：回答中的每个事实性结论必须用 [Cx] 标注来源，
例如"缓存穿透是……[C1]"。
```

---

## 测试

9 个新测试（`tests/test_context_citation.py`）：

**ContextAssembler（5 个）：**
- 引用编号按顺序分配 [C1][C2][C3] ✓
- 相同内容去重 ✓
- 按分数降序排序 ✓
- token 预算截断 ✓
- 单文档占比限制 ✓

**CitationValidator（4 个）：**
- 全部有效引用 ✓
- 不存在的引用被标记 invalid ✓
- 混合场景 validity_rate = 0.5 ✓
- 无引用时 validity_rate = 1.0（无引用即无错误）✓

---

## 踩坑记录

**坑 1：tiktoken 对重复字符压缩。** 测试用 `"a" * 100` 想造 100 token 的块，实际只有 25 token（BPE 压缩重复序列）。修复：用真实感中文文本。

**坑 2：单文档占比限制丢光文档。** 第一块本身就超过 cap 时，整个文档被丢空。修复：`doc_used == 0` 时无论多大都保留第一块。
