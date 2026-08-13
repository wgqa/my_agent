# 65-Gate3数据集划分、Holdout封存与泄漏防护

> G3-DATA-02C：Gate 3 评测数据集的 24/12 分层划分、最终封存与访问隔离。本文面向用户从头学习，不是执行日志。
> 数据身份见 `docs/experiments/gate3_data_freeze.json`；实时状态见 `docs/status.md`。

## 1. 为什么 AI 项目需要评测集

AI 系统的行为来自训练/配置与检索策略的无数决策。没有评测集，你会陷入两个陷阱：

- **凭感觉判断好坏**：改一行 Prompt、调一个 Top-K，你觉得"好像更好了"，但这是主观、不可复现的。
- **过拟合到你的判断**：你在几个例子上把系统调到完美，遇到没见过的真实问题就打回原形。

评测集把"回答质量"变成**可量化、可复现、可回归**的指标（正确率、Recall、nDCG 等），让你能回答："这次改动到底是变好还是变差，幅度多大，在哪些类型上变好。"

本项目是"个人技术学习助手"：用固定语料（37 个笔记文件）+ 固定问题集，评测 RAG 的检索与规划策略是否真的有效，而不是靠"感觉回答得不错"。

## 2. Train / Dev / Test / Holdout 的区别

- **Train**：模型训练用的数据。本项目不训练模型，所以没有 Train 集。
- **Dev（开发集）**：开发和调参时反复使用的数据。你可以看它的逐条结果、分析失败原因、调整策略。**Dev 上的分数可能被"调高"，因为它参与了你的决策**。
- **Test（测试集）**：阶段性最终比较用，不拿来持续调参。一旦你看着 Test 结果继续调，Test 就"变成了" Dev。
- **Holdout（封存集）**：只运行一次、只用于最终泛化证明的独立数据。它在整个开发阶段被物理/流程隔离，任何基于它的调参都会使其失效。

一句话：**Dev 用来"做事"，Holdout 用来"证明"**。完成 Dev 开发后，可以按预注册协议运行一次 Holdout；只有看着 Holdout 结果继续修改系统、调参或反复重跑，才构成 Holdout 污染。

## 3. 本项目为什么是 24 Dev + 12 Holdout

设计文档 §3.2 规定：36 条新问题 + 24/12 分层 split，holdout 至少 7 条多义务。

- **36 条** = 全部题型配额（comparison 8 / multi_entity 6 / causal 6 / troubleshooting 4 / fact 3 / code_symbol 3 / unanswerable_or_no_retrieval 6）。
- **24 Dev**：足够覆盖全部 7 种 query_type 与 3 种 answerability，支撑实现阶段的多轮迭代与失败分析。
- **12 Holdout**：承担最终泛化证明。2:1 是常见规模——开发侧样本多，封存侧样本精。
- **分层（stratified）**：不是随便挑 12 条，而是按题型/answerability/复杂度/领域**配额分配**，防止把复杂题全部堆进 Dev 或全部丢进 Holdout。Holdout 中多义务题 ≥7 条，保证能测出"需要多文档检索"的能力。

## 4. 什么是 Goodhart 定律

> "当一个指标成为目标时，它就不再是好指标。" —— Goodhart's Law

例子：

- 你优化"回答长度"，模型就开始输出长篇废话。
- 你优化"Judge 打分"，模型学会迎合 Judge 的偏好（长度、格式）而非真正正确。
- 你优化"Dev 分数"，Dev 上的调参会抹掉"泛化"信息。

本项目里最关键的应用：**Dev 指标不是最终结论**。如果你在 Dev 上把检索/Router 调到 100 分，这不能证明系统好——只证明它记住了这 24 条。真正的结论必须来自没参与任何调参的 Holdout。

## 5. 什么是数据泄漏

数据泄漏 = 评测信息"渗透"进了系统构建过程，导致分数虚高或失真。典型形态：

- **题面泄漏**：评测问题出现在 Prompt 示例、训练集或调参过程里。
- **答案泄漏**：评测集的答案/Gold 被模型或规则"看到"。
- **标签与目标泄漏**：Holdout 的 Gold、answerability、预期路由、decomposition_expected 或划分归属进入实现流程。
- **调参泄漏**：用 Holdout 结果决定下一步调参方向。

泄漏的后果不是"假阳性"这么简单——它会让你的结论**在任何真实场景都不可信**。本项目用"封存 + 流程隔离 + 只运行一次"来控制泄漏。

## 6. exact duplicate、near duplicate、semantic leakage 的区别

- **exact duplicate（完全重复）**：两条 query 字节完全相同。直接脚本比对即可发现。
- **near duplicate（近似改写）**：措辞不同但明显是同题（改换说法、增减虚词）。需要人看或字符串相似度。
- **semantic leakage（语义泄漏）**：问题不同、措辞不同，但**考察同一事实/同一答案模板**，或一条的 description 直接透露另一条的答案。这是最难防的，必须人工判断。

本项目审计时三个层次都查：脚本查 exact，人工扫 near，逐个审六组"相邻高风险对"查 semantic。结论：跨 Dev/Holdout 无 exact、无 near、无语义等价。

## 7. 为什么同一 relevant_file 不一定构成泄漏

两个 Case 都指向同一个文档，不一定泄漏。判断泄漏的标准是**是否考察同一个知识点**：

- 反例（不算泄漏）：同一技术文档可能同时包含容量规划、索引更新、权限模型等多个独立章节。Dev 与 Holdout 即使引用同一文件，只要 required obligation 不同、答案事实不等价，就不自动构成泄漏。
- 正例（算泄漏）：两条题都问"为什么 embedding 升级要重建索引"，只是换了个问法——泄漏。

所以审计规则是：**相同 relevant_file 不自动判定为泄漏；同领域、同文档但考察不同知识点允许存在。**

## 8. 什么是预注册 split

预注册（pre-registration）= 在**看到任何实验结果之前**，先固定：划分方案、指标、评测集身份。

本项目：`selection_time_relation = before_gate3_implementation_and_metrics`。36 条问题造好后，在实现 Query Planner/Router 之前，Reviewer 就预注册了 24/12 划分（`reviewer_prescribed_stratified_v1`），并算出 `split_candidate_id`。这样：

- 划分只依据题型/answerability/复杂度，**不依据模型效果**——杜绝"哪个结果好就多留哪条"。
- Holdout 内容在实现开始前就被隔离，实现 Agent 无法"无意中"优化到它。

## 9. evaluation_set_id、SHA-256、freeze ID 分别解决什么问题

- **SHA-256（字节身份）**：文件内容的密码学指纹。两个文件字节完全相同 ⇔ SHA 相同。保证"这份文件就是当初那份"。
- **evaluation_set_id（语义身份）**：对规范化 Case 语义的哈希（本项目 `_compute_id`：schema_version + corpus_id + 全部 to_dict 的 Case，JSON sort_keys 序列化后 SHA 前 12 位）。**它绑定语义，不绑定文件字节**——所以换成 canonical 序列化（sort_keys）后 id 不变。解决"评测集是什么"。
- **gate3_dataset_freeze_id**：把"整个数据冻结"（corpus + combined + split + dev + holdout 的全部身份）打包成一个指纹。一次对比即可确认"整套数据是否被改动"。解决"整套冻结状态是什么"。

三者分工：字节指纹保证文件没被换；语义指纹保证评测内容没被改；freeze ID 把多个指纹聚合成一个可引用的整体身份。

## 10. 语义身份与字节身份为什么不同

`evaluation_set_id` 是**语义身份**，`jsonl_sha256` 是**字节身份**。

- 同一个评测集，只要语义（case 内容）相同，哪怕文件换行符、JSON 键序、缩进不同，evaluation_set_id 不变——语义没变。
- 但只要任何一个字节变了，SHA-256 就变。

为什么需要两者？因为：

- 想确认"评测内容没被改"，用语义身份（evaluation_set_id）。
- 想确认"这份文件就是我当初封存的那份、没被替换/重排"，用字节身份（SHA）。

本项目 R1-MICRO 就是例子：把序列化改成 canonical（sort_keys=True）后，**SHA 变了（字节变了），evaluation_set_id 没变（语义没变）**。这恰好证明了两个身份各管各的。

## 11. 为什么 JSON canonicalization 很重要

同一份数据，如果不规定统一的序列化方式，会产生"同一内容、多种字节形态"：

- 键序不同（`{"b":1,"a":2}` vs `{"a":2,"b":1}`）。
- 分隔符不同（`, ` vs `,`）。
- 换行不同（LF vs CRLF）。
- 转义不同（`ensure_ascii=True` 会把中文转成 `\uXXXX`）。

后果：字节哈希不稳定，同一语义产生多个"字节版本"，身份核对会误报或漏报。

Canonicalization（本项目 `python_json_sort_keys_compact_v1`）规定：

- 解析 JSON → `json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。
- UTF-8、无 BOM、LF、每条后一个 LF、末尾一个 LF。

这样任何人在任何平台生成 Dev/Holdout 文件，得到的字节都完全一致，SHA 才可复现、可核对。

## 12. sealed evaluation 的正确使用流程

正确顺序（本项目）:

1. 冻结语料（corpus_id）。
2. 构建问题集（36 条，含 Gold）。
3. 预注册 24/12 split（不依据任何模型效果）。
4. 生成 Dev（公开）与 Holdout（私有），算出各自 evaluation_set_id 与 SHA，算出 freeze ID。
5. 封存 Holdout（迁移私有历史、只读、流程隔离），登记公开 freeze。
6. 实现 Agent 只拿 Dev 开发、调试、调参、晋级。
7. **功能和 Dev 晋级条件全部满足后**，由**独立评测会话**对 Holdout 运行一次。
8. 保留首次结果，不得因结果不好而删除重跑或调整后再跑。

若在第 7 步之前，Holdout 内容被实现 Agent 读到、或基于 Holdout 结果调过参，该 Holdout **立即失效**，必须重新生成并换新 evaluation_set_id。

## 13. 为什么单机项目只能做到流程隔离

隔离有层次：

- **密码学隔离 / 独立 OS 账号 / ACL**：操作系统级权限强制，不同账号互相看不到文件。
- **流程隔离（process-isolated same-OS-user）**：同一个操作系统用户下，靠**目录约定 + 会话纪律 + 流程步骤**隔离。它不宣称阻止"同账号下用 root 权限去读"，而是约束"谁该看什么"。

单机个人项目没有多账号/沙箱，所以本项目明确声明 `isolation_level = process_isolated_same_os_user_v1`，局限为 `not_cryptographic_isolation` 与 `not_separate_os_account`。诚实声明"能做到什么、不能做到什么"，比假装"绝对安全"更重要。

## 14. 如果实现 Agent 看到 Holdout，为什么必须宣布封存失效

Holdout 的价值在于"从未被系统构建过程接触过"。一旦实现 Agent 读到它的 query/Gold：

- Agent 的后续实现决策（哪怕是无意的）会受这些内容影响——等于"预看了测试答案"。
- 之后跑出的分数不再是无偏的泛化估计，而更像"背答案"。

所以规则是：**任何实现 Agent 读取过 Holdout 内容 → 该 Holdout 立即失效**，必须用新的 evaluation_set_id 重建并重新封存。这不是惩罚，而是保护"这个数字还可信"。

本项目同样规定：**数据构建 Agent（当前执行者）知道 Holdout 内容，因此必须永久退出实现阶段**，实现必须由全新的、只拿到 `gate3/dev/` 和公开 freeze 的 Agent 会话承担。

## 15. 本项目目录和文件职责

```
benchmark_work/gate3/
├── dev/                        # 唯一公开开发数据（实现 Agent 只允许读这里）
│   ├── gate3_dev_v1.jsonl      # 24 条 Dev Case（canonical JSONL）
│   ├── dev_manifest_v1.json    # Dev 冻结身份（evaluation_set_id / SHA / 分布）
│   └── README.md               # 使用边界说明
└── sealed/                     # 私有最终评测数据（实现 Agent 禁止读）
    ├── gate3_holdout_v1.jsonl  # 12 条 Holdout Case（私有）
    ├── private_manifest_v1.json# 私有身份 + 访问策略 + 失效条件
    ├── README_PRIVATE.md       # 私有说明（不含题目正文）
    └── history/                # 数据构建历史（drafts、split_work）
```

主仓库（`docs/experiments/gate3_data_freeze.json`）只登记**公开安全元数据**：corpus、combined、Dev、Holdout 的 id/SHA/分布、freeze ID——**不含任何 Holdout case_id、query 或 Gold**。`holdout_case_ids_omitted = true`。

## 16. 常见错误案例

1. **拿 Holdout 调参**：看了一条 Holdout 结果就改 Top-K → Holdout 已污染，分数虚高，结论不可信。
2. **同题换写法放进两个集**：Dev 问"RoPE 编码相对还是绝对"，Holdout 问"RoPE 编码的是什么位置关系"——near duplicate，泄漏。
3. **用同一文档当两个集的不同题但同一知识点**：都问"为什么 embedding 升级要重建索引"，只是换了主语——semantic leakage。
4. **改了 Gold 不重算身份**：改了一个 Case 的 relevant_files 但沿用旧 evaluation_set_id——身份与实际内容不一致，审计发现会直接失败。
5. **把 Dev 分数当最终结论**：在 Dev 调到 100%，声称系统很行——没有 Holdout，等于没有泛化证据。
6. **自己给自己划定 split**：看到部分结果后决定"这几条放 Dev 那几条放 Holdout"——划分被实验结果污染，必须预注册。
7. **字节哈希不稳定**：同一内容生成两次 SHA 不同（换行/键序差异）——没有 canonicalization，身份核对无法复现。

## 17. 面试官可能追问的问题与参考回答

**Q：Train/Dev/Test/Holdout 各干什么？你项目里为什么没有 Train？**
A：Train 是给模型学的；本项目不做模型训练，所以没有 Train。Dev 用于开发和调参，Test 是阶段性比较，Holdout 是只运行一次做最终泛化证明的封存集。我项目用 24 Dev + 12 Holdout，Dev 负责把系统"做对"，Holdout 负责证明"真的对"。

**Q：你凭什么说你的评测没泄漏？**
A：三层控制。第一，划分是**预注册**的，在实现和任何指标运行之前就由 Reviewer 固定，只依据题型/answerability/复杂度。第二，做了 exact/near/semantic 三层审计，并对跨集相邻高风险对逐一人工核对。第三，Holdout 物理封存在私有目录、只读、流程隔离，实现 Agent 拿不到。任何一层被破坏都会宣布封存失效。

**Q：evaluation_set_id 和 SHA-256 有什么区别？**
A：SHA 是字节身份——文件一个字节不同就不同；evaluation_set_id 是语义身份——只要 Case 语义不变，哪怕换成 canonical 序列化字节变了，id 也不变。一个证明"文件没被换"，一个证明"内容没被改"。

**Q：单机项目没有多账号，你的隔离可靠吗？**
A：不可靠到"密码学/独立账号"级别，所以我明确声明它是**流程隔离**：靠目录约定 + 会话纪律 + 只读属性。诚实声明局限比假装绝对安全重要。真正的强隔离需要独立账号/沙箱，本项目诚实标注了这个边界。

**Q：如果实现 Agent 看到了 Holdout 怎么办？**
A：该 Holdout 立即失效。它失去了"未被接触"这个最核心属性，之后跑的分数不能证明泛化。必须重建并重新封存、换新 id。所以本项目规定数据构建 Agent 知道 Holdout，就必须永久退出实现阶段，实现交给全新会话。

## 18. 用户可以亲手完成的练习

1. 用 `json.dumps` 对比 `sort_keys=True` 前后同一个 dict 的字节——直观理解 canonicalization 为什么让 SHA 可复现。
2. 修改一个 Dev Case 的一个字，重算 evaluation_set_id 与 SHA——观察语义身份与字节身份分别怎么变。
3. 自己给 5 条问题写"near duplicate"改写，再判断哪些是泄漏、哪些只是同领域不同题。
4. 找两个同 relevant_file 的 Case，判断是否泄漏——练习"同一文档 ≠ 同一知识点"。
5. 读 `docs/experiments/gate3_data_freeze.json`，说出 Dev/Holdout 的 id、SHA、分布各是什么，为什么这些是"公开安全"的。
6. 模拟一次"用 Holdout 调参"的后果：设想调了一条后分数变高，解释为什么这个分数不可信。

## 19. 30 秒、2 分钟和 5 分钟项目讲解版本

**30 秒**：我给 RAG 助教造了 36 条评测题，24 条公开给开发调参、12 条封存起来只用于最终验证。划分在写任何代码之前就定好，封存题对实现 Agent 不可见，只允许独立最终评测会话读取一次，最后独立跑一次证明系统真的会泛化，而不是背题。

**2 分钟**：RAG 系统改参数容易"自我感觉良好"，所以需要固定评测。我按题型和可答性做了 24 Dev + 12 Holdout 的分层划分，划分是预注册的、不看模型效果。Dev 用来开发调试，Holdout 用流程隔离封存（私有目录 + 只读 + 只运行一次）。我用 SHA 管字节身份、evaluation_set_id 管语义身份、freeze ID 聚合整套冻结身份。泄漏靠 exact/near/semantic 三层审计防。诚实声明这是单机流程隔离，不是密码学隔离。

**5 分钟**：完整讲 Train/Dev/Test/Holdout 区别 → 本项目 24/12 与分层配额 → Goodhart 定律与为何 Dev 指标不算数 → 数据泄漏的三种形态与审计 → 预注册 split → 语义身份 vs 字节身份 + canonicalization → sealed evaluation 的正确流程与失效条件 → 单机流程隔离的诚实边界 → 实现/评测 Agent 的职责分离。

## 20. 与后续 Query Decomposition / Adaptive Retrieval 实验的关系

- Gate 3 评测协议（G3-DESIGN-01，study-note 63）定义 QueryPlan/Planner/Router 等**业务对象**；本笔记封存的是**评测数据**（谁来做，用什么量，怎么隔离）。
- 后续实现（G3-PLAN/DECOMP/MRETR/ADAPT）只用 **Dev** 开发与晋级；达标后由**独立会话**在 **Holdout** 上运行一次做最终泛化结论。
- 实现 Agent 的输入面：项目仓库 + `gate3/dev/` + `docs/experiments/gate3_data_freeze.json`（公开版）。
- Holdout 的 `evaluation_set_id`、`gate3_dataset_freeze_id` 会与实现冻结的 QueryPlan/Router 配置一起，构成 Gate 3 run 的完整可复现身份（设计文档 § 关于 gate3_run_id 的部分）。
- 结论边界：所有 Gate 3 结论必须限定"该冻结语料 + 该 holdout"，不推广为跨语料通用规律。
