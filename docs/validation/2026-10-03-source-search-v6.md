# 2026-10-03：范围搜索候选验证与未晋升决定

## 结论

`code_search_v6` 候选已完成：增加可选 repo-relative 文件/目录 `scope`，返回规范化范围与真正的 `truncated`。**局部回归通过，但真实 Agent 的改善没有得到证明，因此默认搜索保留 code_search_v5。** 不把没有模型使用记录的新参数直接作为项目能力提升。

实现与对照材料集中在 [evaluation/source_search_v6_20261003](../../evaluation/source_search_v6_20261003/README.md)，不另建技术债总表。长期 Task / Evidence / Execution 契约、memory、Dense/Hybrid、写入及沙箱均未实施。

## 范围与安全

- `scope` 可为单文件、目录或 `.`；缺省仍搜索整个绑定项目，合法但不存在的路径返回空集，不回退全仓库。目录组件边界明确，`src` 不包含 `src_backup`。
- 只做 case-insensitive literal substring 搜索；kind 枚举仍是 any/project_code/project_doc。`project_test` 继续归 `find_tests → read_project_context`。没有 AST 排名、测试符号匹配或全局屏蔽 examples。
- 保持 path/line 顺序、最大 10 条、每行 300 字符、每文件 1 MiB 上限。恰好 10 个有效匹配不算截断，必须发现第 11 个**有效匹配**；跨文件 lookahead 也必须遵守 scope/kind/文件限制。`truncated` 只说明匹配条数上限，不能证明不可读/超限文件也已覆盖。
- 禁止绝对路径、盘符、UNC、`..`、控制字符、ADS；检查每个祖先，避免显式 scope 绕过隐藏/排除目录、凭证文件和 symlink/junction 限制。实测后保留候选另补了 Windows 末尾点/空格及目录大小写别名拒绝，未覆盖实测快照。
- 默认 Handler 已逐字节恢复到开发开始时的 v5 快照，原有共享分类等未提交修改保留。现有 Rich Activity 仅增加安全 scope/truncated 摘要白名单，兼容没有这些字段的 v5 观察；不输出原始观察、绝对路径或模型推理。
- 5 次逻辑决策、4 次工具调用、2 次工具错误，以及 Runtime、Planner、Router、Verifier、Decision 主 Prompt、当前 Reader v2 均保持本轮开始时的实现。

## 局部验证

最终执行 9 个相关测试文件，**193 passed / 7 skipped / 3 existing warnings，7.96 秒**。覆盖候选 scope 与安全边界、真实工具、kind filter、历史身份及 harness、Rich Activity、项目挂载、Reader v2 与搜索后读取的预算闭环。7 个跳过是本机无 symlink 创建权限；Windows junction 的仓库内/外两个实际测试通过。没有全量 pytest 或完整 CI job。

初次局部回归为 184 passed / 7 skipped / 2 failed：一项新测试误用 evidence 的字段名，另一项暴露历史 v5 身份校验依赖当前 live version。前者修正测试；后者把历史期望锁定为 v5，仍通过固定旧 checkout 探测，并明确拒绝 v6 冒充历史候选。历史 manifest、dataset、冻结 SHA 和结果未重标。中间候选回归 188 passed / 7 skipped，最终增加边界检查并恢复默认 v5 后得到上述 193 结果；不能相加为新全量基线。

补入现有 CI 的 `tests/test_code_search_scope.py` 明确测试**独立候选**，并断言默认 registry 为 v5；运行手册的 CI 清单同步。之前 2026-10-02 的 70 项维护测试仍是当时的记录。

两个固定真实仓库上的 **40 组** query/kind 组合，未指定 scope 的 `matches` 与 v5 相同；metadata 属于新增 schema，未宣称整个输出对象逐字节一致。脚本化 Runtime 证明“宽搜截断 → 收窄 src → 读取函数 → 回答”可在 **4 次决策 / 3 次工具 / 0 错误**内完成；这只证明机制可行，不证明模型会自主这么做。

## 真实新旧对照

8 个问题在首次付费测试前固定，两项目各 4 题：包含 examples 噪声中的源码定位、函数行为、明确文件路径、合法 example 与 README 文档控制。没有让用户问题直接指定工具参数。每题 v5/v6 一次，交替顺序，共 **16 个真实用户请求**；8 次普通 HTTP、8 次 SSE v2。每个项目/版本独立进程和 SQLite，使用相同当前 Reader、技术语料 BM25、主 Prompt、模型和预算。

源代码固定为 smolagents `c30b115286e000e98711fae5e85993547b73d826` 与 requests `b25c87d7cb8d6a18a37fa12442b5f883f9e41741`，checkout 均干净。知识库状态为 verified/ready，corpus `870e5864df67`、37 文件/215 chunks。

| 指标（每版 8 题） | v5 | v6 候选 |
|---|---:|---:|
| 合法响应 / 预算内 | 8 / 8 | 8 / 8 |
| completed / refused | 7 / 1 | 7 / 1 |
| 读到目标源码的题数 | 7 | 7 |
| 工具调用 / 工具错误 | 17 / 0 | 17 / 0 |
| 搜索调用 / 使用 scope | 8 / 0 | 8 / 0 |
| truncated=true | 不提供该字段 | 2 |
| 逻辑决策 | 25 | 25 |
| 实际 provider 调用（Planner + Decision，含格式修复） | 8 + 26 = 34 | 8 + 26 = 34 |
| 输入 / 输出 token | 156,878 / 5,734 | 161,276 / 5,309 |
| 用户请求耗时合计（不含服务启动） | 43.724 秒 | 40.547 秒 |

**8/8 对的工具调用顺序与读取路径/行窗相同**；7/8 对参数逐项一致，唯一差异为 S01 新版显式传 `mode=window`，旧版省略时也默认 window。计入该缺省值后 8/8 对参数等效，原始差异仍保留。模型实际收到的 Tool payload SHA 不同：v5 `30846e05…`，v6 `7885547b…`，所以不是 harness 没切换工具。S01 两次搜索收到截断标记，却仍更换关键词并读取与旧版相同的行窗。模型从未使用 scope，明确文件路径的题目也没有因此减少调用。

实际模型均为 `deepseek/deepseek-chat`；Planner `gate3_planner_prompt_v1` / `5b209054…`，Decision `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1` / `c465defe…`。两版各发生一次既有输出格式修复；逻辑迭代与实际 provider 调用分别记账。输入 token 增加约 2.8%，本轮耗时差异不能当成可靠性能或费用收益。

## 答案与引用审查

同一实现助手逐题对照 pinned 源码、实际读取内容及公开证据；非独立评分。所问行为两版都是 **5 PASS / 2 PARTIAL / 1 FAIL**。整份答案包括额外断言与公开引用：v5 **3 PASS / 4 PARTIAL / 1 FAIL**，v6 **2 PASS / 5 PARTIAL / 1 FAIL**。单轮语句波动及 Planner 分解差异存在，不能据此宣称候选必然造成质量回归。

| 题目 | 共同现象 / 差异 |
|---|---|
| S01 CodeAgent 执行 | 两版同读 1696-1756，尚未读取方法最后部分；公开 snippet 在 2000 字符处提前截断，多个断言在展示的证据中缺失 |
| S02 execute_tool_call | 两版同读完整方法，但未进一步读取 state 参数替换 helper；公开片段截掉部分异常分支 |
| S03 PythonInterpreterTool.forward | 两版均正确获取限制参数及 Stdout/Output 组合，调用数相同 |
| S04 SQL example | 两版都可读取 examples 源码，但只读 sql_engine，仍对未读取的 CodeAgent 注册行作确定断言 |
| R01 prepare_request | 两版的所问合并与 netrc 条件正确，公开片段包含全部读取范围 |
| R02 环境设置 | 两版核心行为正确；候选额外用 750-779 的 E6 支持 579 行调用点，引用范围不符 |
| R03 Response.json | 两版同读两个窗口，行为正确，但引用未读取的顶部 import；候选的别名描述还过度概括 |
| R04 README | 两版均未调用仓库工具就主动拒答；公开 verifier observation 为 NO_ADDITIONAL_REQUIREMENT / can_finalize=true，不是其拦截 final_answer，也不是预算耗尽 |

## 收尾与后续方向

决定为 **候选保留 / 默认不晋升 / TD-TOOL-02 继续 PARTIAL**。候选 Handler 与实际测试快照分开保留；实测搜索结果对保留候选逐条离线重放一致，新增非法路径规则另有离线回归，没有额外付费请求。

下一步更有根据的是单独审查**模型如何利用已有路径、选择下一跳、判断目标已读全**，以及文档问题为什么没有激活仓库取证。公开证据 2000 字符与读取结果 8000 字符的边界、错误引用和漏读 helper 继续登记既有技术债。仅增加参数还不足以改变这些行为；不通过扩大预算或降低项目定位来掩盖问题，也不在本轮顺带改 Router / Prompt / Runtime。

本轮没有全量验收、独立 judge、重复统计实验、Git commit 或 GitHub push。
