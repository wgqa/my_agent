# Release 2.0 Product Completion Roadmap

> PRODUCT-COMPLETE-19：Release 2.0 Product Completion Route Freeze（2026-09-07）。
> 本文档是仓库内**短而权威**的 Product Completion Contract：新执行者 10 分钟内
> 应该明白"接下来为什么做 20，而不是继续调实验或上 Multi-Agent"。
> 输入材料：三方审计收敛版 `RAG_Agent_Release2_Product_Completion_Roadmap_2026-09-07.md`
> （外部路线文档，仅作路线输入；与其冲突时以当前 Git / code / frozen artifact 为准）。

## 1. Purpose

把当前真实项目状态、Release 2.0 剩余 Product DoD、用户场景验收原则和后续
任务顺序正式冻结，防止后续执行者把 **Architecture Complete** 误当成
**Product Complete**。本路线不重开 Gate 1～G12，不重写历史冻结实验，不改变
项目最终身份，不另起第二/第三条 Product Runtime。

## 2. Current Reality（2026-09-07）

- **Project Identity：** Evidence-Grounded AI Engineering Agent（面向 AI /
  RAG / Agent 研发场景的可评测智能研发 Agent）。不得重新定位成 Generic
  Coding Agent / Multi-Agent Platform / EvoAgent Clone / ChatGPT Clone /
  AI Dev Platform。
- **Architecture-driven Core Agent Development = DONE；** Integration v7 =
  CONDITIONAL ACCEPT / CLOSED；Architecture Integration = ACCEPT / CLOSED。
  Planner / Router / Guard architecture / Unified Runtime migration
  （ARCH-RUNTIME-02 ～ ARCH-CUTOVER-07）不重新打开。
- **Current Product Semantic Quality = CONDITIONAL / KNOWN LIMITATIONS**
  （15D：evidence_acquisition、semantic_grounding、unsupported_material_claim、
  answer_obligation_missing、refusal、context_resolution 等 limitation 已冻结）。
  不得写 Product Semantic Quality = PASS / benchmark solved / fully grounded /
  repository questions reliably solved。
- **Dev-benchmark-driven Product tuning = STOP。** 旧 Integration Dev 是
  Historical Diagnostic Evidence，不是未来逐题 Product optimization set。
- **Streamlit：** FUNCTIONAL DEMO / INTERNAL ENGINEERING UI；
  **Visual freeze ≠ Functional freeze**——未来为 Conversation / Persistence /
  Citation / Product flow 允许修改 Streamlit 功能；padding / border / font /
  button radius / sidebar visual polish / expander styling 继续 STOP。
- **前端冻结与未来 Web UI：** 见 `frontend_productization_freeze.md`
  （Vanilla HTML/CSS/JS，DEFERRED / NOT STARTED；只消费现有 public contracts）。
- **Holdout：** NOT RUN / SEALED。
- 一个重要纠偏：此前的 `NEXT = PROJECT MASTERY / DEMO PREPARATION` 在三方
  复核后属于 **PREMATURE PRODUCT CLOSURE**。Project Mastery / Interview
  Preparation 是 **PARALLEL PERSONAL TRACK**，不是 Product 主线的替代者。

## 3. Frozen Architecture

继续冻结：

- **Single Engineering Agent**（不是 Knowledge/Code/Git/Test 多 Agent 拼装，
  Evidence Backends 不是 Agent）；
- **one trusted control state / one logical Budget Owner**（5/4/2）；
- `ToolAgentRuntime` = Unified Engineering Runtime 内部的 bounded execution
  component，不是第二 controller；不得创建第三条 Product Runtime；
- Evidence Backends：Knowledge RAG、Repository / Code、Git Change、Tests
  （evidence kinds：knowledge / project_code / project_doc / project_change /
  project_test）。

## 4. Remaining Product DoD（Release 2.0 Freeze 前必须完成）

1. **Real Engineering Conversation**（真实多轮工程对话，不是单次问答演示）；
2. **Conversation Persistence**（重启后会话仍在）；
3. **Bounded Context**（多轮历史有界进入每次请求）；
4. **Minimal Answer ↔ Evidence Contract**（关键 claim 可回指 Evidence）；
5. **SSE Activity**（工具/验证/取证活动可观察）；
6. **Stable Functional UI**（功能稳定，不追求视觉极限）；
7. **Failure Semantics**（refused / failed / completed 语义一致可解释）；
8. **Fresh User Scenario Validation**（陌生场景验证，见 §6/§7）；
9. **Minimal CI / Reproducibility**（见 §8 的 24）；
10. **Independent Product Acceptance**（见 §8 的 25）。

注意：**Long-term Memory ≠ Release 2.0 mandatory**。

## 5. Context / Persistence / Memory Boundary

| 概念 | 含义 | Release 2.0 |
| --- | --- | --- |
| Persistence | 保存发生过什么（会话/消息存储） | **MUST**（推荐 SQLite） |
| Context | 本次请求需要选择哪些历史 | **MUST**（优先复用已有 `RecentContextWindow` 6 messages / 1200 tokens + `EngineeringContextResolver`） |
| Structured Summary Memory | 超出 bounded recent 后的压缩记忆 | **CONDITIONAL**（仅当真实多轮验证证明 bounded recent context 明显不足才进入） |
| Vector Memory / Mem0 | 向量记忆库 | **DEFER / NOT PLANNED FOR RELEASE 2.0** |
| Cross-session User Profile Memory | 跨会话用户画像 | **DEFER / NOT PLANNED FOR RELEASE 2.0** |

硬原则：**Conversation / Memory = context，NOT grounding evidence。**
Agent 历史回答不能因为进入 conversation store / memory 就自动成为事实；
grounding 只来自本轮取得的真实 Evidence。

## 6. User Scenario Acceptance Contract

Product 验收从 **Module Acceptance** 升级为 **User Scenario Acceptance**：

> "Planner 接上了"只是 Implementation Milestone。真正的 Product Milestone 是：

```text
用户面对陌生 AI/RAG repository 提出真实工程问题
    ↓
Agent 找到正确 Evidence
    ↓
读取正确实现
    ↓
覆盖关键回答义务
    ↓
Material Claims 得到 Evidence 支持
    ↓
用户任务真正完成
```

**Flagship A — Repository Implementation Understanding + Theory ↔ Code**
典型：某配置在哪里读取、最后在哪里生效？某 Retriever 如何实现？当前实现和
理论/文档设计是否一致？

**Flagship B — Change Impact + Test Recommendation**
典型：某 commit 修改了什么？影响哪些实现？应该检查哪些 tests？
必须保持：**find tests ≠ run tests ≠ tests passed**。

**Mandatory Failure Scenario — Evidence-Insufficient：**
用户询问仓库不存在或证据无法支持的能力时：Agent 搜索 → 说明缺口 →
qualified answer / refusal；不能 hallucinate。

**Mandatory Multi-turn Scenario：**
第一轮 Product Validation 必须至少包含一个真实连续调查：
Turn 1 "Planner 在哪里实现？" → Turn 2 "它产生的 plan 谁消费？" →
Turn 3 "那个 consumer 后面在哪里调用 retrieval？" → Turn 4 "这个流程和文档
一致吗？"；同时验证 Conversation / Context / Code / Docs / Grounding。

## 7. Fresh Validation / Contamination Rule

**Fresh Validation Policy：**
首轮 Product sanity validation = **1–2 pinned repositories、6–10 user tasks**；
不是重新启动 40～60 case 大型 benchmark。Repo 至少满足：AI/RAG/Agent domain、
public、fixed commit、not previously tuned against、human-verifiable、
within current Tool budget。

**Contamination Rule（硬规则）：**
Fresh validation 一旦用于指导 Product 修改，就自动失去 independent
validation 身份：

```text
Fresh Set A → 发现 failure → 根据 Set A 修改 Production
→ Set A = Development / Diagnostic Set
→ 最终验收必须使用 Fresh Set B
```

不得继续拿 Set A 宣称 independent generalization。

**Product Metrics（至少保留）：**
Strict Task Success、Answer Obligation Coverage、Evidence Support、Correct
Code Path Hit@k、Correct Span Read Rate、Wrong Refusal、Justified Refusal、
Context Resolution、User-side Completion、LLM Calls、Tool Calls、Tokens、
Latency、Infrastructure Failure。

明确：**terminal completed ≠ correct answer**；PARTIAL 必须单列，不能计成
PASS。

## 8. Remaining Milestone Sequence（冻结顺序）

```text
PRODUCT-COMPLETE-19      Route / Product Contract Freeze（本文档，已关闭）
    ↓
PRODUCT-CONVERSATION-20  Real Conversation + SQLite Persistence + bounded Context
    ↓
PRODUCT-GROUNDING-21     Minimal Answer ↔ Evidence Contract
    ↓
PRODUCT-VALIDATION-22    Fresh User Scenario Baseline
    ↓
    ├─ 无重复 Product blocker → SKIP 23
    └─ 重复 blocker 被新场景证明 → PRODUCT-REPAIR-23
    ↓
PRODUCT-ENGINEERING-24   Minimal Engineering Closure
    ↓
PRODUCT-ACCEPT-25        Fresh Independent Acceptance
    ↓
RELEASE-2-FREEZE-26      Release 2.0 Freeze
    ↓
DELIVERY-27              README / Demo / Resume / Project Mastery / Interview
```

**PRODUCT-REPAIR-23 是条件任务，≠ automatic。** 只有 Fresh Product Scenarios
再次重复证明某个 failure pattern 时才进入（例如：多个陌生 repository
implementation task 持续无法获取正确 project_code）。此时允许的优先候选：
query construction、symbol/path candidate generation、candidate ranking、
file diversity、correct span selection/read。**禁止默认：** Recovery v2、
More ToolCalls、More iterations、Multi-Agent、GraphRAG、Vector Retrieval。

**PRODUCT-ENGINEERING-24 边界：** 只做真正有校招/产品价值的最小工程化——
push / PR offline CI、requirements.lock / clean startup、cost/token/latency
observability、request deadline、必要时 disconnect stop、minimal bounded
concurrency、setup/run/smoke reproducibility。不得扩展成 platform engineering
project / distributed scheduler / cloud architecture exercise。

**PRODUCT-ACCEPT-25 边界：** 必须最终走
Real UI → Conversation API → Persistence → Bounded Context → Unified
Runtime → Real Provider → Evidence → Answer → Citation。至少真实验：
startup、knowledge readiness、project identity、single-turn repo task、
multi-turn follow-up、conversation isolation、restart persistence、
theory ↔ code、change/test、insufficient-evidence refusal、citation mapping、
SSE activity、provider failure。

## 9. Advanced Feature Defer List（Release 2.0 Freeze 前默认 DEFER）

Multi-Agent；Specialist / Critic；MCP；GraphRAG；Repository Vector Index；
Vector Memory；Mem0；Checkpoint / Resume；Controlled Evolution；Arbitrary
Shell；Auto code modification；Git commit/push Agent；Kafka；Redis Queue；
Kubernetes；Microservices；Java Gateway；Fine-tuning；DPO。

除非未来 Fresh Product Evidence 明确满足 entry condition，否则不进入。

## 10. Release 2.0 Freeze Definition

**Architecture：** Single Unified Runtime；one logical Budget Owner；no hidden
second controller；legacy only regression。

**Product：** Real Conversation；Persistence；Bounded Context；SSE Activity；
Minimal Citation；Stable Functional UI；Failure Semantics。

**Evaluation：** Fresh Product Scenario；Strict Task Success；Grounding；
Obligation Coverage；Refusal；Cost；Infrastructure。

**Engineering：** CI；requirements.lock；setup / run docs；smoke；no secrets；
runtime DB not committed；reproducible startup。

## 11. Governance / Six Questions

所有后续 Production Task 开始之前必须回答：

1. 真实失败是什么？
2. 证据来自哪个版本 / artifact？
3. 责任层在哪里？
4. 修改是不是通用机制，而不是 case 特判？
5. 成功后能证明什么、不能证明什么？
6. 收益是否值得用户投入相同的学习和维护成本？

六问答不清：**NO TASK**。

**R1 / MICRO 纪律：** 一个任务 → 一次实现 → 一次审计 → 关闭。R1/MICRO 只允许：
safety、leakage、core regression、frozen contract regression、明确 correctness
bug、大任务完成约 90% 只剩单点 blocker。不要无限 R1 → R2 → R3 → R4。
