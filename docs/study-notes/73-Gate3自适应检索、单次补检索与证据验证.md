# 73-Gate3自适应检索、单次补检索与证据验证

> G3-ADAPT-06A：把"所有检索固定 BM25"升级为可解释的自适应检索——按 QueryPlan 确定性选 BM25/Hybrid；BM25 证据为空时最多一次 Hybrid 补检索；Verifier v2 输出结构化覆盖结果；RouteDecision 升级 v2。
> 日期：2026-08-13
> 权威来源：实现 `core/adaptive_retrieval/policy.py`、`core/agent_runtime/models.py`（RouteDecision v2 / VerificationResult v2）、`core/agent_runtime/runtime.py`、`core/agent_runtime/adapters.py`、`api/app.py`；测试 `tests/test_agent_runtime.py`、`tests/test_agent_runtime_adapters.py`、`tests/test_api.py`。
> 范围声明：自适应策略完全确定性、不调用 LLM；最多一次补检索、不无限循环；不读 Dev/Holdout、不算指标。

---

## 1. Rule Router 与 LLM Router 的区别

- **Rule Router（本任务）**：用一张**写死的查表**决定检索策略——根据 QueryPlan 的 action/query_type/reason_code 和 Retriever 的能力声明，输出固定策略 + 固定原因码（如 `LEXICAL_EXACT_BM25`、`COMPLEX_SEMANTIC_HYBRID`）。
- **LLM Router**：让模型判断"这题该用哪种检索"。灵活，但**不可复现、不可审计**——模型可能今天选 BM25、明天选 Hybrid，出错没法定位，还多一次模型调用。

Rule Router 的优点正是它"笨"：**确定性**（同样输入永远同样输出）、**可解释**（`strategy_reason_code` 写明为什么选这个策略）、**零模型成本**。策略想升级时，改表即可，行为立刻透明。这是"先可解释，再谈聪明"。

## 2. 为什么代码符号优先 BM25

`code_symbol` 这类问题（如"`run_eval` 是做什么的？"）的关键是**精确的符号/标识符匹配**。BM25 是词法检索，直接按 token 命中打分，对"代码符号、函数名、类名"这种字符串精确匹配非常合适；而 Dense/Hybrid 的语义向量反而可能把符号"模糊化"，召回语义相近但字面不同的东西。

所以策略表把 `fact` 和 `code_symbol` 都固定为 **BM25 + `LEXICAL_EXACT_BM25`**。符号问题要的是"找到写着一模一样符号的那段代码"，词法最直接。

## 3. 为什么复杂语义问题尝试 Hybrid

`comparison / causal / multi_entity / troubleshooting`（以及 `unanswerable` 但要检索核验的题）这类问题，关键词往往**对不上**——问"A 和 B 的区别"但文档里可能通篇没有"区别"二字，靠同义改写、语义相近才召得回。

Hybrid 用 Dense + Sparse + RRF 融合：Dense 抓语义近义，Sparse 抓精确词命中，RRF 平衡。所以策略表给这些类型**优先 Hybrid + `COMPLEX_SEMANTIC_HYBRID`**。但"优先"不是"必须"——如果当前 Retriever 不支持 Hybrid（如只有 BM25Only），就显式降级，见第 6 节。

## 4. 为什么 decomposition 先用 BM25

decomposed 已经把大问题拆成聚焦的子问题，每个子问题本身意图明确。子问题通常是"这个方向上有哪些材料"的具体检索，BM25 足够；而且多子问题要跑多次检索，**先全部用便宜的 BM25**，控制总成本。所以策略表给 decomposed 固定 **BM25 + `DECOMPOSED_BM25_PRIMARY`**。

如果某个子问题 BM25 搜不到，才按第 5 节补一次 Hybrid——**先便宜的，贵的是兜底**。

## 5. 为什么最多一次升级

"补检索"是一个**成本与失控的边界**：每多一次外部调用就多一分延迟、一分失败风险、一分成本。如果允许无限升级（BM25 空 → Hybrid 空 → 再换个策略 → 又换…），系统就可能被拖进循环或无限烧钱。

所以本任务规定**只升级一次**：

- **single**：初始 BM25 空 + 支持 Hybrid → 对同一 query 再跑一次 Hybrid；Hybrid 仍空 → 拒答。
- **decomposed**：每个子问题先 BM25；若有空结果且支持 Hybrid，**只升级第一个缺失子问题**一次；两个以上缺失时，即使第一个被救回，其他仍缺失也必须拒答。

Trace 里的 `retrieval_upgraded` 事件固定 `upgrade_index=1`——一次升级、无循环。预算也收紧到 `max_retrieval_calls=4`（3 BM25 + 1 Hybrid），从机制上保证次数有界。

## 6. capability fallback

策略表说"复杂语义优先 Hybrid"，但**如果 Retriever 根本不会 Hybrid**（`supported_strategies` 里没有 `hybrid`），就**显式降级为 BM25**，原因码 `CAPABILITY_FALLBACK_BM25`。

关键在"显式"：不是悄悄用 BM25，而是**记录下"因为能力不支持所以降级"**。这样审计时能看到"这题本该试 Hybrid，但当前环境不支持"。`PipelineRetrievalAdapter` 用 `supported_strategies` 只读声明能力：HybridRetriever → `("bm25","hybrid")`，BM25OnlyRetriever → `("bm25",)`；Router 拿到这份声明再定策略。

## 7. coverage 与 Faithfulness 的区别

- **coverage（本任务）**：结构化回答"**每个 required 子问题/查询是否至少拿到过候选证据**"——`required/covered/missing query ids`、`coverage_complete`、`upgrade_attempted/used`、`evidence_count`。它是**查询层**的覆盖检查：有没有证据可用来回答问题。
- **Faithfulness（不做）**：判断**答案里的每个断言是否真的被证据蕴含**（claim-level entailment）。这需要细粒度证据与答案逐句比对，本任务不做。

Verifier v2 只回答"覆盖齐不齐"，不回答"证据撑不撑得起答案"。Citation 合法性仍由 `PipelineAnswerAdapter` + `CitationValidator` 强制（答案里的 `[Cx]` 必须存在于本次 Context）。一句话：**coverage 问"有没有"，Faithfulness 问"对不对"**。

## 8. Adaptive Retrieval 的成本边界

自适应不是"越多检索越好"，而是**把每一次调用都花在刀刃上**，边界有三层：

1. **预算硬限**：`max_retrieval_calls=4`（1 Planner + 3 BM25 + 1 Hybrid rescue + 1 Generation = 6 steps），每次调用前检查，超限立即 `BUDGET_EXCEEDED`。
2. **只升级一次**：补检索封顶 1 次，不允许"失败再试"的循环。
3. **策略先行**：初始策略由规则表决定（便宜的 BM25 优先、贵的 Hybrid 兜底），不靠模型临场发挥。

成本可控才能做**对照实验**：`G3-ADAPT-06B` 将用同样的数据跑"自适应 vs 固定 BM25"，比较多出来的调用是否换来可复现的收益。没有成本边界，这个对照就没有意义。

## 9. API 契约修正与本任务接线

本次顺带修复审计发现的 **sources 不一致**：API 现在**只返回 `result.sources` 明确引用的 EvidenceItem**；completed 返回实际引用来源；refused/failed/deferred 的 `result.sources=()` 时 API `sources=[]`，不再因为 EvidenceBundle 里有部分证据就绕过 Result 契约返回。同时 `route` 携带 `router_policy_version` 与 `strategy_reason_code`，`verification` 携带覆盖摘要，`sources[].query_id` 保留。

## 10. 面试可能追问与参考回答

**Q：Rule Router 和 LLM Router 怎么选？**
A：要可复现、可审计、零模型成本就先上 Rule Router——固定查表 + 固定原因码。LLM Router 灵活但不可复现、多一次调用。可先有确定基线，再考虑升级。

**Q：为什么代码符号问题用 BM25？**
A：符号/函数名需要精确词法匹配，BM25 按 token 命中打分最直接；语义向量反而会模糊符号。

**Q：为什么复杂语义问题尝试 Hybrid？**
A：这类问题关键词常常对不上（"区别"在文档里不一定出现），需要 Dense 抓语义近义 + Sparse 抓精确命中，RRF 平衡。

**Q：为什么最多补检索一次？**
A：每多一次调用就多一分延迟/失败/成本。无限升级会拖进循环或失控烧钱。只升级一次 + 预算硬限，次数才有界、实验才能对照。

**Q：capability fallback 是什么？**
A：策略想用 Hybrid 但 Retriever 不支持（supported_strategies 无 hybrid）时显式降级 BM25，并记录 `CAPABILITY_FALLBACK_BM25`，不悄悄降级。

**Q：coverage 和 Faithfulness 的区别？**
A：coverage 是查询层的"有没有证据可用"（required/covered/missing ids）；Faithfulness 是 claim 层的"证据撑不撑得起答案"，本任务不做。Citation 合法性仍由 CitationValidator 强制。

## 11. 当前技术债

- **无 Adaptive Router 调参**：策略表是手写的规则，未按检索质量自动调整。
- **coverage 仍是结构检查**：无 claim-level entailment、无相关性/信息量判断。
- **Hybrid 补检索未在真实语料验证**：本任务全部 Fake/内存索引，未跑 Dev/Holdout 指标。
- **预算只数调用次数**：无 Token 精确计费、无 wall-clock 超时。
- **/agent/query 不接 history**：仍显式拒绝。
- **多 Agent / Tool / MCP / GraphRAG**：全部不在范围。

---

## 边界声明

- 未读取/搜索 Gate 3 Holdout / sealed；示例全部为 synthetic。
- 未运行真实模型/检索；未计算任何指标；未运行 Dev/Holdout。
- 自适应策略完全确定性；补检索最多一次；不无限循环。
- coverage 为 query-level 结构检查，不宣称 claim-level Faithfulness。
