# 103-Gate5：Release 1.0 最终验收与冻结

## Feature Complete 不等于 Release Accepted

Feature complete 表示计划内的代码、界面、脚本和测试已经完成；Release accepted 则要求这些事实被统一审计，并由独立的最终检查确认能在目标环境中持续成立。前者是开发结论，后者是交付结论。Release 1.0 因此保持 `review_pending`，直到远端 CI 和 Reviewer 完成最终签字。

## 为什么 CI 是最后一道 Gate

本机验证能证明当前机器的工作区可用，却不能证明干净 runner 能重现相同结论。CI 用固定依赖锁、独立环境和受控 workflow 复查测试、启动 smoke 和仓库规则。没有远端结果时，不能编造 run ID、通过数量或 conclusion；正确状态是 `REVIEWER FINAL CHECK`，而不是提前关闭 Gate5。

## Freeze 绑定什么

freeze artifact 要绑定“功能和代码已经完成的候选源提交”。本项目的 `release_candidate_source_commit` 是 `a4d5b6c778ec234d0fe38b1b58a6fd794068a90d`，并只引用既有 Gate2、Gate3、Gate4 的冻结身份和公共语料 commit。这样 Reviewer 可以先检查候选代码，再检查 closeout 文档。

freeze 不能自指：如果 JSON 既要包含自己的提交 SHA，又必须在该提交之前写好，就会形成不可满足的循环。把关闭文档视作候选代码的审计附件，而不是候选代码的一部分，既避免循环，也保留清晰的追溯边界。

## Smoke、Demo 与 Benchmark

| 证据类型 | 回答的问题 | 不回答的问题 |
|---|---|---|
| Unit / contract tests | 模块和 API 契约是否按预期工作 | 真实进程能否一起启动、模型质量如何 |
| Startup / integration smoke | 后端、前端和真实 HTTP 连接是否可在隔离环境启动 | 回答是否正确、Agent 质量是否稳定 |
| Release demo | 固定产品场景是否可重复展示，安全边界是否按预期拒绝 | 正式 Gold 指标或泛化能力 |
| Formal benchmark / freeze | 在冻结数据、配置和协议下观察到了什么 | 后续 live 请求必然得到相同回答 |

这四层共同构成当前项目的验证体系：代码/契约测试防止局部回归，进程与全应用 smoke 验证交付链路，Demo 验证可展示产品路径，Gate2–4 的正式冻结 evidence 记录质量观测和已知限制。它们互补，不能相互替代。

## 已知限制为何可以随 Release 发布

发布不是“没有任何限制”，而是限制被识别、记录、没有伪装成已解决，并且不违反当前发布的安全与核心交付承诺。Gate3 的 generation/retrieval-to-answer 问题、Gate4 的 multi-step 与 tool coverage 限制，以及认证、容器化、streaming、upload timeout 等后续工作都已公开归档。它们进入 V1.1 backlog，而不是通过无限延迟 V1.0 来掩盖范围决策。

## Gate 1 到 Gate 5 的工程演进

- Gate1 建立基础 RAG 的正确性边界。
- Gate2 把检索实验变成可复核、可冻结的 evidence。
- Gate3 增加 Planner、Agentic Retrieval、证据验证与一次性 Holdout 的治理。
- Gate4 把结构化 Tool Agent、allowlist、预算和 safe trace 接入系统。
- Gate5 将环境锁定、CI、启动 smoke、全应用联调、能力发现、Demo、README 和仓库卫生收敛为可交付 Release。

面试时可以用这条演进说明 Release engineering：我不把“模型能回答”当作项目结束，而是为依赖、数据身份、API contract、进程启动、用户界面、安全 trace、演示边界、正式评测和已知限制分别建立证据；最后用一个不自指的 freeze artifact 把候选代码和审计状态交给 Reviewer。
