# G11-03：Change Impact 与测试推荐工作流

## 1. Change Impact Analysis 是什么

Change Impact Analysis 不是“改了哪个文件”的文件名摘要，而是从一个真实 Git change 出发，判断哪些行为可能受到影响、哪些测试是合理候选、测试源码实际验证了什么，以及基于这些证据应该推荐什么回归测试。

当前 G11-03 首先做 transfer validation：验证已经通过 G11-02 Formal R6 的通用 Engineering Prompt v2、现有七个只读 Tool 和 5/4/2 Runtime budget，能否迁移到第二个 task family。它不新增 Change Impact 专用 Prompt，也不把一次实验结果包装成新的产品能力。

## 2. 当前工作流

v2 的主链路是：

```text
Change
  -> changed_files
  -> git_diff
  -> Impact
  -> Test Candidate
       | accepted test already in changed_files
       | otherwise find_tests
  -> read_project_context
  -> Test Evidence
  -> Test recommendation
```

三个 required Tool 与一个 optional candidate Tool 的职责不同：

- `changed_files` 先确认 commit range 中实际变化的 repo-relative path 和 change status。
- `git_diff` 读取一个已经定位的文件的 bounded unified diff，提供变更事实。
- `find_tests` 在 accepted test 未出现在 change set 时，从 source path 发现候选测试 path、anchor line 和稳定 reason；它只定位，不判断覆盖。
- `read_project_context` 读取候选测试源码窗口，才把测试内容变成可审计的 `project_test` evidence。

因此回答必须分层：A 是 Git 实际改了什么；B 是基于 diff 可以合理判断的行为影响；C 是工具发现的 candidate；D 是为什么推荐某个测试；E 是测试源码中的哪个断言或场景真正支撑该推荐。

## 3. 为什么不能只看 changed filename

文件名只能提供路径和命名信号，不能证明调用关系、参数流、分支行为或测试断言。一个 `runtime.py` 可能对应多个测试，一个测试也可能通过 fixture、API 或共享 helper 间接覆盖多个模块。反过来，名称相似的测试也可能只验证初始化、错误路径或无关行为。

所以 `changed_files` 暴露的路径和 `find_tests` 的结果都只能称为 candidate。只有后续 `read_project_context(test_path, anchor_line)` 读到真实测试源码，才能说明测试实际构造了什么输入、断言了什么结果，以及它和变更风险之间有什么证据联系。

## 4. Git diff 是事实，Impact 是工程判断

`changed_files` 和 `git_diff` 给出的是仓库历史中的可复核事实：哪个 commit 的哪个文件发生了什么行级变化。Impact 不是 Git 自动返回的字段，而是基于这些变化、上下文和产品契约进行的工程判断。

例如，legacy response 重新对可见 evidence `enumerate(..., 1)`，diff 可以证明编号生成方式；“这是为了避免 Knowledge Evidence 占用 E1 后让 legacy response 从 E2 开始”是基于 endpoint 可见性和兼容契约的影响分析。它必须与 diff evidence 分开表达，不能把推断伪装成 Git 输出。

## 5. 为什么 `git_diff` 必须 bounded

Git diff 可能包含大量新增文件、生成文件、二进制内容或重复上下文。Tool 必须同时限制 capture bytes、输出字符数和输出行数，并且只返回安全完整的记录。bounded contract 保护 Runtime 的上下文预算、响应延迟和 artifact 大小，也避免把不可控仓库内容直接送入模型。

`changed_files.total_count` 在 `truncated=true` 时只代表安全观察到的变更数量，不是完整仓库变更总数。`git_diff.truncated=true` 时只能说明返回内容达到边界，不能假装模型看到了完整 diff。

## 6. `truncated` 不等于 Git command failure

底层 capture 主动达到资源上限时，进程可能因为被终止而返回非零 code，但这不等价于 Git 命令本身失败。实现必须保留已经安全解析出的完整 path/record 或 diff prefix，并把结果标记为 truncated。

真正的 Git command failure 是另一类错误：命令在未被 capture 截断的情况下返回非零 code。两者不能混淆，否则 Agent 可能把“已经拿到的部分事实”丢掉，或者把半截 path 当作完整变更记录。

## 7. `find_tests` 的三个 reason

`find_tests` 的 candidate reason 是确定性的定位信号：

- `mirrored_path`：例如 `src/main/java/a/b/Foo.java` 对应 `src/test/java/a/b/FooTests.java`。
- `filename_match`：源码 stem 与测试文件名有 lexical 关系。
- `content_reference`：候选测试正文出现源码 stem。

reason 可以组合，并按固定优先级和 repo-relative POSIX path 排序。它们分别说明目录镜像、文件名关系或正文引用，不表示测试一定执行到了被修改分支。

## 8. 为什么必须再读取 test source

`find_tests` 不返回测试正文，也不产生 `project_test` evidence。读取测试源码后，Agent 才能确认测试使用了什么 fixture、调用哪个 endpoint 或 handler、断言哪些字段、是否覆盖异常边界，以及它是否真的对应当前变更。

这也防止一个常见错误：仅凭 `tests/test_git_change_tools.py` 这个文件名就声称它已经覆盖了所有 Git truncation 风险。真正的依据必须来自测试中的具体断言，例如 bounded chars/lines、safe prefix、observed name-status records 或 real Git failure 的稳定 error code。

## 9. `project_change` 与 `project_test` 证据链

一个完整的 Change/Test chain 至少包含两类证据：

```text
project_change
  = bounded git_diff 证明实际变更

project_test
  = read_project_context 证明测试源码中的场景/断言
```

二者同时出现只能证明 change evidence 和 test evidence 都被读取，不能自动证明影响推理正确，也不能自动证明测试已经执行通过。Runner 只计算 evidence kind、Tool coverage、sequence 和 completion；影响分析、推荐理由和 claim-level 支持仍由人工 Gold review 判断。

## 10. 四个固定 case

G11-03 固定使用真实历史验收 commit，并把 `base_ref` 固定为 `<target_commit>^`、`head_ref` 固定为 `<target_commit>`：

| Case | Target commit | Focus path | Primary test candidate |
|---|---|---|---|
| CI01 | `465dd65e950e9c4a119820a5a27f558e74ad5892` | `api/app.py` | `tests/test_engineering_agent_api.py` |
| CI02 | `766a836a6728dc7fd4f4f22e9ec8a2387758c5a9` | `core/engineering_knowledge.py` | `tests/test_g11_02_r4_knowledge.py` |
| CI03 | `129175ec422b88677b48c0c5d5997a1a8f229b92` | `core/tool_agent/decision_prompt.py` | `tests/test_g11_02_r5_budget_control.py` |
| CI04 | `23073a5aa6471b2e671385907108008253788dba` | `core/tool_agent/tools/git_change.py` | `tests/test_git_change_tools.py` |

CI01 检查 legacy evidence 编号兼容性；CI02 检查 verified Knowledge backend 的身份与文件真实性边界；CI03 检查 Budget-Aware Decision Guidance 如何把 Runtime-owned control state 送入 Engineering v2 policy，以及它与 hard budget 的关系；CI04 检查 bounded Git output、truncation 和真正 command failure 的区分。

### Benchmark 可执行性也是评测契约

Gold obligation 必须在当前 Tool 能力范围内可达。v2 在进入 Formal 前，由 `tests/test_g11_03_change_impact.py` 用真实 Git 执行每个 target commit 的 `<head>^..<head>` name-only diff，确认 accepted test path 确实在 change set 中；测试 candidate 也可以在 unseen 情况下由真实 `find_tests` 提供。这不是 mock，也不把 Gold test 人为塞进 Tool 输出。

如果 accepted test 不在 change set，benchmark 必须要求 Agent 调用 `find_tests`；如果 accepted test 已经由 `changed_files` 显式暴露，强迫 `find_tests` 就是人为步骤。Tool 正确返回 no candidate 不能被误判成 Agent reasoning failure；这属于 evaluation design error。CI03 的 focus 是 target commit 中真实 changed 的 `core/tool_agent/decision_prompt.py`，四个当前 historical case 则都由 changed-files proof 满足 candidate-source contract。

## 11. 为什么推荐测试不等于执行测试

本 workflow 的输出是 evidence-grounded test recommendation。Agent 可以根据 diff 和测试源码说明“应该优先回归哪个测试，以及它覆盖哪一个风险”，但它没有运行 pytest、Maven、Gradle 或其他测试命令。

执行测试需要独立的命令、环境和结果 provenance。把推荐写成“测试已通过”会混淆静态证据与动态执行证据，也会让用户错误地认为风险已经被验证。

## 12. 5/4/2 budget 下的紧凑链路

Runtime 仍冻结为 5 iterations / 4 Tool calls / 2 Tool errors。三个 required Tool 在 changed-files candidate 路径下可以在五轮内完成；若 test 未出现在 change set，第四个 optional `find_tests` 才进入链路，然后读取 test source，最后输出 final answer。`find_tests` 是否出现不是唯一正确 sequence。

该预算控制的是执行边界，不是答案正确性证明。模型不能通过输出修改 `DecisionControlState`，也不能扩大 Tool calls；v2 的 trusted control state 只是让模型知道剩余能力，Runtime hard enforcement 仍是最终边界。

## 13. 与 G11-02 Theory ↔ Code 的区别

G11-02 连接 Knowledge Evidence 与 Repository Evidence，回答理论、当前实现和二者差异；其固定跨源链路通常包含 `knowledge_search`。G11-03 连接 Git Change Evidence 与 Test Evidence，回答变更影响和测试建议；四个 case 不应调用 `knowledge_search`，因为 Gold 来自真实 commit diff 与真实 test source，而不是通用理论知识。

两者共享 Engineering Agent、Production Prompt v2、七个 Tool、Repair v1 和 5/4/2 budget，但 task family、required Tool contract 和 evaluation obligations 不同。G11-03 首先验证这套通用控制面能否迁移，不以新增 Prompt 解释差异。

## 14. 面试表达

可以这样说明：

> Agent 不是凭测试文件名或经验猜影响。它先用 `changed_files` 和 bounded `git_diff` 固定 Git 事实；如果测试路径已在 change set 中就直接读取，否则用 `find_tests` 找候选，最后用 `read_project_context` 读取测试源码。最终回答把 diff、合理影响、candidate、测试断言和推荐理由分开；推荐测试不等于测试已经执行。

## 15. Transfer validation 边界

G11-03-02 在保留 G11-03-01 runner safety 的基础上，新增 profile-scoped output capacity 与 evaluation contract v2；不修改 Prompt text/SHA、Tool implementation/schema、Knowledge backend、Evidence schema、budget、registry 或 `find_tests` 算法。

Runner 会记录 prompt/repair identity、source checkout、target commit/ref、toolset、budget、safe trace、per-case evidence 和 summary metrics，但不会记录 raw provider output、API key、CoT 或本机绝对路径。Formal DeepSeek 四 case 由用户在同一 real-provider 环境中显式运行；本任务不自动运行 Formal，也不提前判断 Gold correctness。

## 16. Artifact Safety 与 Serialization Boundary

semantic payload != serialized representation。JSON/JSONL 的安全校验必须先反序列化，再递归检查 string leaf；否则 JSON 对普通 literal backslash 的转义可能被 raw-text 扫描误报为 UNC path。Markdown 不是 JSON，因此保留文本层的 repo-root、实际 drive/UNC path 和 secret 防护，但 UNC 也必须满足真实 \\server\share 形状，不能看到任意 \\ 就拒绝。

安全验证不能简单关闭，而应放在正确的 serialization abstraction layer。首轮 Formal run g11-03-change-impact-formal-20260823-235907 因 runner 的 artifact safety serialization false positive 判为 INVALID / INFRASTRUCTURE FAILURE；这是 runner infrastructure 结果，不作 Agent 结论。R2 后正式实验仍需生成新的 run_id。

## 17. Path Detection Requires Lexical Boundaries

URL scheme 和 Windows drive path 共享部分表面语法：http:// 中的 p:/、https:// 中的 s:/ 看起来像 drive prefix。若 regex 在字符串任意位置 search，合法 endpoint 就会和 C:/ 本地路径发生 lexical collision。正确做法是给 local-path token 加左边界，例如 drive prefix 前不得紧邻 ASCII 字母或数字；这样字符串开头、空白、标点或等号后的 C:/ 仍会被拒绝。

这不是把整个 URL whitelist 为安全值。URL query 或 fragment 中若出现 path=C:\\secret.txt，真正的本地路径 token 仍必须被拒绝；修复的是 path token boundary，而不是 endpoint 类型的绕过。第二次 Formal run g11-03-change-impact-formal-rerun-20260824-003342 因 URL scheme substring misclassified as Windows drive path 判为 INVALID / INFRASTRUCTURE FAILURE，同样不作 Agent 结论。

## 18. Formal R3：Valid Negative Result 与 Evaluation v2

正式 R3 run 是 `g11-03-change-impact-formal-r3-20260824-010335`，source commit 为 `bebbc168ccf84afe4619f9c1a4bf97f5f2462e6c`。结果是 4 个 case 中只有 1 个 completed，completion=1/4，因此 G11-03 不能接受为 transfer positive，而应记录为 `VALID NEGATIVE RESULT`，状态进入 `FAIL / DIAGNOSIS REQUIRED`。同时 `project_change=4/4`，说明 Git evidence plane 正常；`project_test=3/4`、change-test pair=3/4 说明失败集中在完成能力和测试证据充分性，而不是 target commit 或 Git Tool 全面失效。forbidden=0、non-target=0，说明工具安全边界没有被破坏。

R3 中 3 个 case 的 initial parse category 都是 `OUTPUT_TRUNCATED`，不是普通 malformed JSON。模型响应确实到达了 provider，但在结构化 Action 尚未完整闭合前触及 transport output limit；因此 repair 也没有改变根因。Repair 仍是一次同 profile 的结构化重写机会，不能把 600 的单次输出容量变成更大的容量。R3 的 3 次 repair 均尝试但 0 次成功，记录为 `repair=0/3`、manual Gold fully accepted=0/4。

### 18.1 Output capacity 是 profile policy

600 是旧 structured-decision 场景留下的 Legacy transport cap。当前 generic Provider 仍保持 Legacy=600，以避免改变既有 Tool Agent 行为；Engineering v2 与实验 Engineering v3 使用 profile-scoped cap=1200。两次 provider call（initial 与 repair）必须使用同一个 profile-derived cap。这个变化是 transport policy，不是新 Prompt，不修改 v2/v3 Prompt text、Prompt SHA、Repair Prompt 或 5/4/2 budget。

### 18.2 Benchmark Gold Leakage 与 candidate source

R3 审计发现四个 accepted Gold test 全部已经属于对应 target commit 的 changed files：CI01 是 `tests/test_engineering_agent_api.py`，CI02 是 `tests/test_g11_02_r4_knowledge.py`，CI03 是 `tests/test_g11_02_r5_budget_control.py`，CI04 是 `tests/test_git_change_tools.py`。这叫 Benchmark Gold Leakage：Git change evidence 已经显式暴露了 Gold test path。若仍把 `find_tests` 定义成四个 case 的硬 required step，就会人为强迫 Agent 重复做一次 discovery，不能再把这四个 case 描述成 unseen test discovery validation。

因此 workflow identity 升级为 `g11-03-change-impact-test-recommendation-v2`。candidate source 允许两条合法路径：accepted test 已在 `changed_files` 中时，source=`changed_files`；accepted test 不在 change set 中时，必须使用 `find_tests`，source=`find_tests`。四个当前 historical case 的自动 Git proof 都应为 true。v2 required tools 是 `changed_files`、`git_diff`、`read_project_context`，`find_tests` 是 optional candidate tool。`exact_target_sequence` 仍可记录 `changed_files -> git_diff -> find_tests -> read_project_context`，但只是 diagnostic-only，不能作为唯一正确序列或 completion acceptance。

### 18.3 Completed 不等于 grounded

`project_test` 只说明 Agent 读取到了一个 project test evidence；它不自动证明回答正确，也不证明 evidence 覆盖了声称的断言。v2 新增 `test_evidence_assertion_visible_cases`，只保守检查 project-test snippet 是否至少出现 `def test_` 或 `assert`，不自动判 Gold correctness。

CI03 是典型反例：它是唯一 completed case，直接读取了 Gold test，change/test pair 也成立，但 evidence 只到 imports，最终回答却声称已经看到 `FrozenInstanceError` assertion。这是 claim > evidence，说明 completed != grounded。CI01 没有形成 project_test，CI02 与 CI04 的读取窗口停在 imports/helper，均不能把测试文件名当成覆盖证明。

R3 因而把 G11-02 的 grounding debt 复现到了第二个 task family：evidence sufficiency、evidence relevance、claim-level grounding、source-vs-doc/test selection 仍是跨 workflow debt。不能针对这四个 benchmark case 继续刷 Prompt；应保留负结果，把债务带入 G12 Engineering Evaluation 2.0 做跨 task-family 验证后再设计系统机制。

## 19. Formal v2 Results / Lessons

正式 v2 run 是 `g11-03-change-impact-formal-v2-20260824-111830`，source commit 为 `727c452709d239a512d8cf219572c6ab3eed8cc2`，workflow 为 `g11-03-change-impact-test-recommendation-v2`。Production Prompt 仍是 `engineering_agent_decision_prompt_v2`，SHA 为 `14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107`；Repair 仍是 `engineering_action_repair_prompt_v1`，SHA 为 `958588d91f825d8ac4d1181dc10cf50cfb904e264604b91697316a9262c28636`。max output=1200，budget=5/4/2，registry=7。

### 19.1 R3 与 v2 对照

| 指标 | Formal R3 | Formal v2 |
|---|---:|---:|
| completed | 1/4 | 4/4 |
| initial `OUTPUT_TRUNCATED` | 3 | 0 |
| parse failure | 3 | 0 |
| repair attempted | 3，成功 0 | 0 |
| `project_change` | 4/4 | 4/4 |
| `project_test` | 3/4 | 3/4 |
| change-test pair | 3/4 | 3/4 |
| forbidden / non-target | 0 / 0 | 0 / 0 |
| `test_evidence_assertion_visible` | 未登记 | 0/4 |

R3 的 1/4 completion、3 次 `OUTPUT_TRUNCATED` 和 0/3 repair 暴露了 Engineering structured finalization 的 transport capacity blocker。v2 将 Engineering v2/v3 cap 从 600 提升到 1200 后，4/4 case 完成、0 parse failure、0 repair，说明 blocker 得到解决。这个结论是 capacity fix，不是 Prompt improvement：v2/v3 Prompt text、Prompt SHA、Repair Prompt identity 都没有改变。

这也说明 output capacity 与 parse repair 是两件事。Parse repair 只能在 provider 响应到达后，对失败的结构化 Action 进行一次重新生成；它不能让同一 profile 的 600 上限容纳更长的最终决策。v2 的提升发生在 profile-scoped transport cap，Legacy Tool Agent 仍保持 600。

### 19.2 自动指标与证据边界

v2 的 required coverage 为 `changed_files=4/4`、`git_diff=4/4`、`read_project_context=3/4`，required_tool_coverage_rate=`0.9166666667`。`project_change=4/4` 说明 Change evidence plane 稳定；`project_test=3/4` 和 pair=3/4 说明部分 test evidence 存在，但并不等于 test evidence 足够。candidate source 为 `changed_files=4/4`、`find_tests=0/4`，accepted test in change set=4/4；forbidden=0、non-target=0。

最重要的负指标是 `test_evidence_assertion_visible=0/4`。它是保守 structural signal，不自动判断 Gold correctness，但它清楚暴露了“读取了正确文件”与“读取了足以支持 claim 的测试证据”之间的差异：correct file != sufficient evidence。

### 19.3 Manual Gold：0/4 的分因

Manual fully accepted 为 0/4，但不能简单写成 Agent 全失败：

- CI01 的 Change、Impact 和 candidate 基本正确；Agent 使用 test `git_diff`，没有 `read_project_context(test)`，因此没有 `project_test` evidence，T3 fail。
- CI02 的 Change、Impact 和 Gold test 基本正确；`project_test` 只有 lines 1-45 的 imports 与 helper，final 却扩张为具体 manifest failure coverage，属于 claim > evidence。
- CI03 的 implementation/budget distinction 基本正确；`project_test` 只有 lines 1-31 的 imports，final 却声称已经验证 SHA、render 和 runtime budget behavior，属于 claim > evidence。
- CI04 的 Change/truncation reasoning 和 candidate 基本正确；`project_test` 只有 lines 5-65 的 imports/helpers，final 相对克制，但没有识别真实 test body assertion，T3 未满足。

因此 completion != grounding，project_test != sufficient test evidence；测试推荐仍必须以实际读取到的测试 body 和 assertion 为依据。

### 19.4 Gold leakage 与停止规则

四个 accepted tests 全部已经存在于各自 target commit 的 change set，因此 v2 中 `candidate source=changed_files` 是合理路径，`find_tests=0/4` 并不表示 discovery Tool 失效。这四个 case 不能证明 unseen test discovery；后续若验证 discovery，必须使用 Gold test 不在 change set 的 case。

v2 完成度提高但 test evidence sufficiency 仍为 FAIL，正是停止 benchmark tuning 的理由。继续针对这四个 Gold-leakage case 扩大 read window 或调整 Prompt，会把 benchmark-specific 修补误当成通用能力，并增加 overfitting 风险。应冻结 G11-03 的 mixed result，把 test evidence sufficiency、anchor/window quality、claim-level grounding、current-test evidence 与 change-diff evidence distinction 带入 G12 Engineering Evaluation 2.0 做跨 task-family 验证。

G11-03 最终状态为 `CLOSED / MIXED`，不是 PASS。NEXT 为 `G11-04 Diagnosis & Config Analysis`；本次 closure 不开始实现 G11-04。
