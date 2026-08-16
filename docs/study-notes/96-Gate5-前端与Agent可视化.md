# 96-Gate5 前端与 Agent 可视化

> **任务**：G5-APP-04-FRONTEND-AGENT-DEMO-ALIGNMENT
> **日期**：2026-08-17
> **产物**：`ui/app.py`（三模式 console）+ `ui/api_client.py` + `ui/renderers.py`
> **本笔记定位**：从学习角度讲清"把 Agent 能力可视化给面试官看"这一层。

---

## 1. 为什么 AI 项目需要 Demo Console

后端能力（RAG / Agentic RAG / Tool Agent）**存在不等于被看见**。面试官 / 同学不会去读 API schema，他们看的是**网页**。

Demo Console 的价值：

- **把三类能力变成三张可点击的页面**——面试时切模式、输问题、看结构化结果，10 秒讲清楚"这个项目做了什么"；
- **展示工程分层**：UI → API → Runtime 各司其职，本身就是架构说明；
- **让 trace / planner / route 等内部结构可见**——这些是普通 RAG 聊天框永远给不了的差异化。

本项目升级前 UI 只接 `/query`，看起来就是个普通 RAG Chatbot；升级后三模式全接上，网页才配得上后端已经做完的 Gate 3/4。

---

## 2. UI / API / Agent Runtime 三层边界

| 层 | 职责 | 本轮改动 |
|---|---|---|
| **UI**（Streamlit） | 输入、展示、交互；**只消费 API 返回的 JSON** | 三模式 console |
| **API**（FastAPI） | 请求/响应契约、安全边界（`extra=forbid`、safe trace） | 不变 |
| **Agent Runtime** | Planner / Adaptive Retrieval / Tool Loop 真实逻辑 | 不变 |

关键原则：**前端适配后端，而不是为 UI 改 AI 内核**。UI 只展示 API 返回的事实字段；如果发现展示不了的 contract 缺陷 → STOP 报告，不自行改 `api/**` / `core/**`。

本项目严格守住了这条：`ui/app.py` / `ui/api_client.py` / `ui/renderers.py` 三个文件全是前端，后端一个字节没动。

---

## 3. 为什么前端不能展示 CoT

Chain-of-Thought（思维链）= 模型"怎么想的"（内部推理步骤）。展示它的问题：

1. **安全**：CoT 可能泄露 Prompt、私有上下文、甚至模型的"小聪明"；
2. **可信度**：CoT 不等于事实，展示了反而让面试官怀疑你是不是在"编"；
3. **边界**：CoT 是模型内部状态，不是 API 契约的一部分，UI 没有权利拿。

所以本项目 API 层早就做了 safe trace（白名单字段），前端**只渲染 trace 里已有的字段**，绝不推断/补造"思考过程"。

---

## 4. Safe Trace 和 Chain-of-Thought 的区别

| | Safe Trace | Chain-of-Thought |
|---|---|---|
| 内容 | **执行事实**：planner 结果、route 选择、检索了哪些子问题、tool 调了哪个、状态码 | **推理过程**：模型内部"先想 A 再想 B" |
| 来源 | Runtime 结构化事件（`event_type` + `summary` + 白名单字段） | 模型输出（未暴露） |
| 可核验 | 是（每步都有真实字段） | 否（不可复现） |
| UI 角色 | 默认折叠展示 | **禁止**展示 |

本项目 Agent trace 是 `planning_completed → routing_completed → retrieval_completed → evidence_merged → verification_completed → generation_completed → run_completed`；Tool trace 是 `Decision（tool_name）→ Tool Result（status）→ ... → runtime_stopped`。这些是**执行事实**，不是 CoT。

---

## 5. completed / refused / deferred / failed 的产品语义

同一个"非 200 也非成功"要分清楚，不能一锅端成错误：

| status | 含义 | UI 呈现 |
|---|---|---|
| **completed** | 正常完成 | ✅ 绿色 success |
| **refused** | Agent 主动拒绝（如安全拒绝） | ⚠️ warning —— **不是错误** |
| **deferred** | 需要但不支持（如 decomposed 只路由不执行） | ⚠️ warning —— **不是错误** |
| **failed** | 结构化失败（预算用尽、解析失败等） | ❌ error —— 是 Agent 的**正常系统结果** |

重点：refused / deferred / failed 都是 **HTTP 200 的结构化结果**（后端语义：Agent 自己的拒绝/失败≠HTTP 500）。UI 不能把它们渲染成"查询失败: {detail}"，也不能渲染成普通成功。这正是 §15 反复强调的"不要混"。

---

## 6. API Client 为什么与页面渲染分离

把 HTTP 从页面代码里拆出来（`ui/api_client.py`），好处：

- **统一错误分类**：connection_error / timeout / http_error / invalid_response，页面层不再到处 try/except `requests`；
- **统一契约**：base_url / timeout / JSON 解码只有一处；
- **可测试**：`tests/test_ui_api_client.py` 用 monkeypatch mock 掉 `requests.request`，就能单独验证每个端点的 payload 和错误语义——**不需要真后端**；
- **页面只关心渲染**：`app.py` 拿 `result` dict → 交给 `renderers.py`；`renderers.py` 拿 dict → 渲染。

一条干净的链：**UI 输入 → ApiClient → 后端 → ApiClient 归一化 → renderers 展示**。

---

## 7. 三种 Agent/RAG 模式对应的后端链路

| 模式 | 前端调用 | 后端链路 |
|---|---|---|
| **Basic RAG** | `POST /query` | 检索 → Rerank → Generate → Citation |
| **Agentic RAG** | `POST /agent/query` | Planner → Adaptive Router → (多子问题) Retrieval → RRF Merge → Verification → Answer → Citation |
| **Structured Tool Agent** | `POST /tool-agent/query` | Decision → Tool → Observation → Decision（有界 Loop）→ Final |

三种模式**历史隔离**（`messages_by_mode`），切模式只看到当前模式的消息——避免演示时 Basic 的问答混进 Tool Agent 页面。

---

## 8. 面试现场如何用 UI 讲项目架构

推荐 2 分钟演示脚本：

1. **开场**：打开 Demo Console，三个模式 = 三种能力（Basic / Agentic / Tool Agent）。
2. **Basic RAG**：传一个文件进知识库 → 问一个问题 → 展示答案 + Sources。讲"最朴素的 RAG 链路"。
3. **Agentic RAG**：切 Agentic → 问一个需要分解的问题 → 展示 **Planner**（query_type / plan_id / subqueries）→ **Adaptive Route**（Planner 的 reason_code 和 Router 的 strategy_reason_code 分开）→ **Verification**（coverage）→ 答案 + 证据。这里可以讲"为什么不能只测最终答案"。
4. **Tool Agent**：切 Tool Agent → 问一个需要计算/查代码的问题 → 展示 **Iterations / Tool Calls / Tool Errors** 三个计数器 + Decision→Tool Result 的安全 trace。讲"有界循环 + Observation 回喂 + safe trace ≠ CoT"。
5. **收尾**：把 trace 折叠，强调"UI 只展示执行事实，不展示思维链"。

加分点：展示 refuse 场景（Tool Agent 拒绝不合理请求），顺势讲"refused 是结构化结果不是 HTTP 错误"。

---

## 附：本轮零副作用声明

- 未改 `api/**`、`core/**`、`config.yaml`、`requirements.*`、CI workflow、frozen artifacts、evaluation datasets、README。
- 后端 contract 足够；前端全部适配，未为 UI 改 AI 内核。
- UI client 测试 10 passed（monkeypatch，无真后端）；py_compile 通过；未消耗 DeepSeek。
