# 101-Gate5：README 与项目叙事

## README 不是项目日志

README 是第一次进入仓库的 front door，不应罗列每一张历史任务卡，也不应把临时实验输出当成当前能力。它需要回答：项目解决什么问题、用户怎样运行、系统边界在哪里、哪些结果有证据、哪些限制仍然存在。实时进度和长篇审计分别放在 `docs/status.md`、冻结 artifact 和 study notes 中。

## 第一屏先讲价值

校招面试官通常先扫标题、简介、亮点和架构。第一屏应在几行内说清这是一个什么系统、相比普通 RAG 增加了哪些能力，以及为什么值得相信。技术名词必须绑定当前代码或证据，不能用未实现组件装饰架构图。

## 功能、实验、工程证据分层

功能章节解释 Basic RAG、Agentic RAG 和 Structured Tool Agent 的产品路径；Evaluation & Evidence 只列少量来自 tracked freeze 的 headline；Reproducibility 说明 lockfile、公共语料身份和验证命令；Safety 与 Known Limitations 说明系统不做什么。这样读者可以区分“代码支持的能力”和“某个冻结数据集上的观测”。

## 负结果和限制也属于叙事

Gate 3 的 generation failure、retrieval-to-answer gap，以及 Gate 4 的 multi-step sequence match 和 required coverage 都是正式证据的一部分。README 诚实保留这些数字，比只展示成功路径更能说明评测没有被选择性汇报。Smoke、Release Demo 和 Formal Benchmark 也必须分开：能启动不代表答案质量，Demo 不是 Gold evaluation。

## 用 Gate 演进组织复杂项目

Gate 1 讲基础正确性，Gate 2 讲可复现实验，Gate 3 讲 Agentic Retrieval，Gate 4 讲安全 Tool Agent，Gate 5 讲 Release Engineering。五个阶段比几十个历史任务名更容易让面试官建立系统心智模型，也能自然引出为什么后续工程工作是能力的一部分。

## 面试讲法

三分钟版本按“定位 → 架构 → 三种模式 → 一个冻结结果 → 一个限制”展开；十分钟版本再补 API contract、Evidence Verification、Tool allowlist、预算控制、CI 和 Full App Smoke。回答结果时同时说明数据范围、证据路径和限制，不把一次 live Demo 响应说成 benchmark，也不把 safe trace 说成 Chain-of-Thought。
