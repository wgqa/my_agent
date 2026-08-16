# Gate 5 Release Readiness Baseline

> **任务卡**：G5-AUDIT-01-RELEASE-READINESS-BASELINE（R1-CROSS-REPO-PROVENANCE-AND-PRIORITY-CORRECTION）
> **性质**：只审计，不修实现（0 生产代码改动 / 0 DeepSeek / 0 Gate 3 rerun / 0 Gate 4 rerun / 0 HTTP smoke / 0 benchmark；本 R1 另含 0 Gate 3 sealed Holdout access）
> **基线 commit**：`2d5d0380b6eab5826c22ed260a245318f6e37e58`（G5-AUDIT-01 基线）
> **日期**：2026-08-16
> **R1 修正**：重新定义 frozen corpus gap（语料已在 public data repo `wgqa/agent_data` 且身份核验一致，主项目缺跨仓 pinning/复现契约）；P0 收敛为 P0-1..P0-4（Docker 降 P1）；Study Note 92 概念修正。
> **机器可读版**：`gate5_release_readiness_baseline.json`（后续 Gate 5 每张任务的 checklist source）

---

## 0. 一句话结论

仓库的**核心能力（Gate 1–4 全链路 + 1716 测试 + 正式冻结评测）已经完全能跑**，但**公开交付面（README / 依赖锁定 / CI / Docker / 公共复现 / 仓库卫生）几乎全部还是空白的**。今天直接发给面试官/同学，对方能跑通基础 RAG 和两个 Agent 端点，但看不到 Gate 3/4 的价值、无法复现任何冻结数字、也没有 CI/Docker 证明工程能力。

---

## 1. 回答"今天直接发给面试官/同学"的问题

| 问题 | 结论 | 说明 |
|---|---|---|
| 什么已经能用？ | READY | 三类 API（`/query` `/agent/query` `/tool-agent/query` `/health`）、Streamlit UI（基础 RAG）、全量 1716 测试（本地 + 模型缓存环境）、索引/检索/生成全链路 |
| 什么只是本机能用？ | PARTIAL | 冻结语料已在**独立 public data repo** `wgqa/agent_data`（`https://github.com/wgqa/agent_data.git`，default branch `master`，当前 HEAD `179f18e8`）并已核验与冻结身份一致（corpus_id=870e5864df67 / 37 files），但主项目**尚未冻结跨仓 commit/path/identity 与公开复现流程**；Gate 3 dev/holdout 数据集仍本机独有（`agent_data` 中 `gate3/` 未 tracked）；`local_files_only=True` 要求本机已缓存 BGE 模型 |
| 什么能复现？ | PARTIAL | Gate 4 评测集（24 case）在仓库内可复现；测试用 Fake 模型离线可跑；冻结结果 JSON 已入库；**Gate 2 冻结语料可经 `wgqa/agent_data@master`（179f18e8）拉取并逐字节重建出同一 corpus_id=870e5864df67** |
| 什么不能复现？ | MISSING | 任何 benchmark 数字（Gate 2/3/4）在新环境**一键**无法复现：无依赖锁、无单命令复现、实验 `config.yaml` 未入库、Gate 3 dev 数据集不在任何 public repo、主项目未 pin 语料所在 agent_data commit |
| 什么有自动测试？ | READY | 1716 passed + 4 skipped，测试全部用 Fake/Mock（离线、不下载模型、不联网） |
| 什么没有 CI？ | MISSING | 仓库无 `.github/`，无任何 CI 管道 |
| 什么能 Docker 化？ | MISSING | 无 Dockerfile / compose / .dockerignore / 健康检查约定 |
| 哪些 API 已完成？ | READY | `/health` `/index/file` `/query` `/agent/query` `/tool-agent/query` `/stats` 均已实现并有测试 |
| 哪些 UI 没接？ | PARTIAL | UI 只接基础 `/query` `/index/file` `/health` `/stats`；`/agent/query` 与 `/tool-agent/query` 未接入 |
| 哪些文档已过时？ | PARTIAL | README 严重落后（只描述早期基础 RAG）；`docs/known-issues.md` 停留在早期 Bug；HANDOFF/roadmap 相对最新但需 Gate 5 收口 |
| 哪些 Secret/配置存在部署风险？ | PARTIAL | 无 `.env.example`；`/stats` 暴露未脱敏的 Config 对象；无鉴权/限流（仅 localhost，属有意边界） |
| 哪些必须修 / 哪些 nice-to-have？ | — | 见 §3 P0/P1/P2 汇总 |

---

## 2. 十类审计矩阵

每条分类定义：`READY` / `PARTIAL` / `MISSING` / `BLOCKED` / `NOT_IN_SCOPE`。

### 2.1 README / public narrative — PARTIAL

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| README 覆盖 Gate 1–4 | PARTIAL | `README.md`（2047 B）只有"文件上传→Loader→Chunker→Embedding→Retriever→Reranker→Generator"一条管线；零 Gate 3 Agentic RAG、零 Gate 4 Structured Tool Agent、零三类 API、零正式实验结果、零 Holdout/Safe Trace、零 limitations（L1-L6） | 面试官只能看到基础 RAG，看不到整个项目最有价值的 Gate 3/4；数字适用范围无人知道 | P1 | G5-README-08（重写 README） |
| 三类 API 呈现 | MISSING | README 只提 `/query`（未列 `/agent/query` `/tool-agent/query`） | 端点存在但公开面不可见 | P1 | G5-README-08 |
| 正式实验结果呈现 | MISSING | README 无 Gate 2 freeze / Gate 3 holdout（obligation 18/21、answer pass 4/10）/ Gate 4 baseline（task_completion 20/24）任何数字 | 冻结成绩散落在 `docs/experiments/*.json`，README 不引用 | P1 | G5-README-08 |
| Quick Start 准确性 | PARTIAL | 有安装/配置/测试/启动段落，但缺单命令复现、缺模型缓存获取命令（`local_files_only=True` 不会自动下载） | 新用户按 README 大概率卡在"没有 BGE 模型缓存" | P1 | G5-ENV-02 + G5-README-08 |
| 架构与 limitations | PARTIAL | 架构图只覆盖基础 RAG；limitations 只 3 条（BM25 重建/多轮 UI 未接/无流式），无 Gate 3/4 limitation（L1-L6） | 公开面高估了能力、低估了边界 | P1 | G5-README-08 |

### 2.2 Dependency reproducibility — PARTIAL（关键缺口）

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| 依赖声明完整性 | READY | 顶层第三方 import（chromadb/dotenv/fastapi/fitz/jsonschema/numpy/openai/pydantic/yaml/tqdm + 函数内 sentence-transformers/streamlit/requests/uvicorn/python-multipart/jieba/tiktoken/pytest）均已在 `requirements.txt` 声明；BM25 为自研（`core/retriever/hybrid.py:26` BM25Index + jieba），无 `rank_bm25` 隐藏依赖 | 无未声明 import | P0 | G5-ENV-02（作为现状核对项保留） |
| lockfile / 版本可复现 | MISSING | `requirements.txt` 全为宽松下限（`pydantic>=2.0` `chromadb>=0.4.0` `openai>=1.0.0` `fastapi>=0.104.0`…）；无 `pyproject.toml`、无 `uv.lock`/`poetry.lock`/`pip freeze` 等价物 | 今天能装，明天可能装出不同的依赖树；1716 测试的结果随安装日期漂移 | P0 | G5-ENV-02 |
| Python 版本声明 | PARTIAL | README 声称 `Python 3.11+`；实际仅在本机 `Python 3.14.0` 验证过（无 3.11 CI 验证） | "3.11+" 是文档声明，不是实际验证范围 | P1 | G5-ENV-02（固定版本 + CI 矩阵） |
| 模型名称/revision 钉住 | MISSING | `config.yaml` 用 `BAAI/bge-small-zh-v1.5`、`BAAI/bge-reranker-v2-m3`，无 revision/token pin | 模型行为随上游发布漂移，冻结数字不可逐字节复现 | P1 | G5-ENV-02 |
| 重模型依赖透明 | PARTIAL | `sentence-transformers` 传递拉入 torch/transformers/huggingface-hub（GB 级）；reranker v2-m3 约 2.2GB | 新环境安装成本/磁盘预期不明 | P2 | G5-ENV-02（CPU/GPU 降级说明） |

### 2.3 Test / CI readiness — PARTIAL

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| 测试套件本身 | READY | 全量 `1716 passed + 4 skipped`（G4-CLOSE-08）；测试全部用 Fake/Mock（`tests/test_embeddings.py:24` 只构造不加载、`test_api.py:16` patch Pipeline、`test_chunk_budget_infrastructure.py` FakeBGEEmbedding），离线可跑、不下载模型、不联网 | 测试质量高，CI 的"测试资产"已具备 | P0 | G5-CI-03（直接用现有套件） |
| CI 管道 | MISSING | 仓库无 `.github/` 目录；无任何 workflow | 没有自动验证，回归只靠人工 | P0 | G5-CI-03 |
| env-gated / 语料依赖测试 | PARTIAL | `tests/test_gate4_tool_use_dataset.py:89` 无 `GATE4_KNOWLEDGE_CORPUS_ROOT` 时 `pytest.skip`；`test_tool_agent_real_tools.py` symlink 用例在部分 OS skip（3 条） | 4 条 skip 需在 CI 明确定义（默认 skip 合法） | P1 | G5-CI-03（把 skip 语义写进 CI 说明） |
| basetemp 配置 | PARTIAL | `pytest.ini` 全局 `basetemp = .tmp_pytest`（Windows 中文用户名规避） | 在 Linux CI 是无效配置但无害；遗留问题导致仓库根堆积 129 个 untracked `.tmp_pytest_*` 目录 | P2 | G5-CI-03 + .gitignore 修复（见 2.10） |

### 2.4 Container readiness — MISSING

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| Dockerfile | MISSING | 根目录无 `Dockerfile` | 无法交付可运行镜像 | P1 | G5-DOCKER-04 |
| docker-compose / 健康检查 | MISSING | 无 compose、无 healthcheck 约定（API 有 `/health` 端点可用作 healthcheck） | 无一键启动 | P2 | G5-DOCKER-04 |
| 模型缓存处理 | MISSING | BGE embedding/reranker `local_files_only=True`（`bge_emb.py:13`、`bge_reranker.py:16`），HF 缓存默认在 `~/.cache/huggingface`；镜像必须预置或挂载模型 | 不做会 503 | P1 | G5-DOCKER-04（数据/模型缓存挂载） |
| Chroma 持久化 | MISSING | `config.yaml` vector_store path=`./data/vector_store`（gitignored） | 应做 volume，否则容器重启丢数据 | P2 | G5-DOCKER-04 |
| API key 注入 | MISSING | `.env`（gitignored）含 `DEEPSEEK_API_KEY`；无 `.env.example` | 容器需明确 env 注入方式 | P1 | G5-ENV-02（.env.example）+ G5-DOCKER-04 |

### 2.5 API surface — READY（带 1 个 minor caveat）

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| 端点定位/实现 | READY | `api/app.py`：`/health`（222）、`/index/file`（277，安全文件名白名单 + 20MiB + 独立临时目录）、`/query`（303，多轮 history）、`/agent/query`（331，Gate 3 结构化 status）、`/tool-agent/query`（348，Gate 4 白名单 trace + 200/503/500 语义）、`/stats`（368） | 三类 Agent API 均已实现并测试 | P0 | G5-README-08（把 API 写进 README） |
| request/response 边界 | READY | `api/schemas.py`：`extra=forbid`（AgentQueryRequest/ToolAgentQueryRequest）、question 1-4000、top_k 1-50、history ≤20、字段级 validator | 输入边界严格 | P0 | 无（保持） |
| 安全边界 | READY | CORS 白名单 `localhost:8501` 仅（app.py:104）、默认监听 `127.0.0.1`（start.ps1/README）、`_safe_trace` 字段白名单（app.py:177-197，禁 key/raw/CoT/prompt/traceback/路径）、上传安全文件名 | 本地暴露边界清晰 | P0 | 无（保持） |
| 初始化依赖 | PARTIAL | lifespan 构造真实 `Pipeline`（急切加载 BGE embedding，`local_files_only=True`）；无模型缓存 → Pipeline init 失败 → 全部 503（有 retry-on-first-request 兜底）；tool-agent 缺 key 时 `build_tool_agent_runtime` 抛 `ValueError` → runtime=None → 503 | 干净环境首次启动即 503，需明确文档 | P1 | G5-ENV-02 + G5-README-08 |
| `/stats` 配置暴露 | PARTIAL | `/stats` 返回**原始 Config 对象**（`app.py:373 "config": p.config`，非 `Config.dump()` 脱敏摘要）；经 jsonable_encoder 序列化全部实例属性（含 `vector_store_path`、模型名、预算参数；**无 API key**） | 无密钥泄漏，但暴露内部实现路径；非脱敏快照 | P2 | 改为 `Config.dump()` 或删除（small fix） |

### 2.6 UI reality — PARTIAL

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| UI 接入面 | PARTIAL | `ui/app.py` 只调 `/health` `/stats` `/index/file` `/query`；**无 `/agent/query` `/tool-agent/query`**；多轮用 session_state 但 `call_query` 不传 history | 不能凭 `ui/` 目录声称 UI 已支持 Gate 3/4（现状也不声称，风险在 README 未澄清） | P2 | 可选：给 UI 加 Agent 标签页（roadmap：UI 非 Gate 5 blocking） |
| README 对 UI 的表述 | PARTIAL | README 只说"UI（新终端）streamlit run"，未说明 UI 只接基础 `/query` | 面试官可能误以为 UI 已演示 Agent | P1 | G5-README-08（明确 UI 能力边界） |

### 2.7 Configuration / secrets — PARTIAL

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| .env 管理 | READY | `.env` 已 gitignored（`.gitignore:6`）；`api/app.py:8-9` load_dotenv；key 从 env 注入不落盘 | 无密钥入库 | P0 | 无（保持） |
| .env.example | MISSING | 仓库无 `.env.example` | 新用户不知道要配 `DEEPSEEK_API_KEY` | P1 | G5-ENV-02 |
| 配置安全默认 | READY | `config.yaml` 无密钥；`Config.dump()` 为脱敏摘要（config.py:188）；API 默认仅 `127.0.0.1`；README 明确公开部署需认证/TLS/限流 | 本地 demo 边界正确 | P0 | 无（保持） |
| 鉴权/限流 | NOT_IN_SCOPE | 项目定位为本地 demo，无鉴权/限流是**有意边界**（README 已声明） | 公开部署前必须补，但非当前 P0 | P1 | 文档声明即可，不入本轮实现 |

### 2.8 Observability / Trace — PARTIAL

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| Gate 3 trace | READY | `/agent/query` 返回结构化 `trace`（`core/agent_runtime/models.py` TraceEvent，脱敏禁 key/raw/prompt/traceback/正文） | 已有安全执行轨迹 | P0 | 无（保持） |
| Gate 4 safe trace | READY | `/tool-agent/query` 只透 `_TRACE_ALLOWED_KEYS` 白名单（app.py:177），"trace ≠ CoT"已落实 | 已满足"不引入 CoT" | P0 | 无（保持） |
| 传输层可观测性 | MISSING | 无 `trace_id`/`request_id` 关联；无服务端结构化日志（仅 `logger.exception` + print）；响应不含 latency/token 摘要 | roadmap G5-TRACE-05/SSE-06 目标未覆盖 | P2 | G5-TRACE-05 + G5-SSE-06 |
| 指标/性能 | MISSING | 无 P50/P95、并发、分阶段耗时报告（G5-PERF-07 目标） | 面试展示缺少性能证据 | P2 | G5-PERF-07 |

### 2.9 Public reproduction — MISSING（关键缺口）

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| 冻结语料 cross-repo provenance（P0-3） | PARTIAL | 冻结 37 文件语料在**独立 public data repo** `wgqa/agent_data`（`https://github.com/wgqa/agent_data.git`，default branch `master`）；当前 master HEAD `179f18e8`（2026-08-07）下 `agent_ai_v1/02_corpus_candidate` 已用现有 `ExperimentCorpus.build` 对 manifest `corpus_entries` 逐字节重建，**file_count=37、corpus_id=870e5864df67 与冻结身份完全一致**，37 文件全 tracked 且工作区 clean。**但主项目未冻结跨仓 commit/path/identity**，master 一移动身份即漂移，且无"拉取+核验+重建"的公开复现流程 | external repo ≠ unavailable data；缺口是 **unpinned external dependency**：语料字节今天一致，但主仓库没有把 agent_data 固定进任何可复现契约 | P0 | G5-ENV-02（跨仓 commit pinning + 公开复现契约：`git submodule`/锁 commit + 自动 corpus_id 校验） |
| Gate 3 dev 数据集 | MISSING | `evaluation/gate3/` 只有代码；`gate3/dev/`（24 case）本机仅存于 `benchmark_work/gate3/`，核验 `agent_data` 中 `gate3/` **整体未 tracked**（`git status` = `?? gate3/`）→ dev 数据集**未入任何 public repo**；sealed holdout（12 case）同样未 tracked（本就不该公开） | dev 数据不可公共获取 → Dev 评测无法在新环境复现 | P1 | G5-ENV-02（dev jsonl 入 public repo + 身份锁定） |
| Gate 4 评测集 | READY | `evaluation/gate4/data/tool_use_dev_v1.jsonl` + manifest 已入库（24 case，evaluation_set_id=5639ca57b09a） | 唯一完整入仓的评测集 | P0 | 无（保持） |
| 实验 config.yaml 入库（P0-4） | MISSING | `git ls-files experiments/` 只含 result/metrics/diagnostics；**12 个实验 `config.yaml` 全部 untracked**（`git status` 显示 `?? experiments/*/config.yaml`） | 结果公开、定义实验的参数没公开 → 结果无法核对/重建 | P0 | G5-ENV-02（补 config 或脚本化重建 + 参数重构验证） |
| 单命令复现 | MISSING | README 无"clone→拉取 agent_data→装→跑测试→起 API→调端点"单命令链；模型缓存获取命令缺失 | 面试官/同学照 README 走会卡 | P1 | G5-README-08（复现命令段，含语料拉取+核验） |
| 模型缓存前置 | PARTIAL | `local_files_only=True` 不自动下载；README 提到"BGE-small-zh-v1.5 模型缓存 (~33MB)"但无获取命令；reranker ~2.2GB 标"可选"但 `config.yaml reranker.enabled=true` | 缺模型即 503 | P1 | G5-ENV-02 + G5-README-08 |

### 2.10 Release hygiene — PARTIAL

| 项目 | 分类 | 证据 | 风险 | Priority | recommended next task |
|---|---|---|---|---|---|
| .gitignore 覆盖 `.tmp_pytest_*` | PARTIAL | `.gitignore:14` 只忽略 `.tmp_pytest/`（精确目录名）；129 个 untracked `.tmp_pytest_*` 目录堆在仓库根 | `git status` 被噪声淹没，公开仓库观感差 | P2 | .gitignore 加 `.tmp_pytest*/` 或 `*.tmp_pytest*` |
| 根目录残留文件 | PARTIAL | 根目录 tracked `test.txt`（174 B 无意义英文句） | 公开仓库有垃圾文件 | P2 | 清理 `test.txt` |
| LICENSE | MISSING | 根目录无 `LICENSE` | 若公开/开源发布需补；若只给面试官看则低优先 | P2 | 补 LICENSE（MIT 或按意愿） |
| 冻结证据文档 | READY | `docs/experiments/*.json` 11 份（gate2/gate3 freeze、holdout final、gate4 baseline/seal/freeze/e2e smoke）均已入库 | 证据链完整 | P0 | 无（保持） |
| benchmark 外部 artifact 边界 | READY | `rag数据集/benchmark_work/` 是独立 git 库，未混入主仓库；`data/vector_store`、`.env` 均已 ignore | 边界清晰 | P0 | 无（保持） |
| .dockerignore | NOT_IN_SCOPE | 无 Docker（见 2.4） | 随 G5-DOCKER-04 一并补 | P2 | G5-DOCKER-04 |

---

## 3. 优先级汇总

### P0（阻塞最终项目交付）— 4 项

| # | 项目 | 分类 | 指向任务 |
|---|---|---|---|
| P0-1 | 无 lockfile / 依赖版本不可复现（tested environment reproducibility） | MISSING | G5-ENV-02 |
| P0-2 | 无 CI 管道（测试资产已齐） | MISSING | G5-CI-03 |
| P0-3 | public corpus cross-repo provenance/pinning/reproduction contract（语料已 public 且身份核验一致，缺跨仓 commit 冻结与公开复现流程） | PARTIAL | G5-ENV-02 |
| P0-4 | 实验 config/参数未入库 → formal experiment config/parameter reconstruction 不可行 | MISSING | G5-ENV-02 |

### P1（明显影响校招展示/复现）— 8 项

| # | 项目 | 分类 | 指向任务 |
|---|---|---|---|
| 1 | README 严重落后于 Gate 3/4、三类 API、正式实验结果 | PARTIAL | G5-README-08 |
| 2 | Python 版本声明无验证（3.11+ 实际只测 3.14） | PARTIAL | G5-ENV-02 |
| 3 | 模型名称/revision 未钉住 | MISSING | G5-ENV-02 |
| 4 | 干净环境首次启动即 503（BGE 模型缓存前置） | PARTIAL | G5-ENV-02 + G5-README-08 |
| 5 | 无 .env.example | MISSING | G5-ENV-02 |
| 6 | Gate 3 dev 数据集未入任何 public repo（本机独有）→ Dev 评测不可复现 | MISSING | G5-ENV-02 |
| 7 | 无 Docker / 容器交付（模型缓存挂载 / key 注入 / healthcheck） | MISSING | G5-DOCKER-04 |
| 8 | README 未说明 UI 只接基础 /query | PARTIAL | G5-README-08 |

### P2（有价值但非必须）— 8 项

| # | 项目 | 分类 | 指向任务 |
|---|---|---|---|
| 1 | `/stats` 暴露原始 Config 对象 | PARTIAL | small fix（用 `dump()`） |
| 2 | 传输层 trace_id/request_id/结构化日志缺失 | MISSING | G5-TRACE-05 / G5-SSE-06 |
| 3 | 性能报告（P50/P95/并发）缺失 | MISSING | G5-PERF-07 |
| 4 | 129 个 `.tmp_pytest_*` untracked 目录 | PARTIAL | .gitignore 修复 |
| 5 | 根目录 `test.txt` 垃圾文件 | PARTIAL | 清理 |
| 6 | 无 LICENSE | MISSING | 补 LICENSE |
| 7 | UI 未接 Agent 端点 | PARTIAL | 可选 UI 任务 |
| 8 | reranker 2.2GB 下载预期不透明 | PARTIAL | G5-ENV-02（CPU/GPU/磁盘说明） |

---

## 4. 本卡约束遵守声明

- **0 生产代码改动**：R0 修改 docs 下 5 个文件；R1 仅修改 4 个文件（baseline.md/json、status.md、study-note 92；study-notes README 索引标题未变，未触碰）。
- **0 DeepSeek / 0 Gate 3 sealed Holdout access / 0 Gate 4 formal rerun / 0 HTTP smoke / 0 benchmark**：全程只读审计；R1 未读取任何 `gate3/sealed/` 内容（仅核验其 untracked 状态）。
- **R1 corpus 身份核验**：用现有 `ExperimentCorpus.build` 对 `agent_ai_v1/02_corpus_candidate` 的 37 个 manifest `corpus_entries` 逐字节重建 → `corpus_id=870e5864df67`、`file_count=37`，与冻结身份**完全一致**；agent_data 当前 HEAD=`179f18e8`，37 文件全 tracked 且工作区 clean。
- 全量测试未重跑（生产代码一字节未动，机械重跑无意义）；只跑 `tests/test_gate4_freeze.py` 验证文档提交无回归。
