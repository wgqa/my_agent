# Hybrid 架构收敛真实验收结果

## 结论

**保留收敛后的实现作为候选；当前不正式替换稳定 Agent 基线，也不合并 main。**

本轮完整正确交付初判为 **17/28（60.7%）**，Task022 Hybrid 为 10/28（35.7%）、B0 为 12/28（42.9%）、B2 为 8/28（28.6%）。消除了 Planner 硬契约早失败，复杂任务恢复明显；但 Typed 保留了 3/4，仍有提前结束、无来源主张和错误拒答。收益不是仅增加 completed，当前安全与稳定性仍不足以直接上线。

评分是逐题阅读最终答案、真实工具返回和引用材料后的 **Codex 开发者来源核对（非盲）**，没有独立人工或盲审授权，不冒充人工验收。次要措辞存在争议的 mix-01/02/03 已在逐题依据中标记，最终采用前应由项目所有者复核。

## 固定身份与执行

- 来源：Task022 业务 `afa384668e00401385b5cc2084d4e515b73474da`，交付 HEAD `ea1a83fe6c66a0a0924446bd6f6974fd2eb7f7af`。
- 分支：`experiment/hybrid-convergence`；工作区：`D:\学习\rag实战项目\rag-knowledge-base-hybrid-convergence`。
- 实测实现提交：`12c6fe93ef078b7a1957f11664aef562da4ab21a`。
- 业务指纹（108 文件）：`4237a411387914dac9cd6a97bf1cccfd26555593e4e3551c14052f58b934c6ee`。
- run_id：`hybrid-convergence-20261015-001`；真实请求 UTC 起止：2026-10-14T18:48:26Z → 2026-10-14T18:52:27Z。
- 原始记录：`D:\学习\rag实战项目\_hybrid_convergence_results\hybrid-convergence-20261015-001`。7 个原始产物 SHA 已核验，无覆盖历史结果。
- 原 28 题、顺序、分类、判据逐项与 Task022 Manifest 一致；三个真实 Git fixture 与知识 DB/5 份语料 SHA 完全一致。语料 identity.verified=false 保留，文件哈希核验不升级该字段。
- 模型请求/响应均 deepseek-flash，Thinking disabled、temperature=0、SDK retries=0；88 个响应 fingerprint 均为 `aeb56401ca74e127821c4f9126dcb669`。这不是模型权重版本证明。
- Agent 保持 5 Decision / 4 ToolCall / 2 ToolErrors / 60 秒；28 Planner + 58 Decision + 2 原生 Decision repair，独立 Selector/Reviewer/新规划调用为 0。
- 本轮为新时间段的单次运行；B0/B2/Task022 是历史参考，不能称同时同条件配对或统计显著的提升。

## 实际修改

知识 Planner 继续使用原五字段协议，只负责检索；converged_hybrid 不要求 task_contract，不调用 to_requirement，也不将模型推断的 operation/object_kind/子查询数量变成硬约束。旧策略和 Router v5 源码保留供对照。

旧 Router 的 profile 保留在记录中。当前硬检查在原 Verifier 接缝根据原始用户请求处理明确的知识材料、路径正文和 diff 缺口；按实际文件类型使用代码、文档和测试正文，不统一折算成 project_code，也不规定固定源码数量。来源与执行预算保留，开放式回答不调用旧自然语言 Binding 作终态裁判。

Typed 仍由原 Decision 的 changed_files_finalization 选择，检查本次成功 Observation、参数/结果摘要、项目 E-ID、明确 Git refs/working_tree、状态和指定路径/文件类别，然后确定性渲染。没有新增 Selector 模型调用。部分清单保留未穷举标记；未执行测试不能被记为执行成功。

在同一 Loop 中，对明确材料缺口的过早 final/refuse 保留一次预算内补证机会。有限自然语言交付可携带 limitations，程序展示未完成事项；can_finalize 只代表允许交付，task_coverage 保守标记 complete/partial/unknown，semantic_correctness 恒为 not_evaluated，外部评分独立。

修改文件：

- `core/unified_engineering_runtime.py`：选择收敛策略，将原始问题传给现有 Verifier。
- `core/engineering_verification.py`：保留历史路径，收敛模式取消模型推断的硬合同和子查询硬覆盖，核对明确材料及 Git 范围。
- `core/tool_agent/runtime.py`：原 Loop 中使用来源校验、直接 Typed 和有限交付，未重写执行器。
- `core/tool_agent/changed_files_typed_finalization.py`：按用户明确范围/筛选/对象检查和渲染，旧模式行为保留。
- `core/tool_agent/decision_prompt.py`：仅给收敛策略追加取证/有限交付指导，既有模型调用复用。
- `core/tool_agent/actions.py`、`runtime_models.py`：兼容 limitations 与交付/覆盖/语义三种状态。
- 既有 `evaluation/task018_e2e/live_e2e_runner.py`、`fake_e2e_probe.py`：增加现有 28 题的单候选模式和诊断字段；未新增 Runner、平台、Gold 或评分器。
- `tests/test_hybrid_convergence.py`：35 项新增离线测试。

源码 Diff（相对 Task022 交付 HEAD，代码冻结时）：

```text
core/engineering_verification.py                   |  76 +++++++
 core/tool_agent/actions.py                         |   8 +
 .../tool_agent/changed_files_typed_finalization.py |  41 +++-
 core/tool_agent/decision_prompt.py                 |  27 ++-
 core/tool_agent/runtime.py                         | 140 ++++++++++--
 core/tool_agent/runtime_models.py                  |  15 +-
 core/unified_engineering_runtime.py                |   4 +-
 evaluation/task018_e2e/fake_e2e_probe.py           |  11 +-
 evaluation/task018_e2e/live_e2e_runner.py          |  42 +++-
 tests/test_hybrid_convergence.py                   | 236 +++++++++++++++++++++
 10 files changed, 570 insertions(+), 30 deletions(-)
```

## 离线验证

- 最终必要回归：**159 PASS / 0 FAIL / 0 SKIP / 1 deselected**；含 35 新增项、旧 Hybrid/Task021/Typed/Requirement/Verifier/Unified 及费用/身份守卫测试。
- 1 项 Task019 专用 live_preflight 身份测试曾因本分支不是 Task019 而失败，未改它或降低身份条件；最终套件排除，并单独以本轮 configure_convergence 的实际身份入口核验通过。
- 开发期间 1 项新增测试使用错误日志字段名引发 KeyError，修正测试读法后通过，未修改业务或评分迎合。
- Fake 实际产品装配经 Planner → 原 Agent Decision → 真 Git/Reader 工具 → Evidence → Typed/自然语言 final 跑通；假 HTTP 请求验证 Flash/Thinking disabled。Fake 成功不计入真实 28 题。
- 正反例保留错误 E-ID/结果摘要/Git scope/状态/对象/路径、未执行测试、locator 冒充实现、截断集合、开放分析误选 Typed 等阻断。

## 总体质量

| 版本 | 完整正确 | 有用部分 | 错误交付 | 未交付 | 完整正确率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 历史 | 12 | 3 | 2 | 11 | 42.9% |
| B2 历史 | 8 | 2 | 2 | 16 | 28.6% |
| Task022 Hybrid 历史 | 10 | 2 | 3 | 13 | 35.7% |
| 本轮收敛 Hybrid | 17 | 3 | 3 | 5 | 60.7% |

Runtime completed 为 23/28，但其中 3 条错误交付、3 条有用部分；只认 17 条完整正确。Runtime coverage 为 3 complete / 18 partial / 7 unknown，不直接用于语义通过率。许多 limitations 只是未执行用户未要求的测试，因此也不能反向把所有 partial 标记当成真实任务未完成。

## 用户指定重点

- 原 8 个 Planner 早失败：**8/8 不再前置失败**，全部进入 Decision；其中 **6/8 完整正确**（ga-02、ga-03、src-01、xt-03、xt-04、mix-01）。ev-01 取得不存在错误但无 E-ID 被误拦；ev-04 合理保留无测试执行能力的拒答。
- Git 状态 Typed：**3/4 完整正确**，无 Typed 错误交付；gs-02 未执行 changed_files 即选 E1，正确阻断，但从 Task022 完整交付回退。
- 12 个复杂任务：B0 **7/12**，B2 **5/12**，Task022 Hybrid **1/12**，本轮 **9/12** 完整正确；仍有 ga-01 错误推断、ga-04 误选终态和 xt-01 遗漏常量。
- 已取得可交付材料却误拒：本轮确认 **1 条 ev-01**，历史 B0/B2/Hybrid 为 7/10/3。gs-02、ga-04 属 Agent 终态策略错误，不能算材料齐全后的 Gate 误拒。
- 未执行 pytest 的 ev-02/ev-04 均拒答，无编造通过数。ND 的总数含这些合理拒答，不从 28 的分母剔除。

## 各类别完整正确（每类 4 题）

| 类别 | B0 | B2 | Task022 Hybrid | 本轮 |
| --- | ---: | ---: | ---: | ---: |
| git_status | 0/4 | 0/4 | 4/4 | 3/4 |
| git_change_analysis | 3/4 | 0/4 | 0/4 | 2/4 |
| source_location_and_explanation | 3/4 | 2/4 | 3/4 | 3/4 |
| cross_file_and_test_analysis | 0/4 | 1/4 | 1/4 | 3/4 |
| rag_question_answering | 2/4 | 1/4 | 1/4 | 1/4 |
| rag_and_code | 4/4 | 4/4 | 0/4 | 4/4 |
| insufficient_evidence_and_refusal | 0/4 | 0/4 | 1/4 | 1/4 |

## 逐题对照

CC=完整正确；UP=有用部分；WD=错误交付（含关键主张来源不支持）；ND=未交付。具体原文、候选、Observation 和 E-ID 见 HYBRID_CONVERGENCE_ACTUAL_ANSWERS.md。

| Case | B0 | B2 | Task022 Hybrid | 本轮 | 实际工具 | 核对结论 |
| --- | --- | --- | --- | --- | --- | --- |
| t22_gs_01 | ND | ND | CC | CC | changed_files | E6 来自完整 commit_range changed_files；五项路径/状态及 rename 方向均与真实 Git 一致。 |
| t22_gs_02 | ND | ND | CC | ND | 无工具 | 第一次 Decision 即提交 filter_status=deleted、E1，未调用 changed_files；E1 实为知识证据，Runtime 正确阻断。属于过早结束，不是材料已足够后的 Gate 误拒。 |
| t22_gs_03 | ND | ND | CC | CC | changed_files | 真实 changed_files 的 E6 和 100% rename 状态支持 old_parser.py → new_parser.py，方向正确。 |
| t22_gs_04 | ND | ND | CC | CC | changed_files | 真实 working_tree 的 E6 仅有 notes/local_sample.md untracked，完整性和范围正确。 |
| t22_ga_01 | CC | ND | WD | WD | changed_files | 仅有 E5 status_list，未取任何 diff；却称 rename 会牵动 main.py 调用方与测试、删除为清理。实际为纯 rename，main.py 无该依赖。后附限制未消除这些过宽主张。 |
| t22_ga_02 | CC | ND | ND | CC | changed_files → git_diff | E5 实际 main.py diff：LIMIT 10→12、函数体不变；数值影响推导正确，未把静态推导称作实际执行。 |
| t22_ga_03 | CC | ND | ND | CC | changed_files → git_diff → git_diff | E7 usage 新增正文与 E8 main.py diff 均取得；新增文档、常量变化及有限关联说明正确。 |
| t22_ga_04 | WD | ND | ND | ND | changed_files | 调用 changed_files 后误选 list_all Typed 终态；本题要求分析全部影响，Typed 正确以 TASK_REQUIRES_NON_STATUS_ANSWER 阻断。 |
| t22_src_01 | ND | ND | ND | CC | code_search | E6 实际 code_search 命中 src/main.py:3；只交付定义文件和行号，满足原问。Runtime 的 partial 是保守标记，不代表本题实际未完成。 |
| t22_src_02 | CC | CC | CC | CC | read_project_context → read_project_context | E6 完整 scale 定义，E7 实际 LIMIT=12 声明；函数乘法与常量均解释正确。 |
| t22_src_03 | CC | CC | CC | CC | code_search → read_project_context | E7 完整 parse 定义，strip 后 lower 的步骤准确，未宣称执行成功。 |
| t22_src_04 | CC | UP | CC | UP | read_project_context | 只读 scale 的两行定义，未取得 LIMIT 声明；诚实给出 3×L，但未交付用户要的常量和确定返回 36，预算仍可读取。 |
| t22_xt_01 | UP | CC | ND | UP | code_search → read_project_context → read_project_context | E6 scale 与 E7 test_scale 已读，但遗漏 LIMIT；只能给出一致性的条件，不能确认实际一致。E4 理论引用也不直接解释断言机制。 |
| t22_xt_02 | ND | ND | CC | CC | find_tests | E6 为真实 find_tests：tests/test_main.py:1、filename_match；只说明候选位置，未升级成覆盖或执行证明。 |
| t22_xt_03 | UP | ND | ND | CC | changed_files → git_diff | E4 状态与 E5 真实双路径 diff 为 similarity index 100% 纯 rename；内容未改变和 old/new 状态解释正确。 |
| t22_xt_04 | ND | ND | ND | CC | read_project_context | E6 为完整两行测试文件，断言 scale(2)==24；无 import/实现/执行证明等边界说明正确。 |
| t22_rag_01 | CC | CC | CC | CC | 无工具 | E1 的固定评测原则及 E3 的 parser/chunker/embedding 版本与索引信息支持回答；子查询缺命中没有替代原始交付义务。 |
| t22_rag_02 | WD | WD | WD | WD | 无工具 | 检索 E1/E2 主要为面试自检问题，未定义具体 verification 的语义保证；却称通过验证能推出陈述内容匹配/合理蕴含。沿用 Task022 对此歧义题的保守来源判据。 |
| t22_rag_03 | CC | WD | WD | WD | 无工具 | 三种处理原则本身常见，但 E1 仅列更新/删除自检问题，未提供跳过、重分块、删向量步骤。将这些核心步骤作为该引用支持的答案，缺乏实际材料支撑。 |
| t22_rag_04 | UP | UP | UP | UP | 无工具 | E1 支持 Mock/Stub 区别，行/分支覆盖检索无匹配；如实保留缺口，未完成第二子任务。原语料有相关内容，属于检索覆盖问题。 |
| t22_mix_01 | CC | CC | ND | CC | read_project_context | E3 实际 parse 源码与 E1 Function Calling 执行循环资料取得；步骤和静态读取不等于执行成功的区分均正确。附加纯函数表述需避免外推到任意 data 类型。 |
| t22_mix_02 | CC | CC | UP | CC | code_search → read_project_context | E4 测试语料 12 秒、E6 完整代码 LIMIT=12 与 scale 均有真实来源；最终明确否认数字相同能证明配置关系。支持该猜测的弱依据段落不宜视为真实配置证据。 |
| t22_mix_03 | CC | CC | ND | CC | read_project_context | E6 真实断言配合 E1/E2 单元测试资料，测试意图与未执行不能宣称通过的核心边界正确；尾段把源码阅读与实际执行条件并列，表述仍需人工复核。 |
| t22_mix_04 | CC | CC | ND | CC | read_project_context → read_project_context | E4 实际 usage 文档、E5 完整 main 代码取得；E1/E2 知识身份与仓库身份分开，未声称全仓已实现元数据要求。 |
| t22_ev_01 | ND | ND | ND | ND | read_project_context | Reader 返回 PROJECT_CONTEXT_FILE_NOT_FOUND；模型给出正确且有限的不存在说明，但没有可引用 E-ID，CURRENT_RUN_EVIDENCE_REFERENCE_MISSING 误拦。 |
| t22_ev_02 | ND | ND | ND | ND | 无工具 | 无测试执行工具，模型 UNSUPPORTED_REQUEST；正确保留能力边界，没有伪造通过数量。 |
| t22_ev_03 | ND | ND | CC | CC | 无工具 | E1 明示本地测试夹具，E2 是通用重试原则；明确不能确认生产 12 秒配置，满足该证据不足题的边界要求。 |
| t22_ev_04 | ND | ND | ND | ND | 无工具 | 没有 pytest 执行记录/能力，模型 UNSUPPORTED_REQUEST；不将测试源码或候选当作执行结果。 |

## 回退和风险

相对 Task022 原完整正确的案例回退：t22_gs_02, t22_src_04；相对 B0：t22_ga_01, t22_src_04, t22_rag_03；相对 B2：t22_xt_01。

- gs-02：模型未取状态材料即结束，程序未错误放行；src-04、xt-01：工具和预算仍可补常量，却提前给出有限内容。说明解除硬合同不能保证自主补证，尤其 limitations 不应成为过早结束的便利出口。
- ga-01：来源真实但解释错误，引用身份和后附限制不能修复未经读取 diff 的重要性/依赖关系推断。
- rag-02/03：存在真实 E-ID，但资料是自检问题而非结论/步骤，程序没有语义蕴含能力。未引入在线 Reviewer，也不宣称轻量来源校验能防止所有幻觉。
- ev-01：真实错误 Observation 没有正式 E-ID，正确否定答复仍被拒；属于确定的剩余误拒。
- 源码义务的有限词面检查尚不覆盖所有自然语言：src-01 原问“不需要解释实现”仍可被 body 检查命中，模型以 limitations 有限交付实际完成定位。若去掉 limitations，存在额外正文误要求风险；不能把本轮结果当作通用语义任务识别已解决。
- partial 标记是保守的交付状态，不足以证明无法继续取证或用户义务全部满足。本次真实发现后未改 Prompt/业务重采样，保留同一冻结对象。
- mix-01 的纯函数描述只宜限定输入字符串；mix-02 的同数值猜测不应作为配置证据；mix-03 末段应进一步分清源码阅读和实际执行各能证明什么。初判依据任务的关键事实，保留这些表述风险供人工复核。

## 请求、Token、费用与时间

| 版本 | Provider 请求 | 总 tokens | 软件估算 US$ | 平均请求/题 | 平均产品耗时秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 历史 | 94 | 493,112 | 0.1613202 | 3.36 | 5.38 |
| B2 历史 | 99 | 545,043 | 0.1766880 | 3.54 | 5.43 |
| Task022 Hybrid 历史 | 77 | 439,905 | 0.1437687 | 2.75 | 4.48 |
| 本轮 | 88 | 516,866 | 0.1669866 | 3.14 | 4.80 |

本轮 input=503,614、output=13,252；Provider 总延迟 128.68s，产品总耗时 134.31s（不含每题子进程启动开销）。无单独 Selector 请求。

相对 Task022 Hybrid 请求 +11、tokens +17.5%、估算费用 +16.1%、产品耗时 +7.2%，同时恢复了原来的早失败；这不是新增模块本身开销的净因果估计。相对 B0 总请求更少，tokens +4.8%；相对 B2 请求和 tokens 均较少。时间差还受非同期服务/缓存状态影响，不作严格性能因果声明。

价格依据已复核 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：为可比性继续按峰时 cache-miss 输入 $0.30/M、输出 $1.20/M 保守估算，cache hit 也按 miss 计；不是实际账单。授权限额 196 请求 / 750,000 tokens / US$0.30，全部未触发，billing_unknown=false、pending=0、零 SDK 重试、零任务重跑。

## 采用决定

解除前置全局硬契约值得保留，Typed 的封闭事实交付也继续有效；本轮真实完整正确率与复杂任务表现改善，因此不建议回到 Task022 的全局硬契约。**但当前收敛版不应直接升级为稳定默认架构**：仍有 Typed 回退、可继续取证时提前 partial、可核验否定事实误拒及来源真实却推断错误的问题。稳定发布暂保持既有经过确认的基线，本分支和实测结果作为候选保留。没有自动合并、上线或追加实验，任务到此停止。
