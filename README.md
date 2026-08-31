# Evidence-Grounded AI Engineering Agent

[![CI](https://github.com/wgqa/my_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/wgqa/my_agent/actions/workflows/ci.yml)

面向 AI / RAG / Agent 研发场景的可评测智能研发 Agent。项目以 RAG-first、Evidence-first 为基础，从知识检索演进到 Repository Evidence、bounded Structured Tool Use 与 Engineering API，并把冻结评测、可复现环境、CI、FastAPI/Streamlit Demo 和安全执行边界作为同一套工程交付的一部分。

## 项目亮点

| 能力 | 当前实现 |
|---|---|
| Basic RAG | Dense / BM25 / Hybrid 检索、Reranker、grounded citation |
| Agentic RAG | Planner、Query Decomposition、Adaptive Retrieval、Evidence Merge、Verifier |
| Structured Tool Agent | 7 个 bounded read-only Tool：`calculator`、`code_search`、`read_project_context`、`knowledge_search`、`changed_files`、`git_diff`、`find_tests` |
| Engineering Agent | 统一 Engineering API、verified knowledge identity、system-bound project identity 与 repository/change/test evidence |
| Safety | Tool allowlist、系统控制预算、duplicate stop、safe trace；不提供任意 shell、文件写入或 Git commit/push |
| Evaluation | Gate 2 Retrieval、Gate 3 Agentic RAG、Gate 4 Tool Agent 冻结证据 |
| Engineering | FastAPI、Streamlit、GitHub Actions、startup smoke、full-app smoke |
| Reproducibility | `requirements.lock`、公共语料 provenance、冻结 artifact 身份 |

这不是只展示一个问答页面的 RAG Demo：每条能力链路都有 API contract、运行时边界、测试或冻结证据可供审计。

## 总体架构

```mermaid
flowchart TD
    U[User / API Client] --> API[FastAPI]
    U --> UI[Streamlit Demo Console: 3 modes]
    UI --> API

    API --> B[Basic RAG /query]
    B --> BR[Retriever]
    BR --> RR[Reranker]
    RR --> BG[Generator]
    BG --> BA[Answer + Citations]

    API --> A[Agentic RAG /agent/query]
    A --> P[Planner]
    P --> D[Query Decomposition]
    D --> R[Adaptive Router]
    R --> E[Retrieval / Evidence Merge]
    E --> V[Verifier]
    V --> G[Grounded Answer]

    API --> T[Structured Tool Agent /tool-agent/query]
    T --> TD[Decision]
    TD --> TC[Allowlisted Tool Call]
    TC --> O[Observation]
    O --> L[Bounded Iteration]
    L --> TF[Final Answer]

    API --> EA[Engineering product path<br/>/engineering/query]
    EA --> F[EngineeringAgentFacade]
    F --> UR[UnifiedEngineeringRuntime]
    UR --> C[Context Resolver]
    C --> P2[Evidence Planner]
    P2 --> RR2[Requirement Router]
    RR2 --> PR[Adaptive Planned Retrieval]
    PR --> AG[Evidence Aggregator]
    AG --> TE[Bounded Tool Execution Engine]
    TE --> EB[Evidence Backends<br/>Knowledge / Repository / Git / Test]
    EB --> UE[One Unified Evidence sequence]
    UE --> EV[EngineeringEvidenceVerifier]
    EV --> FIN[Single finalization point]
    FIN --> ER[Engineering response / SSE]

    API --> LQ[Legacy /query]
    API --> LA[Legacy /agent/query]
    API --> LT[Legacy /tool-agent/query]
    API --> KS[/engineering/knowledge<br/>status / identity only]
```

Engineering Agent 是默认产品定位与统一 API 主入口；Basic、Agentic、Structured Tool Agent 及其 legacy endpoint 保留为独立回归、历史和调试路径，不是 Engineering Runtime 的替代 controller。Tool Agent 的 Observation 是不可信输入，不能改变系统预算、工具注册表或安全边界。Streamlit 目前仍提供 Basic RAG、Agentic RAG 与 Structured Tool Agent 三种 Demo mode；Engineering Agent API 不作为第四个 mode selector。

## 三种 Demo 运行模式与 Engineering API 入口

### Basic RAG

`POST /query`

适合普通知识库问答：检索候选、可选重排、生成有证据约束的答案，并返回来源。Dense、BM25 和 Hybrid 是可比较的检索策略；Gate 2 的冻结 primary 是 BM25，不代表所有问题或所有配置都应盲选 BM25。

### Agentic RAG

`POST /agent/query`

Planner 先产生结构化 QueryPlan，再根据 Query Type 和 evidence target 做 Query Decomposition；Adaptive Router 选择检索策略，Evidence Merge 合并子问题证据，Verifier 检查覆盖后才进入 grounded answer。响应中的 planner、route、verification 和 trace 是可审计执行事实，不是模型私有 Chain-of-Thought。

### Structured Tool Agent

`POST /tool-agent/query`

Decision → Tool Call → Observation → bounded iteration → Final Answer。当前 registry 有 7 个 bounded read-only Tool：Knowledge Evidence 的 `knowledge_search`，Repository Evidence 的 `code_search`、`read_project_context`，Change/Test Evidence 的 `changed_files`、`git_diff`、`find_tests`，以及 Utility `calculator`。运行时控制最大 iteration、tool calls、tool errors，并对重复调用和未注册工具 fail closed。

### Engineering Agent API

`POST /engineering/query`、`POST /engineering/query/stream` 与 `POST /engineering/query/stream/v2` 共用同一个 `EngineeringAgentFacade → UnifiedEngineeringRuntime` 主链，面向当前系统绑定项目与 verified Engineering Knowledge 的 evidence-grounded 分析；v1/v2 只改变安全 observer transport。`GET /engineering/knowledge` 公开 verified Knowledge backend 的状态和 identity，不执行 Agent；`GET /project` 公开当前 system-bound project 的 identity，绝不返回本地绝对路径。`GET /capabilities` 包含 `engineering_agent` capability 状态。

`/query`、`/agent/query`、`/tool-agent/query` 是独立 legacy regression/historical/debugging endpoints，迁移期间保持原有 contract，不重定向到 Engineering 主链。

## 5 分钟体验

### 安装

正式验证环境为 Python 3.14，复现入口是锁定依赖：

```bash
python -m pip install -r requirements.lock
```

生成答案和 Agent 真调用需要设置环境变量：

```bash
export DEEPSEEK_API_KEY="your-key"
```

PowerShell 等价写法是 `$env:DEEPSEEK_API_KEY = "your-key"`。不要把真实凭据写入仓库文件。

### 启动 API 与 UI

```bash
uvicorn api.app:app --host 127.0.0.1 --port 8000
streamlit run ui/app.py
```

打开 Streamlit 地址后，可以在 Agent Console 中切换三种 Demo mode：Basic RAG、Agentic RAG 和 Structured Tool Agent。侧栏会先读取 `/health` 与 `/capabilities`；runtime 未 ready 的模式会在提交前提示，不会等一次 503 才暴露问题。默认产品路径是 Engineering API；它不作为第四个 Streamlit mode selector。

如果 API 不在默认地址，可设置 `RAG_API_URL=http://127.0.0.1:<port>` 后再启动 UI。

### Release Demo

```bash
python scripts/demo_release.py
```

Release Demo 是面向用户的固定演示，不是 benchmark。catalog 固定 6 个场景：Basic RAG、Agentic RAG、calculator、code search、多步工具链观察项和安全边界；其中 5 个 required，1 个 observational。每个场景最多请求一次，不自动重试模型调用。Live Demo 需要真实 `DEEPSEEK_API_KEY`；本轮 Release Demo 尚未产生成功的 live LLM 结果，不把其他 Gate 的 HTTP evidence 冒充为 Demo 结果。

## Smoke、Demo 与 Benchmark

三者回答不同问题：

| 层次 | 命令 | 证明什么 |
|---|---|---|
| Backend Startup Smoke | `python scripts/smoke_local_api.py` | 真实 uvicorn、`/health`、OpenAPI 路由；不调用真实模型，输出 `model_network_not_required=true` |
| Full App Smoke | `python scripts/smoke_local_app.py` | FastAPI + Streamlit server + AppTest 页面执行 + 真实 UI → API integration + runtime capabilities |
| Live Release Demo | `python scripts/demo_release.py` | 真实用户能力演示，需要真实 `DEEPSEEK_API_KEY` |
| Formal Benchmark | 冻结 runner / evidence | 固定数据、配置、身份和指标上的可比较质量结果 |

Smoke ≠ Demo ≠ Benchmark。Smoke 不证明答案质量，Demo 不产生 Gold-based 分数，Benchmark 也不应通过反复重跑来挑选更好看的结果。

## 公共 API

| Endpoint | 作用 |
|---|---|
| `GET /health` | 基础 Pipeline readiness 与公开运行配置 |
| `GET /capabilities` | Basic / Agentic / Tool Agent / indexing 的 runtime capability |
| `GET /stats` | 经过 allowlist 的运行统计与配置快照 |
| `POST /index/file` | 将支持的文档索引到知识库 |
| `POST /query` | Basic RAG |
| `POST /agent/query` | Agentic RAG |
| `POST /tool-agent/query` | Structured Tool Agent |
| `POST /engineering/query` | 统一 Engineering Agent query entry |
| `POST /engineering/query/stream` | Engineering Agent safe Trace SSE |
| `POST /engineering/query/stream/v2` | Engineering Agent Rich Activity SSE |
| `GET /engineering/knowledge` | Verified Engineering Knowledge backend 的公开状态与 identity |
| `GET /project` | 当前 system-bound project 的公开 identity，不暴露本地绝对路径 |

`GET /capabilities` 同时报告 `engineering_agent` 的 runtime capability 状态。完整 request/response schema 以 FastAPI `/docs` 与 OpenAPI 为准；README 只保留产品层入口，不复制每个 Pydantic 字段。

## Evaluation & Evidence

下面只列冻结 artifact 中的 headline，指标定义、配置和 SHA 以对应文件为准。

### Gate 2 — Retrieval

当前 37 个文档、50 个 case、Top-5 chunk 的 document-level 指标中，冻结 primary 是 Recursive + BM25 + `cl100k_content_v1`：

| 指标 | 结果 |
|---|---:|
| Hit@5 | 0.98 |
| Recall@5 | 0.9533 |
| MRR | 0.7873 |
| nDCG@5 | 0.8206 |

证据：[docs/experiments/gate2_freeze.json](docs/experiments/gate2_freeze.json)。这是当前冻结范围内的结果，不是跨数据集的普遍结论。

### Gate 3 — Agentic RAG

Dev 侧冻结系统 evidence（24 cases）记录：retrieval obligation `35/44 = 0.7955`、answer obligation `21/44 = 0.4773`、answer pass `8/20 = 0.40`、citation valid `16/16 = 1.0`。正式 sealed holdout 的最终记录（12 cases，10 个 answerable）是：retrieval obligation `18/21 = 0.8571`、answer obligation `8/21 = 0.3810`、answer pass `4/10 = 0.40`、citation valid `6/6 = 1.0`。

证据：[docs/experiments/gate3_system_freeze.json](docs/experiments/gate3_system_freeze.json) 与 [docs/experiments/gate3_holdout_final.json](docs/experiments/gate3_holdout_final.json)。其中 4/24 Dev generation failures 和 retrieval-to-answer gap 都保留在 headline 中，没有被删除或重新解释。

### Gate 4 — Structured Tool Agent

冻结 public Dev baseline（24 cases）记录：

| 指标 | 结果 |
|---|---:|
| First action accuracy | 21/24 = 0.875 |
| Required tool coverage | 14/20 = 0.70 |
| Task completion | 20/24 = 0.8333 |
| Forbidden tool rate | 0/24 = 0 |
| Duplicate tool rate | 0/24 = 0 |
| Allowed sequence match | 1/4 = 0.25 |

证据：[docs/experiments/gate4_tool_use_dev_baseline.json](docs/experiments/gate4_tool_use_dev_baseline.json)、[docs/experiments/gate4_tool_use_dev_seal.json](docs/experiments/gate4_tool_use_dev_seal.json) 和 [docs/experiments/gate4_freeze.json](docs/experiments/gate4_freeze.json)。`Allowed sequence match` 与 required coverage 是已知限制，不通过修改展示层掩盖。

### G11 — Engineering Task Transfer Validation

| Task Family | Result |
|---|---|
| Theory ↔ Code | MIXED |
| Change Impact & Test | MIXED |
| Diagnosis & Config | NEGATIVE |
| Docs ↔ Code | NEGATIVE |

这是 Engineering task family 的 transfer-validation evidence，不是历史 Gate 4 Tool-use baseline 的替代或重算。各 workflow 共同确认了 Evidence Sufficiency、Claim-Evidence Coverage 以及 cross-file / bilateral grounding 的技术债；这些问题将进入 G12 Engineering Evaluation 2.0，而非由 README 隐藏或改写。

### 冻结评测语义

Gate 2、Gate 3、Gate 4 的正式实验与证据已经冻结。Release 1.0 使用已有 evidence 作为审计依据，不通过重新调参、重复执行 sealed holdout 或挑选结果来制造更漂亮的数字。

## Reproducibility

- Python 3.14 是当前验证版本。
- `requirements.lock` 是安装入口。
- `reproducibility/public_data_lock.json` 锁定公共语料身份。
- `scripts/verify_public_corpus.py` 使用 `--data-root` 重新构建并核对身份。

公共 corpus 来源为 `wgqa/agent_data`，固定 commit 为 `179f18e812ad63c36c5569de8e86c5ff9a931cb5`，路径为 `agent_ai_v1/02_corpus_candidate`，37 files，`corpus_id=870e5864df67`。该 commit 和 corpus identity 以 [reproducibility/public_data_lock.json](reproducibility/public_data_lock.json) 为准。

```bash
python scripts/verify_public_corpus.py --data-root /path/to/agent_data
```

验证命令只读取指定 checkout，不把外部语料复制进本仓库。

## Safety Boundaries

- Tool registry 暴露 7 个 bounded read-only Tool：`calculator`、`code_search`、`read_project_context`、`knowledge_search`、`changed_files`、`git_diff`、`find_tests`。不存在任意 shell Tool、写文件 Tool 或 Git commit/push Tool。
- Tool Agent 使用系统控制的预算：最多 5 iterations、4 tool calls、2 tool errors。
- duplicate tool call 会停止或拒绝继续执行，未注册工具 fail closed。
- Tool Agent decision baseline 不自动重试模型调用；HTTP transport failure 与结构化 Agent failure 分开处理。
- Safe Trace 只记录受控执行事实，不暴露私有 Chain-of-Thought、Prompt、原始模型输出、凭据或本机路径。
- 文档内容、检索结果和 Tool Observation 都按 untrusted input 处理，不获得系统控制权。
- 敏感凭据只通过环境变量注入；默认服务监听 `127.0.0.1`。

## Known Limitations

- Engineering Agent 的统一 API 主链与 Streamlit 三种 legacy/demo mode 分开；当前不把 Engineering 伪装成第四个 UI mode。
- Evidence Sufficiency 与 Claim-Evidence Coverage 尚未由 system-level verifier 强制保证。
- G11 多个 task family 已真实暴露 premature finalization、cross-file / bilateral evidence 缺失等问题。
- Basic `/query` schema 支持 `history`；当前 Streamlit UI 不把会话历史发送给后端。
- Agentic RAG 与 Tool Agent 当前是单轮 request contract；UI 也按模式隔离历史。
- Engineering stream v1/v2 只在 SSE observer transport 上不同，业务结果仍来自同一 Unified Runtime。
- Tool Agent 正式 Dev baseline 的 multi-step allowed sequence match 为 `1/4`，required tool coverage 为 `14/20`；`ACTION_PARSE_FAILED` 为 `2/24`，budget stop 为 `1/24`。
- Gate 3 Dev 侧有 `4/24` generation failures；检索找到证据不等于 Generator 覆盖全部 answer obligation。
- 当前默认是本地单用户 Demo，不包含认证、租户隔离或面向公网的部署安全层。

这些是冻结证据中的已知限制，不是 README 里等待偷偷修掉的数字。

## Engineering Decisions

1. **冻结 primary 选择 BM25。** 在 Gate 2 的明确数据、文档和 Top-5 指标范围内，Recursive + BM25 的 Hit@5、Recall@5 和 nDCG@5 高于对照组；因此记录事实，不把更复杂的 Hybrid 自动当成更好。
2. **冻结 sealed evidence 后不反复调参。** Holdout 只执行授权次数，结果与 provenance 一起封存，避免把评测集变成调参集。
3. **Adaptive Router 使用 deterministic policy。** 路由策略由结构化 Planner 结果和固定 policy 表决定，减少把一次 LLM 随机输出误写成系统设计。
4. **Tool Agent 使用 allowlist + budgets。** 模型只提出结构化 action，Registry/Executor 和 runtime budget 决定是否真正执行。
5. **Safe Trace 不暴露 CoT。** 产品需要展示可审计的事件、工具和结果，不需要也不应展示模型私有推理文本。

相关背景见 [Gate 2 总结](docs/study-notes/60-Gate2评测体系与RAG实验方法总结.md)、[Adaptive Retrieval 记录](docs/study-notes/75-Gate3子查询RRF合并实验.md)、[Tool Agent 总结](docs/study-notes/91-Gate4最终冻结与Structured-Tool-Agent项目总结.md) 和 [能力发现与前端降级](docs/study-notes/100-Gate5-能力发现与前端降级.md)。

## Project Evolution

| 阶段 | 交付重点 |
|---|---|
| Gate 1 | 基础 RAG 正确性、上下文与引用 |
| Gate 2 | 可复现实验、Retrieval Evaluation、策略与分块消融 |
| Gate 3 | Query Decomposition、Adaptive Retrieval、Evidence Verification |
| Gate 4 | Structured Tool Agent、只读工具、安全执行与 formal Dev baseline |
| Gate 5 | Release Engineering、UI、CI、API contract、Smoke 与 Demo |
| G6 | Repository / Engineering Evidence |
| G7 | Observable Demo / UI |
| G8 | Conversation Context |
| G9 | Reliability |
| G10 | Core Evidence Expansion |
| G11 | Unified AI Engineering Agent / Engineering Task Validation |
| G12 | Engineering Evaluation 2.0（CLOSED / FROZEN；Core Agent System COMPLETE） |

G12 已在冻结的 16-case、two-repository transfer benchmark 上完成 Baseline A、最小 deterministic Finalization Guard、同 benchmark A/C Formal 和 Manual Gold。最终 System C 分类为 `VALID / FAIL`：系统具有 mixed task capability，但最小 Guard 未带来预期的 evidence-grounded reliability 提升。这个负结果已被接受并冻结；不会为改善该 benchmark 的结果自动修改 Router 或开启 Gate 13。详见 [G12 final close](docs/study-notes/124-G12最终收口与核心Agent完成.md)。

## Repository Map

- `api/`：FastAPI routes、public response schemas 和 runtime lifecycle。
- `core/`：Pipeline、retrieval、Agent runtime、Tool registry 与执行器。
- `core/engineering_agent.py`、`core/engineering_knowledge.py`、`core/tool_agent/`：Engineering Agent facade、verified knowledge 与 bounded Tool runtime。
- `api/app.py`：public API routes、runtime lifecycle 与 Engineering product entry。
- `ui/`：Streamlit console、ApiClient 和结果 renderers。
- `scripts/`：startup/full-app smoke、Demo harness、corpus verification 与评测入口。
- `tests/`：unit、API contract、runtime boundary、UI logic 和 release smoke tests。
- `docs/experiments/`：tracked freeze、seal 和 release readiness evidence。
- `docs/roadmap.md`：Release 2.0 主路线与后续阶段。
- `docs/status.md`：唯一实时状态表。
- `docs/study-notes/`：设计演进与面向学习的解释。

推荐阅读顺序是：先看本 README 的架构和限制，再看 `api/app.py`、`core/engineering_agent.py`、`core/engineering_knowledge.py` 与 `core/tool_agent/`，最后沿 `docs/roadmap.md`、`docs/status.md` 和对应 Gate 的 evidence path 核对数字。这样可以把产品路径、实现路径和评测证据保持在同一条可追溯链上。

## Docs

- [实时项目状态](docs/status.md)
- [Release readiness 基线](docs/experiments/gate5_release_readiness_baseline.md)
- [API contract 与 runtime capabilities](docs/study-notes/98-Gate5-后端API契约与运行时能力.md)
- [前后端联调与 Full App Smoke](docs/study-notes/97-Gate5-前后端联调与全应用Smoke.md)
- [Release Demo 与产品验收](docs/study-notes/99-Gate5-Release-Demo与产品验收.md)
- [学习笔记索引](docs/study-notes/README.md)

API 交互细节请运行服务后查看 `/docs`；README 负责项目入口、证据路径和边界，不替代 OpenAPI 或冻结报告。
