# 92-Gate5 工程交付基线与 Release-Readiness

> **任务**：G5-AUDIT-01-RELEASE-READINESS-BASELINE（R1-CROSS-REPO-PROVENANCE-AND-PRIORITY-CORRECTION）
> **性质**：只读审计，0 生产代码 / 0 DeepSeek / 0 benchmark / 0 Gate3 sealed access
> **产物**：`docs/experiments/gate5_release_readiness_baseline.md`（矩阵）+ `.json`（机器可读 checklist source）
> **日期**：2026-08-16
> **R1 修正**：§7.1 新增核心教学——`external repo ≠ unavailable data`、`unpinned external dependency = reproducibility gap`（语料已在 `wgqa/agent_data` 公开且身份核验一致，主项目缺跨仓 pinning/复现契约）。
> **本笔记定位**：从学习角度解释"Release Readiness"这个概念群，并映射到本项目审计中看到的真实证据。

---

## 1. 一句话

Gate 1–4 在造**能力**（RAG 管线、Agentic RAG、Structured Tool Agent、冻结评测），Gate 5 在造**可信交付**：让一个新环境（面试官的电脑、同学的电脑、CI 服务器）不需要你的脑内知识就能验证这个项目。

---

## 2. 什么是 release readiness（发布就绪度）

Release readiness = 判断"这个仓库现在能不能作为成品交付给别人"的一组检查项，而不是"代码能不能跑"。

类比：一道菜炒好了（功能完成），但不代表可以端上桌请客。还要问：

- 客人会不会做？（安装步骤）
- 同样的锅和火候，能不能复刻味道？（复现）
- 会不会有人吃坏肚子？（安全）
- 厨房脏不脏？（卫生）

本项目审计的 10 类正好对应这些"上桌"问题：

| 审计类别 | 对应"上桌"问题 |
|---|---|
| README / public narrative | 客人知不知道这道菜是什么、怎么吃 |
| Dependency reproducibility | 换一口锅，味道还一样吗 |
| Test / CI | 有没有自动尝菜的人（不能只靠厨师自己说好吃） |
| Container readiness | 能不能直接端一个标准套餐过去 |
| API surface | 吃法（接口）稳不稳、边界清不清楚 |
| UI reality | 表面上看到的是不是真能吃到的 |
| Configuration / secrets | 会不会把菜谱里的秘方（key）泄露出去 |
| Observability / Trace | 出问题时能不能看清是哪一步 |
| Public reproduction | 客人自己能不能照着复刻 |
| Release hygiene | 盘子里有没有杂质、灰尘、垃圾 |

**核心洞察**：能力是"做出来"，readiness 是"证明给别人"。

---

## 3. 为什么"代码能跑"不等于"项目能交付"

本项目的直接证据（G5-A01）：

- **代码确实能跑**：1716 passed + 4 skipped；本地能起 API 调 `/agent/query`、`/tool-agent/query`。
- **但交付不成立**：
  - 换一台机器，`local_files_only=True` 找不到 BGE 模型 → 启动即 503（`bge_emb.py:13`）；
  - 换一天装依赖，`pydantic>=2.0` 可能装到行为不同的大版本 → 测试结果漂移；
  - 想复现 Gate 3 冻结的 obligation 18/21：语料**已有独立 public data repo**（`wgqa/agent_data`，已核验与冻结身份逐字节一致，corpus_id=870e5864df67 / 37 files），但主项目**尚未冻结跨仓 commit/path/identity**，且实验 `config.yaml` 根本没入库——`external repo ≠ unavailable data`，真正的缺口是 `unpinned external dependency = reproducibility gap`。

"在我这能跑"是**单点事实**；"别人能跑出同样的结果"是**交付标准**。中间差的这一大段，就是 Gate 5 要补的。

---

## 4. requirements 与 lock file 区别（本项目最典型的 P0）

- **requirements.txt（当前项目状态）**：声明"最低可用版本"的**意图**。`pydantic>=2.0` 意思是"别给我 1.x"。但 2.0 和 2.9 可能是两个世界。
- **lock file（缺失）**：冻结**一棵完整的、逐字节可复现的依赖树**——每个包的确切版本 + 传递依赖版本 + 哈希校验。`uv.lock`/`poetry.lock`/`pip freeze` 都属于这一类。

用比喻：requirements 是菜单（"要一道辣子鸡"），lock file 是**精确菜谱加食材批次记录**（鸡 500g、花椒 3g、同一批油）。菜单保证"差不多"，菜谱保证"复刻一致"。

为什么这对 **AI 项目**尤其致命：`sentence-transformers` 会传递拉入 `torch`/`transformers`，这些库版本一变，embedding 数值可能变、tokenizer 行为可能变 → 冻结的 benchmark 数字悄悄失效。所以 lock 不只是"工程洁癖"，是**数字可信度的前提**。

---

## 5. CI 解决什么

CI（持续集成）解决的问题是**"没人盯着也能发现回归"**。

本项目的资产现状：

- 测试套件本身**已经适合 CI**：全部用 Fake/Mock（`test_api.py` patch Pipeline、`test_chunk_budget_infrastructure.py` 用 FakeBGEEmbedding），离线、不下载模型、不联网。这是先辈埋好的红利。
- 但仓库**没有 `.github/`**，等于"有体检仪器、没安排体检"。回归只能靠人肉跑，而人肉会忘。

CI 的另一层价值：**把"我声称能跑"变成"每次提交都被机器验证"**。面试官看 `.github/workflows/test.yml`，比看你嘴里的"我测过"更有说服力。

注意 CI 的边界：CI 验证的是**"代码在这个干净环境里行为正确"**，它不验证模型效果、不跑真实 LLM。所以 roadmap §10.3 要求"大型 BGE、Reranker、外部 LLM 测试用 marker/Fake/人工触发"。

---

## 6. Docker 解决什么、不解决什么

**Docker 解决**：
- **环境一致性（portability 的载体）**：把 Python 版本、系统依赖、模型缓存路径一起打包，避免"在我电脑上明明可以的"。
- **一键启动**：`docker compose up` 就是一个标准"套餐"。

**Docker 不解决**：
- **不解决模型缓存本身**：模型是 GB 级二进制，不进镜像（镜像会巨大）。要么预置、要么挂载。本项目 BGE `local_files_only=True`，镜像里没模型 → 照 503。所以 G5-DOCKER-04 必须把"数据/模型缓存挂载"当一等公民。
- **不解决 API key**：`.env` 不能进镜像，要用环境变量注入。
- **不解决代码逻辑错误**：镜像里跑的还是同一个 bug。
- **不解决评测可复现**：镜像不包含 37 文件语料。

所以 Docker 是"交付形态"的一部分，不是万能药。

---

## 7. reproducibility 和 portability 区别

这两个词经常被混用，但不同：

- **reproducibility（可复现）**：**同一份代码 + 同一份数据 → 得到同一份结果**。重点是"结果可核对"。本项目的实验身份（experiment_id、corpus_id、SHA 绑定）已经做到了评测侧的 reproduce；但公共侧还差：语料没入库、config 没入库。
- **portability（可移植）**：**换一个环境，还能跑起来**。重点是"环境迁移"。Docker、lockfile、`.env.example` 都是 portability。

| | 问的问题 | 本项目现状 |
|---|---|---|
| reproducibility | "换台机器能算出同样的数字吗？" | PARTIAL：语料已在 public repo `wgqa/agent_data` 且身份核验一致，但跨仓未 pin、实验 config 未入库 → 缺冻结的身份链 |
| portability | "换台机器能启动吗？" | MISSING：无 lock、无 Docker、模型缓存前置未文档化 |

一句话：**能移植不等于能复现，能复现不等于能移植**。本项目两件都还没做完。

### 7.1 external repo ≠ unavailable data；unpinned external dependency = reproducibility gap

这是本 R1 修正最重要的概念区分，面试高频：

- **数据在外部仓库 ≠ 数据拿不到**。本项目冻结语料就在 GitHub `wgqa/agent_data`（default branch `master`，HEAD `179f18e8`），任何人 `git clone` 就能拿到，并且它**已经用现有 `ExperimentCorpus.build` 核验过**：对 37 个文件逐字节重建出与冻结完全一致的 `corpus_id=870e5864df67`。所以"语料没公开"是**错误表述**。
- **外部依赖没 pin 住 = reproducibility gap**。真正的问题是：主仓库**没有把 `agent_data` 的哪个 commit / 哪条路径 / 什么身份校验冻结进任何可复现契约**。`master` 是移动的；今天一致，明天 `agent_data` 一更新，语料字节就可能变，冻结数字就静默失效。**语料 public 只保证"可获取"，pin 住才保证"可复现"**。
- 推论：`git submodule` / 锁 commit + 自动 `corpus_id` 校验，是把"外部依赖"变成"冻结依赖"的标准手段（G5-ENV-02 的 P0-3 目标）。

用比喻：食谱书在图书馆人人都能借到（external ≠ unavailable），但你要在菜谱上**写死"用 2026-08-07 那一版"**（pin），否则明天书改版了味道就不一样了。

---

## 8. Secret / config 为什么属于工程能力

有人觉得"API key 放哪"是小事。但这是**能力信号**：

- **做对了**（本项目现状）：`.env` gitignored、`Config.dump()` 脱敏、API 默认 `127.0.0.1`、README 明示公开部署需认证/TLS/限流 → 说明作者**懂安全默认值**。
- **做漏了**：无 `.env.example`（新用户不知道该配什么）；`/stats` 返回原始 Config 对象而非脱敏快照（`app.py:373`，虽无 key，但暴露 `vector_store_path` 等内部路径）。

安全能力在面试里的体现不是"我用了 xxx 框架"，而是"我知道默认值应该收敛、密钥不能进仓库、日志不能带 raw/CoT"。本项目 trace 白名单（`_safe_trace`）本身就是这个能力的展示点。

---

## 9. 为什么 AI 项目尤其需要模型/数据/artifact 身份

普通软件：同一份代码 + 同一份输入 → 同一份输出（确定性）。
AI 项目：**模型权重、模型版本、语料字节、评测集、Prompt 版本、随机种子**任何一个漂移，数字就不成立。

所以本项目在 Gate 2/3/4 反复做同一件事：**给每一份"会变的东西"一个身份**。

- 语料 → `corpus_id=870e5864df67`（37 文件 + SHA）；
- 评测集 → `evaluation_set_id` / `jsonl_sha256`；
- 实验 → `experiment_id` / `run_id` / `source_commit`；
- 系统冻结 → `gate3_system_freeze_id=2ec11a69b173`、`gate4_system_freeze_id=96c159b1ca2c`。

**为什么必须**：因为 AI 结果没有"正确的唯一答案"，只能用**身份 + 冻结字节**来锁死"这就是当时跑的那一份"。没有身份，任何数字都可以被怀疑"你是不是换了个模型重跑的"。

审计里发现的缺口正是身份链的**断点**：冻结语料的字节身份虽可经 `wgqa/agent_data@master` 重建（已核验一致），但主项目**没有把跨仓 commit 钉进冻结契约**，且实验 `config.yaml` 未入库 → 别人无法重建"当时跑的完整身份"（语料来源 + 参数）。

---

## 10. 为什么不能把本地 smoke 当公共复现

本地 smoke（比如 Gate 4 的 6 条 HTTP 200、或"我本地起了服务调了一下"）验证的是**"这条路通不通"**，不是**"别人能不能复现"**。差异点：

1. **本机有模型缓存** → smoke 通过，换台没缓存的机器直接 503；
2. **本机有 `.env`** → smoke 能生成答案，新 clone 没 `.env` 不知道要配什么；
3. **本机语料与冻结身份对齐（但未 pin 跨仓）** → 今天 benchmark 数字能算；别人虽可从 `wgqa/agent_data` 拿到同一批文件（语料已 public 且身份核验一致），但 README 没给"拉取+核验"命令，`master` 一移动就对不上了；
4. **本机是 Windows + 中文用户名** → 连 `pytest.ini` 的 `basetemp` 都是为它打的补丁。

公共复现的标准是：**README 上一行命令 → 新机器从零到结果**。本地 smoke 只证明"我能跑"，公共复现才证明"任何人都能跑出和我一样的东西"。

---

## 11. Gate 5 为什么不继续堆 Agent 技术

Gate 1–4 已经做了四轮能力叠加：RAG → Agentic RAG → Structured Tool Agent → 冻结评测。继续加新 Agent 能力（更强 Planner、更多 Tool、更复杂的 Loop）是**边际收益递减**：

- 面试官看不出 Gate 5 级的新 Agent 能力带来的差别，但**一眼就能看出"连 CI 都没有、README 是 8 月的旧叙事、clone 下来跑不起来"**；
- 招聘方要验证的是**工程可信度**，不是算法炫技；一个能复现、能测试、能 Docker 化的项目，比一个"更强但谁也跑不起来"的项目有说服力得多；
- 新增能力会**污染冻结证据**：任何 Agent 改动都可能让 Gate 3/4 的冻结数字需要重新解释。冻结的 RAG 不重跑，是纪律。

所以 Gate 5 的主题从"造能力"切换为"收口交付"：把已有能力变成**可证明、可复现、可移植、可演示**。

---

## 12. 本项目 10 类差距的面试式总结

面试官可能问："这个项目有什么工程亮点？"

正确回答不是背 Gate 3/4 的数字，而是展示**分层可信度**：

| 层面 | 已做 | 待做（Gate 5） |
|---|---|---|
| 能力 | 三类 API、1716 测试、Agentic/Tool Agent | — |
| 可信 | 冻结身份链（eval/run/freeze id）、offline seal；语料字节身份已核验与 public repo `wgqa/agent_data` 一致 | 跨仓 commit pinning、lockfile、实验 config 入库 |
| 可移植 | `.env` 隔离、`127.0.0.1`、上传安全边界 | Docker、`.env.example` |
| 自动验证 | 测试全 Fake 离线 | CI 管道 |
| 公开叙事 | 冻结 JSON 证据齐全 | README 重写、单命令复现 |

---

## 13. 常见错误

1. **把"我本地能跑"当"交付就绪"**——第 10 节。
2. **以为 lockfile 只是加个文件**——它锁的是**整棵依赖树 + 哈希**，不是声明几个版本。
3. **以为 Docker 是终点**——Docker 不做模型缓存、不做 key、不做评测复现。
4. **把 reproducibility 和 portability 混为一谈**——一个是结果可核对，一个是环境可迁移。
5. **以为 CI 是"多跑一遍测试"**——CI 是"每次提交都被机器验证"的持续约束。
6. **忽视 `.env.example` 这种小文件**——它是"别人能不能上手"的第一个门槛。
7. **认为不加 LICENSE 无所谓**——只要可能公开，它就是标准交付物。
8. **让 `git status` 堆满垃圾**——129 个 `.tmp_pytest_*` 目录，本身就是一种工程态度的展示。
9. **把"语料在外部仓库"说成"语料拿不到"**——`external repo ≠ unavailable data`；本项目语料已在 `wgqa/agent_data` 公开且身份核验一致，真正的缺口是 `unpinned external dependency`（主仓库没 pin 跨仓 commit / path / identity）。

---

## 14. 下一步

- 审计矩阵与 JSON：`docs/experiments/gate5_release_readiness_baseline.{md,json}`（R1 修正：语料 cross-repo provenance 重定义 + P0-1..P0-4 收敛；后续每张 Gate 5 任务的 checklist source）。
- P0 顺序：G5-ENV-02（P0-1 lockfile + P0-3 跨仓 pinning/复现契约 + P0-4 实验 config 重建 + `.env.example`）→ G5-CI-03（P0-2）→ G5-DOCKER-04（P1）→ G5-README-08；P2 项顺带收口。
