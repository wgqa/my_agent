# G12 Baseline A 评测 Harness

## 1. Baseline A 是什么

Baseline A 是 G12 的现状对照组：当前 production Engineering v2、当前 ToolAgentRuntime、7 个 Tool、`5 / 4 / 2` budget，以及没有 Finalization Guard 的现有行为。它不修改 Prompt，不增加 task-family 提示，也不把 Gold metadata 发给模型。

它回答的不是“理想系统应该怎样做”，而是“冻结的当前产品面对同一组题时，实际会产生什么结构性结果”。这使后续 Prompt-only Control B 或带系统 Guard 的 System C 有可比较的起点。

## 2. 为什么先做 Harness，而不是先实现 Guard

Guard 会改变 completed、refused、evidence shape 与成本分布。若没有 Baseline A，之后即使指标变化，也不能分辨是 Guard 带来改进、数据集变化，还是运行环境漂移。先冻结 case、checkout、产品身份和指标，再运行一次正式 Baseline，才能让后续比较有因果边界。

G12-03 只实现 evaluator。Finalization Guard 仍是 `NOT IMPLEMENTED`，不会由这个 runner 偷偷影响 Runtime。

## 3. Evaluator、产品与项目是三层

Evaluator checkout 包含 runner、测试、frozen case 与 Gold，用来组织一次评测。Product baseline 是 `0a1f42e8ee0320486dbd0ddc01400e1e19150501`，runner 要求 evaluator 的 `core/`、`api/`、`demo/`、`config.yaml` 相对该 commit 无差异。Project checkout 是 Agent 实际检索的工程树。

G12 使用两个 project snapshot：

| Project | Frozen commit | Bound API |
| --- | --- | --- |
| `my_agent` | `465dd65e950e9c4a119820a5a27f558e74ad5892` | API A |
| `pydantic_ai` | `bfa8e9187b86aad7ec583665ab2743fadea458b1` | API B |

两个 API 使用同一产品、Prompt、Runtime、Toolset、Knowledge corpus 和 provider/model。唯一主要差异是 `ENGINEERING_PROJECT_ROOT` 绑定的 project。runner 不启动或重启 API；它只对已经由 operator 启动的两个 endpoint 做 public preflight。`/project` 只能证明公开 project identity 和 configured source，不能伪称为 API 对 Git commit 的密码学证明；commit 由本地 checkout validation 证明，runtime binding 是 operator attestation。

## 4. Gold 为什么不能进入请求

每次 `POST /engineering/query` 的 body 精确为：

```json
{
  "question": "<frozen question>"
}
```

`case_id`、task family、required evidence groups、Gold obligations、source paths、accepted tests、label 和难度都留在 evaluator。若把它们发给模型，结果会测到 evaluator 提示而不是 Baseline A 的 product behavior。

同样，case 会根据 `project_id` 精确路由：`my_agent` 到 API A，`pydantic_ai` 到 API B，不能把 16 题都发给同一个 API。

## 5. Evidence Sufficiency 如何自动计算

G12-01 冻结 `required_evidence_groups` 为 AND-of-OR：外层每一组都必须满足，内层任一 public evidence kind 出现至少一次即可。例如：

```text
[[knowledge], [project_code, project_doc]]
```

表示至少一个 `knowledge`，并且至少一个 `project_code` 或 `project_doc`。Change Impact <-> Test 需要 `project_change` 和 `project_test`；`changed_files` 的 candidate provenance 不是 public evidence，不能替代 test behavior evidence。

当 immutable case 标记 `requires_cross_file=true` 时，还必须有不少于 `min_distinct_project_code_paths` 的不同 `project_code` relative path。两次读同一路径不是 cross-file shape。

这些都是 shape-only 指标：Runner 只观察 kind、数量、group 和 distinct path，不能自动判断 snippet 是否相关、实现是否正确、或 claim 是否真的由 evidence 支持。

## 6. Premature Finalization

冻结规则为：

```text
status == completed AND evidence_sufficient == false
    -> premature_finalization = true
```

它记录 Agent 在结构性证据不足时给出了完成答案。`refused` 和 `failed` 即使证据不足也不属于 premature finalization，它们是有效 Agent outcome，会分别进入 refusal/failure metrics。

HTTP 200 中的 `completed`、`refused`、`failed` 都是有效 product outcome。连接错误、evaluator timeout、non-200、invalid response schema 或错误 endpoint identity 才是 infrastructure failure；这会使整个 run 成为 `INVALID / INFRASTRUCTURE FAILURE`，不能得出任何 Baseline 能力结论。

## 7. Automatic 与 Manual Gold 的边界

Harness 自动统计 completion/refusal/failure、Evidence Sufficiency、premature finalization、required/forbidden Tool、evidence kind、cross-file shape、provider calls、Tool calls、iterations、errors、latency、parse/repair、duplicate-stop 和 budget-stop。L1 Transport/Parsing、L2 Planning/Tool-loop、L3 Evidence Acquisition 仅按公开结构分类；L4 Reasoning/Grounding 不自动判。

`Task Success`、`Evidence Coverage`、`Evidence Correctness`、`Claim Grounding`、remediation correctness 和 Docs semantic label correctness 都初始化为 `NOT SCORED`。run 产出的 manual review worksheet 带 Gold obligations、source proof、Agent final answer 和 evidence references，供 Reviewer 人工判断。

## 8. Provenance 与 artifact 安全

正式运行前，runner 同时验证 frozen 16-case SHA、selection SHA、candidate pool SHA、repository manifest SHA、evaluator HEAD/clean、product baseline attestation、两个 project 的 HEAD/clean/full-history/identity，以及 Knowledge 和 API public preflight。artifact 只保存 safe trace、final answer、public evidence 和 evaluator-derived structural diagnostics。

artifact validator 拒绝 evaluator/project/corpus absolute path、API key、raw provider response、private CoT 与 full prompt 字段；Markdown 中的 JSON fenced block 也按结构检查。这样 run report 可以包含 metrics 和 bounded public evidence，而不扩大泄漏面。

## 9. 为什么正式 Baseline 原则上只跑一次

Reviewer 接受 Harness 后，16-case Baseline A 原则上只运行一次。不能反复运行后挑一轮更好的结果，也不能只重跑表现差的单个 case。只有整个 run 被判定为 infrastructure invalid 时，修复基础设施后才能重新发起完整的新 run；旧 invalid artifact 必须保留。

因此 G12-03 当前状态是 `IN PROGRESS / HARNESS REVIEW PENDING`。real-provider Baseline 仍为 `NOT RUN`，Finalization Guard 仍为 `NOT IMPLEMENTED`。
