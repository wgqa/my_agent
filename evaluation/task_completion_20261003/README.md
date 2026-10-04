# 任务完成与文档取证开发实验（2026-10-03）

## 结果与范围

本目录保留两次不同干预的正负结果。每次使用同一份事先冻结的 12 题、旧/新各一轮，共 48 个真实用户请求、187 次实际 provider 调用。全部是已知开发题的诊断；不属于 Holdout，也没有独立评审。

1. 顶层：只改通用 Decision prompt，24 请求 / 92 provider 调用。README 零工具拒答未改善；candidate 有一次 action schema / repair 失败，**NOT_PROMOTED**。生产提示词已按字节恢复，候选与临时专项测试另存快照。
2. `document_source_slice/`：只增加独立项目文档证据档位，24 请求 / 95 provider 调用。三道可答文档题从 0/3 变为 3/3 完成，源码七题工具链完全相同。**保留该切片**，但公开引用截断、源码行为遗漏、R03 表述错误、通用问题拒答仍存在。

详细方法、逐题质量与限制见 [验证报告](../../docs/validation/2026-10-03-project-document-acquisition.md)。`outcome.json` 记录分阶段结论及归档 SHA；不合并两阶段质量指标。

## 文件约定

- `initial_manifest.json`：改变之前的保护文件与基线身份。
- `catalog.json` / `manifest.json`：运行前冻结的输入、SHA、预算与晋升门槛；后续不改写。
- `raw/paired/live_results.jsonl`：逐请求公开响应、实际工具观测、provider 元数据与可信控制状态。不是原始模型思维链；不含 `.env`、数据库或服务日志。
- `raw/paired/run_manifest.json`：关联实际执行与冻结输入的 SHA。
- `raw/paired/comparison.json`：`harness/analyze.py` 从 raw 计算的客观统计，**不是语义自动评分**。
- `document_source_slice/manual_review.json`：同一助手对全部 12 对回答与公共引用的审查。
- `baseline_decision_prompt.snapshot` / `candidate_decision_prompt.snapshot`：提示词实验的实际 Python 文件；candidate_profile.json 另保留模板及调用限制，test_task_completion_policy.snapshot 保存未晋升候选的 4 项测试。
- `document_source_slice/snapshots/requirements_{baseline,candidate}.snapshot`：文档实验两组实际 Router 文件。
- `document_source_slice/snapshots/requirements_retained.snapshot`：最终保留实现。付费实验后补充文件名遮蔽；`raw/retained_offline_audit.json` 核对全部 12 题的路由与付费候选一致，额外路径边界只做离线测试。
- `raw/pytest-targeted.txt`：各阶段对应的局部回归。顶层 195 passed 属于后来撤回的提示词候选；文档阶段 278 passed 才是保留切片的相关回归。
- `document_source_slice/raw/pytest-final-ci-module.txt` / final_test_scope.json：历史身份用例移入 CI 所选模块后的 31 项复验；不与 278 累加。

`__pycache__`、运行时数据库、配置与服务日志不归档。目录设置 `-text`，保存冻结材料的原始字节；不为消除日志格式空白而改写 raw。

## 离线重算

在仓库根目录执行，输出必须是新文件：

```bash
python evaluation/task_completion_20261003/harness/analyze.py \
  --input evaluation/task_completion_20261003/raw/paired/live_results.jsonl \
  --output /tmp/task-completion-comparison.json
python evaluation/task_completion_20261003/harness/analyze.py \
  --input evaluation/task_completion_20261003/document_source_slice/raw/paired/live_results.jsonl \
  --output /tmp/document-source-comparison.json
python evaluation/task_completion_20261003/harness/verify_retained_slice.py \
  --output /tmp/document-source-offline-audit.json
```

Windows 替换输出为有现存父目录的绝对路径。以上三条不调用 provider。离线 audit 用于本次保留代码身份，未来继续修改受保护文件时失败是预期行为，不应更新冻结输入以使其通过。

## 真实重跑条件

不要直接在已经继续开发的工作区重跑或修改原 manifest。用隔离 checkout，从 baseline `d937046d2c0c8d41a74693f879ff41091a861ab9` 恢复同一份输入：

- 顶层实验：将 candidate_decision_prompt.snapshot 原样放回 `core/tool_agent/decision_prompt.py`，让原 harness 能选择 baseline/candidate 两份模板；Router 保留 baseline v1。候选模块包含两份 profile 和一致的 output cap / parse repair 配置。
- 文档实验：主提示词使用 baseline，将 requirements_candidate.snapshot 原样放回 `core/engineering_requirements.py` 以通过候选文件身份预检。每个隔离 App 进程再由原 harness 注入对应 baseline/candidate snapshot，避免类型身份混用。当前 retained 文件不是当时付费 snapshot，不能用它顶替后重标 manifest。
- 两阶段均须提供原 pin、干净 checkout 的 smolagents / Requests，及 corpus `870e5864df67`。runner 的 `--help` 列出 `--smolagents-root`、`--requests-root`、`--corpus-root`、`--output-dir`；输出目录必须不存在。
- runner 默认只做身份预检；显式 `--live` 才启动模型调用。上限为 24 用户请求；基础设施失败即停止，不自动补跑。保留新输出目录，不覆盖这里的 raw。

原 runner 分别为 `harness/run_comparison.py` 与 `document_source_slice/harness/run_comparison.py`，复用的 source_search_v6 passive observer / runner helpers SHA 已冻结。恢复输入可以复现配置，不能保证服务端模型逐字重现原回答。API key 从本地环境提供，不能写入评测归档。
