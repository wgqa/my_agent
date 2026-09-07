# Engineering Answer ↔ Evidence Binding v1 Design

> PRODUCT-GROUNDING-21：让 completed 的 Engineering answer 不再只是"旁边
> 摆着一堆 Evidence Cards"，而是答案文本本身必须引用当前 run 的真实
> Public Evidence。本文是 Grounding v1 的设计契约；它只建立 **structural
> binding**，不声称 semantic support。产品完成路线见
> `release2_product_completion_roadmap.md`。

## 1. Problem

当前 Product 返回 `answer` + `evidence[]`，但两者之间没有 binding：系统
不知道答案的哪句话依赖 E1 还是 E2，也不知道答案是否完全没有引用任何证据。
这是结构性缺陷，不是模型质量问题。

## 2. Why the historical [C] contract is not the answer

`core/generator/citation.py` 的 `CitationValidator` 处理 G3 的
`[C1]/[C2]` 契约，绑定对象是 `EvidenceBundle`（Knowledge Retrieval 的
citation block）。Unified Engineering Runtime 的最终 public evidence 是
`E1/E2/...`（`EngineeringEvidence` / `KnowledgeEvidence`），与 [C] 编号
体系不同源。本任务不修改 G3 [C] 契约（历史仍可用），而是在
`core/engineering_verification.py` 增加 Engineering-specific 的 `[E#]`
binding validation（additive）。

## 3. E-ID truth ownership

- E-ID 唯一 owner 是 Runtime/system。Evidence 分配连续 E1..En，禁止任何
  第二套编号（C1/citation1/ref1）。
- 合法 E-ID 集只能来自 **current run public evidence**；`[E99]` 这类
  不存在的引用一律 INVALID，不忽略、不自动创建、不就近映射。
- 公共 evidence 类型保持五种：knowledge / project_code / project_doc /
  project_change / project_test。

## 4. Trusted Evidence Catalog（metadata only）

`DecisionControlState` 新增内部字段（§11/§12）：

- `available_evidence_refs`：`DecisionEvidenceReference` 序列。每项只含
  locator metadata——knowledge：`evidence_id/kind/source_name/chunk_id/
  rank`；project：`evidence_id/kind/path/start_line/end_line`。
- `citation_required_evidence_groups`：来自 frozen requirement 的
  `required_evidence_groups`，让模型知道 final answer 的引用必须覆盖哪些
  evidence groups。
- `citation_required_min_distinct_project_code_paths`：来自 requirement。

Runtime 在每轮 Decision 前从当前 `evidence[]` 确定性生成 catalog：

- seed（planned Knowledge Retrieval）的 evidence 从第一轮 Decision 起
  就在 catalog 中（不等到 ToolCall 后）；
- `read_project_context` / `git_diff` / `knowledge_search` 产生的新
  evidence 在下一轮 Decision 可引用其真实 E-ID；
- `DecisionControlState.to_dict()` 默认输出 **不变**；新字段仅在
  `include_evidence_reference_control=True` 时渲染，因此旧 Prompt
  Profile 的 rendered messages 与历史行为逐字节一致。

## 5. Untrusted evidence content boundary

绝对边界：snippet、observation_result、document content、code body、
README text 永远不进入 trusted control state。Observation 仍以 user-role
untrusted message 提供。Trusted catalog 只负责 E-ID ↔ locator metadata。
模型不得从 Observation / 用户文本中接受或推断 E-ID；只有
`available_evidence_refs` 列出的 E-ID 合法。

## 6. [E#] answer syntax

正式冻结 `[E1]`、`[E2]`…，parser 为 exact / case-sensitive 的
`r"\[E([1-9][0-9]*)\]"`；`[e1]`、`[E0]`、`[E-1]`、`[Efoo]`、`[E01]` 不算
引用。Action JSON shape 不变（`final_answer.answer` 内联引用，不加
citations 字段，不加第四种 Action）。

## 7. Cited Evidence Subset + requirement reuse

对 answer 解析出的引用（按首次出现去重）取 `cited_evidence`，再用现有
`evaluate_evidence_requirement(requirement, cited_evidence)` 评估：

- 引用子集必须结构上覆盖当前 task requirement（THEORY_CODE 需要
  knowledge + project 组合；CHANGE_TEST 需要两者都引用；cross-file 需要
  引用覆盖 ≥2 distinct project_code path）。
- Evidence 存在不等于 Answer 引用了它：只引用 [E1]（knowledge）而
  requirement 还要 project 侧 → INCOMPLETE。
- 无新算法：没有第二套 "if theory then knowledge" 判定。

## 8. Binding status

`NOT_CHECKED`（proposed_answer=None 的 pre-finalization verification）/
`NOT_REQUIRED`（无 evidence 且无 requirement，禁止制造 fake citation）/
`MISSING`（有 evidence 或 binding 要求却完全没有 `[E#]`）/`INCOMPLETE`
（引用都真实但子集未覆盖 requirement）/`INVALID`（引用了不存在的
E-ID，优先级最高）/`VALID`。`can_finalize` 变为四个正交 check 的合取：
retrieval ∧ evidence requirement ∧ 历史 citation 非 INVALID ∧ binding ∈
{NOT_CHECKED, NOT_REQUIRED, VALID}。内部新增 insufficiency reasons：
`ANSWER_EVIDENCE_REFERENCE_MISSING/INCOMPLETE/INVALID`（不进入用户
prompt 文本）。

## 9. Finalization behavior

- Binding failure（evidence 已足够时）不是 Evidence Acquisition
  failure：`recovery_allowed` 保持 false 语义，不触发 recovery、不追加
  Tool call；按现有 hard-stop 语义以
  `INSUFFICIENT_EVIDENCE_TO_FINALIZE` 终止。genuine evidence 缺失时的
  recovery 语义不变（15D 冻结行为）。
- **No second generation call**：binding 失败不会"再调一次模型请加
  citation"。citation contract 放进第一次 Decision Prompt（grounded
  profile）；真实模型是否稳定遵守由 PRODUCT-VALIDATION-22 暴露。
- 不新增 while/retry/grounding loop；grounding 只是一个额外的确定性
  finalization check。

## 10. Product assembly & prompt identity

- `api/app.py` 仅把 Engineering Product Runtime 的 prompt profile 从
  `ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_PROFILE` 切换为
  `ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_PROFILE`
  （version `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1`，
  SHA256 `c465defe7f9504d7cfb137748ba96fb90cf7bf049c7ca7a93d3f7f56945ebcdf`）。
  新 profile 继承 1200 output cap 与 1 次 parse repair。
- 历史 kind-aware profile 的 version/SHA/template 保持不变
  （SHA256 `de7a0eeb4beaea5ed93e0e4196f55b5253f73408c3e5216379aba0d8a7abd85f`），
  保留为 pre-grounding identity；Legacy `/tool-agent/query` 不受影响。
- 新模板由 frozen kind-aware 模板 + grounding suffix 派生，唯一原地修订
  是历史 "不要要求或编造 E1/E2" 规则：在新 profile 中改为"只有
  available_evidence_refs 列出的 E-ID 合法"，避免 system prompt 自相矛盾。

## 11. API / UI / persistence

- `api/schemas.py` ZERO DIFF：不加 grounding_status/claim_graph/
  citation_map；用户可通过 `answer` 含 `[E1]` 且 `evidence[]` 含 E1 验证
  最小契约。
- 请求契约不变：`/engineering/query` 只有 `question`；conversation API
  只有 `message`。Grounding 是 Product policy，客户端无权控制。
- `conversation_store.py` / `engineering_stream.py` / `ui/**` 无需改动：
  answer 内联 `[E1]` 经 SSE 分块与 SQLite 自然透传；Evidence card 本来就
  以 public evidence_id 渲染，天然闭环。clickable citation / Reference
  Drawer 不是本任务。

## 12. Structural grounding ≠ semantic support

Runtime v1 只机械验证 E-ID truth + requirement shape coverage。不分析哪
句话是 claim、citation 是否语义支持该 claim、答案是否 fully faithful。
Grounding v1 = structural answer-to-public-evidence binding；claim-level
semantic grounding 未被证明。

## 13. Known limitations

- 模型可能引用语法错误的 `[e1]`（不计引用 → 可能 MISSING）。
- 引用位置是否"紧邻 claim"只由 prompt 约束，Runtime 不检查。
- 纯 knowledge 问答要求至少引用一个 evidence（§37 最小 binding），可能
  对极简回答显得严格；这是冻结的最小契约。
- 真实 provider 是否稳定产出合法引用尚未验证（DeepSeek NOT RUN）。

## 14. PRODUCT-VALIDATION-22 handoff

下一任务用人工 User Scenario rubric 验证：真实模型在 grounded prompt 下
的引用行为、语义支持质量、以及 binding 硬停止对用户体验的影响。Fresh
scenario baseline NOT STARTED。
