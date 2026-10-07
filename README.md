# Evidence-Grounded AI Engineering Agent

[![CI](https://github.com/wgqa/my_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/wgqa/my_agent/actions/workflows/ci.yml)

面向 AI / RAG / Agent 研发场景的可评测智能研发 Agent。项目以 RAG-first、Evidence-first 为基础，从知识检索演进到 Repository Evidence、bounded Structured Tool Use 与 Engineering API，并把冻结评测、可复现环境、CI、FastAPI/Streamlit Demo 和安全执行边界作为同一套工程交付的一部分。

当前产品标识为 **2.0.0-dev / development**，尚未正式发布Release 2.0。API、OpenAPI、UI Settings与当前Demo共用版本源；历史Release 1.0冻结证据保持原身份。

HTML 页面现在包含知识库管理：启动后端后打开 `http://127.0.0.1:8000/`，
点击侧栏“知识库”查看、上传、替换或删除文档。默认 Engineering 主会话
检索整个可维护库，数据保存在 SQLite；冻结语料仅用于首次导入或显式
`ENGINEERING_KNOWLEDGE_MODE=verified` 的历史验证。见 [知识库运行说明](docs/knowledge_library_runbook.md)。

Engineering 主入口近期聚焦配置到行为追踪、小范围变更与已有测试定位、文档与实现核对。主页卡片先填写具体调查对象再提交；任务范围、当前可靠性限制和检查结果见 [核心任务说明](docs/core_workflows.md)。

当前质量、调用量、token 消耗和开发基线集中在 [质量与成本索引](docs/validation/2026-10-04-quality-baseline.md)，可离线重新汇总；内容正确性与 completed、预期拒答分开统计。Engineering 与旧 Demo 独立初始化，旧 Pipeline 启动失败时主链仍可用，见 [启动隔离验证](docs/validation/2026-10-04-quality-and-startup.md)。

## 项目亮点

| 能力 | 当前实现 |
|---|---|
| Basic RAG | Dense / BM25 / Hybrid 检索、Reranker、grounded citation |
| Agentic RAG | Planner、Query Decomposition、Adaptive Retrieval、Evidence Merge、Verifier |
| Structured Tool Agent | 7 个 bounded read-only Tool：`calculator`、`code_search`、`read_project_context`、`knowledge_search`、`changed_files`、`git_diff`、`find_tests` |
| Engineering Agent | 统一 Engineering API、可维护知识库与公开 identity、system-bound project identity 与 repository/change/test evidence |
| Safety | Tool allowlist、系统控制预算、duplicate stop、safe trace；不提供任意 shell、文件写入或 Git commit/push |
| Evaluation | Gate 2 Retrieval、Gate 3 Agentic RAG、Gate 4 Tool Agent 冻结证据 |
| Engineering | FastAPI、Streamlit、GitHub Actions、startup smoke、full-app smoke |
| Reproducibility | `requirements.lock`、公共语料 provenance、冻结 artifact 身份 |

这不是只展示一个问答页面的 RAG Demo：每条能力链路都有 API contract、运行时边界、测试或冻结证据可供审计。

## 总体架构

```mermaid
flowchart TD
    U[User / API Client] --> API[FastAPI]
    U --> UI[Streamlit: Engineering 主会话<br/>Advanced / Demo: 3 legacy modes]
    UI --> API

    API --> B[Basic RAG legacy /query]
    B --> BR[Retriever]
    BR --> RR[Reranker]
    RR --> BG[Generator]
    BG --> BA[Answer + Citations]

    API --> A[Agentic RAG legacy /agent/query]
    A --> P[Planner]
    P --> D[Query Decomposition]
    D --> R[Adaptive Router]
    R --> E[Retrieval / Evidence Merge]
    E --> V[Verifier]
    V --> G[Grounded Answer]

    API --> T[Structured Tool Agent legacy /tool-agent/query]
    T --> TD[Decision]
    TD --> TC[Allowlisted Tool Call]
    TC --> O[Observation]
    O --> L[Bounded Iteration]
    L --> TF[Final Answer]

    API --> EA[Engineering product path<br/>/engineering/query]
    API --> CS[Engineering Conversation API<br/>CRUD + message SSE]
    CS <--> DB[(SQLite conversation store)]
    CS --> EA
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

    API --> KS[/engineering/knowledge<br/>status / identity / document management]
```

Engineering Agent 是 Streamlit 默认主会话与统一 API 主入口；会话由后端 SQLite 持久化，通过 Conversation API 提交消息并接收 SSE。Basic RAG、Agentic RAG 与 Structured Tool Agent 保留在折叠的 `Advanced / Demo` 选择器中，使用各自的 legacy API。Tool Agent 的 Observation 是不可信输入，不能改变系统预算、工具注册表或安全边界。

## Engineering 主入口与三种 legacy Demo

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

`POST /engineering/query`、`POST /engineering/query/stream` 与 `POST /engineering/query/stream/v2` 共用同一个 `EngineeringAgentFacade → UnifiedEngineeringRuntime` 主链，面向当前系统绑定项目与 Engineering Knowledge 的 evidence-grounded 分析；v1/v2 只改变安全 observer transport。`GET /engineering/knowledge` 公开当前知识库的状态、模式和 identity，不执行 Agent；默认 managed 模式由 `/engineering/knowledge/documents` 管理文档，历史 verified 模式保留只读冻结身份。`GET /project` 公开当前 system-bound project 的 identity，绝不返回本地绝对路径。`GET /capabilities` 包含 `engineering_agent` capability 状态。

UI 主会话通过 `POST /engineering/conversations` 创建。HTML 默认向 `POST /engineering/conversations/{conversation_id}/messages/stream/v2` 提交 `message`，实时展示工具目标、结果摘要、新增证据与资料校验；公开活动随整轮结果保存，刷新后可在 Activity 中恢复。Streamlit 和历史客户端的 `/messages/stream/v1` 保留兼容。后端加载已提交历史，由现有 Context Window 选取最多 6 条 / 1200 token；整轮消息与结果原子保存后才发布答案。旧 question-only Engineering API 仍接受 `question`，不自动保存为多轮会话。见 [HTML V2 验证](docs/validation/2026-10-07-html-stream-v2.md)。

HTML 的 **New chat** 可选择已添加的项目，或填写本机绝对目录。每个对话固定绑定一个项目，顶部与会话列表显示项目名，切换无需重启。API 层登记目录并按项目复用现有 Core facade，聊天请求只传公开 `project_id`；知识库继续共享且默认检索整库。`/project`、旧 question-only API 和 Streamlit 仍使用启动默认项目。见 [本地项目使用说明](docs/project_mount_runbook.md)。

拒答与失败现在显示具体的中文原因和下一步建议，覆盖证据不足、信息不全、能力/安全判断、运行上限、工具错误和模型故障。原 `status`、原因码和 `answer=null` 保留，新增可选 `feedback` 仅用于提示；已有资料仍可查看。恢复按钮只把原问题填回输入框，等待用户编辑和发送。旧拒答历史也采用新提示展示，不改写旧记录。见 [反馈验证](docs/validation/2026-10-06-user-feedback.md)。

`/query`、`/agent/query`、`/tool-agent/query` 是独立 legacy regression/historical/debugging endpoints，迁移期间保持原有 contract，不重定向到 Engineering 主链。

Jev 预期证据路由已暂缓，Engineering 主链使用原有关键词路由。历史实现与方案见 [归档记录](docs/archive/jev_evidence_routing/design.md)。

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

默认 Engineering 使用可维护知识库，未配置初始语料时可从空库上传。
`ENGINEERING_KNOWLEDGE_CORPUS_ROOT` 可用于首次导入已验证冻结语料；历史验证
模式仍要求该目录有效。新机器的安装和启动步骤见 [本地运行手册](docs/release2_local_runbook.md)。`ENGINEERING_PROJECT_ROOT` 设置启动默认项目，默认指向本仓库；HTML 新对话可独立选择本地项目，见 [挂载操作](docs/project_mount_runbook.md)。

### 启动 API 与 UI

```bash
uvicorn api.app:app --host 127.0.0.1 --port 8000
streamlit run ui/app.py
```

后端启动后可直接打开 `http://127.0.0.1:8000/` 使用 HTML 聊天与知识库管理，无需另起静态服务器。Streamlit 保留为内部 Demo：打开其地址后默认进入 Engineering Agent，可创建、继续或删除后端保存的会话；三种旧 Demo 在侧栏 `Advanced / Demo` 中切换。页面读取 `/health`、`/capabilities`、项目与知识库状态，runtime 未 ready 时会在提交前提示。

如果 API 不在默认地址，可设置 `RAG_API_URL=http://127.0.0.1:<port>` 后再启动 UI。

### 当前 Engineering Demo

使用独立Git样例演示配置追踪、变更/测试定位和文档核对，复用主页题目生成、Conversation API与SSE链路。准备、绑定、预检查和可选真实运行见 [演示手册](docs/demo_engineering_runbook.md)。

```bash
python scripts/demo_engineering.py prepare --workspace ../.codex-test-runs/engineering-demo
# 按演示手册绑定并启动后端、页面后：
python scripts/demo_engineering.py check
# 以下才发送三条真实模型消息，每个场景一次，无任务级重试；输出必须是新文件：
python scripts/demo_engineering.py run --live --output ../.codex-test-runs/engineering-demo-result.json
```

Demo保留实际答案、拒答、来源与保存结果，不产生正确率。三条消息仍会触发原Planner/Decision链，不能当作只有三次provider调用。开发版限制和当前质量记录见 [核心任务范围](docs/core_workflows.md) 与 [质量索引](docs/validation/2026-10-04-quality-baseline.md)。

### 历史 Release 1.0 Demo

```bash
python scripts/demo_release.py
```

Release Demo 是面向用户的固定演示，不是 benchmark。catalog 固定 6 个场景：Basic RAG、Agentic RAG、calculator、code search、多步工具链观察项和安全边界；其中 5 个 required，1 个 observational。每个场景最多请求一次，不自动重试模型调用。Live Demo 需要真实 `DEEPSEEK_API_KEY`；本轮 Release Demo 尚未产生成功的 live LLM 结果，不把其他 Gate 的 HTTP evidence 冒充为 Demo 结果。

## Smoke、Demo 与 Benchmark

三者回答不同问题：

| 层次 | 命令 | 证明什么 |
|---|---|---|
| Backend Startup Smoke | `python scripts/smoke_local_api.py` | 真实 uvicorn、`/health`、OpenAPI 路由；不调用真实模型，输出 `model_network_not_required=true` |
| Full App Smoke | `python scripts/smoke_local_app.py` | 隔离的FastAPI + Streamlit server + AppTest页面、runtime capabilities与版本展示；零模型 |
| Engineering App Smoke | `python scripts/smoke_local_app.py --corpus-root <verified-corpus>` | 真实Engineering装配、三个任务入口和聊天可用；dummy key、零模型 |
| 当前Live Engineering Demo | `python scripts/demo_engineering.py run --live --output <fresh-file>` | 三次真实会话/SSE/保存演示，凭据配置在后端，结果不计作正确率 |
| 历史Live Release 1.0 Demo | `python scripts/demo_release.py` | 旧Basic / Agentic / Tool接口演示，需真实key；保留历史入口 |
| Formal Benchmark | 冻结 runner / evidence | 固定数据、配置、身份和指标上的可比较质量结果 |

Smoke ≠ Demo ≠ Benchmark。Smoke 不证明答案质量，Demo 不产生 Gold-based 分数，Benchmark 也不应通过反复重跑来挑选更好看的结果。

## 公共 API

| Endpoint | 作用 |
|---|---|
| `GET /version` | 当前产品版本与development状态，独立于各runtime就绪情况 |
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
| `GET /engineering/projects`、`POST /engineering/projects` | 列出或添加本地项目，返回公开项目 id |
| `POST /engineering/conversations`、`GET /engineering/conversations` | 创建或列出默认/所选项目会话；`scope=all` 列全部已登记项目 |
| `GET /engineering/conversations/{conversation_id}`、`DELETE /engineering/conversations/{conversation_id}` | 读取或删除会话；可通过 `project_id` 指定其绑定项目 |
| `POST /engineering/conversations/{conversation_id}/messages/stream/v2` | HTML 默认：按绑定项目与历史返回 Rich Activity SSE，保存公开活动 |
| `POST /engineering/conversations/{conversation_id}/messages/stream/v1` | 历史兼容：按绑定项目与服务端历史返回 Trace SSE |
| `GET /engineering/knowledge` | 当前知识库的公开状态、模式与 identity |
| `GET /engineering/knowledge/documents` | 全库文档列表，支持文件名筛选和分页 |
| `GET /engineering/knowledge/documents/{id}` | 指定文档的分段正文预览 |
| `POST /engineering/knowledge/documents` | 上传文档或同名更新 |
| `PUT /engineering/knowledge/documents/{id}` | 替换指定文档 |
| `DELETE /engineering/knowledge/documents/{id}` | 删除指定文档及其分块 |
| `GET /project` | 当前 system-bound project 的公开 identity，不暴露本地绝对路径 |

`GET /capabilities` 同时报告 `engineering_agent` 的 runtime capability 状态。完整 request/response schema 以 FastAPI `/docs` 与 OpenAPI 为准；README 只保留产品层入口，不复制每个 Pydantic 字段。

Engineering Agent 支持明确依据已挂载仓库的 README 等文档回答并引用来源。文档取证的开发验证见 [文档取证验证](docs/validation/2026-10-03-project-document-acquisition.md)。

公开项目读取正文保留 Reader 已返回的完整有界片段；源码与文档的语义正确性仍需核对。验证与容量变化见 [片段一致性验证](docs/validation/2026-10-03-evidence-excerpt-fidelity.md)。

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

这是 Engineering task family 的 transfer-validation evidence，不是历史 Gate 4 Tool-use baseline 的替代或重算。各 workflow 确认的 Evidence Sufficiency、Claim-Evidence Coverage 以及 cross-file / bilateral grounding 缺口，已在 G12 冻结结果与当前技术债中继续记录。

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

2026-10-03 已补齐仓库已有测试的发现与取证链路：原测试拒答和中文改写能够读取完整测试并建议准确命令，5/4/2 与单一循环保留。系统仅建议 pytest 命令，尚不执行测试；另一改写仍生成错误命令，证据存在不等于答案语义正确。见 [测试取证对照与剩余问题](docs/validation/2026-10-03-project-test-acquisition.md)。

2026-10-03 已修复 Engineering Planner 的不检索字段组合冲突：两道计算、通用文档用途对比和新增排序在配对诊断中从 0/4 到 4/4 正确完成，仍保留严格证据校验与 5/4/2。源码回答的越界引用和语义错误继续开放；见 [验证与保留限制](docs/validation/2026-10-03-planner-no-retrieval-alignment.md)。

- Engineering 主会话支持服务端历史与持久化，但每轮仍受 5/4/2 执行预算与 6 条 / 1200 token 上下文窗口约束。当前历史读取和会话详情没有分页，长会话容量优化仍待处理。
- Structural/query-level evidence sufficiency 已由 deterministic verification stack 检查；claim-level semantic grounding/entailment 仍未解决。G12 冻结结果和近期系统诊断保留了这一缺口，当前检查不保证完整 factual verification 或 semantic correctness。
- G11 多个 task family 已真实暴露 premature finalization、cross-file / bilateral evidence 缺失等问题。
- Basic `/query` schema 支持 `history`；当前 Streamlit UI 不把会话历史发送给后端。
- Agentic RAG Demo 会提交 `history` 并经过有界上下文处理；Tool Agent 仍只接受 `question`。legacy Demo 与 Engineering 服务端会话分别保存各自历史。
- Engineering stream v1/v2 只在 SSE observer transport 上不同，业务结果仍来自同一 Unified Runtime。
- Tool Agent 正式 Dev baseline 的 multi-step allowed sequence match 为 `1/4`，required tool coverage 为 `14/20`；`ACTION_PARSE_FAILED` 为 `2/24`，budget stop 为 `1/24`。
- Gate 3 Dev 侧有 `4/24` generation failures；检索找到证据不等于 Generator 覆盖全部 answer obligation。
- 当前默认是本地单用户 Demo，不包含认证、租户隔离或面向公网的部署安全层。

冻结评测保留原始结果；当前产品与维护进度见 [实时状态](docs/status.md)。

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
- `core/engineering_agent.py`、`core/knowledge_library.py`、`core/engineering_knowledge.py`、`core/tool_agent/`：Engineering Agent facade、产品知识库、历史 verified knowledge 与 bounded Tool runtime。
- `api/app.py`：public API routes、runtime lifecycle 与 Engineering product entry。
- `ui/`：Streamlit console、ApiClient 和结果 renderers。
- `scripts/`：startup/full-app smoke、Demo harness、corpus verification 与评测入口。
- `tests/`：unit、API contract、runtime boundary、UI logic 和 release smoke tests。
- `docs/experiments/`：tracked freeze、seal 和 release readiness evidence。
- `docs/roadmap.md`：Release 2.0 主路线与后续阶段。
- `docs/status.md`：唯一实时状态表。
- `docs/technical_debt.md`：技术债清单、重构候选与实际处理进度。
- `docs/study-notes/`：设计演进与面向学习的解释。

推荐阅读顺序是：先看本 README 的架构和限制，再看 `api/app.py`、`core/engineering_agent.py`、`core/engineering_knowledge.py` 与 `core/tool_agent/`，最后沿 `docs/roadmap.md`、`docs/status.md` 和对应 Gate 的 evidence path 核对数字。这样可以把产品路径、实现路径和评测证据保持在同一条可追溯链上。

## Docs

- [实时项目状态](docs/status.md)
- [Release 2.0 本地运行手册](docs/release2_local_runbook.md)
- [技术债清单与处理进度](docs/technical_debt.md)
- [新项目挂载操作](docs/project_mount_runbook.md)
- [2026-10-02 系统覆盖与迁移评估](docs/validation/2026-10-02-system-assessment.md)
- [Release readiness 基线](docs/experiments/gate5_release_readiness_baseline.md)
- [API contract 与 runtime capabilities](docs/study-notes/98-Gate5-后端API契约与运行时能力.md)
- [前后端联调与 Full App Smoke](docs/study-notes/97-Gate5-前后端联调与全应用Smoke.md)
- [Release Demo 与产品验收](docs/study-notes/99-Gate5-Release-Demo与产品验收.md)
- [学习笔记索引](docs/study-notes/README.md)

API 交互细节请运行服务后查看 `/docs`；README 负责项目入口、证据路径和边界，不替代 OpenAPI 或冻结报告。
