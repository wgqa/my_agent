# 第一切片：函数读取与旧版对比

日期：2026-10-02。项目所有者授权实施此前选定的函数读取切片，随后做旧/新对比；总体任务与执行契约留待后续讨论。本轮完成工具改造及验证，没有开始该契约设计。

## 结论

**有足够证据确认，这个切片改善了 Python 长函数的取证完整度，并修正了至少一类由缺失函数末尾造成的错误回答。** 三道历史问题 R01/R03/R05 和新仓库问题 N01 所需的末尾分支，在最终配对测试中全部读到；旧版均缺少相应关键分支。保持原 5 次逻辑决策 / 4 次工具调用 / 2 次工具错误上限。

这不能解释为完整答案质量已过关。最终 8 道新版题的所问行为审查为 **7 PASS / 1 PARTIAL**；把额外陈述与引用范围一并审查后为 **5 PASS / 3 PARTIAL**。R05 仍高估可选校验的保障，N02 对 `self.text` 的额外解释过于笼统，N03 仍引用未读到的调用点。已有 structural grounding 可以放行这些输出，本轮不改写该能力边界或独立产品验收结论。

交付版全量离线回归：**2692 passed / 6 skipped / 4 warnings**，435.85 秒。相比改造前最近一次全量 2658 passed / 6 skipped，新增 34 项有效用例。最终真实对比不是冻结 benchmark 的重跑，也不是独立人工验收。

## 实施范围

修改 `core/tool_agent/tools/read_project_context.py`，新增纯标准库 helper `core/tool_agent/tools/source_navigation.py` 和 `tests/test_source_definition_reading.py`。

| 能力 | 交付行为 |
|---|---|
| 旧调用兼容 | 不传 `mode` 或 `mode=window` 时保留原 `path/line/context_lines` 行窗与原输出字段 |
| Python 函数读取 | `mode=definition` 用 AST 定位锚点所在的最内层函数；支持类方法、嵌套函数、async、多行签名与装饰器 |
| 有界内容 | 每次最多 120 行、8000 源码字符（含行间分隔）、每行 300 字符；保留原 1 MiB 文件上限 |
| 截断与续读 | 返回函数名/起止行、`content_complete`、`truncation_reasons`、`next_line`；保持原锚点，用 `start_line=next_line` 续读，每页计一次原有工具调用 |
| 解析失败与其他语言 | 显式 `fallback_reason`，返回原前后各 30 行的有限窗口；不把文本窗口标记成完整函数 |
| 续读边界 | 函数分页限制在选中函数内，回退分页限制在原窗口内；单行字符截断明确标注，行续读不能补齐该行 |
| 安全边界 | 沿用项目根目录、后缀、secret 文件、路径穿越与 symlink 防护；仅解析，不导入或执行目标项目源码 |

`content_complete` 的含义是**这一份返回内容包含完整函数**，不是答案正确性或最终证据充分性的证明。后续页单独不含完整函数，仍为 false，模型须结合前面各页。本轮没有引入内部自动分页、第二个 Agent loop 或额外额度。

ToolSpec 版本为 `read_project_context_v2`，描述告诉模型类声明/常量/文档用旧 window，函数实现用 definition。Decision 主 prompt、Planner、Requirement、Verifier、Runtime、Executor 和 API/SSE 协议均未修改；保护文件的逐项哈希核对记录在 manifest。工作区此前已有的 SSE 整理和文档修改保留，所以基线是当时工作区快照，并非干净 HEAD。

## 对比方法与身份

付费调用前固定 8 道题：5 道来自上一轮诊断，3 道来自另一仓库 requests；其中 N03 是短函数控制，C04/C07 是常量与文档控制。每道分别运行真实 v1 和 v2，每轮 16 次请求，轮内交替先后顺序。

每个 project/arm 用独立进程和 SQLite，经过真实 FastAPI `/engineering/query` 或 SSE v2、Planner、知识检索、单一 Runtime、工具 Executor、Verifier。v1 仅在验证进程中替换原版 reader 的 schema/描述/handler，生产代码不提供切回开关。Provider 都是 `deepseek-chat`，Planner 和 Decision 主 prompt 哈希一致，变化集中于 reader ToolSpec 与实现。知识库沿用项目 verified BM25 语料。完整模型身份和工具集哈希见 [manifest](../../evaluation/source_reading_v2_20261002/manifest.json)。

| 被测项目 | 固定源码 |
|---|---|
| smolagents | `c30b115286e000e98711fae5e85993547b73d826` |
| requests v2.32.5 | `b25c87d7cb8d6a18a37fa12442b5f883f9e41741` |
| mini 控制项目 | 归档 `fixture_snapshot.json`，同一代码与文档 |

所有 32 次请求 HTTP/公开 response schema 有效，所有 SSE 题均检查单一 final、answer_delta 拼接、done 且无 error；每次计数都在 5/4/2 内。某次业务 `failed` 不算 transport 失败，也不计作回答通过。

评分由实施本轮的同一助手逐条核对公开答案、引用的实际片段与固定源文件。没有调用额外 LLM judge。题目虽然先固定，但包含已知失败题，也用于调试首轮，属于诊断回归，不是封存 Holdout。

## 首轮发现与后续修正

首轮 16 次结果完整保存在 `raw/results_round1.jsonl`。R03 的新版错误地在类声明上使用 definition；此时 `context_lines=0` 回退仅返回一行，又给出可继续向后读的位置。模型随后消耗三次读取，预算内没有拿到 `_run_stream`，虽说明缺证据，仍未完成所问行为。

针对这个通用问题，修正为：无法定位函数时返回原 ±30 行窗口，续读位置只用于该有限范围的真实截断；并明确类声明用 window。没有增加针对 R03 的题型规则。随后重跑同一个 8 题矩阵，首轮失败记录未删除、未用两轮最优答案拼成结果。

第二轮完成后，代码收尾检查进一步发现字符上限触发的回退分页可能随 `start_line` 移动而扩大原窗口。交付版把范围固定在原锚点 ±30 行，新增字符分页及越界测试。该补充没有改变 ToolSpec 和预算：交付版回放第二轮 **10/10 次成功 v2 读取，输出完全一致**，无需追加模型调用。第二轮快照与交付版快照均归档；最终全量离线回归在交付版上运行。

## 最终逐题结果

下表的“整份答案”也审查额外陈述和引用范围；PASS 不是简单按 `completed` 判断。

| 题目 | 旧版读取 → 新版读取 | 工具调用旧→新 | 所问行为旧→新 | 整份答案旧→新 |
|---|---|---|---|---|
| R01 普通工具执行 | 1423–1483 → 完整函数 1453–1502；读到 dict/scalar 与 sanitize 调用 | 2→2 | PARTIAL→PASS | PARTIAL→PASS |
| R03 planning 与步数上限 | 510–570 → 完整 `_run_stream` 540–611；读到兜底与 FinalAnswerStep | 4→4 | FAIL→PASS | FAIL→PASS |
| R05 校验与预算职责 | 510–570 → 540–611；读到可选 `_validate_final_answer` | 2→2 | PARTIAL→PARTIAL | PARTIAL→PARTIAL |
| N01 Session.send | 两窗最远到 733 → 完整 673–748；读到 745–746 的 `r.content` | 3→2 | FAIL→PASS | FAIL→PASS |
| N02 Response.json | 917–977 → 完整 947–980；新版包含最后异常包装 | 2→2* | FAIL→PASS* | FAIL→PARTIAL* |
| N03 短函数 guess_json_utf | 旧窗与新函数均完整覆盖所问实现 | 2→2 | PASS→PASS | PARTIAL→PARTIAL |
| C04 配置常量 | 两版均保留 window；默认 5、环境变量和 1..20 正确 | 2→2 | PASS→PASS | PARTIAL→PASS |
| C07 文档与代码默认值 | 两版都读 docs/config，正确识别 3 与 5 的冲突 | 4→4 | PASS→PASS | PASS→PASS |

**N02 的混杂因素：** 第二轮旧版因 `ACTION_PARSE_FAILED` 且 schema repair 失败没有公开答案，不能把失败→成功归因于函数读取。第一轮旧版通过两次行窗读取完成该题，合计 3 次工具；第一轮新版一次完整函数读取，合计 2 次工具。这是节省重复取证的证据，但不证明解决了动作解析失败。

严格整份答案计数：旧版 **1 PASS / 4 PARTIAL / 3 FAIL**，新版 **5 PASS / 3 PARTIAL**。所问行为计数：旧版 **3 PASS / 2 PARTIAL / 3 FAIL**，新版 **7 PASS / 1 PARTIAL**。这些是这组题的审查结果，不能用作泛化成功率。

具体的体验错误：旧版 N01 明确回答“Session.send 这一层没有显式 content 读取调用”，其证据最远到 733，漏掉实际 745–746。新版用同一项目和同一模型，在更少一次工具调用下读取完整方法，正确回答非流式返回前访问 `r.content`。

## 用量与耗时

第二轮每组各 8 道题，包含旧版 N02 的动作失败与不同的 schema repair 次数，汇总只作描述，不能直接作为纯读取收益的因果估计。

| 指标 | v1 | v2 |
|---|---:|---:|
| 逻辑决策总数 | 29 | 28 |
| 工具调用总数 | 21 | 20 |
| Decision 实际 provider 调用 | 31 | 29 |
| Planner + Decision 实际 provider 调用 | 39 | 37 |
| 全模型输入 tokens | 183,171 | 175,953 |
| 全模型输出 tokens | 5,369 | 6,365 |
| 8 请求累计执行时间 | 48,839 ms | 49,949 ms |
| 单请求执行时间中位数 | 5,657 ms | 6,171.5 ms |

修复调用是已有的解析修复流程，包含在 Decision 的实际 provider 用量中，未新增逻辑决策或工具额度。Planner 调用另行相加，不把公开 execution 中的 Decision 用量误称为整个请求的模型用量。

这一轮输入用量较低、输出更长，但整体时间未下降；首轮新版输入用量与耗时还更高。没有采集缓存计费细项，不估算金额，**不宣称稳定降本或提速**。目前能支持的收益是获取关键分支、减少部分重复读取和纠正具体错误结论。

## 离线验证与剩余边界

新测试覆盖长函数尾部、装饰器/async/嵌套/BOM、多行签名、120 行与 8000 字符限制、行截断、函数与回退分页范围、未知语言/坏语法/类声明回退、schema 和原路径限制、观察与 E-ID 的链路、预算内完成和尝试第五次工具被拒绝。

真实 Runtime 脚本测试：长函数四页时仍是 5 次决策 / 4 次工具，可完成；需要第五页时按现有预算拒绝，原因 `AGENT_BUDGET_EXCEEDED`。没有为长函数特批额度。

此外，`offline_comparison.json` 用实际原版 Handler 快照与交付版 Handler，在固定锚点与相同读取次数下比较原始内容。这部分没有模型方差，可单独检查工具是否真的拿到目标分支。

交付限制：

- AST 函数边界目前只支持 Python；其他语言仍回退行窗。
- 过大函数需要模型选择续读，四次工具预算仍可能不足；没有承诺任意函数或任意工程任务一定完成。
- 单行超过 300 字符仍截断；元信息说明缺口，没有字符级续读。
- 完整读取不自动解决 answer↔evidence 语义支持；R05/N02/N03 的部分通过仍登记为后续证据和完成标准的输入，不在此加新 Guard 例外。
- 陌生仓库搜索排序、测试定位、多轮对象延续、计算的证据类型和未来编辑/运行能力都不属于这个切片。

## 产物与后续

完整原始答案、观察、哈希、快照和复跑命令集中在 [evaluation/source_reading_v2_20261002](../../evaluation/source_reading_v2_20261002/README.md)。最终离线日志见 `raw/pytest-shipping.log`。

TD-TOOL-02 的只读函数获取切片已实施并有明确收益；整个债务与 TD-VERIFY-01 等语义问题继续开放。可以以本轮基线进入后续契约讨论，围绕真实缺口确定完成条件、证据范围及预算职责；本轮没有实施或起草总体任务/执行契约，没有新增 Provider 或 Jev 路由，没有提交或同步 GitHub。
