# G12 外部仓库与 Candidate Pool

## 1. 为什么 G12 需要外部仓库

只在自己的代码库里评测，容易把开发阶段已经见过的文件、测试、Study Note 和失败模式误当成 Agent 的泛化能力。G12 因此要求至少一个内部 clean fixture 和一个公共外部仓库：它们都要固定到可复查 commit，再由同一组现有 Engineering Tools 读取。

这不是为了追求“仓库越大越难越好”。外部仓库必须仍可被当前有界 Tools 实际读取，必须有源码、文档、测试和完整 Git history，且不能要求为某一个仓库临时造索引或改 Tool。

## 2. Evaluator、Runtime 与 Project 是三层

G12 中有三个不同的角色：

```text
Evaluator checkout
    Candidate metadata / Gold proof / validator / tests / study notes
        !=
Runtime checkout
    当前 Engineering v2 产品和现有 7 Tools
        -> ENGINEERING_PROJECT_ROOT
Project checkout
    Agent 真正可以搜索和读取的 frozen source tree
```

Evaluator 可以保存候选题、Gold obligation 和审计说明，但它们不能出现在 Agent 的 searchable project tree。G11-05 已经证明这不是抽象担忧：被评测 Agent 曾实际搜索到 evaluator Study Note，因而那个 run 是 `INVALID / EVALUATION CONTAMINATION`，而不是能力负结果。

G12-02A 的 Project A 是 `wgqa/my_agent` 的 `465dd65e950e9c4a119820a5a27f558e74ad5892` detached clean fixture；它位于 G11-02 至 G11-05 evaluator metadata 出现前。Project B 是 `pydantic/pydantic-ai` 的 `bfa8e9187b86aad7ec583665ab2743fadea458b1` public snapshot。两者都用独立 checkout，不能把 evaluator root 当作项目根目录。

## 3. 为什么选择 Pydantic AI

Pydantic AI 是一个公开的 Python Agent framework。这个 snapshot 有 MIT `LICENSE`、完整 Git history、`pydantic_ai_slim/pydantic_ai/` 源码、`docs/`、`tests/`、`pyproject.toml` 和 README，覆盖 Tool、Agent graph、profile、retry、文档一致性与测试等真实工程表面。

G12-02A 不把它宣布为最终 benchmark，也不把任何单条候选说成已通过 Gold review。它只是一个完成本地 repository proof 后可供 Reviewer 审计的 external candidate。

## 4. Repository Proof 不只是 clone 成功

每个 project checkout 都要验证：

- detached `HEAD` 等于 registry 的完整 SHA；
- tracked-clean；
- 非 shallow，因此 parent、历史 commit 和 diff 可读；
- origin identity 正确；
- 注册的源码、文档和测试树真实存在；
- tracked/python/docs/tests 数量与 registry 的 proof 一致；
- `code_search`、`read_project_context`、`changed_files`、bounded `git_diff`、`find_tests` 都能实际运行；
- configured project binding 的公开 identity 只返回 project name/source，不泄漏本地绝对路径。

Project A 还检查不存在 G11 runner、G11 test、G12 protocol、Study Note 113 或 `evaluation/gate12/`。若这些 evaluator-owned 文件出现在 target，任务必须停下，而不是悄悄换一个 commit。

Pydantic AI 有 `AGENTS.md`、`CLAUDE.md`、`.agents/`、`.claude/`、`.gemini/` 等 agent-facing instruction material。G12 v1 不是 prompt-injection benchmark，因此 validator 拒绝把这些路径作为 candidate Gold source 或候选题主题。它们仍是 project data，Tool 对 Observation 的不可信处理不因此改变。

## 5. Candidate Pool 与 Final Benchmark 的区别

G12-02A 产物是 24 条 `DRAFT / REVIEW REQUIRED` candidates：

```text
4 task families
    x 2 repositories
    x 3 candidates
    = 24 draft candidates
```

它不是 Formal dataset，也没有最终 case ID、Gold score、provider run 或结论。后续 G12-02B Reviewer Audit 才会逐条审核 question、source proof、Gold obligation、独立性和难度，并从池中选择最终约 16 条 case。Reviewer 可以拒绝、重写或不选择任何 draft candidate。

每条 candidate 使用稳定 `g12c001` 到 `g12c024` identity；canonical JSON 的 SHA-256 和整个 JSONL 的 SHA-256 都记录在 manifest 中。修改任一字段都会使 manifest validation 失败。这是草案来源身份，不是对未来 Formal case 的提前封存。

## 6. 四类候选任务

| Family | 最低 public evidence shape | 候选关注点 |
|---|---|---|
| Theory <-> Code | `knowledge` AND (`project_code` OR `project_doc`) | 将冻结 Engineering Knowledge 的机制材料和目标项目实现对照。 |
| Change Impact <-> Test | `project_change` AND `project_test` | 先读真实 Git diff，再读测试正文解释回归依据。 |
| Diagnosis / Config | `project_code`；跨文件时至少两个 distinct paths | 从症状、配置或运行时边界追踪实际实现。 |
| Docs <-> Code | `project_doc` AND `project_code` | 读取文档与当前代码两侧后，草案性标记一致性。 |

这些都是 G12-01 的 AND-of-OR Evidence Sufficiency contract。它只定义 automatic structural shape；相关性、正确性、claim grounding 和 task success 仍是 Manual Gold v1，不能因候选池有 source path 就自动判对。

## 7. Theory 候选为什么要有 Knowledge Probe

Theory <-> Code 不能由模型常识直接出题。G12-02A 用现有 verified Engineering Knowledge backend 做 deterministic BM25 probe，并冻结：corpus `870e5864df67`、37 files、215 chunks、strategy `bm25`、manifest `dbc497c796d5`。

每条 Theory candidate 记录 probe query、top-k returned source identities 和 `knowledge_gold_sources`。例如 Function Calling、工具设计、StateGraph 工具循环和 MCP 结果安全边界都必须真的从该 corpus 返回相关 source。probe query 是 evaluator provenance，不是要求未来 Agent 原样输入的搜索词。

## 8. Unseen-test Discovery

Change Impact 中，`changed_files` 可以说明“测试是否恰好和实现一起改过”，却不能证明测试覆盖了什么。G11-03 已经暴露了这种差异。

因此 6 条 Change candidates 中有 2 条把 `accepted_test_in_change_set` 冻结为 `false`，一条来自每个 repository。它们要求 Agent 通过 `find_tests` 或 `code_search` 发现候选，再用 `read_project_context(test)` 读取测试正文。最终的 `project_test` 才能参与 Evidence Sufficiency：

```text
candidate provenance
    !=
test behavior evidence
```

这也解释了“推荐测试”与“执行测试”的区别。该 workflow 推荐需要回归阅读的测试，不运行测试，也不凭文件名断言它已经覆盖风险。

## 9. Source Proof 如何服务 Reviewer

每个 Gold obligation 至少由一条 `source_proofs` 记录覆盖。proof 有 kind、project-relative path、真实 anchor 和 obligation ids；validator 会在 pinned checkout 实际读取文件并确认 anchor 存在。Change candidate 额外验证 `head^`、`head`、declared changed paths 与 `accepted_test_in_change_set` 的真实 Git truth。

这仍不是自动 Gold scorer。一个 anchor 存在并不证明最终 answer 的影响分析正确，只说明 Reviewer 有一个可复查的起点。G12-02B 应检查 source 是否相关、断言是否足以覆盖风险、obligation 是否准确，以及题目有没有暗含答案。

## 10. 为什么 24 选 16

24 条 draft 给每个 family/repository 组合留下 3 个备选项。最终每 family 预计选 4 条，并尽量在 internal fixture 与 external repo 之间保持平衡。候选池必须大于最终 benchmark，Reviewer 才能因为独立性不足、Gold 不充分、文档 label 不稳或 source window 不适合现有 Tool 而拒绝条目，而不是为了凑数量硬塞进 Formal。

G12-02A 到此只完成 repository proof 和 candidate pool。Formal 仍是 `NOT RUN`，Finalization Guard 仍是 `NOT IMPLEMENTED`，G12-02B 也尚未开始。

## 11. Reviewer Audit Lessons

Reviewer 审计发现，`path` 和 `anchor` 可读取只是 Gold 的最低可复查性，不等于语义已经完整。若问题询问循环边界、失败传播、测试风险或文档一致性，Gold 必须冻结实际条件、状态转换、断言或双方的可比较行为，不能只证明某个类或文件存在。

Change candidate 还必须区分两个历史快照：`project_change` 是 `base_ref..head_ref` 的真实 diff，`project_test` 是 `head_ref:test_path` 的测试正文。`project_source_commit` 只描述当前 fixture 的可用性，不能替代历史 Change Gold。否则一个后续新增的测试会被错误地当成旧提交的回归依据，这就是 temporal leakage。

因此 unseen test 的定义是：测试在 `head_ref` 已存在，并且该路径不在同一 `base..head` change set。它不是“后来在某个 snapshot 出现过的测试”。validator 现在分别验证真实 changed paths、diff anchor、accepted test 的 head-time existence 和测试正文 anchor；future-only test 必须 fail。

Docs <-> Code 也不能由“文档讨论主题 + 代码存在类”推出 `CONSISTENT`。每条候选必须分别冻结文档 claim（D）、当前代码 behavior（C）和双方关系判断（J）。J 可以由两侧 proof 共同支持；若文档只描述概念而真实 ownership 分散在多个实现点，应如实标记 `PARTIALLY CONSISTENT`、`OUTDATED` 或 `INCOMPLETE`，而不是为了分布配额制造 drift。
