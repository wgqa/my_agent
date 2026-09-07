# Streamlit Frontend Productization Freeze

> PRODUCTIZATION-18B：正式冻结当前 Streamlit 前端，明确它的产品定位、已验证
> 能力、已知视觉限制，以及未来 Web UI 的推荐迁移边界。本文档是冻结/交接文档，
> 不是新一轮 UI 改造计划。

**冻结结论（2026-09-07）：**

- **PRODUCTIZATION-18A = ACCEPT / CLOSED**
- **PRODUCTIZATION-18A-R1 = ACCEPT / CLOSED**
- **Current Streamlit UI = FUNCTIONAL DEMO / INTERNAL ENGINEERING UI = FROZEN**

即：当前 `ui/` 是一个功能完整的产品演示与内部工程 UI，不是最终作品集视觉
前端，不是 production-grade UI，也不是 fully polished frontend。

## 1. 当前 Streamlit UI 的定位

`ui/` 继续承担：

- local development UI；
- functional product demo（Engineering Agent smoke / demo 入口）；
- Evidence inspection；
- SSE activity inspection；
- legacy mode access；
- runtime / settings inspection。

它不再继续朝作品集视觉前端方向打磨。

## 2. 当前已支持的能力（不扩大 claim）

- Engineering Agent 是 primary product mode（conversation-first）；
- 会话创建 / 切换 / 本地删除；
- FastAPI integration（`RAG_API_URL`，REST + Engineering SSE）；
- Engineering SSE streaming（activity 与 answer 流式呈现）；
- Answer-first presentation（答案优先，过程细节下沉）；
- Knowledge / Code / Doc / Change / Test 五类 Evidence 展示；
- Evidence IDs / paths / line ranges / snippets（bounded public evidence）；
- Runtime activity visibility（tool call / verification / evidence added 等活动）；
- Refused / failed / completed 三种终态的区分呈现；
- Advanced runtime details（执行摘要压缩后，raw-safe trace 收纳在高级区）；
- Workspace 状态：Project / API / Knowledge（public identity，不暴露本地路径）；
- Legacy 模式保留在 Advanced / Demo 区：Basic RAG、Agentic RAG、Structured Tool Agent。

以上能力均由 `tests/test_ui_productization_18a.py`、`test_ui_renderers.py`、
`test_ui_chat_first.py`、`test_ui_streaming.py`、`test_ui_capabilities.py`、
`test_ui_api_client.py` 与 `scripts/smoke_local_app.py` 的
`FULL_APP_SMOKE_OK` 基线支撑。

## 3. 18A / 18A-R1 已解决的问题（历史记录）

**PRODUCTIZATION-18A：**

- Engineering Agent 成为 primary product path；
- legacy modes 移入 Advanced / Demo；
- Evidence presentation 改进（结构化 kind/id/path/lines/snippet 呈现）；
- Workspace status 增加（Project / API / Knowledge）；
- conversation UX 改进（创建 / 切换 / 删除）；
- streaming activity surfaced；
- presentation helpers / styles 与页面逻辑分离（renderers.py / components.py / styles.py / streaming.py / api_client.py）。

**PRODUCTIZATION-18A-R1：**

- homepage density improved；
- title hierarchy reduced；
- Agent answer hierarchy improved；
- Evidence markdown hierarchy bug fixed；
- Evidence snippets 与 Markdown 渲染隔离（`st.text(snippet)`）；
- execution summary compressed；
- raw-safe trace 移入 Advanced runtime details；
- sidebar tightened；
- streaming chrome normalized。

## 4. 真实剩余限制（KNOWN ACCEPTED LIMITATIONS，只记录，不再修）

- Streamlit default visual language remains visible；
- default sidebar / expander / chat-input behavior remains；
- layout freedom is limited（受 Streamlit 组件体系约束）；
- page still follows Streamlit document-flow model（单列纵向文档流，不是应用式布局）；
- right-side dedicated Activity / Evidence panels are awkward（难以做成并排
  检查面板）；
- Deploy / Streamlit chrome remains visible in local/default presentation；
- fine-grained component interaction is limited；
- final visual polish ceiling is below a custom web frontend。

这些都是当前接受的已知限制，不是 blocker；不会为消除它们而重开 18A-R2。

## 5. Evidence 展示不再重开

R1 已采用 `st.text(snippet)` 将 Evidence snippet 与 Markdown 渲染隔离，修复
了 markdown 层级污染问题。之后不再继续：改 Evidence renderer、改 markdown
策略、改 snippet height、改 card CSS——除非发现真正的 correctness bug。

## 6. Further Streamlit visual polish: STOP

进一步的 Streamlit screenshot-driven polish：**STOP**。

原因：18A/18A-R1 之后已观察到明显边际收益下降；继续调整 CSS / spacing /
expander 并不能解决 Streamlit 本身的布局模型与产品形态限制。本任务禁止顺手
再调 padding、换字体、改颜色、再做 sidebar。

## 7. Future showcase Web UI：DEFERRED / NOT STARTED

推荐方向：**Vanilla HTML + CSS + JavaScript**（而不是默认 React）——项目
主链价值在后端 Agent，前端目标是 showcase quality，不是新增前端技术复杂度。

建议初始结构：

```text
frontend/
├── index.html
├── styles.css
└── app.js
```

如后续变复杂，再拆：

```text
frontend/
├── index.html
├── css/
│   └── styles.css
└── js/
    ├── api.js
    ├── stream.js
    ├── chat.js
    └── app.js
```

## 8. Future Web UI 架构边界

未来 Web UI 只消费现有 public contracts：

- FastAPI REST；
- Engineering SSE；
- Project API；
- Knowledge status；
- Engineering response schema。

**不因为换前端而重写 Agent Runtime。** 目标形态：

```text
frontend
    ↓
FastAPI public API / SSE
    ↓
Unified Engineering Runtime
```

## 9. 推荐未来部署形式（NOT IMPLEMENTED）

优先记录的部署形态：**FastAPI serves static web frontend**：

```text
/                → frontend index
/static/*        → CSS / JS
/engineering/*   → Agent API
```

优点：single origin、无需独立前端服务器、无需不必要的前端 build pipeline。
**当前 NOT IMPLEMENTED**；本任务不开始实现，未来另行授权。

## 10. Streamlit 不删除

未来即使新增 `frontend/`，当前 `ui/` 仍保留为 internal / debug /
development UI，不计划立刻删除。最终形态可以是：

```text
ui/          → Streamlit internal console
frontend/    → Showcase web UI
```

## 11. 校招边界（Interview / Project Value）

当前前端已经足够证明：Agent is runnable、SSE works、Evidence is
observable、Runtime is inspectable。求职主线是 **AI Backend / Agent
Engineering**，因此不再投入大量时间追求 Streamlit 视觉极限。未来自定义
Web UI 的目标是 showcase quality，而不是把前端技术复杂度变成项目核心卖点。

## 12. Validation（2026-09-07 执行）

- `pytest -q tests/test_ui_productization_18a.py tests/test_ui_renderers.py
  tests/test_ui_chat_first.py tests/test_ui_streaming.py
  tests/test_ui_capabilities.py tests/test_ui_api_client.py` → 65 passed；
- `python scripts/smoke_local_app.py` → FULL_APP_SMOKE_OK；
- `git diff --check` → PASS。

冻结期间不改代码：本轮只有本文档与 `docs/status.md` 两个文件变化。
