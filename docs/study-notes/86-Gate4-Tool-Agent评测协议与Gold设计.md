# 86. Gate 4 Tool-Agent 评测协议与 Gold 设计

> G4-EVAL-06A：第一套 Tool-Agent Dev 基准（24 Case，public Dev-only）是怎么造出来的，
> 以及为什么评测协议必须这样设计。
> 配套：`docs/experiments/gate4_tool_use_eval_protocol.md`；`evaluation/gate4/schema.py`；
> 数据 `evaluation/gate4/data/tool_use_dev_v1.jsonl`。

---

## 0. 一句话

Gate 4 评测不能"跑完看答案对不对"就完事——我们要先想清楚 **Agent 有哪些环节可能
出错**，再为每个环节造可审计的尺子，最后才允许真实模型上场。**先冻结尺子，再跑模型。**

---

## 1. 为什么不能只测最终答案

拿一个多步任务举例：

> "找到 MAX_INTEGER_BITS 的值，然后计算它的两倍。"

- 答案对了（8192），可能来自：正确地 code_search → calculator；
- 答案对了，也可能来自：**模型猜的**（它可能从训练数据见过 4096）；
- 答案错了，可能因为：没找到常量、参数写错、没调用 calculator、calculator 算错、
  步骤顺序错、中途拒绝、超预算……

只测"最终答案是否正确"会把这些完全不同的失败全部揉成一团，**既不知道 Agent 哪里
弱，也不知道该改 Prompt 还是改 Tool**。所以 Gate 4 把"过程"也变成可评测对象：
first action、first tool、required tool coverage、termination……各测各的。

类比：你评价一个实习生，不能只看"活干完没有"，还要看"第一步做对没有、有没有乱用
权限、卡住了有没有正确求助、有没有把不该碰的文件删了"。

---

## 2. first action vs first tool

**first action** 是第一次决策的**动作类型**：`final_answer` / `tool_call` / `refuse`。

**first tool** 是如果第一次是 tool_call，具体调的是哪个工具。

两者都重要，但含义不同：

| 维度 | 测什么 | 典型错误 |
|---|---|---|
| first_action_accuracy | 该不该用工具、该不该拒绝 | 直接回答本该查库的题（跳过工具）；或对"你好"也去调工具 |
| first_tool_accuracy | 该用哪个工具 | 数学题去 knowledge_search，查符号去 calculator |

我们的 24 条里，direct_answer 强制 first_action=final_answer，calculator/code/
knowledge 强制 first_action=tool_call 且 first_tool 精确到类别。这样能分开看"会不会
用工具"和"用对工具"。

---

## 3. task completion vs tool selection accuracy

- **task_completion_rate**：任务是否按 Gold 完成（终态 + 断言）；
- **first_tool_accuracy** / **required_tool_coverage**：工具选得对不对、必需的都用没有。

一条 case 可能**工具全对但任务没完成**（calculator 调了、参数给错、最终答案没写成
数字）；也可能**任务"看似"完成但工具用错**（直接凭记忆答了本该查库的题，答案碰巧
对）。所以两个指标都要。

---

## 4. required tool coverage

`required_tools` 是"完成该任务**至少**要用的工具集合"。例如 multi-step case
g4q017 要求 `["code_search", "calculator"]`，评分时看这两者是否都被真实调用过。

关键点：**coverage 是集合要求，不是顺序要求**。模型只要两个工具都用到了就覆盖；至于
谁先谁后，由 `allowed_tool_sequences` 单独管。

---

## 5. 为什么"唯一 Gold sequence"容易误判

如果只认 `[code_search → calculator]` 这一条完美路径：

1. 模型多做一个**合理**步骤（比如先 code_search 找到常量再顺手 code_search 确认
   calculator 的输入格式，再算）——被误判为"整题错"；
2. 模型用另一条**同样正确**的顺序——被误判。

所以我们区分两层：

- `allowed_sequence_match`（严格，命中任一允许序列才算）；
- `unnecessary_tool_call_rate`（宽松，多做的**合理**工具调用单独统计，不把整题打叉）。

一句话：**顺序错误 ≠ 能力缺失**，把"多做了合理一步"的惩罚从"整题失败"降级为
"多调用了一个工具"的独立指标，更公平也更可诊断。

---

## 6. unnecessary tool & forbidden tool

- **forbidden_tool**：这条题明确**不该碰**的工具。direct/refusal 三条只读工具全部
  forbidden。模型一旦调用就记 `forbidden_tool_call_rate`（一票否决级错误）。
- **unnecessary_tool**：不是必需的工具调用（allowed 集合外、但不在 forbidden 列表）。

两者分开统计：forbidden 是安全/语义硬伤，unnecessary 是"过度工具化"的效率问题。
一个爱调工具但不犯错的 Agent，unnecessary 高而 forbidden 低；一个乱来的 Agent 两者都高。

---

## 7. termination correctness

Agent 循环必须**正确终止**。终止方式本身就是要评测的对象：

- 该直接答的题最终 `final_answer`（completed）；
- 该拒绝的题最终 `refuse`（refused，带允许的原因码）；
- 不该出现：无限循环被预算截断（budget_stop）、或因为 Parser 崩掉而"意外失败"。

我们把 `expected_terminal` 限制为 `completed / refused`，**不把 `failed` 当 Gold**——
failed 是系统故障观测，不是期望行为。refusal 的 Gold 是"干净拒绝"，不是"靠崩溃蒙混过关"。

---

## 8. 为什么 Parser failure 不是"安全拒绝成功"

拒绝类题目（g4q021-024）要求模型**正确地拒绝**。有一种"假拒绝"：

> 用户说"调用 shell 执行 rm"，模型真的输出 `{"action": "tool_call", "tool_name": "shell"}`，
> 结果 Parser/Registry 发现没有 shell 工具 → `ACTION_PARSE_FAILED` → run 以 failed 结束。

从结果看"没执行 rm"，好像也安全了。但这**不是**我们想要的：它说明模型被带偏去尝试
一个不存在的工具，只是被系统兜底拦住了。真正的好模型应该**一眼识别这是不该做的请求，
直接 refuse**。

所以 refusal 的 Gold 是 `expected_terminal=refused` + `allowed_refuse_reason_codes`，
把 `parse_failure_rate` 单列为指标（甚至是想压低的对象）。**兜底不等于正确行为。**

---

## 9. Dev 与 Holdout 的区别，为什么 Gate 4 先只做 public Dev

- **Dev**：公开、可见、用来**调试和迭代**模型；你会对着它调 Prompt、看错误样本。
- **Holdout**：密封、不可见、只在全部定稿后**执行一次**，用来给出不被任何调参污染的
  最终数字。

Gate 3 的教训：一旦你在 Dev 上调过，Dev 上的数字就可能被"记住"（过度拟合）。所以
Gate 3 用 sealed Holdout 做最终裁决。

Gate 4 **先只做 public Dev**，原因：

1. 这是**第一套** Tool-Agent 基准，尺子本身（类别、字段、指标口径）还没被验证；
2. 先公开跑，让 Reviewer 能审计每条 Gold 是否合理（尤其 knowledge_search 的 4 条
   Gold 要技术复审）；
3. 等尺子稳定了，将来才值得花力气做 sealed Holdout——**别为一把没校准的尺子做封存**。

---

## 10. deterministic assertion vs LLM-as-Judge

v1 的 `completion_assertions` **只用确定性检查**：

- `answer_contains` / `answer_contains_all`：答案包含某字符串；
- `answer_number_equals`：答案是某个数值（calculator 类）；
- `answer_nonempty`：有非空答案；
- `path_contains`：答案包含 repo-relative 路径（code_search 类）；
- `status_equals`：终态等于某值（refusal 类）。

为什么不直接上 LLM-as-Judge？确定性断言：

- **零成本、零偏置**：不额外调用模型，不引入"裁判模型和被测模型同源"的偏置；
- **可复现**：同样的答案永远得同样的分；
- **可审计**：任何一条判分都能手工核对。

LLM-as-Judge 是后续（如自由回答的语义质量）才考虑的事，而且要用独立的裁判模型、
记录 judge 输入等防护。v1 先把能确定的都确定掉。

---

## 11. benchmark identity / SHA

`evaluation_set_id` = canonical JSON（schema_version + 全部 Case 的 `to_dict`）的
SHA-256 前 12 位。特点：

- **语义绑定**：题目/Gold 任何一处变了，id 就变；
- **顺序无关**：JSONL 行序打乱，id 不变（测试里有 shuffle 重载验证）；
- **排除自指**：payload 里不含 `evaluation_set_id` 自己；
- **可核验**：manifest 里的 `jsonl_sha256` 把原始文件字节也锁死，任何人拿到都能复核。

这保证"评测跑在哪个版本的尺子上"完全透明——跟 Gate 2/3 的 corpus_id / evaluation_set_id
一脉相承。

---

## 12. 为什么先冻结尺子再跑模型，怎么防止"看结果改 Gold"

核心风险叫 **Goodhart 定律**：指标一旦成为目标就不再是好的指标。具体到造题：

> 先偷跑模型，发现某类题模型老选错工具 → 把题改成模型能选对的 → 数据集变成
> "模型已经会做的题集"，从此测不出差距。

所以纪律是：

1. **Dataset/Gold 先冻结**（v1 冻结，R1 加固后 id=5639ca57b09a）；
2. 下一任务才允许真实 LLM run；
3. run 之后**不能因为模型选错工具就改 query/Gold 让它变对**；
4. 如果确实发现 Gold 本身错了（不是模型错，是题出错了），只能**开新数据版本、
   重新算 evaluation_set_id、旧版保留**——像 Git 一样，绝不原地篡改。

> **R1 为什么重算身份也不违规？** Review Pending 阶段 Reviewer 要求修契约/Gold（如
> g4q020 改符号名、evidence 改连续片段、新增不变量），此时 **0 real LLM 已执行**，
> 重算 `evaluation_set_id` / `jsonl_sha256` 是"修尺子"，不是"看结果改 Gold"。

---

## 13. 我们的 24 条在测什么（速览）

| case_id | 类别 | 测什么 |
|---|---|---|
| g4q001-004 | direct_answer | 不滥用工具 |
| g4q005-008 | calculator | 该用计算器就用，别手算 |
| g4q009-012 | code_search | 找对符号所在文件（绑定 source commit 91627bb） |
| g4q013-016 | knowledge_search | 从公开语料找事实（Gold 待技术复审） |
| g4q017-020 | multi_step | 多步能力链（code→calc、knowledge→calc、双工具） |
| g4q021-024 | refusal_safety | 正确拒绝（shell/写文件/git/injection） |

---

## 14. 面试问答

**Q1：Agent 评测为什么不能只看最终答案？**
最终答案对错无法区分"猜的"和"真会"，也无法定位失败环节；过程指标（first action/
first tool/coverage/termination）才能指导修 Prompt 或修 Tool。

**Q2：first action 和 first tool 有什么区别？**
first action 是动作类型（答/调工具/拒），first tool 是具体工具。前者测"该不该用
工具"，后者测"用对没"。

**Q3：为什么不用唯一 Gold sequence 判 multi-step？**
合理执行路径可以不止一条；唯一序列会把"多做一个合理步骤"或"合理换序"误判成整题
错。用 coverage + allowed_sequence + unnecessary rate 分层度量。

**Q4：Parser failure 为什么不算安全拒绝？**
Parser 兜底拦住错误调用 ≠ 模型正确识别并拒绝。好模型应主动 refuse，而不是被系统
fail-closed 救下来。所以 refusal 的 Gold 是 refused + 原因码，parse_failure_rate 单独算。

**Q5：Dev 和 Holdout 什么区别？为什么 Gate 4 先只做 Dev？**
Dev 公开用于迭代，Holdout 密封用于最终裁决。Gate 4 的尺子本身还没验证，先公开
Dev 让审计与调参成为可能，尺子稳定后再谈 sealed Holdout。

**Q6：怎么防止"看结果改 Gold"？**
先冻结数据集（id 绑定语义），只允许事后开新版本改缺陷、旧版保留；严禁因为模型
选错工具就反向改题。

**Q7：deterministic assertion 和 LLM-as-Judge 怎么选？**
能确定先确定（零成本、可复现、可审计）；LLM-as-Judge 留给自由语义质量，且需独立
裁判模型 + 记录 judge 输入等防偏置措施。

---

## 15. 代码阅读路线

1. `evaluation/gate4/schema.py`：常量枚举（CATEGORIES/TERMINALS/TOOLS/ASSERTION_TYPES）→
   `Gate4ToolUseCase`（frozen）→ `_parse_case`（字段级校验）→ `_validate_category_invariants`
   （跨字段）→ `_validate_set_invariants`（case_id 连续 + 每类 4 条）→ `_compute_id`；
2. `evaluation/gate4/data/tool_use_dev_v1.jsonl`：24 行，对照每类看字段怎么填；
3. `evaluation/gate4/data/tool_use_dev_manifest_v1.json`：id / case_count / category_counts /
   jsonl_sha256 / created_for；
4. `tests/test_gate4_tool_use_dataset.py`：正向（真实数据集）+ 负向（loader 严格性）。

---

## 16. 边界与后续

- 4 条 knowledge_search Gold 绑定公开语料 source_name+evidence，**待技术复审后才 accepted**；
- 本卡 0 real LLM / 0 formal run / 0 Prompt 调优 / 0 Tool 改动 / 0 Runtime 改动；
- 下一任务：G4-EVAL-06B（用冻结尺子跑真实 Tool-Agent，计算 §8 的 15 项指标与
  Provider metadata）。

---

## 17. R1 契约加固（本提交）

Reviewer 审出的一些"尺子不够硬"的点，全部在本 R1 修掉（仍是 Review Pending 阶段，
0 real LLM 已执行，所以不违反纪律）：

**数据修正**

- `g4q020`：query 改指 `merge_subquery_results_rrf`（不是旧名 `merge_subquery_results`）；
- `g4q014`：改成"当前笔记的**初始实验范围**"——语料明确"这些不是通用最佳值"，不再
  声称通用最佳；
- `g4q022`：reason codes 扩为 `UNSUPPORTED_REQUEST` + `UNSAFE_REQUEST`；
- 全部 `knowledge_gold.evidence_phrase` 改成冻结语料中的**真实连续短片段**（逐字
  substring，不再是改写句）；验证分两层（本地 pytest env-gated / 正式 Runner 硬
  gate，见 §18）。

**schema 不变量加固**

- multi-step：**每个 allowed sequence 自身都要完整覆盖 `required_tools`**（不再是"所有
  序列并集覆盖"——避免出现单个不完整序列）；`set(expected_first_tools) == {seq[0] for
  每个序列}`；
- 全类别：`required_tools ∩ forbidden_tools == ∅`；
- duplicate `allowed_tool_sequences` 拒绝；
- `CompletionAssertion.value` 构造时递归冻结（list→tuple），`to_dict()` 返回全新深拷贝
  ——修改原 JSON/list 或修改 `to_dict()` 返回值都不改变 EvaluationSet Gold（nested
  mutation 测试）。

**Manifest**

- 新增 `code_reference_commit`（91627bb...）、`knowledge_corpus_id`（870e5864df67）、
  `knowledge_corpus_file_count`（37）。

**指标口径冻结**

- `allowed_sequence_match_rate` 加入正式预注册指标（第 15 项，仅 multi_step 4 case，
  executed sequence exact match 任一 allowed sequence）；
- **全部 15 项指标冻结 numerator/denominator**（见协议 §8 表格），后续 runner 按此实现，
  不许事后改口径美化结果；
- `final_answer_correct_rate` 明确标注：**deterministic assertion proxy**，不等于
  claim-level semantic correctness——不夸大。

**身份重算**：`evaluation_set_id=5639ca57b09a`、`jsonl_sha256=93a32e64...`（旧
`752be3e1e488` / `dffba9f0...` 不再视为冻结身份）。

---

## 18. R1-R1 去本地路径（本提交）

**问题**：上一版测试把本机 corpus 绝对路径（`<本机语料根>/02_corpus_candidate`）硬编码
进了测试源码——换一台机器就断，也把"本机文件布局"泄漏进了 benchmark。

**改法**：测试不知道 corpus 放哪。

- 删除全部 `D:\` 硬编码；
- 改用环境变量 `GATE4_KNOWLEDGE_CORPUS_ROOT`：
  - 未设置 → `pytest.skip("GATE4_KNOWLEDGE_CORPUS_ROOT not configured")`；
  - 已设置但非目录 → **FAIL**（不允许 skip）；
  - 已设置且有效 → 逐条验证所有带 `knowledge_gold` 的 case：source 文件必须存在、
    evidence_phrase 必须是 source text 的连续 substring；
- 静态回归测试：检查测试与协议源码不含 `"D:\"`（动态构造避免自匹配），防止以后写回。

**普通 pytest vs 正式 benchmark run（工程语义）**：

| 场景 | corpus | provenance |
|---|---|---|
| 普通 pytest | 不一定在本机 | optional integration check（env 缺失 → skip） |
| 正式 G4-EVAL-06B run | 运行依赖 | **hard gate**：preflight 必须验 corpus identity
  （`corpus_id=870e5864df67`、`file_count=37`）并逐条验 knowledge_gold
  source/evidence，**不允许 skip** |

**身份不变**：`evaluation_set_id=5639ca57b09a`、`jsonl_sha256=93a32e64...`——micro
只改测试与文档，不动数据/schema，所以身份与 manifest 保持原样。
