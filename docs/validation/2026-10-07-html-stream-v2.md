# HTML 对话切换 Rich Activity V2（2026-10-07）

HTML 原来使用 `/messages/stream/v1`，只有简化状态，实时活动列表还被 CSS 隐藏。
现默认使用项目绑定的 `/messages/stream/v2` 与 `engineering_query_stream_v2`。
V1 stream 实现保持原样，旧 API、Streamlit 和历史会话继续兼容。

## 行为与边界

- 使用已有 Runtime 的 run_started、activity、evidence_added、verification 公共事件。
  工具生命周期按 activity_id 更新，展示目的、目标、结果摘要、错误码和证据链接。
  只呈现公共执行活动，不记录模型推理、原始观察或完整工具参数。
- V2 final/result 增加 `activity` 快照。与 user/assistant 消息原子保存后才发送答案，
  读取旧对话不需要数据库迁移；旧记录没有 V2 活动时仅展示已有 public trace。
  Context Window 仍只读取原 role/content 历史，不加入活动快照。
- V1/V2 对话入口共享绑定、历史、保存和请求生命周期；运行中的项目不被其他会话改变。
  无改动 Core、Prompt、Guard、七工具设计、5/4/2 预算或 SQLite schema。
- HTML 检查 V2 活动形状、终止事件、答案与 final 的一致性；不接受 V1 事件或静默回退。
  异常或不完整流仍提示先检查已保存历史，不自动重试。

## 离线验证

```powershell
python -m pytest -q tests/test_engineering_conversation_stream_v2.py tests/test_engineering_stream.py tests/test_engineering_stream_v2.py tests/test_product_conversation_20.py tests/test_product_engineering_24b.py tests/test_local_project_binding.py tests/test_engineering_feedback.py tests/test_product_delivery.py --basetemp=./.tmp_pytest_html_v2_final_20261007 --disable-warnings
```

结果：**100 passed / 3 warnings**。其中一个 Python 用例调用 Node，执行
`tests/frontend_feedback.test.mjs` 和 `tests/frontend_stream_v2.test.mjs` 的 **29 项**检查。
不将 Node 子检查重复累加到 Python 数量。覆盖真实工具的两项目读取、错误绑定、目录失效、
多轮历史、重启后活动恢复、保存失败不呈现答案、拒答/失败反馈、worker 断开清理，以及 V1 兼容。
Node 覆盖跨 UTF-8/CRLF 帧、V2 路径和 project_id、生命周期合并、活动恢复及旧协议拒绝。

Python 编译、三个前端模块语法、git diff --check、CI/手册 53 模块清单对齐通过。

## 实际 HTML

隔离 uvicorn 服务使用真实只读工具与脚本化决策，全部 SQLite 与截图位于工作区的
`.codex-test-runs/html-stream-v2/`，不提交。验证实时读取目标与范围、Activity 详情、刷新后
同样的记录、E1 跳转到真实 config.py 第 1–2 行、旧 V1 会话继续发送 V2 消息与中文拒答。
测试夹具的初始化/动作构造错误在本地修正；此前 error/done 未留下半轮消息。

没有外部模型调用、全量 pytest 或 GitHub Actions；这些检查验证展示与保存，
不代表模型答案质量或误拒答有所改善。
