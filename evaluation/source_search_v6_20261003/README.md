# code_search 范围搜索候选：未晋升

2026-10-03 的 TD-TOOL-02 小切片。实现可选文件/目录 `scope`、真实命中截断 `truncated`，并保持 literal 搜索、kind 过滤、路径/行排序、10 条/300 字符/1 MiB 上限。候选代码在 [candidate.py](candidate.py)，**默认 registry 继续使用原来的 code_search_v5**。

局部离线回归最终 **193 passed / 7 skipped**；两仓库固定 8 题、16 次真实用户请求均通过 HTTP/SSE 协议和 5/4/2 预算检查。新旧每组都使用 17 次工具调用、获取 7/8 题目标源码；新候选 **scope 使用 0/8 次搜索**，两个 `truncated=true` 也未改变下一步行为。没有证明问答收益，故未晋升；不能把 Handler 可缩小范围的单元测试当成真实 Agent 自主定位改善。

详细审查见 [验证报告](../../docs/validation/2026-10-03-source-search-v6.md)。所问行为两版都是 5 PASS / 2 PARTIAL / 1 FAIL；包含额外断言及公开引用的整份答案分别为 v5 3 PASS / 4 PARTIAL / 1 FAIL、v6 2 PASS / 5 PARTIAL / 1 FAIL。相同助手审查，单轮开发诊断，非独立验收。

文件职责：

- `initial_manifest.json`：改动前工作树快照身份、受保护源码与历史 Reader 归档 hash。
- `manifest.json`：**付费请求之前冻结**的题集、v5/v6 快照、运行源码和仓库身份。不是当前默认版本说明。
- `catalog.json` / `review.json`：用户问题及不发送给模型的 gold、逐题审查。
- `snapshots/code_search_v5.snapshot` / `code_search_v6.snapshot`：实测的两个版本，保留原样。
- `candidate.py`：保留供后续开发的 v6 候选；实测后补强 Windows 路径末尾点/空格及排除目录大小写别名，未再次付费测试；8 个实测搜索结果已离线逐条重放一致。
- `offline_comparison.json`：真实仓库 40 组旧版 matches 一致性检查。
- `raw/paired/`：脱敏的实际响应、工具观察、provider metadata、配对摘要。
- `outcome.json`：当前默认回到 v5 的身份、离线重放、受保护文件核对和最终材料 hash。
- `harness/`：复用上一轮 Reader 对照的真实 API 启动及被动观察方式；没有产品开关、新生成器或第二个 Agent 循环。

复跑需要自行准备干净的固定 checkout；不用安装或执行被检查项目：

| 项目 | commit |
|---|---|
| smolagents | `c30b115286e000e98711fae5e85993547b73d826` |
| requests | `b25c87d7cb8d6a18a37fa12442b5f883f9e41741` |

默认命令只检查输入，不访问 provider；使用新的输出目录：

```powershell
python evaluation/source_search_v6_20261003/harness/run_comparison.py `
  --smolagents-root 'D:\path\smolagents' `
  --requests-root 'D:\path\requests' `
  --corpus-root 'D:\path\02_corpus_candidate' `
  --output-dir 'D:\path\fresh-search-comparison'
```

需要再次真实测试时显式加 `--live`。每次最多 16 个用户请求，不重试基础设施失败，不覆盖旧结果；Planner 和 Decision 的实际调用数另行记录，本轮总计 **68 次 provider 调用**（含两次既有格式修复），不是 16 次 provider 调用。

离线导出及复核（导出目录中的目标文件须不存在）：

```powershell
python evaluation/source_search_v6_20261003/harness/analyze.py `
  --input-dir 'D:\path\fresh-search-comparison' `
  --output-dir 'D:\path\fresh-audit-export'
```

验证协议中的历史 v5 校验与当前 live version 解耦，仍拒绝 v6 冒充历史 12B candidate；冻结的 protocol/dataset/toolset 数字及历史结果未重标。现有长期 Task/Evidence/Execution 契约继续暂缓。
