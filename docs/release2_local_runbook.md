# Release 2.0 本地运行手册（Local Runbook）

> 目标：在一台新机器上按明确步骤完成 clean install、启动 backend / frontend、
> 健康检查与 smoke。本文是操作手册，不是设计文档；README 的作品集表达属于
> DELIVERY-27，不在此处。

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

可选：DeepSeek key（真实 provider 回答需要；放仓库根目录 `.env`，已被
`load_dotenv()` 自动加载）：

```powershell
Set-Content -Path .env -Value "DEEPSEEK_API_KEY=sk-..." -NoNewline
```

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

浏览器打开 `http://localhost:8501`。UI 默认模式即 Engineering Agent；side-by-side
的 legacy demo 在 Advanced/Demo 选择器中。

## 6. Runtime SQLite（会话持久化）

- 位置：`data/runtime/engineering_conversations.sqlite3`（自动创建）。
- 已被 `.gitignore` 覆盖（`data/runtime/`），**不得提交**。
- 可用 `ENGINEERING_CONVERSATION_DB` 指到自定义路径（测试/隔离用）。

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
- 单次 Engineering run 使用系统拥有的 60 秒 cooperative deadline。超时会在
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
  tests/test_product_grounding_21.py \
  tests/test_product_repair_23.py
```

全量回归（Release 2.0 当前基线：2657 passed / 7 skipped）：

```bash
python -m pytest -q --basetemp="$TMP/my_agent_pytest_full"
```

Windows 注意：pytest 默认 temp 目录位于用户目录下，用户名含空格时可能触发
`PermissionError (WinError 5)`，因此本地命令一律带显式 `--basetemp`（CI 的
`$RUNNER_TEMP` 无此问题）。

## 9. 已知边界

- 不配置 API key 时：smoke、离线测试、backend/frontend 健康全部可用；
  `/engineering/query` 会因 provider runtime 初始化失败而不可用（这是显式
  fail-closed，不是 bug）。
- 本仓库的 git diff / code_search 类 Tool 以 `ENGINEERING_PROJECT_ROOT`
  指向的目录为工程对象（默认仓库自身）；不要把语料仓库当成 Engineering
  Project。
- CI 不下载任何语料、不运行真实 provider、不跑 Holdout / Set A 评测。
