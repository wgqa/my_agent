# 66-Gate3-QueryPlan强类型契约

> G3-PLAN-03：Gate 3 QueryPlan 强类型 Schema（QueryPlan / Subquery / fallback factory）。
> 日期：2026-08-13
> 权威来源：主设计文档 `docs/design/g3_query_decomposition_adaptive_retrieval.md`（§5、§11、§14）；决策记录 `docs/adr/ADR-001-gate3-planning-routing-evidence-boundary.md`（D1/D2）；实现 `core/query_planning/models.py`；测试 `tests/test_query_plan.py`。
> 范围声明：本任务只做 Schema 契约，不实现 LLM Planner、Router、Retriever、EvidenceBundle 或实验指标。

---

## 1. QueryPlan 解决什么问题

Gate 2 冻结了"简单检索就够强"的基线（Recursive + BM25 top5 在 Benchmark v1 上是 winner）。Gate 3 要回答的是一件事：

> 把问题拆成子问题再检索（Decomposition）、并给不同子问题选不同检索器（Adaptive Retrieval），是否比"原问题一次 BM25 / 一次 Hybrid"带来可复现的收益，收益是否值得额外的检索调用、Token、延迟和失败风险。

要做这种**受控对照**，必须先把"规划"这件事本身变成**可以冻结、可以复现、可以审计**的对象。这就是 QueryPlan：

- 它回答四个问题：**这是什么类型的问题？需要检索吗？要不要分解？如果分解，最多拆成哪几个子问题？**
- 它把 LLM 的"想法"压成**固定 Schema**，而不是一段自由文本。自由文本当然可以按字节哈希，但缺少稳定的结构化字段边界，难以做字段级校验、规范化比较和失败归因，也不适合作为可审计的规划契约。
- 它强制**有界**：最多 3 个子问题、每个子问题最多 1000 字符、evidence_target 最多 500 字符。上限是执行配置，不由模型输出控制。

一句话：QueryPlan 是"规划结果的**强类型、不可变、可哈希、可序列化**快照"，是 Gate 3 实验身份链（plan_id → snapshot → run_id）的第一个环节。

## 2. QueryPlan、RouteDecision、EvidenceBundle 的边界

三层各管一件事（ADR-001 D1）：

| 层 | Schema | 回答的问题 | 允许/禁止 |
|---|---|---|---|
| QueryPlan | `query_plan_v1` | 问题是什么类型、要不要检索、要不要分解、拆成哪些子问题 | **禁止**携带 selected strategy、candidate_k、final_k、reranker 开关、max retrieval rounds、Gold obligation ID、隐藏思维链 |
| RouteDecision | `route_decision_v1` | 为原问题或某个子问题选哪个 Retriever（bm25/simple/hybrid） | 绑定一个已规范化 QueryPlan；不生成子问题、不判断 Gold、不承担实验编排 |
| EvidenceBundle | `evidence_bundle_v1` | 每个子问题的命中如何保留、去重、确定性合并成最终 Top-5 文档 | 绑定 plan_id 与对应 RouteDecision |

**为什么必须分离**：三个职责的失败模式不同——规划失败是 schema/分类问题，路由失败是策略选择问题，合并失败是证据丢失问题。分离后每一层都能独立验证、独立回退。更重要的是：QueryPlan 一旦生成要**跨实验组复用**（C 组 Decomposition+BM25 和 D 组 Decomposition+Adaptive 必须用同一份 QueryPlan snapshot），如果把路由或合并逻辑混进 QueryPlan，共享 snapshot 就没有意义了——Router 对照就被"两次不同的规划"污染。

本任务只做 QueryPlan 层。RouteDecision 和 EvidenceBundle 是后续 G3-ADAPT-06 / G3-MRETR-05 的事。

## 3. 为什么不能让 LLM 直接控制检索上限

最大子问题数（3）、每子问题字符（1000）、evidence_target（500）、retrieval rounds（1）、Retriever 调用（3）、最终唯一文档数（5）、temperature（0）、max output（800 tokens）、timeout（20s）、重试（0）、Reranker（false）、Corrective（false）——**全部是不可变执行配置**（设计文档 §11）。

**原因（ADR-001 D2）**：

- 一旦上限由 LLM 输出控制，成本、时延、失败风险就变成了模型行为的一部分，实验前无法冻结身份，A/B/C/D 四组就无法对照。
- 有界性本身就是 Gate 3 的研究对象——"收益是否值得额外检索调用与失败风险"只有在有界预算下才可测。
- 模型输出越界时**回退**到原问题单次 BM25，而不是截断后继续。截断会让"模型输出了 4 条"和"模型输出了 3 条"变成同一个东西，破坏可解释性。

所以 QueryPlan 的 `subqueries` 长度约束（0 / 空 / 2~3 条）写死在 Schema 校验里，不可能是"模型决定拆几条都行"。

## 4. frozen dataclass 与不可变快照

QueryPlan 和 Subquery 都是 `@dataclass(frozen=True)`。frozen 意味着构造之后任何字段都不可改——试图给 `plan.subqueries[0]` 赋值会抛 `TypeError`，试图改 `plan.original_query` 会抛 `FrozenInstanceError`。

**为什么不可变**：

1. **身份稳定**：plan_id 是内容的哈希。如果对象能改，plan_id 就失效了。
2. **跨实验组共享安全**：C/D 要复用同一份 snapshot，可变对象可能在某个环节被意外改动，导致两个组用的"同一份"其实不是同一份。
3. **并发/缓存安全**：不可变对象可以在多个 Retriever 调用之间安全共享，不用担心时序问题。

另外内存里的 `subqueries` 是 `tuple` 不是 list。tuple 不可变且可哈希，list 可变且不可哈希。这也保证 QueryPlan 可以作为 dict 的 key 或在集合中使用。

## 5. 字段级校验和跨字段不变量的区别

这是本任务最重要的区分之一：

- **字段级校验**（field-level）：约束**单个字段**自身是否合法。例如 `action` 必须是枚举之一、`original_query` 长度 1~4000、`retrieval_required` 必须是严格 bool。类型错误抛 `TypeError`，值错误抛 `ValueError`。
- **跨字段不变量**（cross-field）：约束**字段组合后**是否语义合法。例如 `action=decomposed_retrieval` 但 `subqueries=()`——每个字段都"合法"（action 是枚举、subqueries 是空 tuple），但整体无意义：Retriever 无从执行分解。

**为什么需要两层**：只有字段级校验时，畸形 QueryPlan 会一路进入执行层，产生无法归属的错误（是规划错还是检索错？）。有了跨字段不变量，错误在规划层就被拦截并 fail-fast。任务要求任何违反不变量就抛异常，绝不静默修。

典型的字段级约束（本实现 `_validate_text` + 枚举/类型检查）：

- 字符串非空、非纯空白、首尾无空白（**不自动 strip**，直接拒绝）；
- 长度有界；
- 枚举成员校验；
- 严格 bool（`type(x) is not bool` 拒绝 1、"true"、None 等）。

## 6. no / single / decomposed 三种 action

`action` 是 QueryPlan 的执行方式枚举，只有三个值，每个都有严格的跨字段不变量：

| action | retrieval_required | subqueries | 执行语义 |
|---|---|---|---|
| `no_retrieval` | false | `()` | 完全不检索，不生成任何 RouteDecision。query_type 必须是 `unanswerable_or_no_retrieval`，reason_code 必须是 `NO_RETRIEVAL_NEEDED` |
| `single_retrieval` | true | `()` | 原问题一次检索，只生成一条 `subquery_id=ROOT` 的 RouteDecision |
| `decomposed_retrieval` | true | 2~3 条，ID 连续 `sq1→sq2→sq3`，required 全 true，query 不得完全重复 | 每个子问题各生成一条 RouteDecision，不额外做 ROOT 检索 |

`query_type=unanswerable_or_no_retrieval` 时用 `retrieval_required` 区分两种语义：

- `retrieval_required=false` → no_retrieval（不检索）；
- `retrieval_required=true` → unanswerable check（允许检索一次核实"确实不可答"，reason_code 只能是 `UNANSWERABLE_CHECK` 或 `PLANNER_FALLBACK`）。拒答正确性属于 Gate 5，Gate 3 只记录行为。

`reason_code` 是审计用的封闭枚举（`NO_RETRIEVAL_NEEDED` / `SIMPLE_FACT` / `CODE_SYMBOL` / `COMPARISON_EVIDENCE` / `MULTI_ENTITY_EVIDENCE` / `CAUSAL_SYNTHESIS` / `TROUBLESHOOTING_EVIDENCE` / `UNANSWERABLE_CHECK` / `PLANNER_FALLBACK`）。**本 Schema 只强制任务明确规定的映射**（如 `NO_RETRIEVAL_NEEDED` 只能配 no_retrieval、`PLANNER_FALLBACK` 只能是 single_retrieval+空 subqueries），不发明"fact 必须用 SIMPLE_FACT"这类设计文档里没有的强约束。

## 7. Subquery 为什么最多 3 条

设计文档 §11 硬预算规定最大子问题数 = 3，并且"任何模型输出都不能突破这些上限"。

**为什么是 3**：

- Gate 3 的问题类型里，比较题需要两侧各一条（2 条），多实体/多跳题通常 2~3 条就够。3 条在覆盖率和成本之间是个经验折中。
- 每多一条子问题就多一次检索调用（+1）、多一份 Token、多一点延迟和失败概率。有界性是"收益是否值得额外调用"唯一可测的前提。
- 如果模型输出超过 3 条，QueryPlan 校验直接拒绝（`decomposed_retrieval 要求 subqueries 数量为 2 或 3，实际 N`），由 G3-DECOMP-04 捕获后回退，而不是截断成 3 条继续。

## 8. fallback 为什么回到原问题单次 BM25

设计文档 §5.9 与 §11 规定：Planner Schema 无效、越界、空结果或重复结果时，规范化为一个合法的 fallback QueryPlan：

- `retrieval_required=true`
- `action=single_retrieval`
- `reason_code=PLANNER_FALLBACK`
- `subqueries=()`
- `fallback_policy=single_bm25_original_query`
- 之后再算 plan_id

**为什么是 BM25**：Gate 2 的正式结论是 Recursive + BM25 top5 是 Benchmark v1 的 winner（`dbc497c796d5`）。当复杂规划失败时，最保守、最不容易引入新错误的兜底就是退回"已知最好的简单策略"。BM25 也最稳定，且查询阶段不需要生成 query embedding，也没有 Dense/融合路径的额外查询复杂度。回退到 Hybrid 或 Dense 反而是把失败风险嫁接到更复杂的通道上。

注意 fallback 保留原 `query_type`（`build_fallback_query_plan(original_query, query_type)` 原样传入），因为 query_type 是"问题本身是什么"的分类，不是规划执行的结果。

## 9. plan_id 如何计算

plan_id 是规范化 QueryPlan 的稳定哈希，算法固定（设计文档 §5.2.1、§8.5）：

1. 取身份 payload：`schema_version` + 除 `plan_id` 外的全部字段（`original_query`、`query_type`、`retrieval_required`、`action`、`reason_code`、`subqueries`、`fallback_policy`）。subqueries 序列化成 list of dict，**顺序保留，不排序**。
2. canonical JSON：`json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`，再 `.encode("utf-8")`。sort_keys 保证 dict 键序无关；ensure_ascii=False 保证中文不转义；紧凑分隔符保证字节稳定。
3. `plan_id = SHA-256(canonical)[:12]`（12 位小写十六进制）。

验证：任务给出两个固定测试向量，实测 `plan_id` 与硬编码值完全一致——

- 向量 1（fact / single_retrieval，`original_query="什么是 BM25？"`）→ `b8aa7cf8f976`
- 向量 2（comparison / decomposed 两条子问题，`original_query="比较 BM25 和 Dense 检索"`）→ `84233ef03b4b`

身份里**不包含**时间、路径、对象地址、latency、原始模型输出。

## 10. 为什么 plan_id 不包含自身

这是哈希构造的必然：plan_id 是"规范化 QueryPlan 的 SHA-256[:12]"，如果 payload 里包含 plan_id 字段，那计算 plan_id 时又需要先知道 plan_id——**循环依赖，哈希算不出来**（ADR-001 R1 补充）。

所以任何"对象自指"的身份哈希都必须排除该字段本身。实现上用 `identity_payload()` 这个**窄接口**返回排除 plan_id 的身份载荷；`to_dict()` 才返回含 plan_id 的完整快照。`from_dict()` 读取完整快照后，用 `identity_payload()` 重算 plan_id 并**核对**是否与快照里的 plan_id 一致——不一致就抛 `ValueError`，防止序列化数据被篡改或来自错误来源。

## 11. 为什么 subquery 顺序进入身份

两条子问题 `[sq1, sq2]` 和 `[sq2, sq1]` 不是同一份规划——sq1 先生成说明它更优先，合并轮转（`subquery_round_robin_v1`）也是按 sq1→sq2 顺序取文档。如果哈希把 subqueries 当**集合**（先排序再哈希），这两种顺序会得到同一个 plan_id，抹掉顺序语义。

所以实现里 subqueries list **不排序**，保持 sq1→sq3 原序进入 canonical JSON。反过来这也是跨字段不变量的一部分：decomposed 的 subquery id 必须按顺序连续（`sq1,sq2` 或 `sq1,sq2,sq3`），顺序本身就是规划身份的组成部分。

## 12. Schema 校验不能解决哪些语义问题

QueryPlan 的 Schema 校验是**结构级**的，解决不了**语义级**的问题。任务明确把这些留给 G3-DECOMP-04 的 Planner 输出验证策略：

- 是否引入了原问题里不存在的新实体（例如问题只提 A，子问题却问 B）；
- 比较题是否保持了问题两侧的对象（两侧都拆出来了，还是一侧被丢了）；
- `evidence_target` 是否语义上正确（写了但指向错误证据）；
- 子问题是否携带了隐式 Gold 信息（等于泄漏答案）；
- 两条子问题是否语义近义但措辞不同（Schema 只能拒绝"query 字符串完全相同"的重复）。

本实现只拒绝"query 字符串完全相同"的重复子问题——这是唯一能**确定性、无脆弱关键词规则**判断的项。其余必须靠人工或更高级的验证，不能靠几行关键词正则假装"做了语义检查"。

## 13. 项目代码位置与测试位置

- 实现：`core/query_planning/__init__.py`（公开 API：`QUERY_PLAN_SCHEMA_VERSION` / `QUERY_PLAN_ACTIONS` / `QUERY_PLAN_REASON_CODES` / `QUERY_PLAN_QUERY_TYPES` / `QUERY_PLAN_FALLBACK_POLICY` / `Subquery` / `QueryPlan` / `build_fallback_query_plan`）；`core/query_planning/models.py`（全部逻辑）。
- 测试：`tests/test_query_plan.py`（90 个 synthetic 测试）。
- 约定：
  - `Subquery`：frozen dataclass，字段 `id/query/evidence_target/required`，构造即校验。
  - `QueryPlan`：frozen dataclass，字段 `schema_version/plan_id/original_query/query_type/retrieval_required/action/reason_code/subqueries/fallback_policy`。
  - 对外构造一律 `QueryPlan.create(...)`（自动算 plan_id）；`QueryPlan.from_dict(...)`（读完整快照并验证 plan_id）；`identity_payload()` 排除 plan_id 的窄接口。
  - `build_fallback_query_plan(original_query, query_type)` 构造合法 fallback。
  - `core/query_planning` 不反向依赖 `evaluation`；不使用 Pydantic；路由字段（selected_strategy/candidate_k/reranker/max rounds）一律不混入 QueryPlan。

## 14. 常见错误案例

1. **把路由字段塞进 QueryPlan**：给 QueryPlan 加 `selected_strategy` 或 `candidate_k`——违反三层边界，共享 snapshot 失效。
2. **`action=no_retrieval` 却 `retrieval_required=True`**：字段各自合法，组合矛盾，跨字段不变量拒绝。
3. **`reason_code=NO_RETRIEVAL_NEEDED` 配 `action=single_retrieval`**：NO_RETRIEVAL_NEEDED 只属于 no_retrieval。
4. **`decomposed_retrieval` 只有 1 条子问题**：必须是 2 或 3。
5. **子问题 id 不连续或乱序**：`[sq1, sq3]` 或 `[sq2, sq1]` 都拒绝。
6. **两条子问题 query 完全相同**：结构级唯一能确定性判断的语义错误，拒绝。
7. **`plan_id` 格式错误或与内容不符**：必须是 12 位小写十六进制且与重算值一致；改内容不换 id 会让 `from_dict` 报错。
8. **首尾空白混入字符串**：实现不 strip，直接拒绝——避免"同一问题两种字节形态"污染身份。
9. **让模型决定上限**：模型输出 4 条子问题就允许——违反有界原则，必须回退。

## 15. 面试官可能追问与参考回答

**Q：为什么 QueryPlan 用 frozen dataclass 而不是 Pydantic？**
A：项目约定标准库、零新增依赖。frozen dataclass 已经能提供不可变性、字段校验（`__post_init__`）、`to_dict/from_dict`；而且身份哈希要求 canonical JSON，Pydantic 的序列化并不直接等价，反而引入额外依赖和序列化语义。

**Q：plan_id 和 to_dict 里的 plan_id 有什么区别？**
A：它们是同一个值。区别在接口：`identity_payload()` 排除 plan_id（用于身份哈希，避免自指），`to_dict()` 包含 plan_id（完整快照）。`from_dict()` 用 identity_payload 重算并与快照里的 plan_id 核对。

**Q：为什么不能把 subqueries 排序后再算哈希？**
A：子问题顺序有执行语义（合并轮转按 sq1→sq2 取文档）。排序会把两种不同规划折叠成同一 id，破坏复现和审计。

**Q：跨字段不变量和字段级校验各管什么？**
A：字段级管"单个字段合不合法"（类型、枚举、长度、空白），跨字段管"组合后合不合语义"（如 decomposed 必须有 2~3 条、no_retrieval 必须 retrieval_required=false）。两层都要，缺一层就会放过畸形 QueryPlan 进入执行层。

**Q：fallback 为什么是单次 BM25 而不是 Hybrid？**
A：Gate 2 结论 BM25 是 winner；规划失败时退回"已知最好的简单策略"最保守，不把失败风险嫁接到更复杂的融合通道上。

**Q：这个 Schema 能防数据泄漏吗？**
A：不能，也不该。Schema 只保证结构合法；子问题是否携带隐式 Gold 是语义问题，要由 G3-DECOMP-04 的输出验证策略 + 人工审计处理。Schema 能做的是确定性拒绝"query 字符串完全重复"。

## 16. 用户可以亲手完成的练习

1. 用 `python` 跑 `QueryPlan.create(original_query="什么是 BM25？", query_type="fact", retrieval_required=True, action="single_retrieval", reason_code="SIMPLE_FACT")`，看 `plan_id` 是不是 `b8aa7cf8f976`。然后改一个词，观察 id 变化。
2. 尝试 `QueryPlan.create(...)` 构造 `action="decomposed_retrieval"` 但只给 1 条子问题，读报错信息，理解跨字段不变量。
3. 给 Subquery 传 `required=False`，读报错，理解 v1 为什么强制 true。
4. 把两条子问题顺序对调（sq2 在前）构造 decomposed，读报错，理解为什么顺序是身份的一部分。
5. 对同一份 plan 调 `to_dict()` 两次，修改第一次的返回值，确认第二次返回值不受影响（to_dict 修改隔离）。
6. 用 `from_dict` 读一个改了 `plan_id` 的快照，确认抛 `ValueError`。

## 17. 30 秒、2 分钟和 5 分钟讲解版本

**30 秒**：Gate 3 要做"拆问题再检索"的对照实验，就得先让"规划"本身可冻结、可复现。QueryPlan 就是把规划结果变成强类型不可变对象：固定 Schema、字段级校验、跨字段不变量、稳定 plan_id。超出上限或 schema 不合法就回退到原问题单次 BM25。

**2 分钟**：QueryPlan 回答四个问题——问题类型、要不要检索、要不要分解、拆成几个子问题。它与 RouteDecision（选检索器）、EvidenceBundle（合并证据）严格分离。用 frozen dataclass 保证不可变，内存里 subqueries 是 tuple。plan_id 是对排除自身字段的规范化 JSON 做 SHA-256 前 12 位，所以内容变 id 必变、顺序参与身份。跨字段不变量保证 no/single/decomposed 三种 action 的组合语义合法，任何违规 fail-fast，由 G3-DECOMP-04 捕获后回退单次 BM25。

**5 分钟**：完整讲三层边界（QueryPlan/RouteDecision/EvidenceBundle）→ 硬预算为何不可由 LLM 控制 → frozen dataclass 与不可变快照 → 字段级校验 vs 跨字段不变量 → no/single/decomposed 三种 action 的不变量 → 为什么最多 3 条子问题 → fallback 为什么回到 BM25 → plan_id 的 canonical JSON 算法、为何排除自身、为何保留 subquery 顺序 → Schema 解决不了的语义问题 → 代码/测试位置 → 常见错误 → 面试问答。

## 18. 与下一步 G3-DECOMP-04 的关系

本任务（G3-PLAN-03）只提供 **Schema 与合法构造**：

- 谁调用 LLM、怎么从自然语言判断 query_type、怎么生成子问题——**都不是本任务的事**。
- 本任务提供的是 G3-DECOMP-04 可以放心依赖的强类型壳子：`QueryPlan.create`、`QueryPlan.from_dict`、`build_fallback_query_plan`。

G3-DECOMP-04（有界 Planner 与 fallback）要做：

- 调用 Planner 生成原始输出；
- 解析并决定传入哪个合法 query_type；
- 捕获 Planner 解析失败，调用 `build_fallback_query_plan(original_query, query_type)` 回退；
- 对 Planner 输出做**语义验证**（新实体、比较两侧对象、evidence_target 正确性、隐式 Gold、语义近义重复）——这些本任务的 Schema 明确不解决。

本任务还明确了状态机：审计（G3-PLAN-03 REVIEW PENDING）通过后，进入 G3-DECOMP-04；在此之前不实现、不假装实现 Planner/Router/Evidence 任何业务逻辑。
