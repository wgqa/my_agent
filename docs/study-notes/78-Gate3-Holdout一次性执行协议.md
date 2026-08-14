# 78-Gate3-Holdout一次性执行协议

> G3-HOLDOUT-09A-HARNESS：建立一次性、Freeze-bound 的 Holdout execution harness（09A 只跑 preflight/dry-run，不真正运行 Holdout）。
> 日期：2026-08-14
> 关联 Freeze：gate3_system_freeze_id=`2ec11a69b173`、frozen_code_baseline_commit=`fed9d15…`
> 09A preflight 实测：holdout_run_id=`a1dc0a4bab03`、0 LLM / 0 Retrieval / 0 Embedding、sealed_read=False、未创建正式 attempt。
> 本任务：0 Planner / 0 Generator / 0 Judge / 0 Retrieval / 0 Embedding / 0 Index / 0 Holdout / 0 sealed 读取。

---

## 0. 一句话

Freeze 通过了不等于能马上跑 Holdout——你还需要一个**一次性执行协议**：独立身份、唯一配置来源、无性能 override、attempt ledger、Gold 隔离、preflight 门禁。09A 把这套基础设施造好并只做 dry-run；真正打开 sealed 是在 09B（授权后）。

## 1. 为什么 Freeze 通过后还不能立即执行 Holdout

- Freeze 只把"系统身份"钉死了，但**执行纪律**还没钉：谁可以跑、跑几次、能不能改参数、出问题能不能重试。没有这些，跑 Holdout 时一冲动就能毁掉"唯一一次"。
- 09A 就是把"执行纪律"做成代码：preflight 门禁 + attempt ledger + 禁 override。Freeze 回答"状态是什么"，09A 回答"怎么安全地只用一次"。

## 2. Dev runner 与 Holdout runner 为什么必须身份隔离

- 如果用 `dev_evaluation_set_id` 字段冒充 Holdout，身份哈希里就是"Dev 的 id"，将来无法从 artifact 判断"这份结果属于哪套数据/哪个协议"。
- Holdout 用独立 `Gate3HoldoutConfig`，绑定：freeze_id、dataset freeze id、**holdout**_evaluation_set_id、holdout_case_count=12、actual_execution_source_commit + 全部 frozen 配置。身份是独立的、自描述的。
- 面试说法："Dev 结果和 Holdout 结果必须能靠 run_id 直接区分，否则一次误标就能把整个泛化结论污染。"

## 3. 为什么不能用 CLI override frozen 参数

- 一旦 CLI 允许 `--generator-model xxx`，Freeze 就形同虚设——跑的人可以"顺手"换模型，结果既不是 frozen 系统、也无法复现。
- 正确关系：`gate3_system_freeze.json` → 解析 → 验证 freeze_id → 生成 Holdout runtime config。**配置的唯一来源是 Freeze 文件**，CLI 只接受执行位置参数（路径）。
- 09A 的 CLI 显式 `assert_no_forbidden_overrides`：任何 `--model/--temp/--top-k/--merge-*` 直接拒绝。

## 4. attempt ledger 为什么重要

- Holdout 只能跑一次。**ledger 是"这一次"的持久化证据**：谁、在哪个 freeze 下、哪个实际 commit、什么时候开始、什么状态。
- 状态机：prepared → running → completed / failed_system / invalid_infrastructure。
- **最保守规则（09A-R1-LEDGER-MICRO 硬化）**：只要 ledger 存在**任何合法 attempt（含 prepared）**，就禁止自动创建另一个；invalid_infrastructure 的替代由 Reviewer 单独放行，本层不留自动后门。
- **read_attempt_ledger 严格校验**：schema / attempts 类型 / 每条 attempt 结构 / 合法 status，未知或损坏一律 fail-closed（ValueError）。
- **atomic_create_attempt 跨进程互斥**：sibling lock 文件 `O_CREAT|O_EXCL|O_WRONLY`，持锁期间完成 read→validate→check→append→write；异常残留 lock 不自动删除（fail-closed，交 Reviewer 判断）；`started_at` 写入真实 UTC 时间。
- 09A 的 preflight 只检查 ledger"尚未消费"，**绝不创建正式 attempt**——否则还没跑就把唯一机会消耗了。

## 5. system failure 与 infrastructure-invalid 的区别

- **failed_system**：系统本身的行为性失败（如 generator 空输出、答案错误）——这是**真实结果**，保留，绝不允许换参数重跑"看能不能更好"。
- **invalid_infrastructure**：基础设施级失败（API 全挂、文件损坏、进程崩溃）——这次 attempt 没有产生有效观测。
- **关键：invalid_infrastructure 也不能由 Agent 自动重跑。** 必须 STOP → Reviewer audit → Reviewer 显式授权或拒绝替代 attempt。否则"基础设施坏了就重跑"会成为绕过 one-shot 的漏洞。

## 6. Generation / Gold isolation

- Generation 阶段只能看到 `case_id + query`（复用 `GenerationCase`），永远看不到 answerability / evidence_obligations / relevant_files / Gold / Judge rubric。
- 测试用 `SECRET_GOLD_SENTINEL_09A` 放在 synthetic Gold 字段里，断言它绝不出现在 generation 输入中——一旦泄露，测试立即失败。

## 7. actual execution source commit 和 frozen code baseline commit 为什么不同

- **frozen_code_baseline_commit** = Freeze 那一刻的代码基线（`fed9d15…`），是"被冻结的系统"的下界。
- **actual_execution_source_commit** = 真正执行那一刻的 HEAD（= freeze commit + harness commit，即 09A 之后的最新 HEAD）。
- 两者都要进 Holdout 身份：frozen 证明"系统语义没变"，actual 证明"这次跑的到底是哪一版代码"。将来审计时能同时回答"系统从什么时候开始冻结"和"这次 run 用了哪一版 harness"。

## 8. 面试如何解释一次性 Holdout protocol

一条线：
1. **数据隔离**：Dev/Holdout 24/12 分层封存，Holdout 从未被读取。
2. **系统冻结**：Freeze Candidate 把代码+数据+模型+prompt+merge 全部钉死成 `freeze_id`，任何变更都要先问 freeze 还成不成立。
3. **身份隔离**：Holdout 用独立 `Gate3HoldoutConfig`，绑定 freeze_id 与实际执行 commit。
4. **配置唯一来源**：只从 Freeze JSON 生成配置，CLI 无性能 override。
5. **一次性**：attempt ledger 记录唯一一次 attempt；active/completed/failed_system 禁止第二次；invalid_infrastructure 也需 Reviewer audit 才能替换。
6. **preflight**：真正打开 sealed 前先 dry-run（0 LLM/0 retrieval/0 embedding、不读 holdout、不开 manifest、不建 index、不创建 attempt）。

一句话总结："Freeze 锁住'系统是什么'，09A 锁住'怎么只用它一次'。"

---

## 边界声明

- 未读取/搜索 gate3/sealed；09A 全程只用 tmp_path / synthetic fixture / 公开 freeze JSON。
- 0 LLM / 0 Retrieval / 0 Embedding / 0 Index / 0 Holdout / 0 sealed 读取。
- preflight 未创建正式 attempt ledger entry；未创建 output-root。
- 09A 完成后停住；未运行 --phase generate；实际 Holdout 待 09B 授权后执行。
