# G11-03：Change Impact 与测试推荐工作流

## 1. Change Impact Analysis 是什么

Change Impact Analysis 不是“改了哪个文件”的文件名摘要，而是从一个真实 Git change 出发，判断哪些行为可能受到影响、哪些测试是合理候选、测试源码实际验证了什么，以及基于这些证据应该推荐什么回归测试。

当前 G11-03 首先做 transfer validation：验证已经通过 G11-02 Formal R6 的通用 Engineering Prompt v2、现有七个只读 Tool 和 5/4/2 Runtime budget，能否迁移到第二个 task family。它不新增 Change Impact 专用 Prompt，也不把一次实验结果包装成新的产品能力。

## 2. 当前工作流

固定链路是：

```text
Change
  -> changed_files
  -> git_diff
  -> Impact
  -> find_tests
  -> Test Candidate
  -> read_project_context
  -> Test Evidence
  -> Test recommendation
```

四个 Tool 的职责不同：

- `changed_files` 先确认 commit range 中实际变化的 repo-relative path 和 change status。
- `git_diff` 读取一个已经定位的文件的 bounded unified diff，提供变更事实。
- `find_tests` 从 source path 发现候选测试 path、anchor line 和稳定 reason；它只定位，不判断覆盖。
- `read_project_context` 读取候选测试源码窗口，才把测试内容变成可审计的 `project_test` evidence。

因此回答必须分层：A 是 Git 实际改了什么；B 是基于 diff 可以合理判断的行为影响；C 是工具发现的 candidate；D 是为什么推荐某个测试；E 是测试源码中的哪个断言或场景真正支撑该推荐。

## 3. 为什么不能只看 changed filename

文件名只能提供路径和命名信号，不能证明调用关系、参数流、分支行为或测试断言。一个 `runtime.py` 可能对应多个测试，一个测试也可能通过 fixture、API 或共享 helper 间接覆盖多个模块。反过来，名称相似的测试也可能只验证初始化、错误路径或无关行为。

所以 `find_tests` 的结果必须称为 candidate。只有后续 `read_project_context(test_path, anchor_line)` 读到真实测试源码，才能说明测试实际构造了什么输入、断言了什么结果，以及它和变更风险之间有什么证据联系。

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

Gold obligation 必须在当前 Tool 能力范围内可达。固定 case 在进入 Formal 前，由 `tests/test_g11_03_change_impact.py` 使用真实 repo 的 `FindTestsHandler` 执行 `find_tests`，确认 `accepted_test_paths` 至少有一个实际出现在返回的 candidate paths 中。这不是 mock，也不把 Gold test 人为塞进 Tool 输出；它只是验证 evaluation case 与当前 `find_tests_v1` contract 对齐。

如果 Tool 正确返回 no candidate，说明 benchmark 的 focus path 与 discoverability contract 不可执行，属于 evaluation design error，不能误判成 Agent reasoning failure。CI03 因此使用该 commit 中真实 changed 的 `core/tool_agent/decision_prompt.py`，其目标测试通过 public import 直接引用 `decision_prompt`，可以被现有 `content_reference` 规则发现。

## 11. 为什么推荐测试不等于执行测试

本 workflow 的输出是 evidence-grounded test recommendation。Agent 可以根据 diff 和测试源码说明“应该优先回归哪个测试，以及它覆盖哪一个风险”，但它没有运行 pytest、Maven、Gradle 或其他测试命令。

执行测试需要独立的命令、环境和结果 provenance。把推荐写成“测试已通过”会混淆静态证据与动态执行证据，也会让用户错误地认为风险已经被验证。

## 12. 5/4/2 budget 下的紧凑链路

Runtime 仍冻结为 5 iterations / 4 Tool calls / 2 Tool errors。四个 required Tool 恰好可以在五轮内完成：前四轮依次读取 change、diff、candidate 和 test source，第五轮输出 final answer。

该预算控制的是执行边界，不是答案正确性证明。模型不能通过输出修改 `DecisionControlState`，也不能扩大 Tool calls；v2 的 trusted control state 只是让模型知道剩余能力，Runtime hard enforcement 仍是最终边界。

## 13. 与 G11-02 Theory ↔ Code 的区别

G11-02 连接 Knowledge Evidence 与 Repository Evidence，回答理论、当前实现和二者差异；其固定跨源链路通常包含 `knowledge_search`。G11-03 连接 Git Change Evidence 与 Test Evidence，回答变更影响和测试建议；四个 case 不应调用 `knowledge_search`，因为 Gold 来自真实 commit diff 与真实 test source，而不是通用理论知识。

两者共享 Engineering Agent、Production Prompt v2、七个 Tool、Repair v1 和 5/4/2 budget，但 task family、required Tool contract 和 evaluation obligations 不同。G11-03 首先验证这套通用控制面能否迁移，不以新增 Prompt 解释差异。

## 14. 面试表达

可以这样说明：

> Agent 不是凭测试文件名或经验猜影响。它先用 `changed_files` 和 bounded `git_diff` 固定 Git 事实，再用 `find_tests` 找候选，最后用 `read_project_context` 读取测试源码。最终回答把 diff、合理影响、candidate、测试断言和推荐理由分开；推荐测试不等于测试已经执行。

## 15. Transfer validation 边界

G11-03-01 只新增 runner、deterministic contract tests、Study Note 110 和状态记录。它不修改 API/runtime、任何 Prompt、Tool implementation/schema、Knowledge backend、Evidence schema、budget、registry 或 `find_tests` 算法。

Runner 会记录 prompt/repair identity、source checkout、target commit/ref、toolset、budget、safe trace、per-case evidence 和 summary metrics，但不会记录 raw provider output、API key、CoT 或本机绝对路径。Formal DeepSeek 四 case 由用户在同一 real-provider 环境中显式运行；本任务不自动运行 Formal，也不提前判断 Gold correctness。

## 16. Artifact Safety 与 Serialization Boundary

semantic payload != serialized representation。JSON/JSONL 的安全校验必须先反序列化，再递归检查 string leaf；否则 JSON 对普通 literal backslash 的转义可能被 raw-text 扫描误报为 UNC path。Markdown 不是 JSON，因此保留文本层的 repo-root、实际 drive/UNC path 和 secret 防护，但 UNC 也必须满足真实 \\server\share 形状，不能看到任意 \\ 就拒绝。

安全验证不能简单关闭，而应放在正确的 serialization abstraction layer。首轮 Formal run g11-03-change-impact-formal-20260823-235907 因 runner 的 artifact safety serialization false positive 判为 INVALID / INFRASTRUCTURE FAILURE；这是 runner infrastructure 结果，不作 Agent 结论。R2 后正式实验仍需生成新的 run_id。
