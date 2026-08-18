# 99-Gate5：Release Demo 与产品验收

## Smoke、Demo 与 Benchmark

Startup smoke 只回答“服务能不能启动并通信”；它使用 dummy key、离线模型边界和健康端点。Release Demo 回答“用户拿什么问题可以看到真实产品能力”；它允许真实 key，通过正式 HTTP API 走一组固定场景。Benchmark 则回答“在冻结数据和指标上质量如何”；它需要 Gold、严格身份和可比较的统计。三者目标不同，不能把 Demo 结果写成 benchmark 分数。

## Demo case 不是 Gold evaluation

Demo fixture 和 case catalog 是公开的产品演示输入，只为在 5～10 分钟内解释 Dense/BM25/Hybrid、Planner、Verifier 和工具调用。它们不包含 Gate 3 Holdout、Gate 4 Gold 或 sealed 数据，也不计算 Accuracy、F1、Recall 等指标。固定问题提升可演示性，但不构成模型能力的无偏估计。

## 为什么 CI 不跑真实 LLM Demo

真实 Demo 依赖 API key、网络、模型服务和随机响应，成本、延迟和可重复性都不适合每次 CI。CI 只测试 harness 的 catalog、payload、preflight、边界和脱敏；现场或明确授权的环境才执行 live demo。

## 固定 case 与一次请求边界

固定六个 case 让面试者能稳定讲清产品路径，同时限制每个 case 只发一次请求，不自动 retry、不因结果不好重跑。这样一次结果是事实记录，而不是通过反复提问挑选出来的展示结果。失败时报告失败，交由 Reviewer 判断是否是产品问题。

## Required 与 Observational

五个 required case 是 Basic RAG、Agentic RAG、calculator、code search 和 safety boundary；它们决定 Demo 是否完成。multi-step tool case 是 observational：记录 `expected_tool_sequence` 与 `actual_tool_sequence`，但不因当前系统尚未稳定实现 code_search → calculator 链而把整个 Demo 判失败。这直接暴露 Gate 4 已知边界，而不是修改 Runtime 让输出好看。

## Safety Demo 如何证明“没有执行”

Safety case 请求执行 `git reset --hard`，但 shell 不在 allowlist。验收只检查 HTTP 结构化返回和 safe trace 中没有 `shell` tool；harness 自身不调用 shell，也不把问题交给本地 subprocess。安全证明是“危险路径没有出现”，不是要求模型返回某段固定拒答文字。

## 从 safe trace 讲 Tool Agent

现场先展示 tool name、调用计数和安全 trace，再解释 Decision → Tool → Observation → Final 的边界。calculator 最容易稳定展示数值工具，code_search 展示项目自描述能力，multi-step 展示当前限制。raw model response、Prompt、CoT、API key 和本机路径都不进入终端摘要或 artifact。

## 5 分钟现场流程

1. 启动后端并执行 `python scripts/demo_release.py`。
2. 先看 Preflight：Pipeline、Basic RAG、Agentic RAG、Structured Tool Agent 的 readiness 来自 `/capabilities`，不可用能力会提前 SKIP，不等到 503 才暴露。
3. 说明两份 demo fixture，然后演示 Basic 检索和 Agentic 规划。
4. 演示 calculator，再演示 code search；最后展示 multi-step 的实际序列和 safety case 的无 shell 证据。
5. 以 Required passed/failed、Observational 和安全摘要收尾，不把一次随机答案宣称为质量基准。

## 产品验收的 release engineering 价值

Demo harness 是 API contract 的真实消费者：它使用 `/health` 和 `/capabilities` 做 preflight，使用正式三种 Query API，不重新实现 Agent。它把启动证据和冻结评测之间的产品空白变成一条有界、可审计、可面试复述的路径，同时保留模型随机性和已知能力边界的诚实记录。
