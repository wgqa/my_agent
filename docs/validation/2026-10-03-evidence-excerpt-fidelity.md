# Reader 与公共证据正文一致性（2026-10-03）

## 保留结论

保留公共项目读取片段的一致性修复：**不再把已受 Reader 大小约束的文本二次截成 2000 字符**。`project_doc`、`project_code`、`project_test` 共用一个转换与容量策略；每个有效 Reader 返回的 `lines[].text` 按原顺序完整组成公开 `snippet`，行号必须连续且与声明范围一致。

离线回放之前两次真实实验的 **48 个用户请求 / 41 次成功读取**：旧公共证据有 **23/41 次二次截断**，涉及 20 个请求；新转换 **41/41 与实际返回文本完全一致、0 次二次截断**，原证据编号、kind、路径和行范围不变。历史回答没有重生成或重评分，不把此结果称为新模型正确率。

相关 15 个模块局部回归 **303 passed / 6 skipped / 3 warnings**；6 项是当前 Windows 账户不能创建符号链接，其他隔离与边界用例通过。最大窗口测试随后改用真实 Reader 生产数据，ASCII / 中文 / emoji 三项单独复验 **3 passed**，不与 303 累加。无新增真实 provider 调用、未运行完整 CI 或全量 pytest。

## 根因与切片边界

旧转换位于 `ToolAgentRuntime._evidence_from_project_context()`：

```python
snippet = "\n".join(texts)[:2000]
# start_line / end_line 仍来自整个 Reader 返回范围
```

Reader 本身已经限制窗口行数、单行长度和函数页大小。模型在 Observation 中得到完整返回内容，公共证据却只保留开头。例如 smolagents Quick demo 已在 README 23–83 的实际读取里，公开 E6 止于 demo 前，用户无法通过展示的正文核对答案。

本切片不按题目、语言或仓库名称决定补充内容，也不拆分 E-ID 或新增续读调用。已有 Reader 内容一次转换成公共正文，最终非流式 API 和两版 SSE 使用相同的 response builder。Router、Planner、Verifier、Prompt、预算及停止策略保持原样。

## 共用容量规则

新增叶模块 [`source_excerpt.py`](../../core/tool_agent/source_excerpt.py)，集中既有 Reader 限制并提供转换校验；原工具模块保留同名常量导入入口。

| 类型 | 既有生产边界 / 公共正文边界 |
|---|---|
| window | 前后最多 30 行，合计最多 61 行；每行最多 300 字符 |
| definition | 每页最多 120 行 / 8000 字符；每行最多 300 字符 |
| 项目读取 Evidence | 上限从旧 2000 改为现有最大窗口的 `61 × 300 + 60 = 18360` 字符 |
| project_change | 仍为 2000 字符；diff 的单独正文对齐不在此切片 |
| knowledge | 仍为 500 字符 |

窗口与函数的生产限制均未提高，搜索仍是 v5，Reader 仍是 v2，ToolSpec 描述、schema、version 与决策可见 toolset SHA 不变。Runtime model、API 校验和 OpenAPI 条件 schema 使用同一策略，Git diff 不因读取片段扩展而放宽。

转换拒绝行数与范围不一致、不连续行号、bool 伪装行号、超长单行、超出模式页容量或未知模式等数据；不为使它“成为证据”而裁掉一部分或伪造范围。单行被 Reader 既有 300 字符限制裁掉的原文件字符不会凭空恢复，本修复只保证**实际返回内容**与公共正文一致，不宣称原始文件完整。

## 真实记录回放

运行前保存初始 manifest、六个受改动模块的原始字节与保护文件 SHA。输入复用上轮两阶段 `live_results.jsonl`，没有重写 raw、案例、manifest、答案或评审结论。回放按每条实际 `source_read` 关联原公开 E-ID，并验证：

1. 旧正文等于实际读取文本的 2000 字符前缀，确实存在截断。
2. 新正文逐字符等于全部已返回文本，并通过当前 API Evidence schema。
3. 原 E-ID、kind、路径、start/end 保持一致；未修改模型动作、工具参数或读取范围。
4. 上轮归档 33 个文件与本轮 13 个保护文件保持原始 SHA。

原记录回放只包含真实出现的 `project_code` / `project_doc`；`project_test` 用真实 Reader + 完整 Runtime/API/SSE 的局部回归覆盖。

| 文档阶段 candidate 示例 | 原 E-ID / 范围 | 旧 → 新正文字符 |
|---|---|---:|
| D02 Quick demo | E6 / README 23–83 | 2000 → 3454 |
| S01 CodeAgent | E6 / agents.py 1696–1756 | 2000 → 2996 |
| S02 ToolCallingAgent | E5 / agents.py 1453–1502 | 2000 → 2408 |
| R03 JSON 第一次读取 | E6 / models.py 910–970 | 2000 → 2545 |
| R03 JSON 第二次读取 | E7 / models.py 940–1000 | 2000 → 2410 |

41 次实际读取中最大正文为 6193 字符。具体输入 SHA、逐条长度、正文 SHA、保护文件与工具身份见 [`raw/replay.json`](../../evaluation/evidence_excerpt_20261003/raw/replay.json)。复跑方式见 [实验归档](../../evaluation/evidence_excerpt_20261003/README.md)。回放是固定数据上的转换验证，未执行新的 Agent 对话。

## 局部回归与集成

新增 31 项回归，包括真实 Reader 到完整 Runtime、非流式 API、SSE v1、SSE v2 的尾部正文一致性；窗口/函数读取，文档/源码/测试文件，最大 Unicode 窗口，越界或不连续返回的拒绝，Runtime/API/OpenAPI 分类容量一致性及可信 control 不包含源码正文。

既有回归覆盖证据去重、编号、工具身份、函数分页、路径隔离、知识引用、Git 变更与流式协议。新文件加入现有 CI，运行手册逐项对齐，当前清单共 36 个模块；本次只执行相关 15 个模块，不等于完整 CI job。

最初的新测试误用了不存在的 control 字段名，修正为已有的 `available_evidence_refs`。随后局部测试发现旧 `_READ_RESULT` 夹具标注 1–2 行，却只给第 1 行；补齐第二行，保留严格转换校验。失败日志与修正范围保存在新归档，不放宽生产规则掩盖不一致。

## 整体架构与代价

- 5 次决策 / 4 次工具调用 / 2 次工具错误不变。没有新增循环、模型层、动态工具或特批。
- E-ID 仍对应一次有效读取范围；去重键、可信引用目录及最终结构验证不变。模型依旧使用原 Observation，源码正文不进入可信 control；不增加一份模型上下文副本。
- 响应字段与 SSE 事件结构不变，但项目读取 `snippet` 的最大允许值扩大。**严格按旧 2000 字符 schema 校验响应的外部客户端需要更新**；仓库现有前端直接显示完整字符串，不设置该长度限制。
- 公共响应和持久化的 `result_json` 会变大。单项最大 18360 字符仍为硬上限；本次未做存储或大规模渲染性能测试，TD-STORE-02 继续开放。
- 此处只变更公共 Evidence 数据转换与容量规则，Runtime 控制循环未改。长期 Task / Evidence / Execution v2 契约继续暂缓。

## 未关闭的债务

D02 的“实际读到但公开正文截断”已修复。S01 未读取函数末尾、S02 未读取 state 替换 helper、S04 未读取注册代码，以及 R03 引用窗口外导入和错误条件描述都不能由此修复。原 Verifier 仍做结构绑定，不证明自然语言结论被引用内容蕴含。

因此只将 TD-VERIFY-01 / TD-TOOL-02 中的**Reader → 公共正文丢失**切片标为已解决，保留源码取证完整性与语义正确性债务。下一步仍应先界定任务所问各项是否取得相应材料，避免增加逐题规则或扩大预算。
