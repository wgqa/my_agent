# 93-Gate5 可复现环境与输入锁定

> **任务**：G5-ENV-02-REPRODUCIBLE-ENVIRONMENT-AND-INPUTS
> **性质**：依赖 lock（P0-1）+ public data lock（P0-3）+ 实验 config 可审计化（P0-4）；不碰 CI/Docker/README 大改
> **日期**：2026-08-16
> **本笔记定位**：从学习角度讲清楚"环境可复现"这一组概念，并用本项目真实证据说明为什么 lock/pin/身份是硬要求。

---

## 1. 一句话

本卡把"用什么 Python/依赖、哪一版公开语料、哪些正式实验参数"从**人脑里的知识**变成**仓库里可核验的契约**。

---

## 2. requirements vs lock

| | requirements.txt | lock（本卡新增） |
|---|---|---|
| 表达 | "最低可用版本"的**意图** | "精确到这一棵依赖树"的**事实** |
| 覆盖 | 直接依赖 | 直接 + 传递依赖 + 确切版本 + 哈希 |
| 可复现 | 今天能装、明天可能装出不同 | 同一 lock 恒得同一环境 |
| 类比 | 菜单（"要辣子鸡"） | 菜谱 + 食材批次记录 |

本项目 `requirements.txt` 是宽松下限（`pydantic>=2.0`…）。新增的 lock 文件（`pip freeze` 导出）把当前 Python 3.14 环境里**实际装到的一组确切版本**完整钉住。

**重要边界（如实记录）**：本卡只能声明 **Python 3.14 已验证**（干净 venv 从 lock 安装 + 全量测试通过）。**不能宣称 3.11 已验证**——3.11 兼容性留给 CI 卡用实际矩阵证明。lock 是"这台机、这个 Python 的复现锚"，不是"所有 Python 的承诺"。

---

## 3. direct vs transitive dependency

- **direct（直接依赖）**：你的代码里直接 `import` 的包。本项目顶层只有约 20 个（fastapi / chromadb / sentence-transformers / openai / pydantic…）。
- **transitive（传递依赖）**：这些包自己依赖的包。`sentence-transformers` 会拉入 `torch`、`transformers`、`huggingface-hub` 等——它们不在 `requirements.txt` 里，但**决定了 embedding 数值是否一致**。

为什么必须一起锁：只锁 direct 依赖，传递依赖仍然随日期漂移。torch 换个 patch 版本，tokenizer/矩阵行为可能变 → 冻结 benchmark 数字悄悄失效。lock 的价值就是**连看不见的传递依赖也钉死**。

---

## 4. 为什么"我的电脑能跑"不等于环境可复现

本项目四个真实反例：

1. `bge_emb.py:13` / `bge_reranker.py:16` 用 `local_files_only=True` → 我的机器有 HF 缓存能跑，新机器没缓存直接 503。
2. 依赖是 `>=` 下限 → 我的环境测过，明天新装的是另一套版本。
3. `.env` 有 `DEEPSEEK_API_KEY` → 我能生成答案，新 clone 没有。
4. `pytest.ini` 的 `basetemp` 是我这台 Windows 中文用户名环境的补丁。

"我本地全绿"是一个**单点观测**；"换台干净机器从 lock 安装还能全绿"才是**可复现**。本卡验收的核心动作就是：干净 venv → `pip install -r <lock>` → 全量测试。

---

## 5. external repo commit pinning

上一卡（G5-AUDIT-01-R1）已确立：语料在独立 public repo `wgqa/agent_data`，不是"别人拿不到"。但 **public ≠ 可复现**——`master` 是移动的。

本卡新增 `reproducibility/public_data_lock.json`，把三样东西钉死：

- **commit**：`179f18e812ad63c36c5569de8e86c5ff9a931cb5`
- **path**：`agent_ai_v1/02_corpus_candidate`
- **identity**：`corpus_id=870e5864df67`、`file_count=37`

配套 `scripts/verify_public_corpus.py`：`--data-root <agent_data checkout>`，校验 HEAD==锁定 commit、语料路径存在、用现有 `ExperimentCorpus.build` 重建出相同 corpus_id/file_count，任一不符 **fail-fast**（退出码非 0）。

为什么 pin commit 而不是"clone master"：master 今天一致、明天可能漂移。pin 住 commit，才保证"验证时看到的字节 == 冻结时的字节"。

---

## 6. corpus_id 为什么比"文件夹名字一样"可靠

"文件夹名字一样"是**表面特征**——文件列表一样不代表内容一样（改名、改一个字节都看不出来）。

`corpus_id` 是**内容指纹**：对每个文件算 SHA-256 + size，按相对路径排序后对结构化清单再算 SHA-256，取前 12 hex。任一文件任一字节变化 → corpus_id 必变。

所以验证语料不是"看看 37 个文件在不在"，而是"逐字节重建出同一个 corpus_id=870e5864df67"。`ExperimentCorpus.build` 就是这个现有逻辑，verify 脚本直接复用它，没有另造一套。

---

## 7. experiment config 为什么属于实验 provenance

一个实验的"身份"不只是结果数字，而是 **"用什么参数跑出来的"**。参数记录（experiment config）是 provenance 的一部分：没有它，结果无法解释、无法复现、无法审计。

本项目的设计：`ExperimentConfig` 把所有实验参数做成 frozen dataclass，`experiment_id = 按字段序序列化后 SHA-256[:12]`。**同一个参数集恒得同一个 id，任一参数变化 id 必变**。目录名就是 experiment_id，tracked 的 `index_manifest.json` 里同时记录了 `experiment_id` 和 `config` 参数集——这是运行时写下的、git 不可变的审计记录。

---

## 8. 为什么不能根据 result.json 猜历史 config

本卡 P0-4 的关键教训——**身份不可逆**：

- `experiment_id` 是 SHA-256 的**前 12 位**，是单向哈希。给你一个 id，你**推不出**原始参数。
- 更隐蔽的是：`ExperimentConfig` 的**字段集在 Gate 2 期间演进过至少 4 次**（rrf_k 规范化 → embedding identity → rrf_tie_breaker → IMPL-20 加 budget/runtime 字段）。同样的参数集，在不同 schema 下算出的 id 不同。
- 实测：用**当前** schema 对 12 份 config.yaml 重建，只有 3 份 aligned（IMPL-20 之后）能对上目录名；其余 9 份（Gate 2，更早 schema）对不上。用"旧 11 字段"近似重建也只能对上约一半。

**结论**：历史 experiment_id 无法用当前代码可靠重推导。所以本卡**没有**"猜一个旧 schema 去凑 id"，而是：
1. 用 tracked `index_manifest.json` 的 `experiment_id == 目录名` 绑定作为**审计锚点**（这条对全部成立）；
2. 对当前 schema 可重建的 aligned 实验，契约测试断言重建==目录名；
3. pre-IMPL-20 实验的 id 是**运行时记录的冻结引用**，测试只验绑定、不伪造重建。

这正是任务卡的护栏：**不能为了 checklist 变绿制造伪 provenance**。

---

## 9. 为什么那 12 份 config.yaml 没入库（如实报告）

本机存在 12 份 untracked `experiments/*/*/config.yaml`。按任务流程逐一验证后**决定不提交**，两个硬理由：

1. **身份不可证**：多数 config 无法用当前/近似 schema 重建出目录名 experiment_id（第 8 节）；
2. **含绝对路径**：每份都带 `vector_store.path: D:\学习\...`（本机绝对路径），扫描命中"绝对本地路径"，按约束不能原样提交。

因此：**正式实验参数的可审计记录 = 已 tracked 的 `index_manifest.json`（config 字段 + experiment_id 绑定）**，而不是这 12 份 workspace 运行时文件。契约测试新增 `test_no_absolute_path_or_secret_in_tracked_configs` 防止未来把带绝对路径/secret 的 config 提交进来。

---

## 10. 验收动作与零副作用声明

- 干净 venv：`pip install -r <lock>`（P0-1 环境契约）
- `python -m pytest -q --basetemp=.tmp_pytest_g5env02`（全量，≥1716 passed + 4 skipped，passed 只升不降）
- `python scripts/verify_public_corpus.py --data-root <agent_data checkout>`（P0-3 语料契约，正向 OK / 负向 fail-fast）
- `git diff --check`
- 证明：commit=`179f18e…`、corpus_id=`870e5864df67`、file_count=37、0 secret / 0 绝对私有路径 / 0 sealed access

本卡未改 RAG / Agent / Tool / Prompt / Runtime，未跑 DeepSeek / Gate3 / Gate4 benchmark，未访问 Gate3 sealed，未复制语料，未引入 submodule。
