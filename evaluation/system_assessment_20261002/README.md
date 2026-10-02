# 2026-10-02 系统诊断记录

这是两个新项目上的有界系统诊断，不是正式独立验收或旧 benchmark 重跑。所有任务结果保留；后续用它调试后，只能作为诊断回归集。

| 文件 | 内容 |
|---|---|
| [manifest.json](manifest.json) | 主项目 HEAD / 实际代码哈希、语料与模型身份、预算、分布、数据文件哈希 |
| [results.jsonl](results.jsonl) | 30 项问题、公开答案/证据、阶段观测和逐项审查理由 |
| [infrastructure.json](infrastructure.json) | 42 项迁移与边界检查、最终全量 pytest、低层分词噪声/语料覆盖诊断 |
| [fixture_snapshot.json](fixture_snapshot.json) | 控制项目的文本、baseline 配置和故意保留的变更/文档/测试冲突 |

首轮 28 项：20 completed / 8 refused；逐条源码与引用审查 10 PASS / 12 PARTIAL / 6 FAIL。PASS 含 4 项预设的合理拒答。另有 F01 不可信文档实际暴露检查，以及 F02 Planner schema 诊断复现；两项都没有覆盖或替换首轮结果。

审查由同一 Codex 助手依据公开输出和固定源码完成，没有使用第二个评审模型或独立人工评审。`gold_paths` 是调查目标和定位线索，不是机械打分条件；主要问题、材料支持和必要前提决定 grade。

本轮 Production 策略未改。唯一新测试代码修正是 `tests/test_api.py` 的不可用 Runtime fixture 清空 Engineering facade。最终全量测试为 2658 passed / 6 skipped；6 项均受当前 Windows symlink 权限限制。

逐条结果可这样离线读取，不触发模型请求：

```python
import json
from pathlib import Path

path = Path("evaluation/system_assessment_20261002/results.jsonl")
cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
for case in cases:
    print(case["id"], case["public_response"]["status"], case["review"]["grade"])
```

完整临时 runner 和本机原始日志留在工作区 `.codex-test-runs/assessment-20261002-07d98cdbea5341329a7f7e21f396d3b4/`。此目录中的环境、临时 Git checkout 和 SQLite 不作为产品依赖，不加入 Git。可携带的结果已去掉本机绝对目录；没有 key、原始模型输出或思维链。

新项目实际操作见 [挂载手册](../../docs/project_mount_runbook.md)；全部结果、失败过程与重构切片见 [评估报告](../../docs/validation/2026-10-02-system-assessment.md)。后续候选应先用这些结果检查针对性变化，再用从未用于修改的仓库和问题独立验收。
