# ARCH-EVAL-08A：V7 架构整合评测协议

> 状态：ARCH-EVAL-08A-R1-MICRO = BLOCKED；ARCH-EVAL-08A-R2-MICRO = CURRENT / REVIEW PENDING<br>
> 日期：2026-08-31<br>
> 主题：Architecture Integration Evaluation Protocol Freeze<br>
> 权威资产：[evaluation/integration_v7/](../../evaluation/integration_v7/)

## 1. 这一步解决什么问题

G11 的 ToolAgent-only 主链是当时合理的最小实验面，但它把 G3/G8 的能力留在
主链之外，形成 Architecture Integration Drift。ARCH-RUNTIME-02 至
ARCH-CUTOVER-07 已按 component migration 建立统一 Runtime seam；08A 先冻结
一把可审计的尺子，回答 A/B 的架构整合是否产生真实效果。08A 是 Evaluation
Design + Dataset Freeze + Contract/Validator + Deterministic Tests + Study Note，
不是 Provider 运行或结果报告。R1 的 `ACCEPT / CLOSED` 已撤回；最终 ACCEPT
必须由独立审计作出，Agent 不得自我接受。

## 2. 当前与目标架构

架构冻结起点的实际 Engineering 主链是：

```text
Engineering request -> ToolAgentRuntime
                    -> Decision -> Tool -> Observation -> finalization

G3 Planner / QueryPlan / decomposition / adaptive / multi-query /
MinimalEvidenceVerifier       = capability islands, not this main chain
G8 Context / Standalone Resolver= capability island, not this main chain
G11 Unified Evidence + G12 Requirement/Guard = ACTIVE inputs
```

目标是一个 Unified Engineering Agent Runtime：

```text
Context Resolver -> Evidence Planner -> Execution Policy
                  -> Tool Execution Engine -> Evidence Aggregator
                  -> Evidence Verifier -> Finalization Policy
                  -> Activity / Observability
```

Knowledge RAG、Repository、Git、Test 都是 Evidence Backend，不是独立 Agent。
目标原则是 Single Engineering Agent、one trusted control state、one logical
budget owner。`ToolAgentRuntime` 迁移期可以继续执行 5/4/2，但只属于 Tool
Execution Engine，不是第二个 controller。

## 3. A/B、项目和 corpus

- System A：`0eef8ef9d6decdaa10efebe04087b06611654670`，最后一个业务代码
  ToolAgent-only pre-architecture baseline；不能替换成 G12 `0a1f42...`、System C
  或其他 Gate commit。
- System B：`385b7795eafde7c114efc382e95c0d18ec273f54`，Unified Runtime v7
  cutover baseline。
- A/B 共享 `wgqa/my_agent` 的目标项目快照 `385b779...`，独立、full-history、
  clean、read-only checkout，通过 `ENGINEERING_PROJECT_ROOT` 绑定；公开 artifact
  不写本地绝对路径。
- 共享已验证 corpus：`wgqa/agent_data` commit
  `179f18e812ad63c36c5569de8e86c5ff9a931cb5`、path
  `agent_ai_v1/02_corpus_candidate`、37 files、215 chunks、`bm25`、
  `corpus_id=870e5864df67`、manifest experiment `dbc497c796d5`。

A/B identity 记录 provider/model、Engineering/repair Prompt、toolset、5/4/2、
network retry 和 output cap；B 另外记录 Planner、Adaptive policy、retrieval
top-k/call cap、merge/RRF 和 Evidence Verifier contract。字段来自真实代码或
冻结资产，不虚构不存在的版本字符串。

## 4. Dataset freeze 与 independence

固定 9 个 family，每个 family 2 个 Dev、1 个 Holdout，共 18 + 9 = 27：

`knowledge_only`、`repo_only`、`theory_code`、`context_followup`、`change_test`、
`docs_code`、`diagnosis`、`decomposed_knowledge`、`insufficient_refusal`。

所有 case 是新 ID、新问题、新 obligations、source proofs 和 independence note；
不复用或简单改写 G12 final 16。确定性 validator 检查 exact/normalized question、
case ID、exact source-proof identity、Dev/Holdout overlap；change/test 不共用
禁止的 target commit，context 不共用 follow-up dependency，decomposition 不做
简单 rename。Holdout note 必须解释其相对 Dev/G11/G12 的独立性。

Case contract 至少包含 schema、split、family、difficulty、question、bounded
conversation context、project/corpus provenance、Gold obligations、source
proofs、required evidence groups、required/forbidden tools、path lower bound、
expected outcome 和 independence note。Context case 明确保存 history、
current_question、expected_standalone_intent；history 遵守 G8 的最多 6 条和
1200-token bound。Change/test case 另存 base/head ref 和 accepted test paths。
所有路径为 repo-relative POSIX path；每条 proof 还必须有不超过 300 字符、位于
冻结 source anchor 附近的精确 `source_excerpt`，不存绝对路径、API key、raw CoT 或
full prompt。`project_change` 必须属于真实 `base_ref..head_ref` diff 且 excerpt 来自
head 侧变更；`project_test` 必须在 head 可读、属于 `accepted_test_paths`，并以实际
断言作为 bounded proof。`decomposed_knowledge` 的 facets 用于补充人工语义完整性，
不得用重复的 `required_evidence_groups` 伪造 coverage。

R1 将 `required_tools` 限定为两套系统共有的 dynamic ToolAgent obligations，
并为每条 case 增加 `required_tools_by_system`。A 的 knowledge acquisition 可由
`knowledge_search` 覆盖；B 的 knowledge acquisition 由 planned retrieval 和
knowledge evidence metrics 覆盖，因此 B 不因正确跳过 `knowledge_search` 而丢失
tool coverage。Manifest 同时记录 A base/effective registry、B base/effective
Engineering registry 与 planned knowledge backend；B effective dynamic registry
不包含 `knowledge_search`。

## 5. 运行、指标和人工 rubric

A/B 使用相同 provider/model、项目快照、corpus、environment、question、Gold 和
适用 output cap。case 奇数按 A→B，偶数按 B→A；不能看过 A 的结果再改 B。

自动指标冻结为 task completion、required evidence coverage、tool coverage、
premature finalization、refusal correctness、context resolution、knowledge
source hit@5、retrieval call count、subquery coverage、hybrid rescue attempted/used、
merged evidence count、tool/LLM call count（context、planner、ToolAgent decision、
repair、total）、E2E/组件 latency 与 token cost。Token usage 不可得时为
`UNAVAILABLE`；retrieval call 不是 LLM call。

R1 metric semantics：`task_completion` 只从 Runtime/business terminal state
读取 `completed/refused/failed`，不自动判断 Gold semantic obligations；Task
Success 与 Answer Obligation 仍由人工评分。`required_evidence_coverage` 严格为
`satisfied required groups / total required groups`，当前 schema 不虚构
obligation-to-group mapping。`premature_finalization` 读取 finalization 时的
required-evidence/typed state；`refusal_correctness` 比较 expected outcome 与
terminal answer/refusal state，拒答理由质量仍属 manual rubric。

每 case 人工记录：Task Success `PASS/FAIL`；Evidence Correctness
`PASS/PARTIAL/FAIL`；Grounding `PASS/PARTIAL/FAIL`；O1/O2 与 aggregate；
Unsupported Claim `NONE/PRESENT`；Citation Validity
`VALID/INVALID/NOT_PRESENT/NOT_APPLICABLE`。Citation validity 只证明 citation
ID 可解析，不证明 semantic entailment；`[C1]` 有效不能推出 Grounding PASS。

## 6. 失败、污染与 Holdout

基础设施失败包括 provider outage/APIConnectionError、port/process、错误或 dirty
repo、corpus mismatch、缺少环境、artifact write failure；这些运行是 INVALID，
不产生 product result。Planner/retrieval 错误、证据不足、提前 finalization、错误
拒答、unsupported claim 是产品负例，正常进入比较。

Dev 可以诊断和验证指标。Holdout candidate SHA 必须在首次 open/run 前冻结；冻结后
不得因结果修改生产、Prompt、Router、Guard、budget、Gold 或专门制造简单 case，
否则 Holdout 不再独立。文件可在 repo 中，但默认只允许 Dev；Holdout 必须显式给出
`--split holdout --confirm-frozen-candidate <exact SHA>`。08A 不运行真实 Provider、
不打开 Holdout、不做人工评分、不生成产品结果。

R1 是 pre-run protocol repair：更新 Holdout Gold/source proof 不属于
result-driven contamination，因为 Holdout 从未执行。R2 是同一 pre-run protocol
上的 Gold semantic provenance closure，不是结果驱动修正。R0 protocol SHA
`e440ed8c32b366e99980b3b3fbd01f4325978547b929fbd6e94adec48b791f42` 已被
supersede，R1 SHA `534c0a69c817125c23cf2b1d75d60df1c3cd65dacf13844ee4b654206e313d31`
也由 R2 supersede；二者从未成为 product run/result。R2 将 project code/doc 固定在
target `385b7795eafde7c114efc382e95c0d18ec273f54`，knowledge 固定在已验证的
agent_data commit `179f18e812ad63c36c5569de8e86c5ff9a931cb5`；此前 R0 的
`...c5ff5a...` 不是有效 Git object，历史事实不改写。校验器审计 file、
tracked-at-commit、exact excerpt、historical diff/test membership 和 safe path；
语义 entailment 由 `gold_proof_audit_v1.jsonl` 的 review 记录承载，不由 validator
从 class/type 名称自动推导。

## 7. Artifact 与验证边界

`protocol_manifest_v1.json` 锁定 protocol/dataset SHA、case/family counts、A/B
commit、target commit、corpus、Prompt/Planner/Policy/Toolset/Budget identity、
metric schema、manual rubric、failure/contamination policy、Gold proof audit 和
Holdout guard。`gold_proof_audit_v1.jsonl` 对每个 case/obligation/proof 记录
`case_id`、`obligation_id`、proof locator、exact excerpt 与 `review_decision`；它是
Gold provenance，不是 Holdout 或任何产品结果。当前记录为 prepared ACCEPT，最终
independent audit sign-off 仍 pending。
SHA 对 canonical JSON 内容计算；dataset 或 manifest 发生 mutation 时 validator
fail closed。未来结果 artifact 必须带 system/target/corpus/case/metric/rubric/
failure provenance，且不得带绝对路径、credential、raw provider/model output、
private reasoning 或 full prompt。

## 8. 面试两分钟讲法

“G11 用 ToolAgent-only 是有意的最小化：先验证 bounded tool safety、Engineering
evidence transfer 和 failure semantics，不把 Gate 3 的另一套 AgentRuntime 混进
变量。它是临时简化，不是最终架构。现在不回滚或复制 Gate 3，而是把 QueryPlan、
decomposition、adaptive retrieval、multi-query merge、G8 context 和 verifier
作为 component 接到一个 Unified Engineering Agent Runtime。最关键的约束是一个
trusted control state 和一个 logical budget owner；ToolAgentRuntime 只继续做
5/4/2 execution component，不能再套成第二个 controller。ARCH-EVAL-08A 先冻结
全新的 27-case A/B protocol、项目和 corpus identity、自动指标、人工 rubric、
污染规则和 Holdout deny-by-default，之后才有资格讨论效果；本阶段没有 Provider
结果，也不把结构化 evidence sufficiency 说成完整语义正确性保证。”

## 9. 复习要点

1. G11 ToolAgent-only 合理但临时；
2. G3/G8 不永久丢弃，也不复制成第二个 Agent；
3. Evidence Backend 不拥有 Agent/controller 身份；
4. 一个 trusted control state、一个逻辑 budget owner、一个 finalization；
5. Protocol freeze 先于真实 A/B，Holdout 默认拒绝；
6. Citation validity、evidence coverage 与 semantic grounding 必须分开表述。
