# Engineering Conversation v1 Design

> PRODUCT-CONVERSATION-20：把 "UI 看起来像多轮、Runtime 每轮独立" 的产品，
> 变成真正的 UI → Server Conversation → SQLite → bounded Context → Unified
> Runtime → persistence → SSE → UI 多轮 Engineering Agent。本文是该 vertical
> slice 的设计契约；产品完成路线见 `release2_product_completion_roadmap.md`。

## 1. Persistence != Context

- **Persistence** 保存发生过什么：会话、消息、assistant 的 public result。
- **Context** 决定本次请求哪些历史进入 Runtime。
- Store 只负责 load committed history；**哪些消息进入 Runtime** 仍唯一由既有
  `EngineeringContextResolver` → `RecentContextWindow`（6 messages / 1200
  tokens，newest-first fit + truncation）决定。Store 不复制第二份窗口策略。
- 传给 Context Resolver 的只有 `role` / `content`；`result_json`、evidence、
  trace、tool sequence、project path 永远不成为 conversation context。

## 2. Server owns conversation truth

- SQLite（`api/conversation_store.py`，标准库 `sqlite3`，无新依赖）是唯一
  事实 owner；Streamlit `session_state` 只是 render/cache。
- 默认库：`data/runtime/engineering_conversations.sqlite3`（已被 gitignore
  覆盖，runtime DB 不入库）；可用 `ENGINEERING_CONVERSATION_DB` 指向测试路径。
- `PRAGMA user_version = 1`；第一版无迁移框架。connection per operation，
  无跨线程共享连接。
- conversation id / message id 均为服务端 `uuid4().hex`；客户端不能自定义。
- Title：初始 `New conversation`；第一轮 terminal result 落库时取第一条
  user message（collapse whitespace，≤36 chars），不调用 LLM。

## 3. Schema（v1）

```text
conversations(id PK, title, project_key, project_name, project_source,
              created_at, updated_at)
messages(id PK, conversation_id FK→conversations ON DELETE CASCADE,
         role CHECK(user|assistant), content, result_json NULL, created_at)
```

`result_json` 只允许 `_build_engineering_response(...)` 产生的 **public safe
Engineering response**（status/answer/reason_code/failure_code/iterations/
tool_calls/tool_errors/safe trace/public evidence）。禁止：raw model output、
raw ToolObservation、Prompt、CoT、API key、traceback、本机绝对路径、私有
runtime requirement state。

## 4. Project isolation

- 会话创建时绑定当前系统选定的 Engineering Project；客户端不能选 root。
- 服务器内部以 `project_key = SHA-256(resolved project root)` 隔离不同仓库；
  `project_key` / root / 绝对路径**永不**返回给客户端（公开只有
  `project_name` / `project_source`）。
- list 只返回当前 project_key；get / delete / send 对不属于当前项目的
  conversation 一律 404（不泄露"它属于另一个本地项目"）。

## 5. API contract

冻结不变：`/engineering/query`、`/engineering/query/stream`、
`/engineering/query/stream/v2` 仍是 question-only（`extra=forbid`，附带
`history` 字段 → 422）。历史 regression / benchmark 契约不受影响。

新增 Product Conversation API：

```text
POST   /engineering/conversations                          → 201 summary
GET    /engineering/conversations                          → list (updated_at DESC)
GET    /engineering/conversations/{id}                     → detail + messages
DELETE /engineering/conversations/{id}                     → 204（级联删消息）
POST   /engineering/conversations/{id}/messages/stream/v1  → SSE 一轮对话
```

Message 请求体只有 `{"message": ...}`（`extra=forbid`、nonblank、
≤ MAX_QUESTION_CHARS）。客户端绝不能提交 history / project / provider /
model / budget / tools / prompt / context window。

## 6. Turn flow 与 atomic persistence

```text
conversation_id → load committed history → verify project binding
    ↓
facade.run(new_message, conversation_context=stored_history)
    ↓
build public result
    ↓
before_public_result 回调：atomic 事务 insert user + insert assistant
                          + update conversation → commit
    ↓
evidence SSE → answer_start → answer_delta → final → done
```

- completed / refused / failed 都形成完整一轮记录。
- Infrastructure error（worker exception / SQLite failure）→ 不得持久化
  half-turn；UI 显示失败提示。Persistence callback 抛异常 → 流以
  `error` + `done` 结束，**绝不出现** answer_start / answer_delta / final，
  因此 UI 永远不会宣称成功而 server 没有保存。
- assistant message content：completed → public answer；refused / failed 且
  answer 为 null → 仅由 public fields 生成的确定性文本（如
  `Refused: INSUFFICIENT_INFORMATION`）。
- 实现 seam：`stream_engineering_query(..., before_public_result=None)`，
  默认 None，三条旧 question-only endpoint 行为逐字节不变。

## 7. Memory != Evidence

stored messages / assistant answers / result_json 全部属于 **Conversation
Context**，不是 Grounding Evidence。下一轮 Runtime 的 Evidence 仍必须从
Knowledge / Code / Docs / Git / Tests 重新取得。禁止把 previous assistant
answer 转换成 EngineeringEvidence。

## 8. UI wiring

- Engineering conversation：server-backed（create / list / switch / delete /
  重启与刷新后可恢复）；提交走
  `POST .../messages/stream/v1`；pending user message 立即渲染但**不进
  cache**，done 后 `GET detail` 以 server state 为准；stream 失败 → 显示
  错误，不留下 server 没有的 half-turn。
- 本地 ephemeral Engineering history **NOT MIGRATED**（允许）。
- Legacy（Basic / Agentic / Structured Tool Agent）保持 local demo /
  regression 状态，不写 Engineering SQLite；Advanced selector 切换时
  server conversation 保持 engineering identity，legacy demo 使用独立本地
  会话，状态不串。

## 9. Known limitations / deferred

- Conversation / Memory 是 context，不是 grounding evidence；多轮语义质量、
  grounding、acquisition 改进不属于本 slice（见 21 / 22 / 25）。
- Structured Summary Memory：CONDITIONAL（仅当真实多轮验证证明 bounded
  recent context 明显不足）；Vector Memory / Mem0 / 跨会话画像：DEFER。
- 单文件 SQLite 适合本地/单机部署；并发写为第一版未优化项。
- 无迁移框架：schema 变更需显式新版本（PRAGMA user_version）。
