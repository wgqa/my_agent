# 98-Gate5：后端 API 契约与运行时能力

## Health 与 Capabilities 的区别

`/health` 保持已有语义：基础 RAG Pipeline 已就绪才返回 HTTP 200，未就绪返回 503。因此它是 Basic RAG 的 readiness 信号，不是整个应用全部功能的承诺。

`/capabilities` 则无论 runtime 是否已初始化都返回 HTTP 200，并分别报告 Pipeline、AgentRuntime 和 ToolAgentRuntime。它把“端点可以正常说明系统状态”与“某项功能当前能执行”分开，客户端可以据此禁用或提示不可用的模式。

## HTTP 200 不表示所有 runtime 可用

FastAPI lifespan 会独立初始化三种 runtime。Pipeline 成功而 AgentRuntime 初始化失败是合法状态；此时 `/health` 仍是 200，`/capabilities.agent_runtime_ready` 为 false，`features.agentic_rag` 也为 false。不能因为基础检索成功就假定 Planner 或 Structured Tool Agent 同样可用。

## 为什么公共 API 要有 response_model

`response_model` 让返回数据先通过 Pydantic 校验和序列化，再写入 OpenAPI。客户端、测试、文档和 `/docs` 因而共享一个可读的 contract，而不是依赖某次 Python 对象碰巧被 FastAPI 序列化出的 JSON。`/stats` 和 `/capabilities` 现在分别有 `StatsResponse` 与 `CapabilitiesResponse`。

## Config 不是公共 response

内部 `Config` 记录加载路径、vector store 路径和运行参数；即使它有 `dump()`，也不等于每个字段都适合公开。公共 API 采用 allowlist：只构造 embedding、chunker、retriever、reranker 和 generator 的必要摘要。`_path`、`vector_store_path`、环境变量、API key、Authorization 和原始 Config 对象都不出现在 `/stats`。

Allowlist 的语义是“只有明确审查过的字段可以发布”；blacklist 是“假定未知字段安全，直到有人想起把它删掉”。在 Release API 中，前者更适合抵御 Config 未来新增敏感字段后的意外泄露。

## Schema、Endpoint 与 Runtime 三层

Schema 定义 JSON 的形状和 OpenAPI 说明；Endpoint 定义 HTTP 路径、状态码和如何填充 schema；Runtime 是 Pipeline、AgentRuntime、ToolAgentRuntime 的实际初始化状态。三者需要协作，但不能混为一谈：`CapabilitiesResponse` 是稳定 schema，`/capabilities` 是可查询 endpoint，ready 布尔值则是每次请求时的 runtime 事实。

## 503 与 Agent 的 HTTP 200

503 表示基础设施无法提供某项服务，例如 Pipeline 或某个 Agent runtime 未初始化。相反，已初始化 Agent 在执行后给出 `refused`、`failed` 或 `deferred` 是结构化业务结果，按 Gate 3/4 冻结 contract 继续返回 HTTP 200。这一轮没有改变 `AgentQueryResponse` 或 `ToolAgentQueryResponse`，只补上发现能力的 release contract。

## 面试中的 API contract engineering

可以这样表述：我把 RAG 后端从“能返回 dict”收口成公开、可验证的 API contract。对 `/stats` 使用 Pydantic allowlist 防止本机路径泄露，并在 OpenAPI 中声明 schema；对独立初始化的 Pipeline、Agent 和 Tool Agent 增加 `/capabilities`，使 UI 和运维能区分基础 readiness 与具体功能 availability；同时保留既有 503 和 Agent 结构化业务状态语义，避免破坏冻结接口。
