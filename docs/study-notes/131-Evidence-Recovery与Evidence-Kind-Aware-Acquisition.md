# 131：Evidence Recovery 与 Evidence-Kind-Aware Acquisition

## 先区分“需要什么证据”与“怎么找证据”

Engineering Agent 不是“搜到一点相关文本就回答”的聊天器。它先要知道某个结论需要哪类公开证据：`project_code` 说明实际实现，`project_doc` 说明项目文档，`project_test` 说明测试行为，`project_change` 说明变更。这个集合是 Evidence Requirement。它是对回答资格的约束，不是给模型的可选建议。

工具则属于另一个层面。`read_project_context` 是项目代码、文档和测试的最终 public evidence producer；`code_search` 只做路径发现；`find_tests` 专门发现测试；`git_diff` 产生变更证据。把 requirement、discovery 和 producer 分开，才能避免“读到 README，却声称验证了实现”的常见错误。

## Finalization Guard 解决了什么

Finalization Guard 读取可信 Runtime control state，检查当前 public evidence 是否已经满足 Requirement。若还缺 `project_code`，它会阻止 final answer，并把缺失项通过 `finalization_blocked` 与 `missing_evidence_groups` 暴露给 Decision。这样模型不能把 Knowledge Evidence 或 project_doc 误当作代码证据，Runtime 仍是最终 hard-enforcement owner。

这一步解决的是“不能过早结束”。它没有自动保证模型下一次会挑选最合适的 discovery 参数。

## 为什么 Recovery Contract 还不够

Recovery Contract 已经要求：finalization 被阻止、工具仍可调用时，Decision 必须继续取得缺失 evidence。可真实运行仍发现一个缝隙：Repo Backend 已支持 `code_search.artifact_kind`，但模型可能省略该参数、传 `any`，甚至在缺 `project_code` 时传 `project_doc`。

因此，Backend 有 capability 不等于 Agent 会正确使用 capability。Guard 识别了“还缺代码”，Recovery 也要求“继续行动”，但 acquisition intent 没有被精确传到 Tool arguments，结果仍可能先读到文档，再因缺代码而拒答。

## 12B → 12C → 12D 如何定位问题

12B 给 Repo Evidence Backend 增加了向后兼容的 `artifact_kind`：`project_code` 过滤实现路径，`project_doc` 过滤项目文档，未提供时保持原有搜索行为。它回答了“Backend 能否提供正确候选集”。

12C 没有改变模型决策，而是把 `code_search` 的安全 intent projection 放进 Activity：只记录公开枚举的 `artifact_kind`、有限的 repo-relative top paths 和 `read_project_context` 的 evidence id。它回答了“真实运行时模型到底请求了什么”。

12D 对三个冻结 Dev case 做了一次诊断。Activity 显示：模型确实调用过 `code_search`，但没有一次以 `project_code` 作为 discovery intent；有的省略，有的选择 `project_doc` 或 `any`，随后读取项目文档，Finalization Guard 正确拒绝完成。这个负结果把问题从“过滤能力是否无效”缩小为“Decision 没有把缺失 evidence kind 映射为 Tool 参数”。

## 新的 Intent Contract

本次只新增一个窄的 Decision profile suffix。`missing_evidence_groups` 是 trusted Runtime evidence intent：当 Decision 选择 `code_search` 为缺失的 `project_code` 找路径时，必须传 `artifact_kind=project_code`；为缺失的 `project_doc` 找路径时，必须传 `project_doc`。它不是 Router 的关键词规则，也不包含具体 case、文件名或评测文本。

`project_test` 故意不借用这个过滤器：测试发现仍是 `find_tests → read_project_context`。当没有相应缺失 obligation 时，Decision 也不应为了“更保险”强加过滤器，保证普通搜索的旧语义不漂移。

## 为什么不让 Runtime 偷偷改参数

若 Runtime 看到缺 `project_code` 就改写模型的 `code_search` arguments，表面上会让一次评测更漂亮，但会破坏责任边界：Decision 记录的动作与 Backend 实际执行的动作不同，Activity 不再能解释真实决策，且 Runtime 变成第二个隐性 controller。

这里的正确分工是：Runtime 可信地发布 Requirement 与 Guard；Decision 显式选择工具及其 intent；Backend 按 schema 精确执行；Activity 只记录安全、可审计的公开投影。这样 `artifact_kind` 的使用或未使用都能被诊断，而不是被系统悄悄掩盖。

## 面试复盘怎么讲

可以按“负结果驱动的边界收敛”来讲：先说明代码与文档是不同 Evidence kind，Guard 能阻止错误完成；再说明只加过滤能力并不能让 Agent 自动选对参数；随后用安全 Activity 将失败定位到 acquisition intent；最后选择最小修复——新增一个独立 Prompt identity，把 trusted missing evidence 映射到现有 Tool schema，而不重写 Runtime、Router 或 Backend。

重点不是宣称模型已经永远正确，而是说明系统能够把一次真实失败分解为可验证的控制状态、Decision、Tool intent、Backend 结果和最终 Guard。这样后续真实回归可以检验新 profile，历史 profile 与历史实验身份仍保持可复现。
