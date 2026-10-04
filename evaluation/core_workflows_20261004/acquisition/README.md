# 对象取证后续切片（2026-10-04）

前三个轻量候选未晋升后，继续改造同一个 Reader 的对象定位与读取。此归档保留19次真实请求；开发6题沿用原问题，后续8题、四个会话检查和一次变更入口修订检查分别预先声明，不能混合成独立成功率。初版 catalog 与 helper 快照保留，原失败没有删除或重试覆盖。

当前 Engineering 使用 `read_project_context_v4` 与对应 decision v4，legacy 默认 Reader v2 及历史 prompt 身份保留。主接口、单 Runtime、七工具、5/4/2不变。Python具名/文件内匹配与其他文本的匹配窗口均只读取允许文件；不运行目标项目。

`raw/` 保存实际响应、来源观察与每阶段代码/项目身份。`manual_review.json` 是同一开发助手对源码、读取范围与完整答案的审查，不是独立验收。`summary.json` 区分核心任务与边界控制，内容分数不根据 completed、关键词或 E-ID 自动生成。

原14题之后补齐一般文本的文件内匹配，修正短名歧义与空正文片段；最后四题通过实际新会话消息/SSE接口检查，保留长文档的前后结果。变更表单又明确“已给定路径”，单独检查一次，旧入口误拒答仍保留。五次真实会话检查均验证持久化返回等于最终响应。它们没有启动完整前端，不构成 Full App smoke。

`first-round-reader.snapshot` 按原manifest SHA精确还原初版Reader，`runtime_snapshots/` 保存本切片当时已修改的其他生产模块；开发阶段的旧API源码还保存在上层 `baseline/app.snapshot`。未修改模块的身份在各manifest中。快照不是运行时插件。最终代码身份和原始响应hash见 `archive_manifest.json`。

零模型复核：

```powershell
python -m evaluation.core_workflows_20261004.acquisition.analyze
```

脚本校验原始返回未改、预算、无额外历史/Resolver成本、每段公共证据与固定源文件一致，以及返回的22个限定定义与实际Python AST一致。它不自动判定自然语言答案正确。

需要主动开启的真实回放：

```powershell
python -m evaluation.core_workflows_20261004.acquisition.run --phase entry_confirmation --workspace <isolated-workspace> --corpus-root <verified-corpus> --output-dir <fresh-output> --live
```

每题只发一次，基础设施/provider失败即停止。不同修订的回放需要对应代码身份；在当前树重跑得到的是新结果，不能覆盖旧记录或宣称精确复现模型文本。已使用的问题不再是未见验收集。当前长期语义支持债务与一般自由任务规划仍开放，见 [验证报告](../../../docs/validation/2026-10-04-core-workflows.md)。
