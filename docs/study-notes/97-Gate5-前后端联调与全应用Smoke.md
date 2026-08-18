# 97-Gate5：前后端联调与全应用 Smoke

## 1. Integration smoke 是什么

Integration smoke 是发布链路的最小可用性证明：把真实进程、真实配置边界和真实模块连接起来，只验证关键路径能启动、能通信、能返回基本事实。它不是质量评测，也不是完整端到端场景；本轮的关键路径是 FastAPI → `/health`、`/stats` → Streamlit `ApiClient` → 页面脚本。

## 2. Backend startup smoke 与 Full App smoke

RUN-04 的 backend startup smoke 只启动真实 uvicorn，检查 `/health` 和 OpenAPI 路由。它能证明 API 进程可启动，但不知道前端如何消费响应。

RUN-05 在同样的临时 cwd、隔离 vector store、dummy key 和 Hugging Face 离线环境中再启动真实 Streamlit。除了检查 Streamlit 的 `/_stcore/health`，还用 `streamlit.testing.v1.AppTest` 执行 `ui/app.py`，并让页面通过真实 `ui.api_client.ApiClient` 访问刚启动的 FastAPI。

## 3. 为什么端口打开不等于 UI 可工作

Streamlit server 可以监听端口，即使页面脚本导入失败、后端地址错误、health/stats contract 不匹配，端口仍可能返回健康状态。因此 process-level health 只能证明服务器活着；AppTest 才能证明页面脚本实际执行，并观测到标题、后端在线状态、真实配置、stats 和模式控件。

## 4. AppTest 的价值

`AppTest.from_file("ui/app.py")` 不需要浏览器或 Selenium，却会运行页面代码和 Streamlit widget tree。本轮没有 monkeypatch `ApiClient`，而是设置 `RAG_API_URL` 指向动态后端端口，真实执行 `/health`、`/stats`。模式切换只触发页面重跑，不提交任何 query。

## 5. 动态端口解决什么问题

脚本分别申请 backend 和 Streamlit 的 `127.0.0.1` 空闲端口，避免依赖 8000/8501，也避免开发机上已有服务或并行 CI 任务造成冲突。前端地址通过环境变量传入，测试结束后两个子进程都终止，临时目录自动清理。

## 6. 环境变量解耦

`ui/app.py` 使用 `RAG_API_URL`，未设置时仍默认为 `http://localhost:8000`，所以日常运行方式不变。Smoke 可以把动态 backend 地址注入 Streamlit 子进程和 AppTest，而不需要把测试端口写进 UI 代码。

## 7. Smoke 为什么不调用 LLM

发布 smoke 的问题是“应用能否交付并互相连接”，不是“模型回答得好不好”。本轮使用 dummy `DEEPSEEK_API_KEY`、dummy `OPENAI_API_KEY`、空 `HF_HOME`、`HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`，只读取 health/stats，不调用 `/query`、`/agent/query` 或 `/tool-agent/query`。真实模型和 Planner 应由独立的 Demo/benchmark 流程验证。

## 8. 四类验证的边界

| 层次 | 证明什么 | 本轮是否执行模型 |
|---|---|---:|
| Unit | 单个函数、协议解析、渲染分支的局部正确性 | 否 |
| Integration smoke | 真实组件和进程能启动并通信 | 否 |
| E2E / Demo | 用户路径和业务结果完整跑通 | 本轮不做 |
| Formal benchmark | 冻结数据、身份和指标上的可比较质量结论 | 本轮不做 |

## 9. 当前项目四层验证体系

当前交付证据可按四层理解：单元/API contract 测试保证局部行为；RUN-04 backend smoke 保证真实 FastAPI 启动；RUN-05 full app smoke 保证 FastAPI 与 Streamlit 的真实连接；Gate 3/4 的冻结评测和后续 Demo 才负责检索、答案、Planner 或 Tool-Agent 质量。层次越高，成本和外部依赖越大，因此不能用低层测试替代高层启动证据，也不能把 smoke 结果写成模型质量结论。

## 10. 面试中的 Release engineering 表述

可以这样概括：我为 RAG 应用建立了离线 release smoke，使用临时工作目录和动态 localhost 端口启动真实 FastAPI 与 Streamlit；前端通过环境变量连接真实 backend，`AppTest` 执行页面脚本并验证 health/stats、模式和页面结构；整个检查不需要真实 key、不下载模型、不调用 LLM，失败时会脱敏输出并清理子进程。它补上了“服务能启动”与“用户界面真的能接上服务”之间的证据缺口。
