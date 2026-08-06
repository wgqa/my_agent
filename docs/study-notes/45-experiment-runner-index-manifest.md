# ExperimentRunner 可复现语料入库与原子 Index Manifest（G2-ER-05 / R1）

> 2026-08-06 — 314 → 332 passed（G2-ER-05）
> 2026-08-07 — 332 → 334 passed（G2-ER-05-R1）
> 入库阶段的目标不是"能写进向量库"，而是"这次实验用了哪些文件、
> 什么内容版本、生成了什么索引，都能被完整复现和审计"。

## 入库状态机

```text
Manifest 已存在？ ──是──> FileExistsError（index_file 调用 0 次）
      │否
      ▼
入库前完整性校验（一次性验证全部文件）
      ▼
按 corpus.entries 顺序逐文件 pipeline.index_file()
      ▼
每文件 status 必须 == "create"（no_change/update 立即失败）
      ▼
vector_store.count() == 所有 chunks 之和
      ▼
Hybrid：_rebuild_sparse_index(strict=True) + sparse_count == vector_count
      ▼
原子写入 index_manifest.json（临时文件 → flush → fsync → os.replace）
```

失败语义：原异常向外传播；不留下成功 Manifest；保留 Workspace 和
部分索引用于诊断；不把工作区标记为 indexed/success。

## 入库前完整性校验

必须在第一次 `index_file()` 前重新读取全部语料原始字节并一次性验证：

- 文件仍然存在、仍是普通文件；
- 实际 `size_bytes` 与 `CorpusEntry` 一致；
- 实际 SHA-256 与 `CorpusEntry` 一致；
- `resolve()` 后真实路径仍在 `corpus_root` 内；
- 不静默重算 `corpus_id`。

## R1：根目录锚点不可变（阻塞修复）

原实现把锚点写成：

```python
root = Path(corpus.corpus_root).resolve()
```

Bug：`ExperimentCorpus.build()` 已经把 `corpus_root` 保存为构建时的
规范真实路径；但如果 build 后整个根被删除并替换成指向外部的
Windows Junction / 符号链接，第二次 `resolve()` 会把外部目标当作新的
可信根，导致路径逃逸校验错误通过。

修复：锚点必须是构建时记录的路径本身，不再二次 resolve 后当新根：

```python
anchor = Path(corpus.corpus_root)          # build 时的规范可信根
if not anchor.exists(): raise FileNotFoundError(...)
if not anchor.is_dir():  raise ValueError(...)
if anchor.resolve() != anchor:
    raise ValueError("corpus_root 在构建后被重定向或替换：anchor -> resolved")
```

每个文件仍按 `(anchor / relative_path).resolve()` +
`is_relative_to(anchor)` 校验，保证"内部 subdir 被重定向到外部"同样
被拦截（该测试保留）。

校验函数返回已验证的规范路径：

```python
validated_paths: tuple[Path, ...]
```

`index_corpus()` 用 `zip(corpus.entries, validated_paths)` 按相同顺序
直接调用这些路径，避免校验后重新拼装另一套路径。

## Index Manifest

字段：

```text
schema_version / experiment_id / corpus_id / chunk_strategy /
retriever_strategy / config（完整 ExperimentConfig）/ corpus_entries /
files（relative_path + sha256 + size_bytes + document_id + chunks + status）/
file_count / total_chunks / vector_store_count / sparse_index_count（非 Hybrid 为 null）
```

要求：UTF-8 JSON、字段明确、`sort_keys=True` 稳定序列化、不写绝对
`corpus_root`、不写 API Key、不写对象 repr/内存地址；相同配置 + 相同
Corpus + 相同入库结果 → 相同业务内容。

## Hybrid 稀疏一致性

`retriever_strategy == "hybrid"` 时调用现有严格重建
`pipeline._rebuild_sparse_index(strict=True)`，再校验
`retriever._bm25.doc_count == vector_store.count()`；不一致立即失败，
不允许 Hybrid 以 Dense-only 状态完成。simple/mmr 不强求 BM25。

## 测试策略

- 普通测试全部使用 FakePipeline / FakeVectorStore / FakeBM25，不加载
  真实模型、不调用网络、不写真实用户目录；
- 链接测试辅助先尝试 `symlink_to()`（Linux / Windows 开发者模式），
  失败回退 `cmd /c mklink /J`（Windows Junction），两者都不可用时跳过；
- R1 回归测试：build 后删除整个 `corpus_root`，替换为指向外部的
  junction/symlink，外部目录放同名、同大小、同 SHA-256 文件；断言
  第一次 `index_file()` 前失败、`pipeline.calls == []`、无 Manifest；
- 保留内部 subdir 逃逸测试，并新增未重定向时按 entries 顺序入库的
  正常路径测试。

## 教训

1. **"可信根"只能定义一次**：一旦 `ExperimentCorpus.build()` 把
   `corpus_root` resolve 成规范路径，它就成为身份的一部分；运行期
   再次 resolve 并替换锚点，等于把"验证过的世界"换成了"当前的世界"。
2. **校验与消费要共享同一份结果**：校验函数返回 `validated_paths`，
   入库直接使用，避免校验一套路径、执行另一套路径。
3. **回归测试要构造"看起来完全合法"的攻击**：外部文件同名、同大小、
   同 SHA-256，只有路径身份不同——正是这种案例才能证明校验检查的
   是身份而非内容。
4. **明确 TOCTOU 边界**：本次只修复确定性根目录锚点丢失；"校验完成
   与读取之间"被恶意并发进程瞬间替换的完整 TOCTOU 不在范围内，属于
   已声明的未处理边界。
