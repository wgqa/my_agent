# 67-Gate3有界Planner输出解析与Fallback

> G3-DECOMP-04A：Planner 抽象接口、严格结构化输出解析、错误分类与统一 fallback。
> 日期：2026-08-13
> 权威来源：主设计文档 `docs/design/g3_query_decomposition_adaptive_retrieval.md`（§4.1、§5、§11、§12）；决策记录 `docs/adr/ADR-001-gate3-planning-routing-evidence-boundary.md`（D1/D2）；实现 `core/query_planning/planner.py`；测试 `tests/test_query_planner.py`。
> 范围声明：本任务不接入真实 LLM、不写正式 Prompt、不运行 Dev/Holdout 指标；所有示例为 synthetic。

---

## 1. Planner 在 RAG/Agent 系统中的职责

Planner 是 Gate 3 的"问题分类 + 拆解"环节。它的输入是用户的**原始问题**，输出是**结构化规划**：这是什么类型的问题、要不要检索、要不要拆成子问题、拆成哪几个子问题。

Planner 是 RAG 系统里离"LLM 自由发挥"最近的组件之一。正因为它直接消费模型输出，必须在它外面包一层**可信边界**——否则模型随口编的字段、多余的解释文字、越界的策略参数，就会一路污染到检索执行层。

在 Gate 3 的层分里：

- **QueryPlan**（已实现，study-note 66）是"规划结果"的强类型容器；
- **Planner 输出解析**（本任务）是"模型 JSON → 可信 QueryPlan 或确定性 fallback"的守门员；
- 后续 **Router / Retriever / EvidenceBundle** 再消费这份 QueryPlan 执行检索与合并。

## 2. 为什么 Planner 不能直接返回任意 Python dict

模型输出的原始 JSON 是一个**无约束 dict**：它可以有任意键、任意类型、任意嵌套、甚至重复键。如果直接把 dict 丢给下游：

- 下游无从知道哪个字段是必须的、哪个值合法；
- 一个 `retrieval_required` 传成 `1`、`action` 拼错成 `parallel_retrieval`，直到执行层才爆炸，错误归属不清；
- dict 无法哈希、无法作为实验身份，也就无法进 `plan_id` 身份链。

QueryPlan/Subquery 的强类型契约（frozen dataclass + 字段级校验 + 跨字段不变量）就是要**把无约束 dict 变成有约束对象**。Planner 这一层负责把模型 JSON **严格转换成**那个强类型对象，而不是让 dict 裸奔。

## 3. 为什么模型输出是不可信输入

同一个问题，模型今天输出 `{"action": "single_retrieval"}`，明天可能输出：

- `以下是思考过程：{"action": "single_retrieval"}`
- `{"action": "single_retrieval"}（已根据上下文优化）`
- 代码块包起来的 JSON
- 把 `retrieval_required` 写成 `"true"`（字符串）
- 自作主张加 `selected_strategy: "hybrid"`、`candidate_k: 30` 这类检索参数
- 甚至给两个子问题起了重复的 query

这些都不是"可以修一修再用"的问题——它们是**输出契约被破坏**的信号。对评测系统而言，**"模型这次没按格式输出"本身就是一条重要记录**：它计入 fallback rate、schema validity，直接影响"Decomposition 是否值得"的结论。所以宁可判定失败并回退，也不要静默修复掩盖真实失败率。

## 4. 可信字段与不可信字段的边界

模型输出里**只允许**五个字段：

```
query_type, retrieval_required, action, reason_code, subqueries
```

除此之外一切字段（`original_query`、`schema_version`、`plan_id`、`fallback_policy`、`selected_strategy`、`candidate_k`、`reranker_enabled`、`max_rounds`、任何 Gold/评测标签）都属于**不可信字段**，出现即视为 schema 违规。

为什么这样划分：

- 模型能合理地"判断问题类型、要不要检索、要不要拆解"——这些是规划域；
- 模型**不能**决定"用什么检索策略、候选池多大、身份哈希是什么"——这些是执行配置与身份域，属于系统冻结契约；
- 一旦让模型输出这些字段，它就能在每次调用里偷偷改变实验身份或预算，A/B/C/D 对照就被污染。

实现上用 `PLANNER_MODEL_ALLOWED_FIELDS` 这个 frozenset 表达白名单，未知字段一律 `PLAN_INVALID_SCHEMA`。**用白名单而不是黑名单**——默认拒绝一切，只有明确允许的才放行。

## 5. 为什么 original_query 必须由本地注入

`original_query` 是 QueryPlan 身份的组成部分（参与 `plan_id` 哈希），也是后续检索、合并、评测的锚点。如果它来自模型输出：

- 模型可能在两次调用里改写措辞，导致同一问题产生不同 plan_id，破坏 C/D 共享 snapshot；
- 模型可能注入与调用方请求不一致的问题文本，下游检索的就是错误问题；
- 模型可能把 `original_query` 和它自己幻觉出的"更精确"版本混在一起。

所以解析函数 `parse_planner_output(original_query=..., ...)` 用**调用方传入的原值**注入，模型输出里出现 `original_query` 字段直接判 `PLAN_INVALID_SCHEMA`。

## 6. 为什么 plan_id 不能由模型生成

`plan_id` 是"规范化 QueryPlan 排除自身字段后 SHA-256[:12]"（study-note 66 §9/§10）。它必须由本地代码在**规范化完成之后**计算，模型不可能知道规范化后的 canonical JSON 是什么。

如果允许模型输出 `plan_id`：

- 模型可以任意声称身份，身份就失去了"内容哈希"的防伪意义；
- 无法验证一致性（模型输出的 plan_id 和内容对不上时，谁负责？）。

所以 `plan_id` 由 `QueryPlan.create` 计算，模型输出里出现 `plan_id` 字段直接判 `PLAN_INVALID_SCHEMA`。`schema_version` 和 `fallback_policy` 同理，都是本地常量注入。

## 7. strict JSON 与"尽力修复 JSON"的权衡

模型经常产出"不完全是 JSON 的 JSON"：前后有解释文字、被 Markdown 代码块包住、少个括号。两种策略：

- **尽力修复**：写正则抠出 `{...}`、自动补括号、忽略前导文字。好处是"能用的输出变多"；坏处是修复规则本身脆弱、不可审计，且**掩盖了模型没遵守输出契约这一事实**。
- **strict**：`json.loads` 解析完整字符串，任何不匹配直接失败并回退。好处是行为可预测、失败可归因；代价是"好输出"可能被误杀。

Gate 3 选择 **strict**。原因：这是受控实验，schema validity 与 fallback rate 是**研究指标**。如果偷偷修复，指标就失真了——你不知道模型到底有多守规矩。宁可回退，也不掩盖真实行为。

## 8. 未知字段为什么应该 fail-fast

未知字段 = 模型输出了白名单之外的东西。常见形态：

- 越界字段：`selected_strategy`、`candidate_k`、`reranker_enabled`——模型试图干预检索策略；
- 身份字段：`original_query`、`plan_id`——模型试图干预身份；
- 幻觉字段：`explanation`、`confidence`——模型加了没约定的键。

如果**忽略**未知字段（静默丢弃），模型会持续输出这些字段而无人知晓，契约慢慢腐化；如果**接受**它们，则模型获得了修改系统行为的能力。fail-fast 是唯一安全选择：出现未知字段就整体失败并回退，把"模型越界"显式暴露成指标。

## 9. JSON 重复 key 的风险

JSON 标准建议对象成员名称保持唯一，但不少解析器仍会接受重复 key；不同实现可能保留首值、保留末值或直接报错，因此不能依赖默认行为。攻击或幻觉场景：

```json
{"query_type": "fact", "query_type": "comparison", ...}
```

默认解析后 `query_type` 是 `comparison`——前一个值被静默丢弃。这在评测里意味着：模型可能"先写一个再改一个"，最终值不可复现、不可审计。

实现用 `json.loads(raw, object_pairs_hook=...)`：hook 收到每个对象的键值对列表，发现重复 key 直接抛异常，整体判 `PLAN_INVALID_SCHEMA`。这个 hook 对**嵌套对象**（包括每个 subquery）同样生效，所以 subquery 内重复 key 也会被拒绝。

## 10. QueryPlan 与 PlannerOutcome 的区别

- **QueryPlan** 是"规划内容"：纯数据容器，描述问题类型、action、subqueries、plan_id。它不关心这份计划是模型给的还是 fallback 生成的。
- **PlannerOutcome** 是"Planner 这一轮的输出包装"：除了 `plan`，还带两个**过程元数据**——`fallback_used`（这次是否回退了）和 `failure_code`（若回退，失败代码是什么）。

区分很重要：同一个 QueryPlan 对象，正常路径和 fallback 路径都会产生；但**审计**需要知道"这次是模型直接给出的，还是解析失败后系统兜底的"。`PlannerOutcome` 把这两条信息绑定在一起，并且用 frozen dataclass + 构造时校验保证**组合不变量**：

- normal：`fallback_used=False`、`failure_code=None`、`plan.reason_code != "PLANNER_FALLBACK"`；
- fallback：`fallback_used=True`、`failure_code` 是允许枚举、`plan` 必须是单次检索 `PLANNER_FALLBACK`。

`to_dict()` 只含 `plan / fallback_used / failure_code / call_metadata`，**不含** raw_output、完整异常、traceback、Prompt、思维链——错误细节留在日志，不进结果对象。

### 10.1 call_metadata（04B-01 新增）

`PlannerOutcome` 增加可选字段 `call_metadata`（`PlannerCallMetadata`）：

- **parser-only**：`parse_planner_output` 单独调用时不附加元数据，`call_metadata` 为 `None`；
- **Provider 运行时**：真实/注入 Provider 返回时必须附加元数据（provider/model/prompt_version/prompt_sha256/call_count/tokens/latency_ms）；
- `PlannerCallMetadata` 是观测事实，**不参与 plan_id**；不含 API Key、Authorization、base_url 秘密参数、raw model output、traceback、完整异常或思维链；
- 原始模型输出**不保存到 outcome**，只作为 `parse_planner_output` 的输入。

04B-01 还区分两类 **Provider 层失败**（与 parser 层失败不同）：超时 → `PLANNER_TIMEOUT`；认证/限流/连接失败/HTTP Provider 错误/响应结构缺损 → `PLANNER_PROVIDER_ERROR`。非法/空模型文本仍由 `parse_planner_output` 分类（PLAN_EMPTY/INVALID_SCHEMA/OVER_DECOMPOSE/UNDER_DECOMPOSE/DUPLICATE_SUBQUERY）。`BaseQueryPlanner.plan(original_query) -> PlannerOutcome` 接口不变，04B-01 只是它的一个真实实现。

## 11. fallback 为什么是系统行为

`PLANNER_FALLBACK` 是**系统拥有的状态**，模型无权主动声明。原因：

- 如果模型能输出 `reason_code=PLANNER_FALLBACK`，它就能在任何时候"自己选择放弃"，把本应成功的规划伪装成系统兜底；
- fallback 意味着"这轮规划没有按预期产出计划"，这是需要人工审计的事件，不能由模型自说自话。

所以解析器遇到模型输出 `reason_code == "PLANNER_FALLBACK"` 直接判 `PLAN_INVALID_SCHEMA`。fallback 只能由 `build_fallback_query_plan` 这个系统函数产生。

## 12. 为什么 fallback 回到原始 query

fallback 的意义是"复杂规划失败了，退回最保守的路径"，而不是"换一个更花哨的问题再试"。回退必须**保留调用方传入的原始 query**：

- 检索执行层按原问题单次 BM25 检索，结果可预测、可复现；
- 不静默生成新 query——那等于在没有监督的情况下引入新的规划决策，违背"回退"的语义。

所以 `build_fallback_query_plan(original_query)` 直接用原 query 构造；它的 `query_type` 固定为系统专属 `unknown`（见 §12.1），调用方、Dev 或 Gold 都不参与 fallback 类型。

### 12.1 为什么 fallback 的 query_type 必须是 unknown

Planner 失败时**不存在可信分类结果**：模型没有产出可用的 query_type，调用方也没有能力判断"这题本该是什么类型"。因此 fallback 使用系统专属 `unknown`：

- **禁止**用 Gold 标签、Dev 标签、部分非法模型输出或任意语义类型填充 fallback 的 query_type——那等于伪造一个"分类正确"的假象，污染正常分类准确率；
- `unknown` 不是模型输出类别、不是数据集标签，只属于 `PLANNER_FALLBACK`；
- `query_type = unknown` ⇔ `reason_code = PLANNER_FALLBACK` 双向强约束：模型输出 `unknown` 判 `PLAN_INVALID_SCHEMA`，系统也不允许用分类类型构造 fallback。

这**不是**新增第八种业务问题类型：`unknown` 只出现在系统 fallback 路径，永远不进正常分类指标。

## 13. 为什么 fallback 选择单次 BM25，而不是继续让模型修复

设计文档 §5.9/§11 规定 fallback = `single_retrieval` + `PLANNER_FALLBACK` + 空 subqueries + `single_bm25_original_query`。三个理由：

1. **BM25 是已知最强的简单基线**：Gate 2 结论 Recursive+BM25 top5 是 Benchmark v1 winner（`dbc497c796d5`）。规划失败时退回"已知最好的简单策略"最保守。
2. **不把失败风险嫁接到更复杂路径**：让模型"再修一次"（重试）等于把一次失败变成两次随机机会，成本、延迟、失败率都不可控，也无法在实验前冻结。
3. **零额外查询复杂度**：BM25 查询阶段不需要生成 query embedding，也没有 Dense/融合路径的额外开销。

fallback 是一次性、确定性、无重试的。失败就是失败，记下来，用最稳的路走完这轮。

## 14. 错误分类对评测和排障的价值

Gate 3 设计文档 §12 定义了一组失败代码（`PLAN_*`、`ROUTE_*`、`RETRIEVAL_*` 等）。本任务落实其中的规划层分类：

- `PLAN_EMPTY`：模型没输出；
- `PLAN_INVALID_SCHEMA`：JSON 非法、顶层类型错、重复 key、字段缺失/未知、类型/枚举/跨字段错误；
- `PLAN_OVER_DECOMPOSE`：拆超过 3 条；
- `PLAN_UNDER_DECOMPOSE`：标了分解却只给 0/1 条；
- `PLAN_DUPLICATE_SUBQUERY`：子问题 query 完全重复；
- 预留（后续 04B 使用）：`PLAN_NEW_ENTITY`（新增实体）、`PLANNER_TIMEOUT`（超时）。

分类的价值：

- **指标**：fallback rate、schema validity 按失败代码分层，才能判断"模型主要栽在哪"；
- **排障**：看到 `PLAN_OVER_DECOMPOSE` 就知道要收紧 Prompt 的子问题数量约束，看到 `PLAN_DUPLICATE_SUBQUERY` 就知道要去重策略有问题；
- **归因**：错误在规划层被拦截并回退，不会一路漏到执行层变成无法归属的检索错误。

**分类优先级必须稳定**：先顶层与字段集合，再 action/subqueries 基础类型，再 decomposed 数量，再 Subquery 构造，再重复 query，最后 QueryPlan.create 完整校验。稳定性保证同一输入永远得到同一失败代码，可复现。

## 15. 调用方错误与模型输出错误的区别

`parse_planner_output` 区分两类错误：

- **调用方错误**（程序员的 bug）：`original_query` 非字符串/空白/首尾空白、`raw_output` 非字符串。这些**直接抛 TypeError/ValueError**，不转 fallback——因为 bug 必须立刻暴露，不能伪装成"模型输出不好"。
- **模型输出错误**（预期内的坏数据）：空输出、非法 JSON、字段越界等。这些**转 fallback**并记录 `failure_code`。

实现顺序保证这个区分：解析**一开始**就调用 `build_fallback_query_plan(original_query)`——这一步会校验 `original_query`，非法则直接抛。也就是说，**调用方参数在接触任何模型输出之前就被验证了**，不可能被误判成模型错误。fallback 的 query_type 由 factory 内部固定为系统专属 `unknown`，调用方不需要也不能提供。

## 16. 为什么不能吞掉所有 Exception

解析器只在**受控的预期失败点**捕获异常：

- `json.loads` 的 `JSONDecodeError` 和自建的 `_DuplicateKeyError` → `PLAN_INVALID_SCHEMA`；
- `Subquery.from_dict` 的 `TypeError/ValueError` → `PLAN_INVALID_SCHEMA`；
- `QueryPlan.create` 的 `TypeError/ValueError` → `PLAN_INVALID_SCHEMA`。

除此之外的异常（编程错误、意外的系统异常）**不捕获、不吞**，让它们向上传播。原因：

- 吞掉一切 = 把真实 bug 变成静默 fallback，错误无法归属；
- 调用方参数错误（`original_query` 非 str 等）发生在 `build_fallback_query_plan` 阶段，不在 try 块内，保证它们永远以异常形式暴露；
- `raw_output` 非 str 的 TypeError 也在 fallback 构造之后显式抛出，不被转成模型错误。

原则：**只有"模型 JSON 结构坏掉"这一种失败才回退；系统自身的问题一律抛异常。**

## 17. 为什么本任务不复用现有 Generator

项目里有 `core/generator/*` 的 `BaseGenerator`/`OpenAIGenerator`/`DeepSeekGenerator`。它们是为**RAG 回答生成**设计的：带回答 Prompt、可能返回异常字符串、有重试行为。Planner 的契约完全不同：

- Planner 需要**结构化 JSON**，Generator 产出自由文本回答；
- Planner 是**单次调用、无重试、严格解析**；Generator 有重试和降级；
- 复用 Generator 会把"回答生成"的 Prompt、重试、异常字符串语义污染进"规划"路径，且不符合 Planner 的身份与失败分类。

所以本任务定义独立的 `BaseQueryPlanner` 抽象接口（`plan(original_query) -> PlannerOutcome`），04B 才实现真实 Provider。Generator 一行不改。

## 18. 为什么本任务不接真实 LLM

本任务建立的是**输出边界**：无论未来接什么模型、用什么 Prompt，模型返回的 JSON 都要经过这套严格解析。边界本身不依赖具体模型，所以现在就能写、能测、能冻结。

不接真实 LLM 的三个原因：

1. **可测试性**：边界逻辑可以用 synthetic JSON 全覆盖测试，不依赖网络/API Key/模型行为；
2. **冻结在前**：正式实验要求 Planner Prompt、provider/model、temperature 在 holdout 前冻结，但**边界代码可以先冻结**；
3. **职责分离**：04A 只做"解析 + 分类 + fallback"，04B 才做"如何调用模型 + Prompt + 超时"。

## 19. 常见错误实现

1. **用正则从模型输出里抠 JSON**：`re.search(r'\{.*\}')` 会漏掉嵌套、误匹配解释文字，且重复 key 检测无从谈起。
2. **忽略未知字段**：`obj.get("query_type")` 默认容忍多余字段，模型越界无人察觉。
3. **静默 strip 或补字段**：`query.strip()` 把"模型带了首尾空格"变成"好像很规范"，掩盖契约破坏。
4. **接受 `PLANNER_FALLBACK` 作为模型输出**：让模型自导自演"放弃"，审计失效。
5. **把调用方参数错误也转 fallback**：`original_query` 传错了却得到 fallback，bug 被吞。
6. **to_dict 里塞 raw_output/traceback**：结果对象变得不可复现、不可哈希，还泄漏敏感细节。
7. **分类不稳定**：先检查子问题重复再检查数量，导致同一输入两种失败代码。
8. **用 `json.loads` 默认行为接受重复 key**：后值覆盖前值，值不可复现。

## 20. 面试可能追问及回答

**Q：为什么不能用"尽力修复 JSON"来提高成功率？**
A：这是受控实验，schema validity 和 fallback rate 是研究指标。修复规则会掩盖模型不守契约的真实行为，让指标失真。宁可回退也不掩盖。

**Q：重复 key 为什么危险？你如何处理？**
A：JSON 标准建议对象成员名称唯一，但很多解析器仍会接受重复 key，且行为不一（保留首值、保留末值或直接报错），不能依赖默认行为，否则输出不可复现。我用 `object_pairs_hook` 在解析期检测重复 key，出现即失败。

**Q：未知字段为什么 fail-fast 而不是忽略？**
A：未知字段往往意味着模型越界（试图干预策略或身份）。忽略它契约会腐化；fail-fast 把越界显式暴露成指标。

**Q：调用方错误和模型错误怎么区分？**
A：解析一开始先 `build_fallback_query_plan(original_query)` 校验 original_query，非法直接抛 TypeError/ValueError。模型输出错误走 try 块转 fallback。raw_output 非 str 也显式抛 TypeError。fallback 的 query_type 由 factory 内部固定为系统专属 unknown，调用方不需要也不能提供。

**Q：fallback 的 query_type 为什么是 unknown？**
A：Planner 失败时不存在可信分类结果——模型没产出可用类型，调用方也没能力判断"这题本该是什么类型"。用任何语义类型填充都是伪造分类，也禁止用 Gold/Dev 标签填。所以 fallback 用系统专属 `unknown`，它不是模型输出类别、不属于数据集标签，且与 `PLANNER_FALLBACK` 双向强约束，不参与正常分类准确率。

**Q：fallback 为什么回退单次 BM25 而不是重试？**
A：重试把一次失败变成两次随机机会，成本/延迟/失败率不可控，无法在实验前冻结。BM25 是已知最强的简单基线，规划失败退回最保守路径最稳。

**Q：PlannerOutcome 和 QueryPlan 有什么区别？**
A：QueryPlan 是规划内容的强类型容器；PlannerOutcome 额外携带"是否 fallback"和"失败代码"两个过程元数据，并强制 normal/fallback 组合不变量。

## 21. 本任务在 Gate 3 全链路中的位置

Gate 3 任务链（设计文档 §14）：

```
G3-PLAN-03  QueryPlan 强类型契约        ✅（含 R1-MICRO）
G3-DECOMP-04A  Planner 输出边界/解析/fallback  ✅（本任务）
G3-DECOMP-04B  真实 Planner Provider + Prompt + 超时   ⏳ 下一步
G3-MRETR-05  EvidenceBundle + 多查询检索
G3-ADAPT-06  可解释 Router
G3-CORRECT-07  条件性 Corrective Retrieval
G3-EVAL-08  Dev 晋级 + 冻结配置 + 正式 holdout
G3-CLOSE-09  失败分析与 Gate 3 freeze
```

本任务交付的是 **Planner 的"输入面"**（原始 JSON → 可信 QueryPlan/fallback），04B 交付 **Planner 的"调用面"**（怎么调模型、超时、语义约束）。两者都完成后，规划环节才端到端可用。

## 22. 下一步 G3-DECOMP-04B 会增加什么

本任务**不实现**，只预留了接口与失败代码：

- **`BaseQueryPlanner` 的真实子类**：实现 `plan(original_query)` 调用真实 Provider；
- **正式 Prompt**：约束模型输出成五字段 JSON；
- **单次调用 / 超时边界**：用 `PLANNER_TIMEOUT` 捕获超时（本任务只有声明，没有超时机制）；
- **语义约束**：新增实体检查（`PLAN_NEW_ENTITY`）、比较两侧对象保持、evidence_target 正确性、语义近义重复——本任务的 Schema 无法确定性判断，04B 需要更高级的验证策略；
- **fallback 自动生效**：fallback 的 query_type 已由本任务固定为系统专属 `unknown`，04B 接入真实 Provider 后，任何解析失败都直接走 `build_fallback_query_plan(original_query)`，无需再决定 fallback 类型。

所有示例均为 synthetic；本任务未接触任何 Dev/Holdout 真实题目。
