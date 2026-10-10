# R01：当前任务被历史改写覆盖——修复与验证

结论：**本次修复了 Engineering 的任务交接问题，原始任务不会被模型返回的整句改写直接替换。正常追问仍能继承对象并读取源码。绑定目录与自然概览的资料入口尚未处理。**

本次只交付 R01，下一项为 R02。没有开展目录重构、长期契约实施、环境检查工具、知识库状态查询或历史引用回查。

## 根因与实现

旧链路虽然保存了 original_input，但后续仅消费模型的 standalone_query。Resolver 在“同一个项目、不同动作”的追问中返回上一轮任务，合法 JSON 仍被当作本轮任务传递。

Engineering 新 profile 让同一次上下文调用只返回有界 reference_context 或 null。系统根据实际用户消息构造输入，模型不能提供或修改 current_request。旧式完整改写以及无效输出不能替换当前请求；预期 Provider 错误仍回退原句，不增加调用重试。

有必要的指代对象时，Planner / Decision 接收分别标明 current_request 与 reference_context 的数据；不需要补全时继续使用原句。模型提示明确当前消息决定动作，历史只提供对象，引用提示仍是不可信数据。

ContextSnapshot 单独提供词法视图，去掉传递用的字段名，供既有需求路由和 BM25 使用。检索调用与 Observation 记录实际查询文本；QueryPlan、EvidenceBundle 和 Verifier 的 identity 保持一致。检索策略、Top-K、升级/分解策略与次数上限不变。

## 修改边界

生产修改集中在 7 个输入交接及配置文件：

- Context Resolver：增加 Engineering 专用的对象补全 profile，保留通用 v1 默认。
- Engineering Context：由原始问题构造交接，提供不含传递字段名的词法视图。
- Unified Engineering Runtime：仅调整路由 / 检索使用的输入视图。
- Engineering Retrieval：可选的实际查询文本；旧调用默认行为与计划 identity 保留。
- Planner / Decision Prompt：新增明确任务与指代职责的版本，旧版本及 hash 保留。
- API 装配：选择上述 Engineering profile，默认及注册项目复用同一工厂。

没有修改 ToolAgentRuntime 主循环、Budget 模型、Executor、Tool 参数 Schema、需求路由算法、Evidence Verifier、Citation 规则、终态、QueryPlan Schema 或数据库结构。仍为 5 次决策 / 4 次工具调用 / 2 次工具错误；Engineering 保持 6 个可调用工具，动态 knowledge_search 仍禁用。

新 Decision profile 沿用旧 Reader profile 的完整模板和控制机制，只增加输入职责说明。parse repair 上限仍为 1，Decision 输出上限仍为 1200；没有增加第二个 Agent 或语义裁判模型。

## 局部回归

最终结果：**312 passed，3 项既有依赖警告，无失败**。运行受影响的 19 个测试模块，没有跑全盘评测。

覆盖错误改写注入、非法参考载荷、Provider fallback / 程序错误区分、正常源码追问、计划与检索 identity、传递字段不污染查询、无历史输入、会话隔离、现有来源 / citation 规则、预算 / deadline / cancel、旧 profile 与装配兼容。

测试数据库和 pytest 临时目录使用独立临时位置，未操作真实会话库。首次运行遇到默认 pytest 临时目录访问错误，改用独立目录后完成验证，没有修改用户目录权限。回归中的旧行为断言已按新的输入职责更新；历史 Prompt 身份检查仍保留。

## DeepSeek 真实对照

模型 deepseek-chat，temperature=0；从真实 SQLite 只读加载同一会话历史与知识库快照，再以内存运行，不启动 API lifespan 或写回用户对话。

知识库 revision=9，37 个文档 / 215 chunks；快照 SHA256 为 4f0b66f5bc2bb5a15d62eb327e4758bc9eddffcdc9e2a7bb4d4a92f380ea7fab。A 使用历史 Resolver / Planner / Decision profile 及旧交接行为，B 使用候选配置；主循环和工具实现相同。

| 场景 | 实际结果 | 可得结论 |
|---|---|---|
| A：完整历史后“说一下目前的项目” | 改为“目前咱们的系统绑定的哪个项目目录”；single_retrieval；refused；1 决策 / 0 工具 | 原任务覆盖可真实复现 |
| B：同一原句及完整历史 | 保留“说一下目前的项目”；no_retrieval；refused；1 决策 / 0 工具 | 覆盖已消除，但概览入口缺口仍在 |
| B：源码配置之后“它的默认值呢？” | 继承 ToolAgentBudget.max_tool_calls 和实际文件；读取源码，回答默认值 4；2 决策 / 1 工具 | 正常追问和来源校验未退化 |
| B：源码问题后“什么是 LoRA？” | 原句保留，完成知识回答；1 决策 / 0 工具 | 新话题未继续旧代码任务 |
| B：明确先读 README 再概括 | completed；2 决策 / 1 工具 | 现有 Reader 能力仍有效，未新增概览能力 |
| B：独立绑定目录问题 | Resolver 保留原句 | 本次未修 R02，不能据此宣称目录已可回答 |
| B：两对象后的模糊“它” | Resolver 返回两个候选；执行端 refused；1 决策 / 0 工具 | 没有擅自选定，但 Resolver 消歧语义仍有局限 |
| B：拒答后明确给出源码路径 / 对象 | Resolver 保留明确原句 | 拒答历史未覆盖用户补充 |
| B：另一种“工程用途和使用方式”表达 | Resolver 保留原句，reference_context=null | 同对象新动作的一项变式检查 |

去除词法查询中的传递字段名后，再验证源码默认值与歧义场景，分别仍为 completed（2/1）与 refused（1/0）。实际 BM25 查询是问题和对象文本，没有 current_request / reference_context 字段名；原始失败和前一版结果均保留，未丢弃不利记录。

共保留 12 条检查记录，包含对照、Resolver 单独检查以及最终输入视图后的复核，合计 31 次实际 LLM 调用、80,810 input tokens、2,276 output tokens。正常源码追问的 4 次实际模型调用分别是 Context 1、Planner 1、Decision 2；不能把它们与逻辑决策或工具调用混为一谈。

8 个完整链路记录的可调用 tool-set hash 均为 5b1cc58be8a9c289972f1ee4951f41e74f68d2952f66172b5c3fac6db75de267，工具集合未变。原会话仍为 8 条消息，updated_at 仍为 2026-10-09T13:49:09.665813+00:00，逐项内容比较也未变化。

原始记录：[真实对照 JSON](D:/学习/rag实战项目/rag-knowledge-base/docs/validation/2026-10-10-r01-current-request-live.json)。它只记录问题、对象提示、计划、合法动作、来源、指标与结果，没有模型 CoT、密钥或完整 Prompt。

## 完成范围与限制

R01 的结构性覆盖漏洞已处理，有限真实对照支持其效果。本文不是独立大样本评测，不用这些开发案例报告普遍成功率。

reference_context 的对象语义仍由模型判断，不能保证永远正确。多个对象的病例没有严格返回预期的 null，但执行端拒答；保留这项边界，不追加分隔符或关键词规则来假装完成通用消歧。

自然项目概览仍拒答，绑定目录聊天入口仍缺失，拒答文案 / 页面归属仍按后续独立问题处理。本次没有把输入修复扩成这些能力的混合改动。

正在运行的后端需要重启并重新装配 Runtime / 项目缓存才能使用新 profile，仅刷新浏览器不会替换已创建的实例。没有提交或推送，工作区其他 CI、运行手册及工具评测 v2 文件保持独立。
