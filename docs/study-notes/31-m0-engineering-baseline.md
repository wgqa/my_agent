# M0：工程基线（规范化修整全记录）

> 2026-07-24 — 4 个任务全部完成并推送 GitHub

## 概览

| 任务 | 目标 | 提交 |
|------|------|------|
| M0-T1 | Git 初始化 + 基线冻结 | `8993841` |
| M0-T2 | 测试完全隔离 | `232ebf6` |
| M0-T3 | 配置校验 + Fail Fast | `4b0c2ed` |
| M0-T4 | README + 启动脚本 + 依赖 | `fd24ada` |

---

## M0-T1：基线冻结

### 做了什么

1. `git init` 初始化仓库
2. 创建 `.gitignore`，排除 `data/vector_store/`、`*.pyc`、`.env`、`.pytest_cache/` 等
3. 记录环境基线：Python 3.14.0，Windows 11，61 passed + 6 PermissionError
4. 初始提交（100 个文件，6277 行），推送 `https://github.com/wgqa/my_agent.git`

### 为什么

后续任何修改都有版本对照。`.gitignore` 防止密钥和数据文件被误提交。

### 关键文件

```
.gitignore
docs/baseline.md
```

---

## M0-T2：测试隔离

### 修了什么问题

| 问题 | 文件 | 修复 |
|------|------|------|
| `./data/test_store` 硬编码相对路径 | `test_pipeline.py` | 改用 `tmp_path` fixture |
| `"sk-test"` 被新版 OpenAI SDK 拒绝 | `test_pipeline.py` | 改用合法格式 `"sk-0000..."` |
| 默认 embedding provider 是 openai | `pipeline.py` 第 57 行 | 改为 `"bge"` |

### 新增 4 个隔离验证测试

- `test_pipeline_does_not_create_default_store_dir` — 无配置不崩溃
- `test_pipeline_uses_injected_in_memory_store` — 内存模式正常
- `test_persistent_store_uses_tmp_path` — 持久化到临时目录
- `test_tests_are_independent_of_execution_order` — collection_name 隔离

### 关键改动对比

**test_pipeline.py（旧 vs 新）：**
```python
# 旧
config = {"vector_store": {"path": "./data/test_store"}}
with tempfile.TemporaryDirectory() as tmpdir:
    ...

# 新
def test_pipeline_with_bge_embedding(tmp_path):
    store_dir = tmp_path / "vector_store"
    config = {"vector_store": {"path": str(store_dir)}}
    ...
```

**pipeline.py 默认 embedding：**
```python
# 旧：provider = cfg.get("provider", "openai")  → 无 config 时尝试 OpenAI
# 新：provider = cfg.get("provider", "bge")      → 无 config 时本地 BGE
```

---

## M0-T3：配置校验与 Fail Fast

### 新增 `core/config.py`

旧方案：配置是原始 YAML 字典 `{}`，各方法里靠 `self.config.get("key", default)` 取值。key 拼错不报错，overlap >= size 不报错。

### Config 类三道校验

**第一道：白名单（provider/strategy）**
```python
if prov not in ("bge", "openai"):
    raise ConfigError(f"未知 embedding provider: {prov}")
```

**第二道：数值边界**
```python
if self.chunk_overlap >= self.chunk_size:
    raise ConfigError(f"overlap ({self.chunk_overlap}) >= size ({self.chunk_size})")
```

**第三道：关联校验**
```python
if self.reranker_candidate_k < self.reranker_final_k:
    raise ConfigError(...)
```

### 在 Pipeline 中的使用变化

```python
# 旧：cfg.get("size_tokens") or cfg.get("chunk_size", 512)
# 新：self.config.chunk_size

# 旧：cfg.get("path", "./data/vector_store")
# 新：self.config.vector_store_path
```

### Fail Fast 效果

| 场景 | 旧行为 | 新行为 |
|------|--------|--------|
| provider 写错 | 静默降级 | 启动报错 |
| overlap >= size | 无效分块 | 启动报错 |
| candidate_k < final_k | Reranker 异常 | 启动报错 |

---

## M0-T4：README + 启动脚本 + 依赖

### README.md

10 个部分：项目目标、当前能力、架构图、环境要求、安装、测试、启动、配置、已知限制、Roadmap。

### requirements.txt 补充

| 包 | 原因 |
|------|------|
| requests | Streamlit UI 直接依赖 |
| python-multipart | FastAPI 文件上传 |
| jieba | BM25 中文分词 |
| tiktoken | TokenCounter |
| pytest | 测试框架 |

### start.ps1

Windows 一键启动脚本（API + UI 两个新窗口）。

### api/app.py 修复

- 添加 `load_dotenv()` 加载 `.env`
- `/health` 端点改用 Config 属性访问
