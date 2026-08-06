# ExperimentRunner 第二步：ExperimentWorkspace 独立实验工作区

> 2026-08-05 — 213 → 228 passed（含复审路径逃逸修复）
> 实验隔离的第一步：每次实验一个独立目录、一份独立向量库、一份
> 覆盖实验字段后的派生配置，杜绝"不同实验共享旧索引"的失真。

## 为什么需要独立工作区

Pipeline 从 YAML 构建，ChromaDB 路径由 `vector_store.path` 决定。
如果不隔离：实验 A 改了 chunk_size 后跑实验 B，B 检索的仍是 A 的
旧索引——这正是 E-02（chunk_strategy 保护）禁止的失真。与其在
Evaluator 里拒绝，不如让每次实验天然拥有自己的索引。

## 目录结构与派生配置

```
<workspace_root>/<experiment_id>/<run_id>/
├── config.yaml      # 派生配置
├── vector_store/    # 独立 ChromaDB（绝对路径写入派生配置）
└── result.json      # 结果文件（运行时写）
```

- `experiment_id` 来自 ExperimentConfig（同配置同目录，重复运行
  同 run_id 会被 FileExistsError 拒绝）；
- `run_id` 只允许 `[A-Za-z0-9_-]+`——构造即校验，防路径穿越；
- 派生配置：读基础 YAML 只读不写，保留 embedding/generator/reranker
  等非实验配置，覆盖 8 个实验字段（字段名与 `core/config.py` 读取
  键严格一致：`chunker.size_tokens`/`overlap_tokens`/`retriever.rrf_k`）；
- `vector_store.path` 写入工作区内**绝对路径**——相对路径会随 CWD
  漂移，不同进程跑同一个工作区会指向不同位置；
- 写入用 `mkstemp` + `os.replace` 原子替换，避免崩溃留下半个 YAML。

## 复审教训：符号链接路径逃逸

第一版用字符串前缀判断路径归属：

```python
str(p.resolve()).startswith(root)   # 脆弱且不正确
```

复审构造 `runs/<experiment_id> → /tmp/outside` 符号链接，`prepare()`
把工作区建到了根目录外。修复：

```python
candidate = (root / experiment_id / run_id).resolve()
if not candidate.is_relative_to(root):
    raise RuntimeError("实验工作区路径逃逸 workspace_root……")
```

**三个要点**：
1. `workspace_root` 先在 `__init__` 中 `resolve()` 为规范绝对路径；
2. 归属判断用 `Path.is_relative_to()`（真正的路径语义，解析符号链接），
   不是字符串前缀；
3. 校验发生在 `mkdir()` **之前**——逃逸时不留下任何外部目录。

## 测试：平台兼容的目录链接

审计环境是 Linux（symlink），开发环境是 Windows（无 symlink 特权，
`WinError 1314`）。测试用**双通道兜底**：

```python
try:
    link.symlink_to(target, target_is_directory=True)
except (OSError, NotImplementedError):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], ...)
```

junction 不需要管理员权限，且 `Path.resolve()` 同样会跟随它——
两条路径都能真实复现逃逸场景，测试在任意平台都验证到核心逻辑。

## 教训

1. **路径归属校验是安全边界**：`resolve()` 解析链接后再判断，
   且判断必须是路径语义（is_relative_to），不是字符串前缀。
2. **平台差异要写进测试**：跳过测试（`pytest.skip`）会静默失去
   覆盖；用等价机制（junction 替代 symlink）保持验证真实发生。
3. **派生配置的字段名是与 Config 的契约**：写错一个键，实验就
   跑在默认值上——靠 Runner 的一致性校验兜底（见 study-notes 41）。
