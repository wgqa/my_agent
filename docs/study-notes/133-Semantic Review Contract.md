# Semantic Review Contract：把“完成”与“答对”分开

自动化指标是工程评测的第一层，但它们不是答案准确率。`task_completion` 只比较运行终态与期望终态；它能告诉我们一次 answerable 任务有没有走到 completed，却不能证明答案是否覆盖了每个关键要求。把这种流程状态直接命名为 accuracy，会让后续排查失去方向。

15C 将人工审查拆成互不替代的维度：terminal outcome、逐条 Gold obligation coverage、answer grounding、context semantic assessment 和 refusal assessment。没有一个“overall score”可以替代这些记录。一个回答可以终态正确但漏掉 obligation，也可以 obligation 覆盖完整却没有被本轮 evidence 支撑；这两种问题的修复方向完全不同。

## Structural sufficiency 不是 semantic grounding

Runtime requirement state 只描述公开 evidence 的 kind、数量与路径结构是否满足当前产品 requirement。Router-Gold contract match 只描述两个结构契约是否一致。二者都不检查自然语言 claim 是否真的由 snippet 支持。

Grounding 审查只能查看本轮 `semantic_runs.jsonl.public_evidence`。Gold source proof 是裁判手中的参考资料，不是 Agent 已经检索、读取或引用的事实。即使 Gold 中存在正确实现，Agent 没取到该 evidence 时，评审仍可以给出“答案语义正确，但 grounding unsupported”。这正是把产品输出和 evaluator oracle 分开的价值。

## Context 不能只看字符串完全相等

既有 `resolution_correct_frozen_exact` 是一个稳定的 exact-string 自动信号。它适合回归比较，却不是语义等价判定：Resolver 可能换了措辞、压缩了表达，但仍准确保留用户意图。因此 context follow-up 的人工审查要基于 `resolved_input` 与 frozen `expected_standalone_intent` 的语义关系。exact=false 仍然允许 context semantic PASS。

## 为什么先冻结 rubric，再开始人工评分

真实结果出现后再改标签或阈值，很容易让 rubric 向已知样本过拟合。15C 先固定版本、合法枚举、逐 obligation 记录方式、invalid 的 N/A 语义和禁止的复合分数。这样 15D 开始人工评审时，评审者看到的是同一把尺子；如果未来需要改尺子，应创建新版本，而不是回写历史 review。

## 15C 与 15D 的关系

15C 只提供离线合同：怎样写 review，怎样校验 review，哪些结论不能自动推出。15D 才会在真实 15B semantic artifact 存在后，按这个合同进行人工语义评分与报告。两者分开能避免在没有完整观察样本时先设计一个看似精确、实际不可审计的评分体系。

面试中可以把它概括为：先把运行事实、独立 Gold 与人工判断分别版本化，再讨论质量指标。这样既避免把 Guard 通过误称为“答案正确”，也避免让评测逻辑反向污染 Agent 的生产决策。
