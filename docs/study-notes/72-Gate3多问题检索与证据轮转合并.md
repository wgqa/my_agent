# 72-Gate3多问题检索与证据轮转合并

> G3-RUNTIME-05C：decomposed_retrieval 从 deferred 变成真正可执行的多子问题检索链路——sq1/sq2/sq3 独立 BM25 → subquery_round_robin_v1 证据合并 → required-subquery 覆盖检查 → Grounded Answer。
> 日期：2026-08-13
> 权威来源：实现 `core/agent_runtime/evidence.py`、`core/agent_runtime/runtime.py`、`core/agent_runtime/models.py`；测试 `tests/test_agent_runtime.py`、`tests/test_agent_runtime_adapters.py`、`tests/test_api.py`。
> 范围声明：本任务实现真多 Query 检索执行；仍只用 BM25、不做 Adaptive Router、不读 Dev/Holdout、不算指标。

---

## 1. Query Decomposition 与普通多次搜索的区别

- **普通多次搜索**：因为"第一次没搜够"，对同一个问题再搜几次——本质是**重试或补搜**，每次都是同一意图。
- **Query Decomposition**：Planner 先把这个大问题**拆成几个独立子问题**（sq1/sq2/sq3），每个子问题代表一个**不同的检索意图**，然后分别检索。多出来的检索次数是"任务结构本身要求"的，不是"失败了补救"。

区别的关键在**意图是否拆分**。普通多次搜索没有拆意图，只是反复；分解检索把一个问题拆成多个更聚焦的问题，每个子问题在自己的方向上取证据，最后再合并。decomposed 的路线图是：**拆 → 分别搜 → 合并 → 综合回答**。

## 2. 为什么有效分解后不再检索 original_query

一旦 Planner 判定这个问题"需要分解"（decomposed_retrieval），说明**原问题太宽，直接搜它得到的证据是混杂的**——多个实体/多个方面混在一起，BM25 打分互相稀释。

如果此时还去检索 original_query，就相当于"既拆了又没拆"：多花一次调用，拿回一份和子问题互相重叠、噪音更高的结果，还可能干扰合并的确定性。所以本任务明确规定：**分解后只检索子问题，绝不检索原问题**。测试里专门断言了检索调用都发生在子问题上、没有一次是 original_query。

## 3. 为什么每个子问题独立检索

- **聚焦**：每个子问题只在它自己的语义上召回，避免大问题把不同方面的文档搅在一起。
- **可覆盖检查**：能逐子问题判断"这个方面有没有证据"。如果只有一个合并结果，就没法知道"到底是哪一块缺了"。
- **预算可控**：每个子问题正好一次调用，次数固定（2 个子问题 = 2 次，3 个子问题 = 3 次），成本可预期。

独立检索是"拆"的意义所在：不拆，就永远不知道自己缺哪一块。

## 4. Round-robin 相比简单拼接的优势

**简单拼接**（如 `A,B,C,D,F`）会把 sq1 的前三名全放进来，sq2/sq3 可能一个都进不来——**最前面的子问题霸占全部证据**，后面的子问题即便有高质量结果也被挤掉。

**Round-robin（subquery_round_robin_v1）** 每轮让每个子问题各贡献一个候选：

```
sq1=A,B,C   sq2=A,D,E   sq3=F
轮1: A(sq1) D(sq2) F(sq3)
轮2: B(sq1) E(sq2)
结果: A, D, F, B, E
```

这样每个子问题都"被听见"，证据在子问题间**轮转平衡**，比简单拼接更公平，也更能支撑"综合回答"——因为每个子问题都至少贡献了证据。

## 5. 为什么不能跨子问题直接比较 BM25 score

BM25 分数是**同一个查询、同一个文档集合内部**的相对打分。不同子问题查询词不同、命中情况不同，它们的分数**不在同一把尺子上**：sq1 的 0.8 和 sq2 的 0.8 没有可比性，直接按分数全局排序等于拿两把不同的尺子比长度。

所以合并**严格保留每个子问题内部的检索顺序**（该子问题内 BM25 高的靠前），轮转只按"子问题顺序 + 内部排名"取候选，**绝不跨子问题排序**。测试用一个"sq1 高分在后、低分在前"的反例证明合并结果不是按分数排的。

## 6. 全局去重规则

合并时做**全局去重**（跨子问题，不是每个子问题内部）：

1. **chunk_id 非空**：按 chunk_id 去重——同一条 chunk 不管被哪个子问题召回，只保留一次。
2. **chunk_id 缺失**：按 `(source_name, content)` 去重——没有稳定 chunk_id 时用"来源 + 正文"判断是否同一条。

保留**首次出现顺序**：哪个子问题先把它带进来，就归谁（也决定了它的 query_id）。去重规则与 EvidenceBundle 一贯契约一致。

## 7. Citation 为什么要在 merge 后重新编号

每个子问题自己的检索结果是独立编号的，如果不重新编号，多个子问题都会冒出 `[C1]`，答案里的 `[C1]` 就不知道指哪条。合并后必须**按最终 Bundle 顺序重新分配 `[C1]~[C5]`**，保证整个答案的引用空间唯一、连续。

这也解释了为什么合并必须**确定性**：同一组输入永远得到同一份编号，可复现、可审计。

## 8. query_id 如何保留证据来源

合并给每条证据打上 `query_id`，记录它**第一次进入最终 Bundle 时来自哪个子问题**（sq1/sq2/sq3）。

- 用途 1：API 的 `sources[].query_id` 让调用方知道这条证据支撑的是哪个子问题；
- 用途 2：审计时能追溯"这条证据是谁搜出来的"。

注意：同一条文档可能被多个子问题召回，但**只保留一次**，query_id 记的是"第一次带它进来的子问题"。

## 9. required subquery 证据覆盖

QueryPlan v1 里所有 Subquery 都 `required=true`，即**每个子问题都是必需的**。因此 decomposed 路径执行完所有子问题检索后，要做一次**覆盖检查**：

- **所有 required 子问题都有原始检索结果**（每个子问题返回非空）→ 只要最终 Bundle 非空 → `supported / can_generate=true`；
- **任意 required 子问题结果为空** → `insufficient_evidence / can_generate=false`，reason_code=`INCOMPLETE_SUBQUERY_EVIDENCE`，**不调用 AnswerPort**，返回固定拒答文本。

注意一个关键语义：**同一条文档可以同时支撑多个子问题**。即使全局去重后只保留一次，只要该子问题的原始检索结果非空，就不自动判它"无证据"。覆盖检查看的是"每个子问题是否至少拿到过候选"，不是"合并后还剩几条"。

## 10. 为什么部分缺证据时拒答

如果 Planner 认为这个问题需要 3 个子问题分别取证，而其中一个子问题搜不到任何东西，那答案就是**残缺的**——那个子问题对应的维度没有事实支撑。硬着头皮生成，等于用不完整证据编答案。

所以：**缺一块就不生成，返回拒答文本**。这是"诚实优于看起来完整"。测试证明部分子问题空结果时：状态 refused、AnswerPort 一次都没被调用、verification 标记为 INCOMPLETE_SUBQUERY_EVIDENCE。

## 11. Budget 怎样限制调用次数

05C 把 `AgentRunBudget.max_retrieval_calls` 从 1 调到 **3**，因为最多可能跑 3 个子问题检索：

```
1 Planner + 3 Retrieval + 1 Generation = 5 个外部步骤（≤ max_steps=6）
```

但预算只是**上限**，不是"必须用满"：single 路径仍只检索 1 次、direct 路径 0 次。每次子问题检索**前**都单独检查预算；如果只允许 2 次检索而问题有 3 个子问题，第三个子问题在真正调用前就 `BUDGET_EXCEEDED` 停止，不继续剩余检索或生成。测试验证了"预算 2 次时第 3 次检索前停止、且第 3 次从未被调用"。

## 12. Trace 如何展示多步执行

多子问题执行在 Trace 里是**清晰的逐条事件**：

```
run_started → planning_completed → routing_completed
→ retrieval_completed(sq1) → retrieval_completed(sq2) → retrieval_completed(sq3)
→ evidence_merged → verification_completed → generation_completed → run_completed
```

每条 `retrieval_completed` 只保存 `subquery_id / strategy / documents_returned / retrieval_call_index`（不含子问题全文、文档正文）。合并后多一条 `evidence_merged`，记录 `merge_policy / input_candidate_count / final_unique_count / duplicate_count / truncated / covered_query_count / required_query_count`（不含证据正文）。

Trace 的纪律和 05A 一致：只记结构化事实与计数，**不记正文、子问题文本、Key、raw output、traceback**。

## 13. 当前能力边界

- **只用 BM25**：每个子问题固定 `strategy=bm25`，没有 Dense/Hybrid 自适应。
- **无 Adaptive Router**：路由仍是确定性映射，不按问题类型选策略。
- **最小覆盖检查**：只做"每个 required 子问题是否有候选"的结构检查，**不宣称 obligation-level / claim-level Faithfulness**。
- **不比较跨子问题分数**：合并不跨子问题排序。
- **无真实 Dev/Holdout 指标**：本任务全部 Fake/内存 BM25 验证，未跑真机评测。
- **decomposed 不再返回 DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED**：正常合法 QueryPlan 不会再走 deferred；该错误码保留为兼容枚举。

## 14. 面试可能追问与参考回答

**Q：Query Decomposition 和普通多次搜索有何区别？**
A：普通多次搜索是对同一意图反复补搜；分解检索先把问题拆成多个独立意图（子问题），每个子问题独立检索再合并。多出来的调用次数是任务结构要求的，不是补救。

**Q：为什么分解后不检索原问题？**
A：既然判定问题太宽才分解，再搜原问题等于又拿回混杂结果，多花一次调用还干扰合并的确定性。测试断言检索都发生在子问题上。

**Q：Round-robin 为什么比简单拼接好？**
A：简单拼接会让最前面的子问题霸占全部证据；轮转让每个子问题每轮各贡献一个，证据在子问题间平衡，每个方面都被"听见"。

**Q：为什么不能跨子问题比 BM25 分数？**
A：BM25 分数是同一查询、同一文档集合内部的相对分；不同子问题查询词不同，分数不在同一把尺子上。合并只保留子问题内部顺序，绝不跨子问题排序。

**Q：部分子问题没搜到怎么办？**
A：只要有一个 required 子问题结果为空，就判定 insufficient_evidence（INCOMPLETE_SUBQUERY_EVIDENCE），不调用 AnswerPort，返回固定拒答文本。缺一块就不编。

**Q：预算从 1 调到 3 会不会让 single 多检索？**
A：不会。预算只是上限，single 仍只检索 1 次、direct 0 次；每次检索前单独检查，超限立即 BUDGET_EXCEEDED。

**Q：为什么 merge 后要重新编号 citation？**
A：每个子问题独立检索会各自冒出 [C1]，不重编号则答案引用空间冲突。合并后按最终顺序重新分配 [C1]~[C5]，保证唯一、连续、可复现。

## 15. 下一阶段 Adaptive Router

当前路由是确定性的：decomposed → bm25。下一阶段（G3-ADAPT-06A）将引入 **Adaptive Router**：按查询类型（fact / comparison / multi_entity / causal / code_symbol / troubleshooting）选择检索策略与参数，并用更强的 **Evidence Verifier v2** 做更细的证据校验。本任务的 subquery_round_robin_v1 与覆盖检查将成为那套自适应系统的基础。

---

## 边界声明

- 未读取/搜索 Gate 3 Holdout / sealed；示例全部为 synthetic。
- 未运行真实模型/检索；未计算任何指标。
- 只用 BM25；无 Adaptive Router；覆盖检查为最小结构检查，不宣称完整 Faithfulness。
- decomposed_retrieval 已可真实执行 2~3 次子问题检索；deferred 仅保留为兼容枚举。
