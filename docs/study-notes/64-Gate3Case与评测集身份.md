# 64 - Gate3Case 与评测集身份

> G3-DATA-02A：Gate3Case 与 Gate3EvaluationSet 强类型契约（数据模型 + 严格 JSONL Loader + 稳定 evaluation_set_id）。
> 日期：2026-08-09
> 权威来源：设计文档 `docs/design/g3_query_decomposition_adaptive_retrieval.md`（§3.2 / §10.1 / §11）；实现 `evaluation/gate3/evaluation_set.py`；测试 `tests/test_gate3_evaluation_set.py`。

## 0. 这个任务建了什么、没建什么

G3-DATA-02A 只完成了 **Gate 3 评测集的数据 Schema 基础设施**：

- 三个 frozen dataclass：`EvidenceObligation`、`Gate3Case`、`Gate3EvaluationSet`；
- 严格 JSONL Loader（`load_jsonl(path, corpus)`，corpus 必须是 `ExperimentCorpus`）；
- answerability 跨字段不变量（构造前 fail-fast）；
- 稳定 `evaluation_set_id`（canonical JSON + SHA-256[:12]）；
- 76 个测试。

**没有**建：36 条真实问题、24/12 的 dev/holdout 划分、sealed holdout 内容、QueryPlan/Planner/Router/EvidenceBundle/Agent 业务实现。这些都属于后续任务（G3-DATA-02B 及之后）。

---

## 1. 为什么 Gate 2 的 RetrievalCase 不够

Gate 2 的 `RetrievalCase` 只有三个字段：`case_id`、`query`、`relevant_files`（一个排序去重的文件集合）。它表达的是"整个问题需要哪些文档"。

Gate 3 的复杂问题（comparison、multi_entity、causal synthesis）需要表达**"问题的每一部分各需要什么证据"**——这就是 evidence obligation。Gate 2 的一个扁平文件集合做不到：

- 无法表达"A 侧证据在文件 x，B 侧证据在文件 y，两侧都要"；
- 无法评估"检索到了 A 侧但漏了 B 侧"这种**部分失败**；
- 无法为每个 obligation 单独打 required/optional。

所以 Gate3Case 需要 `evidence_obligations`（结构化的 obligation 列表）+ 顶层 `relevant_files`（所有 obligation 的排序去重并集，作为总览快照）。

## 2. Evidence Obligation 与 relevant_files 的区别

- `relevant_files`（单个文件列表）：一个检索目标的证据文件集合，排序去重。
- `evidence_obligation`（一条完整记录）：`obligation_id + description + relevant_files + required`。它既描述"要找什么证据"（description），又给出"证据在哪"（relevant_files），还标注"是否必须命中"（required）。

**不变量**：answerable 时顶层 `relevant_files` 必须严格等于所有 obligation `relevant_files` 的**排序去重并集**。这不是冗余，而是数据一致性检查——防止标注者手写的总览与各部分不一致，避免"总览说覆盖了文件 y，实际没有 obligation 指向 y"。

## 3. 为什么三种 answerability 需要不同的不变量

三种 answerability 对应完全不同的评测语义，各自的字段组合约束必须独立 fail-fast：

| answerability | retrieval_required | obligations | relevant_files | decomposition_expected | query_type |
|---|---|---|---|---|---|
| answerable | true | 非空，≥1 个 required | == 并集 | （允许分解） | 不能是 unanswerable_or_no_retrieval |
| unanswerable | true | 空 | 空 | forbidden | unanswerable_or_no_retrieval |
| no_retrieval | false | 空 | 空 | forbidden | unanswerable_or_no_retrieval |

**为什么 unanswerable 的 retrieval_required=true，而 no_retrieval 是 false**：unanswerable 需要"检索一次以核实不可回答"（设计文档 §5.9），Gate 3 只记录 Planner/Router 行为，拒答正确性属于 Gate 5；no_retrieval 则要求产生**零检索调用**，所以 retrieval_required 必须为 false。两者字段约束不同，就不能共用一套校验。

## 4. 字段类型合法 ≠ 对象状态合法

单个字段通过类型检查（"`action` 是枚举""`relevant_files` 是数组"）只保证**每个字段自己合法**，不保证**字段组合后有语义**。这是设计文档 R1 反复强调的"跨字段不变量"：

- `answerable` 且 `evidence_obligations=[]`：每个字段都"合法"，但没有任何证据义务，检索无从评测；
- `no_retrieval` 且 `decomposition_expected="required"`：矛盾，一个不检索的问题不该要求分解；
- `unanswerable` 且 `relevant_files` 非空：不可回答的问题不该有"相关文件"。

所以解析器在**构造 Gate3Case 之前**先跑 `_validate_answerability_invariants`，任何违反立即抛错（带行号 + case_id），而不是等到评测阶段才暴露。这就是"字段类型合法 ≠ 对象状态合法"的工程含义。

## 5. 为什么数据顺序不应改变 evaluation_set_id

同一份评测集，如果 JSONL 里 Case 的**出现顺序**变了，评测内容并没有变——Case 集合、query、obligations 都一样。如果顺序改变 ID，那么"同一份数据"会被当成"两份不同数据"，破坏可复现性。

实现保证顺序无关的方式：

- 解析后 `cases` 按 `case_id` 排序；
- obligation 按数字编号排序（o1..oN）；
- `relevant_files` / `tags` 排序去重；
- 规范化路径统一 POSIX（`\` → `/`，折叠 `./`）；
- identity payload 用 `sort_keys=True` 的 canonical JSON。

因此反斜杠路径、字段书写顺序、文件顺序、obligation 顺序、标签顺序这些**不改变语义的差异**都不会改变 ID。

## 6. 为什么语义字段变化必须改变 ID

反过来，任何**改变评测语义**的内容都必须改变 ID。`evaluation_set_id` 是实验身份的一部分（Gate3Run 绑定它），语义变了而 ID 不变，就会把不同数据混成同一实验。

测试覆盖的语义变化都要求 ID 改变：query 改了、obligation description 改了、required 标志改了、answerability 改了、retrieval_required 改了、删掉一个 Case。这些都是"评测内容不同"，所以 ID 必须不同。

## 7. 为什么 dev/holdout 必须是两个 evaluation_set_id

sealed holdout 的隔离纪律（设计文档 §3.4）要求：实现冻结前 holdout 从未被读取。如果 dev 和 holdout 混在同一个 evaluation_set_id 里，任何基于该 ID 的实验都无法区分"我在 dev 上调参"和"我在 holdout 上作弊"。分成两个独立 evaluation_set_id，才能让 holdout 在实现冻结前保持不可见、在冻结后独立运行、原则上一生只跑一次。

## 8. frozen dataclass 与内存快照的作用

- **frozen**：构造后不可变，防止后续代码意外改坏一个 Case 或 obligation，保证评测输入稳定。
- **内存快照**：`load_jsonl` 一次性把 JSONL 读入内存并完全规范化为不可变对象，**后续评测不再依赖原文件**。之后文件被移动、修改、删除都不影响已加载的评测集；身份绑定的是规范化内存内容，而不是文件路径或 mtime。

## 9. 为什么这个任务还没有创建真实 holdout

G3-DATA-02A 只提供"容器"（强类型 Case 与评测集契约 + 严格 Loader + 稳定 ID），**真实 36 条问题、24/12 分层 split、sealed holdout 文件都属于 G3-DATA-02B**。holdout 的 Query/Gold 必须存放在用户控制目录、实现冻结前不得进入主仓库（设计文档 §3.4）。所以本任务明确不生成真实数据、不划分 split、不读取未来 holdout——先冻结数据 Schema，再谈真实数据。

---

## 关键知识点速记

- Gate 3 评测集需要**结构化 evidence obligation**（部分失败可评估），Gate 2 扁平 relevant_files 不够。
- 三种 answerability（answerable/unanswerable/no_retrieval）各有独立跨字段不变量，构造前 fail-fast。
- 字段类型合法 ≠ 对象状态合法；组合约束必须显式校验。
- `evaluation_set_id` 只绑定语义：顺序、反斜杠、字段书写顺序不改变 ID；语义字段变化必须改变 ID。
- dev 与 holdout 必须是两个 evaluation_set_id，才谈得上 holdout 隔离。
- frozen + 内存快照 = 评测输入不可变、不依赖原文件。
- G3-DATA-02A 只建了数据 Schema 基础设施；36 条问题与 sealed holdout 尚未创建。
