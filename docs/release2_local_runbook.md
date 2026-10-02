# Release 2.0 本地运行手册（Local Runbook）

> 目标：在一台新机器上按明确步骤完成 clean install、启动 backend / frontend、
> 健康检查与 smoke。Engineering 主会话是当前 UI 默认入口，旧模式保留在
> Advanced / Demo。当前进度以 [status.md](status.md) 为准，历史评测保持冻结。

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

## 3. Engineering Knowledge Corpus（必需，指向已冻结语料）

Unified Engineering Runtime 启动时会校验语料身份（corpus_id
`870e5864df67` / 37 files / 215 chunks / bm25），不通过则 Engineering 端点
不可用（其它 legacy 端点不受影响）。

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

健康检查（都应为 200）：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/stats
curl http://127.0.0.1:8000/capabilities
curl http://127.0.0.1:8000/engineering/knowledge   # ready=true / verified=true / corpus_id=870e5864df67
```

`/engineering/knowledge` 的 `ready=false` 基本都是 corpus 环境变量缺失或哈希
不匹配，回到第 3 步。

## 5. 启动 Frontend（Streamlit）

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
- UI 提交 `message` 到 Conversation SSE API，后端加载历史，由 Context Window
  选取最多 6 条 / 1200 token；旧 `/engineering/query` 系列只接受 `question`。
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

与 CI（`.github/workflows/ci.yml`）同一组 provider-free 回归：

```bash
python -m pytest -q \
  --basetemp="$TMP/my_agent_pytest" \
  tests/test_api.py \
  tests/test_tool_agent_core.py \
  tests/test_tool_agent_decision.py \
  tests/test_tool_agent_runtime.py \
  tests/test_tool_agent_evidence.py \
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
  tests/test_engineering_context.py \
  tests/test_engineering_retrieval.py \
  tests/test_unified_engineering_runtime.py \
  tests/test_tool_agent_finalization_guard.py \
  tests/test_engineering_stream.py \
  tests/test_engineering_stream_v2.py \
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
- 本仓库的 git diff / code_search 类 Tool 以 `ENGINEERING_PROJECT_ROOT`
  指向的目录为工程对象（默认仓库自身）；不要把语料仓库当成 Engineering
  Project。
- CI 不下载任何语料、不运行真实 provider、不跑 Holdout / Set A 评测。

## 10. 挂载其它项目

源码目录和知识库目录分别配置；`ENGINEERING_PROJECT_ROOT` 绑定在后端启动时，
切换需要重启。一步步操作与已验证限制见 [新项目挂载手册](project_mount_runbook.md)。
