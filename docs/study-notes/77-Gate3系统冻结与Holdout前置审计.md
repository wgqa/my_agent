# 77-Gate3系统冻结与Holdout前置审计

> G3-FREEZE-08-SYSTEM：把已 Reviewer Accepted 的 Gate 3 Dev 侧系统正式做成机器可核验的 Freeze Candidate，作为未来唯一一次 sealed Holdout run 的前置基线。
> 日期：2026-08-14
> frozen_code_baseline_commit：`fed9d15b950fe543d1afc99a2a21a5ad5d299320`
> gate3_system_freeze_id：`2ec11a69b173`（`docs/experiments/gate3_system_freeze.json`，machine-computed，排除自指）
> 本任务：0 Planner / 0 Generator / 0 Judge / 0 Retrieval / 0 Embedding / 0 Holdout / 0 sealed 读取；只改 4 个 docs/freeze metadata 文件。

---

## 0. 一句话

Dev 调完、指标审完、系统行为摸清之后，必须把**整个系统的身份（代码 + 数据 + 模型配置 + 实验 provenance）**冻结成一个哈希 ID，之后的任何变化都必须先问"这个 freeze 还成立吗"。Freeze Candidate 是给"唯一一次 sealed Holdout run"上保险的。

## 1. 为什么 Dev 调完后一定要 Freeze

- **Dev 是拿来调模型的，Holdout 是拿来验证泛化的。** 如果允许在 Dev 上反复调、看完 Holdout 再回来改，那 Holdout 就不是"没见过的测试集"，而是第二份 Dev——分数全部失真。
- Freeze 的本质：**在"我还能改"和"我不能改了"之间画一条线**。线这边的状态写死（代码 commit + 配置 + 数据 id + 实验 id），线之后只允许按合同跑一次。
- 面试里最扎实的一句话："Dev 上的每个数字都可能是过拟合的结果，所以我只信一次 Holdout；为了让它可信，我必须先把 Dev 侧系统的每一个可配置面都钉死。"

## 2. Freeze 和 Git commit 有什么区别

- **Git commit** 只锁**代码**：它不保证"跑出来的结果"和"代码"一一对应，也不锁模型、prompt、temperature、retry、merge 策略、数据版本。
- **Freeze** 锁的是**整个实验身份**：代码 commit + 数据 freeze id（Dev/Holdout + 各自 SHA）+ 模型/温度/超时/max_tokens/retry + prompt 版本/SHA + merge/runtime 配置 + 06C/07A/repair 的 run id 和 Artifact SHA + 最终 headline + known limitations + Holdout 执行合同。
- Git 回答"代码是什么"；Freeze 回答"**拿到这份结果时，整台机器处于什么状态**"。

## 3. 为什么 Prompt / model / temperature / retry / merge policy 都属于实验身份

- 这些都是会改变输出的可配置面。**一个实验要可复现，必须记下所有"改了就会变结果"的旋钮**，而不只是代码。
- temperature=0 不保证确定（服务端可能有采样），但它至少把温度钉在一个值；max_retries 决定超时后是重试还是失败；merge_policy 决定候选怎么进最终证据——这些全部进入 run identity（run_id/repair_id 的哈希），任何一个变了，ID 就变，旧结果就不能拿来比较。
- 这正是本项目一路坚持的：`run_id`/`repair_id`/`freeze_id` 都从 canonical JSON payload 算哈希，**配置是身份的一部分**。

## 4. 为什么要把 06C 和 07A 分开解释

- **06C = 受控检索对照**：用**冻结 Planner snapshot** 跑 A/B/C/D，只改 merge 一个变量，证明"RRF merge v2 把 merge-drop 5→0、final obligation 32→37"。它隔离了"执行方式"变量，是**检索层**的证据。
- **07A = 真实 E2E**：用**live Planner + 真实 Generator**，测的是"开箱即用的整条链"。它暴露了 retrieval→answer gap、generator 空输出、Planner drift 等**真实系统行为**。
- 两者回答的问题不同：06C 说"检索选择策略好不好"，07A 说"整个系统现在到底行不行"。混为一谈会得出错误结论（比如把 37→35 的检索差异误判成 merge 回归）。

## 5. 为什么 37/44 → 35/44 不代表 merge regression

- 06C 的 37/44 是**冻结 snapshot plan**下的检索覆盖；07A 的 35/44 是 **live Planner 自己生成的 plan** 下的检索覆盖。两次的 plan 不同，所以不是同一个实验的两次运行。
- live Planner 有**非确定性/漂移**（subquery 措辞变化 → plan_id 变化 → 检索结果变化），这是 Planner 层的行为差异，不是 merge 层变了。
- 判断"是不是 merge 回归"只看**同一套 plan 下 merge 前后**的差异——06C 已经证明 merge v2 在同一 plan 下把 final 覆盖从 candidate 那里保住了。Freeze 的 known_limitations L2 明确写了这条，防止将来被误读。

## 6. generation source commit 与 evaluation source commit 为什么可以不同

- **generation** 决定"答案是什么"（Planner/Retrieval/Generator），绑定 generation_source_commit。
- **evaluation** 决定"答案怎么打分"（citation denominator、Judge gating、指标聚合），绑定 evaluation_source_commit。
- 两者可以不同：只要评价代码在生成**之后**修正，评价与生成就是两个可分别审计的阶段。07A 的 repair 正是这样——generation 用 `6a783c4`，evaluation 用 `a9e2d9a`，两个都进了 repair identity。这样"答案是谁产生的"和"评分是谁算的"都能独立回答。

## 7. provenance repair 为什么不等于第二次性能实验

- repair 是**纯离线**：0 次 LLM 调用，只对已持久化的 case_results + judge 输出重算指标。它不产生新答案，不改系统。
- 它只修"评价口径"（citation denominator、零 obligation 的 Judge 门控、去硬编码），不是"换个参数再跑一次看结果更好"。
- 所以 4172 → repair 的对照标注为 **offline evaluation provenance repair，非性能 A/B**——generation/retrieval 观测全部继承，只有评价口径被修正。

## 8. 为什么 Holdout 只能跑一次

- 跑一次得到的是"这台系统在没见过的问题上的真实表现"。
- 跑两次（即使参数不变），只要看了第一次结果再决定第二次，就是在用 Holdout 调——泄露了答案。**authorized_runs = 1** 从合同层面杜绝这种诱惑。
- 唯一允许重跑的场景是**基础设施级 invalid run**（API 全挂/文件损坏/进程崩溃）且要保留 invalid 记录与原因；"结果不理想"不构成重跑理由。

## 9. 为什么看完 Holdout 后不能继续调 Dev

- 看完 Holdout 后再调 Dev，等于把 Holdout 的信息（哪怕只是"哪类题挂了"）带进了 Dev 迭代，下一轮 Holdout 就脏了。
- 正确的流程：Freeze → 唯一一次 Holdout → 拿结果做**整体结论**（晋级/降级/重做数据或架构），而不是微调参数再测。
- 合同里 `post_holdout_dev_tuning = forbidden` 就是这个意思。

## 10. 面试如何讲 Gate 3（六块）

- **检索能力**：冻结语料 Hybrid（BM25+Dense+RRF），06C 单变量证明 RRF merge v2 把 merge-drop 5→0、final obligation 32→37、Hit@5 0.95、Recall 0.875（冻结 plan 下）。
- **Planner drift**：live Planner 与冻结 snapshot 的 plan_id 只 5/24 精确一致（措辞漂移），导致 37→35 的检索覆盖差；这是 Planner 非确定性，不是 merge 回归。
- **Generator failure**：4/24 GENERATION_FAILED，deepseek-v4-flash 对复杂 decomposed context 输出空串；真实系统失败，保留在 headline，不粉饰。
- **retrieval→answer gap**：检索 obligation 35/44 但答案 obligation 只有 21/44——**找到证据 ≠ 覆盖义务**，是当前已知瓶颈（L3）。
- **LLM-as-a-Judge 局限**：Judge 是辅助评估，非人工 Ground Truth；Judge(deepseek-chat) 与 Generator(deepseek-v4-flash) 不同模型但同属 DeepSeek family，存在潜在同源偏置；Judge 输出结构化 + 严格 parser + invalid fallback。
- **reproducibility/provenance**：双 source commit（generation vs evaluation）、source lock（事先冻结 expected hashes，mismatch fail-fast）、纯离线 repair、freeze_id 机器计算。整套证明"每个数字都能追溯到：哪份代码、哪份数据、哪个配置、哪次运行"。

---

## 边界声明

- 未读取/搜索 gate3/sealed；Holdout metadata 仅用公开登记的 evaluation_set_id（79a6bc0814a3）与 case count 之外无内容级信息。
- 0 LLM / 0 Retrieval / 0 Embedding / 0 Index / 0 Dev rerun / 0 Holdout。
- Freeze 状态为 REVIEW PENDING（Agent 不得自行写成 Reviewer accepted）；Holdout = BLOCKED。
- Freeze JSON 由脚本机器生成，freeze_id 从 canonical payload 独立重算，非手写。
