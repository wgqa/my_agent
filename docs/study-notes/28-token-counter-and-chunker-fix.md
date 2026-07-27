# Files: core/chunker/token_counter.py + fixed_size.py + recursive.py + semantic.py

## 作用

这四份文件构成 RAG 的分块系统重构核心。

**问题背景：** 原实现的分块系统有三个关键缺陷：
1. **FixedSize** 用 `split()` 按空格分词，中文无空格文本完全不切
2. **Recursive** 接收了 `chunk_overlap` 参数但从未使用
3. **Semantic** 定义了 `min_chunk_len`/`max_chunk_len` 但从不校验

**解决方案：** 统一引入 TokenCounter 作为计量单位，修复三个 chunker 的核心算法。

---

## 完整代码（逐行讲解）

### TokenCounter — 统一的分词接口

```python
from typing import List


class TokenCounter:
    def __init__(self, encoding_name: str = "cl100k_base"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding_name)
        except ImportError:
            self._enc = None
```

- `cl100k_base` 是 OpenAI 的通用 tokenizer，支持中英文混合文本
- `try/except` 处理 tiktoken 未安装的情况，降级不崩溃
- `self._enc` 后续所有方法通过它判断是否走真实 tokenize

```python
    def count(self, text: str) -> int:
        if self._enc:
            return len(self._enc.encode(text))
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars)
```

- `count()` 是 chunker 最常用的方法
- 有 tiktoken：`encode(text)` 得到 token ID 列表，`len()` 即 token 数
- 无 tiktoken：经验公式——中文用 1.5，其他 1.0
- `'一' <= c <= '鿿'` 是 Unicode 中文字符范围（CJK 统一表意文字）

```python
    def encode(self, text: str) -> List[int]:
        if self._enc:
            return self._enc.encode(text)
        return list(text.encode("utf-8"))

    def decode(self, token_ids: List[int]) -> str:
        if self._enc:
            return self._enc.decode(token_ids)
        try:
            return bytes(token_ids).decode("utf-8", errors="replace")
        except Exception:
            return "<decode_error>"
```

- `encode/decode` 用于 FixedSize 和 Recursive 的切分操作
- 有 tiktoken：双向转换，无损
- 无 tiktoken：encode 返回 UTF-8 字节列表，decode 反向。只是兜底不崩溃

---

### FixedSizeChunker — 从词级到 token 级

```python
class FixedSizeChunker(BaseChunker):
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        token_counter: TokenCounter | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._counter = token_counter or TokenCounter()
```

- `token_counter` 可选注入，不传则新建。Pipeline 可以注入统一的 counter

```python
    def chunk(self, documents: List[Document]) -> List[Document]:
        chunked = []
        chunk_index = 0

        for doc in documents:
            tokens = self._counter.encode(doc.content)
            total = len(tokens)
            step = self.chunk_size - self.chunk_overlap

            if total <= self.chunk_size:
                chunked.append(self._make_chunk(doc, tokens, chunk_index, 0, total))
                chunk_index += 1
                continue

            start = 0
            while start < total:
                end = min(start + self.chunk_size, total)
                chunked.append(self._make_chunk(doc, tokens, chunk_index, start, end))
                chunk_index += 1
                if end == total:
                    break
                start += step

        return chunked
```

- `encode(doc.content)` → 把文本转成数字 ID 列表。中文也能正确切分
- `step = chunk_size - chunk_overlap` → 滑动窗口步长
- 短文档直接整篇输出；长文档从 `start=0` 每次前进 `step` 取 `chunk_size`

```python
    def _make_chunk(
        self, doc: Document, tokens: List[int], idx: int,
        start: int, end: int,
    ) -> Document:
        return Document(
            content=self._counter.decode(tokens[start:end]),
            metadata={
                **doc.metadata,
                "chunk_index": idx,
                "token_count": end - start,
                "token_start": start,
                "token_end": end,
            },
        )
```

- `decode(tokens[start:end])` → 将 token ID 区间还原回文本
- metadata 增加 `token_count`、`token_start`、`token_end`，用于实验追踪

---

### RecursiveChunker — 让 overlap 真实生效

```python
class RecursiveChunker(BaseChunker):
    SEPARATORS = ["\n\n", "\n", "。", ".", " ", ""]

    def __init__(self, chunk_size=512, chunk_overlap=64, token_counter=None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._counter = token_counter or TokenCounter()
```

核心改动：`chunk_overlap` 不再是个摆设，在 `_hard_split` 中会真实使用。

```python
    def chunk(self, documents: List[Document]) -> List[Document]:
        chunked = []
        for doc in documents:
            tokens = self._counter.encode(doc.content)
            chunks = self._split_tokens(tokens, 0, len(tokens))
            for i, (start, end) in enumerate(chunks):
                chunked.append(self._make_chunk(doc, tokens, i, start, end))
        return chunked
```

- 入口改为在 token 级别操作，`_split_tokens` 返回 `(start, end)` 区间列表

```python
    def _split_tokens(self, tokens, start, end):
        span = end - start
        if span <= self.chunk_size:
            return [(start, end)]

        text_segment = self._counter.decode(tokens[start:end])
        result = self._split_by_separator(text_segment, tokens, start, end, 0)

        final = []
        for s, e in result:
            if e - s > self.chunk_size:
                final.extend(self._hard_split(tokens, s, e))
            else:
                final.append((s, e))
        return final
```

- 先尝试用分隔符递归切分（语义边界优先）
- 超长的区间用 `_hard_split` 硬切，不超长的保留
- "递归"的含义：先语义边界，边界不够细就降级到硬切

```python
    def _hard_split(self, tokens, start, end):
        span = end - start
        if span <= self.chunk_size:
            return [(start, end)]

        step = self.chunk_size - self.chunk_overlap
        chunks = []
        s = start

        while s < end:
            e = min(s + self.chunk_size, end)
            chunks.append((s, e))
            s = s + step
            leftover = end - s
            if leftover > 0 and leftover < self.chunk_size * 0.3:
                break

        return chunks
```

- `step = chunk_size - chunk_overlap` — **overlap 终于真实生效了**
- 例：chunk_size=384, overlap=64 → step=320。块1: [0,384), 块2: [320,704)
- 重叠区域 64 token，两个块都包含这部分内容

---

### SemanticChunker — 让 min/max 真实生效

```python
    def _group_sentences(self, sentences, embeddings):
        groups = [[sentences[0]]]
        for i in range(1, len(sentences)):
            last_group_text = "".join(groups[-1])
            if self._counter.count(last_group_text) >= self.max_chunk_len:
                groups.append([])
                groups[-1].append(sentences[i])
                continue
```

- **第 1 道防线：max 上限检查**。每添加一个句子前先算当前组 token 数
- 旧版完全不检查，可能产生远超 max 的块

```python
            sim = self._cosine_sim(embeddings[i-1], embeddings[i])
            if sim < self.threshold:
                if self._counter.count(last_group_text) < self.min_chunk_len:
                    groups[-1].append(sentences[i])
                else:
                    groups.append([])
                    groups[-1].append(sentences[i])
            else:
                groups[-1].append(sentences[i])
```

- **第 2 道防线：min 检查**。相似度低于阈值（话题变了）
- 但当前组仍小于 min → 不切，继续追加，避免过小碎片

```python
        merged = [groups[0]]
        for g in groups[1:]:
            g_text = "".join(g)
            merged_last_text = "".join(merged[-1])
            if self._counter.count(merged_last_text) < self.min_chunk_len:
                merged[-1].extend(g)
            elif self._counter.count(g_text) < self.min_chunk_len:
                merged[-1].extend(g)
            else:
                merged.append(g)
        return merged
```

- **后处理合并**：分组后再次检查 min，过小的组与前一组合并
- 保证输出中没有任何一个组低于 min

---

## 重点总结

1. **TokenCounter 是三层修复的基础：** 统一了"token 数"的计量标准，不再出现"有的地方用词数、有的地方用字符数"的混乱。

2. **FixedSize 的核心改动：** 从 `split()` 按空格分改成 `encode()` 按 token 分。700 字中文现在能正确切出多个块。旧版第 19 行 `doc.content.split()` 对中文文本是 bug。

3. **Recursive 的核心改动：** overlap 参数接入 `_hard_split` 的 `step` 计算。旧版第 12 行接收了 `chunk_overlap` 但下面从未引用——形同虚设的参数。

4. **Semantic 的核心改动：** `min_chunk_len`/`max_chunk_len` 在三处真实执行。旧版 `_group_sentences` 只用阈值分组，这两个参数是死代码。

5. **近似处理：** `_find_split_boundaries` 用字符比例映射 token 位置，不是精确对齐。对多数文本误差在可接受范围。

## 大厂面试可能问

- **Q: 为什么引入 TokenCounter 而不是直接用 tiktoken？** — 抽象隔离。如果后续换成 BGE 的 tokenizer，只需要改 TokenCounter 一个类，所有 chunker 不需要动。

- **Q: fallback 的中文 1.5 token 估算可靠吗？** — 经验值。1000 个中文字约 1500-1800 token，准确度约 ±15%。只在没装 tiktoken 时启用。

- **Q: 三种 chunker 怎么选？** — Recursive 是通用默认，90% 场景够用。FixedSize 适用于需要严格等长块的消融实验。Semantic 适用于话题边界清晰的长文档，但速度最慢。
