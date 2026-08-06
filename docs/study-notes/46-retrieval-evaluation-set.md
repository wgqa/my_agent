# 可复现 RetrievalEvaluationSet：文档级标注与稳定 evaluation_set_id（G2-EVAL-06）

> 2026-08-07 — 334 → 382 passed
> 旧 `Evaluator.QAPair.relevant_ids` 使用 Chunk ID，Fixed/Recursive 的
> Chunk ID 不同，chunk_size/overlap 变化后也会变化；文档级评测必须
> 使用 Corpus 中稳定的规范相对文件路径。

## 数据流

```text
JSONL 测试集
→ 严格解析与校验（行号定位错误）
→ 绑定 ExperimentCorpus（relevant_files 精确匹配 entries）
→ 规范化 RetrievalCase（POSIX 路径 + 排序 tuple）
→ 稳定 evaluation_set_id（SHA-256）
```

`load_jsonl()` 一次性读取并返回完全驻留内存的不可变快照，后续评测
不再依赖原 JSONL 文件内容。

## JSONL Schema

每行一个独立 JSON object，只允许三个字段：

```json
{
  "case_id": "q001",
  "query": "BM25 索引在哪里重建？",
  "relevant_files": ["core/pipeline.py", "core/retriever/hybrid.py"]
}
```

- 未知字段、缺失字段一律拒绝（防止拼写错误被静默忽略）；
- 纯空白行稳定忽略；空文件 / 只有空白行拒绝；
- 第一版只允许至少一个相关文件的正例查询。

## 校验契约

| 字段 | 规则 |
|------|------|
| case_id | 非空字符串；只允许字母、数字、`-`、`_`；全集唯一 |
| query | 非空字符串；不得只含空白；首尾空白直接拒绝；完全重复拒绝 |
| relevant_files | 非空数组；每项字符串；拒绝绝对路径与 `..`；Case 内去重；规范化后与 `corpus.entries[].relative_path` 精确匹配 |

路径规范化：`\` 统一为 `/` → `PurePosixPath.as_posix()`（折叠 `./` 与
重复斜杠）→ 检测绝对路径（POSIX 绝对路径、盘符 `C:/`、UNC `//`）与
`..` → 与 Corpus 路径集合精确匹配（不做 basename 模糊匹配）→ 排序后
保存为 tuple，使标注顺序不影响身份。

## evaluation_set_id 的规范 payload

```python
payload = {
    "schema_version": 1,
    "corpus_id": corpus.corpus_id,
    "cases": [
        {"case_id": c.case_id, "query": c.query,
         "relevant_files": list(c.relevant_files)}
        for c in sorted_cases
    ],
}
canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
evaluation_set_id = sha256(canonical.encode("utf-8")).hexdigest()[:12]
```

绑定 schema_version + corpus_id + 全部规范化 Case（case_id、query
原文、排序后的 relevant_files）；禁止字段拼接、repr、对象地址、
JSONL 绝对路径、修改时间、输入行顺序。Corpus 内容改变 → corpus_id
改变 → evaluation_set_id 必然改变。

## 异常定位

所有解析/校验失败都带 JSONL 行号；能取得 case_id 时同时给出
case_id；JSON 解析失败时用 `raise ... from exc` 保留原始解析原因。

```text
第 4 行 case_id=q003：relevant_files 包含不属于 ExperimentCorpus 的路径 docs/x.md
```

## 教训

1. **标注的单位决定可复现性**：Chunk ID 是"分块策略 + 参数"的产物，
   文件相对路径才是跨策略稳定的身份；Chunk → 文件的映射留给下一任务
   （Index Manifest 已记录 relative_path → document_id）。
2. **严格 Schema 比宽容解析更安全**：未知字段拒绝、缺失字段拒绝，
   才能让拼写错误在数据构建期暴露，而不是在评测期变成脏数据。
3. **身份必须由规范内容决定**：行顺序、relevant_files 顺序都不参与
   ID；排序 + `sort_keys=True` + 固定 separators 的无歧义 JSON 是唯一
   payload。
4. **选择并测试空白行策略**：忽略纯空白行是稳定契约；空文件与
   只有空白行的文件仍必须拒绝。
