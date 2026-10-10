# 第二层工具过程评测：离线准备

日期：2026-10-09。项目所有者授权在同一 checkout 编写评测内容，正式模型评测前告知。
本轮未调用真实模型；Git 下载是固定源码准备，不是模型评测。

## 交付

新增 `evaluation/tool_calls_v2/`、`scripts/run_tool_call_evaluation.py` 和两个 pytest 模块。
48 道开发题、24 道新题；真实主链使用六个可调用工具，注册但禁用的 knowledge_search 另做离线契约。
保留当前 API 装配、Planner/检索/Tool/Verifier/Guard 和 5/4/2 预算，未修改 core、生产 API 或 HTML。

源码与 Gold 的当前内容 SHA 为 `00449e755b7d4a39b82607368e5473a577444ebdf6091c4da03c590e59d1b4c2`。
Requests commit、urllib3 commit、fixture Git patch 与每个输入内容 SHA 在 protocol 中冻结。
参数评分接受合法路径及 commit alias；正文按实际行哈希检查，候选/导入/搜索不能冒充测试正文。
逐 SDK 调用记录 Planner、Decision 与修复的 usage；不保存模型思考过程、原始输出、Prompt 或真实凭据。

## 验证身份

| 验证 | 范围 | 能说明什么 |
|---|---|---|
| 新增 pytest | 90 项，零网络模型调用 | 评分器反例、契约、观测透明性、缺失 usage、记录损坏、版本身份与重算 |
| 相关八模块回归 | **237 passed / 1 skipped / 2 warnings**，包含新增 90 项，不累加 | 新评测与现有 Reader、Git、测试发现、Guard、产品入口、Decision 的兼容性 |
| Gold 预检 | 72 题，真实只读工具执行参考路径 | 目标材料与参数可达；合成 terminal 不证明 Guard 或模型自主能力 |
| 产品入口回放 | 72 题，替换 Planner/Decision | 当前装配、六工具禁用边界与实际停止行为；不是模型成功率 |

最终 Gold 预检 **72 PASS / 0 无效**；产品入口脚本回放 **71 PASS / 1 PARTIAL / 0 无效**。
唯一 PARTIAL 为下述 `dev-015`。两份报告均标记 `is_model_quality_result=false`，实际 provider 调用为 0。
Gold 报告已使用保存的 cases/calls 成功离线重算，原记录不覆盖。

两个 warnings 来自已安装依赖的弃用提示，未升级共享环境。
CI 和手册均加入两个模块，所选清单共 55 个模块且顺序一致；本轮没有执行完整 CI / 全量测试。

最终准备报告：

- [Gold 可达性](../../evaluation/tool_calls_v2/results/offline_gold_20261009_final/report.md)
- [完整主链脚本回放](../../evaluation/tool_calls_v2/results/offline_facade_20261009_final/report.md)

这些文件的 manifest 保存实际业务、评测器、评分规则与所选案例 SHA。正式模型运行要重新冻结当时实际版本；并行对话的新业务改动不会自动获得本轮验证结论。

## 发现与边界

初次 authoring 的 `find_tests(timeout.py)` 只返回前 10 个候选，未包含原先期待的 `test/test_util.py`。
在调用模型前将普通候选题换为 filepost 的明确目标；Timeout 的真实正文仍在多材料题覆盖。
初次预检保留在 `offline_gold_20261009_a`，不能把旧、新 Gold 的分数混在一起。

源码定位问法 `dev-005` 激活正文护栏；参考路径增加合法的短 Reader 跟进，未改 Gold 目标或生产策略。
`dev-015` 只问已删除的源码清单。最小路径已取得目标变更集合，但当前 Guard 仍可能因缺源码正文拒答。
保留它的“应完成”预期和 PARTIAL 记录；没有通过改预期为拒答来掩盖问题，也没有为了评测修改核心逻辑。
这是一条脚本回放发现，真实模型是否选择额外步骤、是否误拒答仍待正式运行。

离线全过程使用工作区内专用临时目录、源码 fixture 和 SQLite；未向 8000 服务发送评测请求、停止或重启服务。
新题是相关 HTTP/Python 仓库迁移，同一开发助手 authoring/评分；没有独立人工或 sealed holdout。
第三层最终答案质量、多轮、HTML/SSE、知识库和项目切换的验收尚未由本轮覆盖。

## 正式运行前

告知项目所有者后，先按冻结题集运行开发集，再以同一业务/规则版本运行新题。
记录差结果、误拒答、解析失败和成本；争议、失败及通过样本进入单独复核队列。
不自动挑选重试，不将离线 PASS 写成当前模型通过，也不把一次第二层基线写成端到端质量达标。

命令与报告格式见 [使用说明](../../evaluation/tool_calls_v2/README.md)。
