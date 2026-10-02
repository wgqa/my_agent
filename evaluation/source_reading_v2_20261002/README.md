# 函数读取第一切片：配对诊断证据

本目录保存 2026-10-02 的源码读取改造记录。结论与逐项解释见 [验证报告](../../docs/validation/2026-10-02-source-reading-v2.md)。这是一轮针对工具行为的诊断，由同一 Codex 助手逐条审查，不替代冻结 benchmark 或独立产品验收。

## 文件

- `catalog.json`：付费调用前固定的 8 道题、关键源码行与每轮请求上限，未因结果改题。
- `comparison.json`：两轮用量、最终逐题源码与引用审查。所问行为与整份答案分别打分，`completed` 不等于通过。
- `offline_comparison.json`：固定锚点的旧/新 Handler 对比，不调用模型。
- `manifest.json`：源码 commit、目标文件哈希、模型与 prompt/toolset 哈希、保护文件和产物哈希。
- `raw/`：原始 32 次 HTTP/SSE 结果、各阶段被动观察、两次候选身份及收尾回放；第一轮负结果完整保留。
- `snapshots/`：原版 reader、首轮、第二轮、交付版 reader 和稳定的 AST helper。快照不作为产品工具注册。
- `harness/`：使用真实 app 的复跑脚本。额外观察只记录公开结果、安全用量和 schema 字段，不记录 key 或模型内部推理。
- `fixture_snapshot.json`：mini 控制项目的源码与文档。

首轮与第二轮各 16 次请求，总计 32 次。原 `max_live_requests=20` 是每轮上限。修正首轮发现的通用类声明回退问题后重跑固定矩阵，未丢弃首轮、未混合两个候选取最优结果。

第二轮之后又收紧了**回退分页的原窗口边界**。这没有修改 ToolSpec、prompt、Runtime 或预算；`raw/post_audit_replay.json` 记录交付版对第二轮 10 次 v2 成功读取的逐项回放，结果全部一致。第二轮付费测试对应 `reader_round2.snapshot`，交付版对应 `reader_shipping.snapshot`，不要混淆二者。交付版另做全量离线回归。

控制题 C04/C07 的冻结 catalog 将 config.py 上界写成 10，该固定 fixture 实际只有 8 行。原 catalog 保留；评分时按真实 EOF=8 截齐，记录在 `comparison.json.critical_span_normalizations`，两组采用相同规则。这一调整不改变题目或结果。

## 复跑

使用项目已安装的依赖，在仓库根目录运行。需要固定版本的本地源码，只读这些文件，不安装或执行被测仓库：

| 源码 | commit |
|---|---|
| smolagents | `c30b115286e000e98711fae5e85993547b73d826` |
| requests v2.32.5 | `b25c87d7cb8d6a18a37fa12442b5f883f9e41741` |

```powershell
python evaluation/source_reading_v2_20261002/harness/run_comparison.py `
  --smolagents-root 'D:\path\smolagents' `
  --requests-root 'D:\path\requests' `
  --corpus-root 'D:\path\02_corpus_candidate' `
  --output-dir 'D:\path\new-comparison-run' `
  --candidate-revision shipping
```

默认只检查输入哈希，**零模型调用、不创建运行目录**。追加 `--live` 才会执行 16 次可能计费的请求，需本地 `.env` 中已有 `DEEPSEEK_API_KEY`。每次使用全新输出目录；provider/transport 异常时停止，不自动重复付费请求。每个 project/arm 使用独立进程、配置与 SQLite，交替先后顺序，部分题覆盖 SSE v2。`--candidate-revision round1` / `round2` 可复跑归档候选。

脚本固定 reader 快照，仍使用当前 app 及本地配置。`run_manifest.json` 会记录当前保护文件哈希及是否与历史 app 相同；后续 Runtime/配置改变后，不能把新结果称为历史测试的精确重现。实时模型标签也可能发生服务端变更。

工具离线回归不需要 key：

```powershell
python -m pytest -q tests/test_read_project_context.py tests/test_source_definition_reading.py
```

完整离线回归沿用项目现有的 `GATE4_KNOWLEDGE_CORPUS_ROOT` 配置与测试依赖。`raw/pytest-shipping.log` 保存这次最终结果。
