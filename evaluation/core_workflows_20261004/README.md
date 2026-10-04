# 核心任务检查归档

2026-10-04的前35次真实请求、三个未保留的轻量候选、三例初版任务入口验证。这个阶段API/Core确曾恢复至起点，见 [restoration.json](restoration.json)；随后在 [acquisition/](acquisition/README.md) 实施对象取证并另行记录19次请求，最终生产代码已有该切片。两阶段共54请求，内容审查均来自同一开发助手，不是独立验收或项目总体成功率。

- [完整报告](../../docs/validation/2026-10-04-core-workflows.md)
- [原问题与判据](catalog.json)；原始及阶段修订 catalog 分别保留为 `initial_catalog.snapshot`、`pre_guided_catalog.snapshot`
- `raw/<phase>/`：真实返回和阶段输入身份；不要覆盖原始记录
- `source_snapshots/`：实际读过的九份固定来源，含有意设置的工作区回归
- `prompt_candidate/`、`reader_candidate/`、`planner_candidate/`：未启用的开发代码快照
- [逐项内容审查](manual_review.json) 与 [摘要](summary.json)
- [取证切片设计/落地记录](../../docs/design/core_workflow_acquisition_slice.md)

零模型检查：

```powershell
python -m evaluation.core_workflows_20261004.analyze
```

分析核对返回记录 SHA、每个结果都有显式审查、访问返回与固定来源的正文一致、HTTP/SSE 和预算、provider-reported 调用与 token 范围；不会根据 completed、关键词或引用合法性自动给 PASS。

重新执行需要现有干净固定提交的 Requests，以及已验证的 Engineering corpus。所有运行使用新工作目录/输出目录，显式 `--live` 才调用模型；每阶段至多八个请求，不自动重试付费问题。源码项目不安装依赖或执行其测试。示例：

```powershell
python -m evaluation.core_workflows_20261004.run --workspace D:/temp/new-workflows --prepare-from D:/path/to/pinned-requests
python -m evaluation.core_workflows_20261004.run --workspace D:/temp/new-workflows --phase development
python -m evaluation.core_workflows_20261004.run --workspace D:/temp/new-workflows --phase development --corpus-root D:/path/to/verified-corpus --output-dir D:/temp/new-results --live
```

开发阶段可选择且只能选择一个 `--candidate`（通用策略）、`--reader-candidate` 或 `--planner-candidate`。快照只在隔离评测进程装配，不改变正常 app 配置。重新执行属于新诊断，不保证复制远端模型的逐字答案，不能覆盖本轮原数据。

历史候选回放继续使用其旧Reader/prompt配对，正常app使用最终对象Reader；当前树重跑不能当作原时代码精确复现，需核对阶段manifest与快照。
