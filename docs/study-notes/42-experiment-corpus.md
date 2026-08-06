# ExperimentRunner 第四步：ExperimentCorpus 可复现语料清单

> 2026-08-05 — 242 → 256 passed（含复审序列化歧义修复）
> 语料清单固定"本次实验用了哪些文件及其内容版本"，否则指标无法
> 复现——文件内容变了，corpus_id 必须变，旧的实验结果才能被识别
> 为"过期"。

## 校验链：进入清单前的一切防御

`build(corpus_root, relative_paths)` 按顺序执行：

1. `corpus_root` 存在且是目录（`resolve()` 为规范绝对路径）；
2. 列表非空；
3. `relative_path` 非绝对路径；
4. `PurePosixPath.as_posix()` 规范化（统一分隔符、折叠 `./`），
   保留 `..` 供拒绝检查——任何 part 为 `..` 直接拒绝；
5. 重复路径拒绝（规范化后比较，`README.md` 与 `./README.md` 等价）；
6. 扩展名白名单 `.txt/.md/.pdf/.py/.js/.java`；
7. `(root / posix).resolve()` 后 `is_relative_to(root)`——符号链接
   逃逸拒绝（同 Workspace 的教训，见 study-notes 40）；
8. `is_file()` 必须是普通文件；
9. **不同目录同名文件拒绝**：`Pipeline.index_file()` 用 basename
   生成 document_id，`project-a/README.md` 与 `project-b/README.md`
   会互相覆盖——先保护，不改 Pipeline（临时兼容限制）。

## 哈希与排序

- SHA-256 用 `read_bytes()` **原始字节**，不文本解码——编码/换行
  转换（CRLF↔LF）不改变哈希；
- `entries` 按规范化 POSIX `relative_path` 排序——输入顺序无关。

## 复审教训：corpus_id 的序列化歧义

第一版用分隔符拼接：

```python
payload = "|".join(f"{path}:{sha}:{size}" for e in entries)
```

路径没有禁止 `:`/`|`，审计构造碰撞：

```text
清单 A: 两条 (x, h1, 1) + (y, h2, 2)
清单 B: 一条 (x:h1:1|y, h2, 2)
→ 两者 payload 都是 "x:h1:1|y:h2:2" → corpus_id 相同
```

**修复**：无歧义结构化序列化——JSON：

```python
data = [{"relative_path": ..., "sha256": ..., "size_bytes": ...} for e in sorted(entries)]
payload = json.dumps(data, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
```

- JSON 转义天然处理 `:`/`|`/引号/反斜杠；
- `sort_keys=True`：字典字段顺序无关；
- entries 先排序：输入顺序无关；
- `ensure_ascii=False` + 显式 UTF-8：中文路径可复现；
- 保持 12 位长度（48 bit，审计判定暂可接受）。

**通用教训：哈希输入的规范化是身份的一部分。** 拼接分隔符时，任何
字段都可能包含分隔符——用结构化序列化（JSON/长度前缀）而非未转义
字符串拼接；并且"字段顺序无关"要同时体现在实现（sort_keys）和
测试（构造顺序不同 → 同 ID）里。

## 与 ExperimentConfig 的对称性

| 维度 | ExperimentConfig | ExperimentCorpus |
|------|------------------|------------------|
| 身份 | experiment_id | corpus_id |
| 序列化 | 字段名序拼接 + SHA-256 | 排序 entries JSON + SHA-256 |
| 顺序无关 | dataclass 字段序固定 | entries 按 path 排序 |
| 敏感 | 任一字段变化 | 任一文件内容/路径变化 |
| 教训 | 39 号笔记（类型契约） | 本笔记（序列化歧义） |

两个身份都服务同一目标：**实验可复现、可比对、可寻址**。
