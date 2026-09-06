# Semantic Evaluation Artifact Contract：让未来的评测有事实可评

工程 Agent 的自动指标很有价值，但它们主要描述链路状态，不等同于答案质量。一次运行显示“完成”、工具覆盖率很高，最多说明流程走到了终点；它并不能证明答案回答了用户问题、关键 claim 有证据支持，或拒答是否真正合理。要做这些判断，评测系统必须在运行当时保存有限但可信的事实。

`Semantic Evaluation Artifact` 就是这层事实契约。它不做评分，也不引入第二个 Runtime；它只把一次 VALID worker run 的公开产物固定下来：最终答案、公开 evidence、运行时 requirement state、当时已算出的 Router-vs-Gold structural match、context 的 resolved input，以及工具调用顺序。未来 scorer 再把这个 artifact 与冻结的 case oracle join，判断答案覆盖、claim 支持与拒答合理性。

## 为什么自动指标不等于语义质量

例如 `task_completion` 通常只看终态是否与期望终态一致，`required_evidence_coverage` 只看 evidence kind 是否出现，`context_resolution_correct` 曾是与冻结文本的 exact-string 对比。它们适合稳定、廉价的回归检查，却不能回答：

- 答案是否漏掉了用户要求的关键事实？
- 一条引用是否真的支持对应 claim？
- Resolver 改写后的语句与标准答案措辞不同，但语义是否正确？

因此，automatic metric 是运行信号，semantic evaluation 是随后基于公开事实进行的独立判断。两者不能互相冒充。

## 为什么必须保存最终答案

没有 final answer，评测只能看到“Runtime 是否完成”，永远看不到“完成了什么”。语义评测 artifact 允许保存 completed answer，但它只保存终态正文：不保存原始模型输出、provider response、Decision JSON、推理过程、system/full prompt 或 repair 原文。最终答案是用户可见的结果，才是判断覆盖与事实正确性的对象。

所有保留字符串仍经过已有的 `safe_artifact()` 边界。它负责拒绝敏感字段，并对绝对本地路径与 secret-like value 做统一脱敏。评测需要答案文本，不需要机器路径、凭据或隐私推理。

## Public evidence snippet 和 observation dump 的差别

公开 evidence 是 Runtime 已提升为最终 evidence 的受限事实。项目 evidence 只有 ID、kind、repo-relative path、行范围和 bounded snippet；knowledge evidence 只有 ID、source、chunk、rank、score 和 bounded snippet。这些字段足以让评分者检查“答案中的 claim 能否从公开证据得到支持”。

Tool observation 则可能包含完整匹配列表、调用参数、机器上下文或未被最终采用的内容。把 observation dump 交给评测既不必要，也会扩大泄露与误读风险。契约保留可评分证据，不复刻执行现场。

## 为什么 Runtime state 与 Gold oracle 必须分开

`runtime_requirement_state` 是产品在本次运行中实际计算出的 trusted control state；`router_gold_contract_match` 是 worker 当时已经计算好的 structural comparison。它们解释 Runtime 为什么允许或阻止 finalization，但不携带 Gold obligations、source proofs 或 expected answer。

Gold 是 evaluator 的独立 oracle。若把 Gold 混入运行 artifact，产品输出和裁判依据就难以区分，也容易让后续实现无意中依赖评测数据。正确组合是：运行 artifact 记录“系统做了什么”，冻结 case 记录“评测要求什么”，scorer 在评测层显式 join 两者。

## 历史缺失字段不能事后补造

14C 的结论是一个重要的工程纪律：历史 raw artifact 没保存完整 Runtime state 或 Router contract 时，不能根据今天的 Router、missing groups 或 Gold 倒推当时的事实。`False` 不是 `unknown`。

15A 改变的是未来：VALID worker payload 缺少答案、公开 evidence、完整 requirement state、contract match 或 context payload 时，artifact 直接 fail closed。这样下一次实验结束后，评测不再依赖猜测，也不用把历史 reconstruction 伪装成已持久化事实。

## 面试复盘说法

可以用四层结构说明这项设计：

1. Runtime 负责做决策并产生 bounded public evidence。
2. Artifact contract 负责安全、完整地固定评测需要的运行事实。
3. Frozen case/Gold 负责提供与产品隔离的评判标准。
4. Semantic scorer 只在两者齐备后评价答案质量，不反向影响产品行为。

这体现的不是“多存日志”，而是可审计实验设计：保存最小充分事实，明确不可恢复的历史边界，同时避免把 prompt、CoT、凭据和原始 observation 变成评测数据。
