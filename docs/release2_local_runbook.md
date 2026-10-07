# Release 2.0 本地运行手册（Local Runbook）

> 目标：在一台新机器上按明确步骤完成 clean install、启动 backend / frontend、
> 健康检查与 smoke。Engineering 主会话是当前 UI 默认入口，旧模式保留在
> Advanced / Demo。当前进度以 [status.md](status.md) 为准，历史评测保持冻结。

当前开发版为 **2.0.0-dev / development**；API/OpenAPI/UI/Demo共用
`core/product_version.py`。这不是Release 2.0正式冻结。当前三个场景的独立样例、
UI操作与会话记录命令见 [Engineering演示手册](demo_engineering_runbook.md)。

## 1. 前置条件

- Windows / Linux / macOS 均可；本项目在 **Python 3.14** 上开发与验证（CI 同版本）。
- `git`、`python -m pip` 可用。
- **不需要 GPU、不需要向量库服务**；检索为本地 BM25，runtime SQLite 为标准库。
- 可选：DeepSeek API Key（仅真实 provider 回答需要；离线测试、CI、smoke 全部不需要）。

## 2. Clean install

```bash
git clone <this-repo> rag-knowledge-base
cd rag-knowledge-base

python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

python -m pip install -r requirements.lock
```

`requirements.lock` 已完整 pin 版本（119 项），不要手动升级；如果需要重建
lock，走独立任务卡，不在本手册范围。

## 3. Engineering Knowledge（默认可维护库，可选初始语料）

默认 `ENGINEERING_KNOWLEDGE_MODE=managed`，产品库保存于
`data/runtime/engineering_knowledge.sqlite3`。可以从空库开始，通过后端
提供的 HTML 页面 `http://127.0.0.1:8000/#knowledge` 上传文档；主会话默认
检索整库。上传、替换、删除与重启恢复见 [知识库说明](knowledge_library_runbook.md)。

以下步骤用于**可选的首次初始化**：先验证 `870e5864df67` / 37 files /
215 chunks / bm25，再导入产品库。历史 benchmark 与下方既有 verified
smoke 显式使用 `ENGINEERING_KNOWLEDGE_MODE=verified`，继续保留原始只读
校验及 readiness 契约。managed 库初始化完成后不再重复导入初始语料。

```bash
git -c core.autocrlf=false clone https://github.com/wgqa/agent_data.git
cd agent_data && git checkout 179f18e812ad63c36c5569de8e86c5ff9a931cb5
```

```powershell
# Windows PowerShell（路径按实际 clone 位置调整）
$env:ENGINEERING_KNOWLEDGE_CORPUS_ROOT = "D:\path\to\agent_data\agent_ai_v1\02_corpus_candidate"
```

```bash
# Linux / macOS
export ENGINEERING_KNOWLEDGE_CORPUS_ROOT=/path/to/agent_data/agent_ai_v1/02_corpus_candidate
```

注意：**必须用 `core.autocrlf=false` clone**（或 clone 后不做换行转换地
checkout）。语料校验按文件字节哈希比对 authority manifest，CRLF 转换会导致
`corpus file hash or size does not match authority manifest`。

DeepSeek key 在启动后端的终端中设置（真实 provider 回答需要）：

```powershell
$env:DEEPSEEK_API_KEY = "your-key"
```

也可以在仓库根目录 `.env` 中配置 `DEEPSEEK_API_KEY` 与语料路径，后端会通过
`load_dotenv()` 自动加载；编辑对应配置项即可，保留已有其它配置。

## 4. 启动 Backend（FastAPI）

```powershell
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Engineering 主链检查（应为 200）：

```bash
curl http://127.0.0.1:8000/capabilities
curl http://127.0.0.1:8000/version               # version=2.0.0-dev / stage=development
curl http://127.0.0.1:8000/engineering/knowledge   # 默认 mode=managed / mutable=true / verified=false
curl http://127.0.0.1:8000/engineering/knowledge/documents
```

`/capabilities.features.engineering_agent=true` 和 `/engineering/knowledge`
的 `ready=true` 表明主链已装配。managed 模式的 `verified=false` 是正常状态，
管理能力由 `mutable=true` 表示；历史 verified 模式才要求冻结 corpus 身份。
`ready=false` 时检查知识库配置、DeepSeek key及后端初始化日志；主链凭据缺失
时，已成功初始化的 managed 文档管理仍可用。就绪检查不调用模型，不证明额度可用。

`/health` 与 `/stats` 仍描述旧Pipeline；旧配置、向量库或Demo初始化失败时可返回
503，Engineering独立初始化且页面仍按各feature判断可用性。需要使用旧Demo时再检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
```

新加的故障隔离检查使用临时无效legacy配置、dummy key、临时项目与数据库，
真实启动uvicorn并让实际页面AppTest连接，只有本地HTTP，不提交模型问题：

```powershell
python scripts/smoke_engineering_isolation.py --corpus-root "$env:ENGINEERING_KNOWLEDGE_CORPUS_ROOT"
```

成功输出 `ENGINEERING_ISOLATION_SMOKE_OK`。需要第3步已有的完整verified corpus，
不会下载语料或模型；不重启或改写正在运行的服务、项目或数据库。

## 5. 打开 HTML 页面 / 可选 Streamlit Demo

浏览器直接打开 `http://127.0.0.1:8000/`。左侧“知识库”进入文档管理，
可查看正文、上传、替换和删除；聊天默认检索整库。HTML 静态资源与 API 同源。

点击 **New chat** 可选择已添加项目或填写本机绝对目录，新对话固定绑定
该项目。顶部和会话列表显示项目名，切换旧对话自动恢复原绑定，无需重启。
知识库继续共享；具体操作见 [本地项目说明](project_mount_runbook.md)。

以下是保留的 Streamlit 内部 Demo：

新开一个终端（沿用同一 venv 与 corpus 环境变量）：

```powershell
$env:RAG_API_URL = "http://127.0.0.1:8000"
python -m streamlit run ui/app.py --server.port 8501
```

浏览器打开 `http://localhost:8501`。默认进入 Engineering Agent 主会话，可创建、
继续或删除服务端保存的会话；Basic RAG、Agentic RAG 与 Structured Tool Agent
位于侧栏折叠的 `Advanced / Demo` 选择器。

## 6. Runtime SQLite（会话持久化）

- 位置：`data/runtime/engineering_conversations.sqlite3`（自动创建）。
- 已被 `.gitignore` 覆盖（`data/runtime/`），**不得提交**。
- 可用 `ENGINEERING_CONVERSATION_DB` 指到自定义路径（测试/隔离用）。
- 项目登记保存在旁边的 `engineering_projects.sqlite3`，可用
  `ENGINEERING_PROJECT_DB` 单独指定；需与会话数据库一起保留以恢复绑定。
- UI 提交 `message` 到 Conversation SSE API，后端加载历史，由 Context Window
  选取最多 6 条 / 1200 token；旧 `/engineering/query` 系列只接受 `question`。
- HTML 默认使用 `/engineering/conversations/{id}/messages/stream/v2`，实时呈现
  工具目标、结果摘要、新增资料与校验状态。V2 的 final/result 带 `activity`，
  与整轮消息原子保存；刷新后 Activity 仍可显示。公开活动不进入 role/content 历史。
  Streamlit、旧客户端的 v1 端点和旧会话继续兼容；HTML 不回退到 v1。
- 每操作使用独立连接，提交或回滚后显式关闭；整轮 user/assistant 消息与结果
  原子保存，保存失败不会发布成功答案。历史全量读取与详情分页仍待优化。

## 7. Smoke（不需要 LLM / API key）

```bash
python scripts/smoke_local_app.py
```

脚本会自行拉起真实 uvicorn + 真实 Streamlit 进程（临时端口），断言 backend
`/health` 200、`/stats`、`/capabilities`、UI 模式齐全，并以
`streamlit.testing.v1.AppTest` 渲染首页。期望输出：

```
FULL_APP_SMOKE_OK
```

## 7a. Engineering request lifecycle（PRODUCT-ENGINEERING-24B）

- 每个 Engineering request 的 public response 可带 `execution` 摘要：
  `elapsed_ms` 是 wall-clock elapsed time，`decision_llm_calls` 是实际
  Decision call 数；`input_tokens` / `output_tokens` 只聚合 provider 回报的
  usage，缺失时保持 `null`，不估算、不输出 raw provider response。
- Tool Agent 执行阶段使用系统拥有的 60 秒 cooperative deadline；前置 Context /
  Planner / Planned Retrieval 不在该计时范围。超时会在
  下一次 Decision 或 Tool 安全边界停止，并返回 safe failure code；不会强杀
  正在进行的 provider 网络调用，也不会改变 5/4/2 budget。
- 进程内最多同时 admission 2 个 Engineering run；满载时 fail-fast 返回
  HTTP 503，不建立 queue。SSE 客户端断开时通过 cancellation event 通知 Runtime，
  后续安全边界不再发起新的 Decision / Tool；正常完成、异常和断开都会在
  worker 实际终止后由 completion callback exactly once 释放 admission slot。
- 这组 lifecycle 约束不改变 Agent 的 Prompt、Router、Evidence、Tool registry
  或 conversation atomic-turn 语义。离线回归与 `smoke_local_app.py` 均不需要
  API key。

## 8. 离线测试

2026-10-07 HTML 切换 V2：CI/下列清单新增 `test_engineering_conversation_stream_v2.py`，
共 **53 模块**。相关 8 模块 **100 passed / 3 warnings**，包含 Node 的
**29 项**反馈/V2 传输及活动展示子检查，不与 Python 数量累加。实际 HTML 在
隔离服务验证实时读取记录、刷新恢复、证据跳转、V1 旧会话继续发送 V2 消息及
拒答提示；真实工具与脚本化决策，零外部模型调用。见 [HTML V2 验证](validation/2026-10-07-html-stream-v2.md)。

2026-10-06 用户反馈：CI/下列清单新增 `test_engineering_feedback.py`，共
**52 模块**。相关 11 模块 **113 passed**，其中专项 20 项包含 Node 的
16 项前端反馈/SSE 子检查；文案和安全动作收口后专项 20 项复验通过，
不累加。CI 显式提供 Node 24，本地缺少 Node 时该子检查会标记 skip。
真实 HTML 验证旧历史、新 SSE 拒答、资料查看、仅填输入的恢复按钮、
超时和小屏，零模型调用。见 [用户反馈验证](validation/2026-10-06-user-feedback.md)。

2026-10-05 本地项目绑定：CI/下列手册清单新增 `test_local_project_binding.py`
和 `test_engineering_project_workspace.py`，共 **51 模块**。相关 9 模块
**119 passed / 1 skipped**，另 7 模块 API/SSE/启动回归 **104 passed**，
两组不重叠。真实 HTML 在隔离服务验证项目登记、无效目录、两项目读取与切换、
刷新恢复及 390px 小屏；零外部模型请求，未运行全量 pytest 或 GitHub Actions。
见 [项目绑定验证](validation/2026-10-05-local-project-binding.md)。

2026-10-05 知识库管理：CI/下列手册清单新增 `test_knowledge_library.py`，
共 **49模块**。本次知识库专项最终 **20 passed**；其余相关启动、API、会话、
检索与 SSE 回归 **195 passed / 1 skipped**。真实 HTML 页面在隔离库中验证
上传、替换、筛选、正文与删除取消，删除 API 后检索同步消失；手机宽度无
横向溢出。零模型调用，未运行全量 pytest 或 GitHub Actions，详见
[知识库验证](validation/2026-10-05-knowledge-library.md)。下方是此前切片记录。

2026-10-04 交付一致性切片：CI/手册清单现为 **48模块**，新增产品演示/版本与
已有startup/full-app/legacy-demo回归。当前Full App smoke可传`--corpus-root`
验证主Engineering装配和三个入口；默认smoke使用隔离的空语料配置，不继承真实
项目、语料、数据库或key，不能将默认smoke当作主链ready证明。

```powershell
python scripts/smoke_local_app.py --corpus-root "$env:ENGINEERING_KNOWLEDGE_CORPUS_ROOT"
```

检查记录见 [交付验证](validation/2026-10-04-product-delivery.md)。下方44/42/38/37
模块为前几次切片记录；本轮也只做相关局部验证，未执行完整CI或全量测试。

2026-10-04 后续质量汇总/启动隔离：下列清单现为 **44模块**。本次按授权只跑
API/UI/启动与报告六个相关模块，**122 passed**；真实故障隔离smoke通过，
零新增付费模型调用，未执行整个CI清单、全量或GitHub Actions。

质量报告可单独离线重新生成：

```powershell
python scripts/report_current_quality.py --output-prefix docs/validation/2026-10-04-quality-baseline
```

它保留内容分数与运行状态的区别，输出各阶段质量、完整token usage与耗时，
并展示当前代码与最近真实检查的差异。见 [质量索引](validation/2026-10-04-quality-baseline.md)。
下面42/38/37模块和其它结果均为此前切片记录。

2026-10-04 核心任务入口/对象取证切片：三张卡片先填写目标，明确变更文件后直接围绕该文件调查；Engineering启用Reader v4与对应decision v4，legacy v2保留，无新增生产环境变量。前三个轻量候选未启用。下列CI/手册清单为 **42模块**；本地执行该清单加四架构模块959 passed/9 skips，随后Reader/表单局部回归通过、不累加。54真实请求包括五个实际会话SSE/持久化检查；完整答案仍有未读语义推断与一般规划缺口，第一项仍OPEN。见 [任务范围](core_workflows.md)、[验证记录](validation/2026-10-04-core-workflows.md)。下段38模块是此前切片状态。

2026-10-03 最新测试取证切片：Engineering 使用测试域搜索 v7 与 grounded v2，legacy 默认 v5/v1 保留，无新增环境变量。下列 CI/手册清单现为 **38 模块**；相关23模块371 passed/7 skips，最终规则六模块184 passed（集合重叠不累加），新模块37项通过。32次真实请求中，原测试拒答与中文改写正确完成，另一个改写仍有错误 pytest 建议；系统只读取测试与建议命令，没有执行挂载仓库测试。见 [验证报告](validation/2026-10-03-project-test-acquisition.md)。下面的37模块数字是前一切片当时状态。

2026-10-03：Engineering Planner 显式使用现有字段组合约束的提示词 v2，旧 Gate 3 v1 默认身份保持可用；无需新增环境变量。相关 15 模块局部 **377 passed / 3 warnings**，CI/下列手册清单为 37 模块。16 次真实旧/新请求验证了计算、通用问答与排序的误拒答修复；源码/知识语义支持仍有缺口，见 [验证报告](validation/2026-10-03-planner-no-retrieval-alignment.md)。本轮未运行完整 CI 或全量测试。

与 CI（`.github/workflows/ci.yml`）同一组 provider-free 回归：

```bash
python -m pytest -q \
  --basetemp="$TMP/my_agent_pytest" \
  tests/test_api.py \
  tests/test_knowledge_library.py \
  tests/test_local_project_binding.py \
  tests/test_engineering_feedback.py \
  tests/test_engineering_project_workspace.py \
  tests/test_engineering_startup_isolation.py \
  tests/test_current_quality_report.py \
  tests/test_product_delivery.py \
  tests/test_release_startup.py \
  tests/test_release_app_startup.py \
  tests/test_release_demo.py \
  tests/test_tool_agent_core.py \
  tests/test_tool_agent_decision.py \
  tests/test_tool_agent_runtime.py \
  tests/test_tool_agent_evidence.py \
  tests/test_project_evidence_excerpt.py \
  tests/test_tool_agent_real_tools.py \
  tests/test_engineering_agent_api.py \
  tests/test_test_discovery_tools.py \
  tests/test_git_change_tools.py \
  tests/test_read_project_context.py \
  tests/test_source_definition_reading.py \
  tests/test_code_search_scope.py \
  tests/test_arch_integration_12a_code_search_kind_filter.py \
  tests/test_arch_integration_12a_r1_tool_identity.py \
  tests/test_conversation_context.py \
  tests/test_g9_reliability.py \
  tests/test_agent_runtime_adapters.py \
  tests/test_domain_models.py \
  tests/test_fixed_size_chunker.py \
  tests/test_recursive_chunker.py \
  tests/test_token_counter.py \
  tests/test_chunk_budget_infrastructure.py \
  tests/test_engineering_verification.py \
  tests/test_engineering_requirements.py \
  tests/test_project_document_requirements.py \
  tests/test_project_test_acquisition.py \
  tests/test_project_target_reader.py \
  tests/test_core_workflow_entry.py \
  tests/test_core_workflow_streamlit.py \
  tests/test_core_workflow_reference_paths.py \
  tests/test_engineering_planner_alignment.py \
  tests/test_engineering_context.py \
  tests/test_engineering_retrieval.py \
  tests/test_unified_engineering_runtime.py \
  tests/test_tool_agent_finalization_guard.py \
  tests/test_engineering_stream.py \
  tests/test_engineering_stream_v2.py \
  tests/test_engineering_conversation_stream_v2.py \
  tests/test_product_conversation_20.py \
  tests/test_conversation_store_lifecycle.py \
  tests/test_product_grounding_21.py \
  tests/test_product_repair_23.py
```

全量回归命令（本次维护按授权只做局部验证，未运行此命令）：

```bash
python -m pytest -q --basetemp="$TMP/my_agent_pytest_full"
```

Windows 注意：pytest 默认 temp 目录位于用户目录下，用户名含空格时可能触发
`PermissionError (WinError 5)`，因此本地命令一律带显式 `--basetemp`（CI 的
`$RUNNER_TEMP` 无此问题）。

临时目录也应尽量短。2026-10-02 的全量诊断中，过长的工作区临时路径使 Git
clone fixture 报 `Filename too long`；改用短目录后全量通过。不要据此放宽项目
隔离断言。该次使用现有 Gate 4 corpus 验证了原本可选的一项 provenance check，
历史结果为 2658 passed / 6 skipped；6 项剩余跳过均因 Windows 无法创建 symlink。
完整过程见 [系统评估](validation/2026-10-02-system-assessment.md)。

2026-10-03 的搜索切片为**未晋升候选实验**，默认 registry 继续 v5。新增
`test_code_search_scope.py` 在 CI 中验证独立候选及默认不晋升边界；相关 9 个文件
局部 **193 passed / 7 skipped**，未执行完整 CI / 全量回归。16 个配对真实用户
请求（68 次实际 provider 调用）未证明取证收益，见
[范围搜索验证](validation/2026-10-03-source-search-v6.md)。

同日文档取证切片保留 `PROJECT_DOC_V1`，相关局部 **278 passed / 3 warnings**，
CI 所选新文档模块（含历史身份防漂移）复验 **31 passed / 2 warnings**，两者不累加。
该阶段的 CI 与运行手册清单逐项对齐，当时共 35 个模块；没有执行完整 CI / 全量回归。
两阶段 48 个真实用户请求 / 187 次 provider 调用保留正负结果，5/4/2 不变；
详见 [文档取证验证](validation/2026-10-03-project-document-acquisition.md)。

随后公共读取正文一致性切片，相关 15 模块 **303 passed / 6 skipped / 3 warnings**，
最大窗口三项改用真实 Reader 的复验 **3 passed**，不与前者累加。
当前上面的 CI / 运行手册清单共 36 模块；上一段 35 是文档切片完成时的历史清单。
固定回放 41 次旧成功读取，二次截断 23 → 0；没有新增 provider 调用，未执行完整 CI / 全量。
项目读取公开 snippet 上限变为 18360 字符，严格旧客户端需更新 schema；
见 [片段一致性验证](validation/2026-10-03-evidence-excerpt-fidelity.md)。

随后共享文件分类切片记录全量 **2691 passed / 7 skipped**，其中可选 provenance
校验已单独补跑 **1 passed**，剩余 6 项为 Windows symlink 限制；见
[实时状态](status.md)中的该切片记录。这里保留实际执行口径，不合并推算新基线。

本次 CI / SQLite 维护只执行下面五个测试文件，结果 **70 passed**；无真实模型
请求，未执行完整 CI job 或全量回归。README / 运行手册对齐仅核对源码，未测试。

```bash
python -m pytest -q --basetemp="${TMPDIR:-/tmp}/my_agent_pytest_maintenance" \
  tests/test_source_definition_reading.py \
  tests/test_arch_integration_12a_code_search_kind_filter.py \
  tests/test_arch_integration_12a_r1_tool_identity.py \
  tests/test_conversation_store_lifecycle.py \
  tests/test_product_conversation_20.py
```

## 9. 已知边界

- 不配置 API key 时：smoke、离线测试、backend/frontend 健康全部可用；
  `/engineering/query` 会因 provider runtime 初始化失败而不可用（这是显式
  fail-closed，不是 bug）。
- HTML 会话的 git diff / code_search 类 Tool 使用该会话创建时选择的项目；
  旧 question-only API / Streamlit 使用 `ENGINEERING_PROJECT_ROOT` 的启动
  默认目录（默认仓库自身）。不要把语料仓库当成 Engineering Project。
- CI 不下载任何语料、不运行真实 provider、不跑 Holdout / Set A 评测。

## 10. 挂载其它项目

源码目录和知识库分别管理。HTML 新对话可添加或选择本地目录，切换不重启；
`ENGINEERING_PROJECT_ROOT` 仍控制启动默认项目，仅修改该默认配置需要重启。
操作与已验证限制见 [新项目挂载手册](project_mount_runbook.md)。
