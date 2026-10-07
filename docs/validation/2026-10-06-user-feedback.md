# 拒答与故障用户反馈（2026-10-06）

## 问题与改动

原 HTML 对证据不足仅显示 `Insufficient evidence was found.`，大部分其它拒答/失败显示 `Unable to complete this request.`；会话正文保存 `Refused: CODE` / `Failed: CODE`。503 被一律显示为 busy，缺少项目失效、模型失败和传输中断的恢复建议。

新增 API 层 `engineering_feedback`，按稳定公开终态与原因码生成固定标题、说明、建议和编辑动作。`EngineeringQueryResponse.feedback` 为可选字段，成功结果为 null；原 status、原因码、answer、evidence、execution 和 SSE schema 身份保持。覆盖三个模型拒答码、六个系统终止码与三个 Decision 失败码。未知码不回显原始值或推测具体原因。

HTML 显示卡片；已有公开资料可以打开 Sources 查看，但不当作已完成的结论。“补充问题”/“重新填写问题”只恢复对应用户问题到输入框，用户决定修改和发送，未增加自动重试。安全拒答不提供原问题恢复动作。Streamlit 的 Engineering 结果共用同一原因说明，legacy Demo 渲染保持。

新拒答/失败正文保存可读提示；旧记录在详情读取时补充反馈，原 SQLite 内容、结果和后续 load_history 不被迁移或重写。Core、Prompt、Guard、Planner、工具、检索、5/4/2 与历史窗口不改。提示不是新的模型回答，也不是取证依据。

HTTP 容量满与 503 服务不可用分开说明；404/409 建议刷新列表、恢复目录或创建新项目对话，输入错误建议检查问题。断线/超时/不完整流提示先检查已保存历史，避免把不确定的请求直接重发。诊断只保留 HTTP 状态和受控错误类别，不显示原始 HTTP detail 或异常文本。前端新增终态/answer 一致性校验：done 无 final/error、重复终态、不完整流、拒答携带答案、成功答案与分片不一致均进入故障提示。

## 离线检查

```powershell
python -m pytest -q tests/test_engineering_feedback.py tests/test_product_conversation_20.py tests/test_engineering_stream.py tests/test_engineering_stream_v2.py tests/test_engineering_agent_api.py tests/test_product_engineering_24b.py tests/test_local_project_binding.py tests/test_conversation_store_lifecycle.py tests/test_core_workflow_streamlit.py tests/test_release_app_startup.py tests/test_product_delivery.py --basetemp=./.tmp_pytest_feedback_01 --disable-warnings
# 113 passed, 3 warnings in 19.37s

python -m pytest -q tests/test_engineering_feedback.py --basetemp=./.tmp_pytest_feedback_02 --disable-warnings
# 20 passed, 3 warnings in 3.12s

node --test tests/frontend_feedback.test.mjs
# 16 passed
```

专项 20 个 pytest case 覆盖所有公开非成功终态的真实 SSE→原子存储→详情恢复、状态/answer 不变、无答案分片、无自动再请求、旧记录不改写、未知/非法代码不泄漏、成功答案保持、两种 Streamlit AppTest，以及 Node 子检查。Node 16 项覆盖反馈回退、安全动作、busy/503/目录失效区别、传输失败提示不确定保存状态与不泄漏原始细节，以及完成/拒答/错误和八种不完整或矛盾 SSE。上述结果有重叠，不累加成新基线。

文案和安全动作收口后的专项与 Node 复验通过。CI/手册清单一致为 52 模块，使用 [官方 setup-node](https://github.com/actions/setup-node) 提供 Node 24（无 npm 依赖安装）；本地没有 Node 时仅其包装子检查标记 skip。未运行完整 CI job、GitHub Actions、全量 pytest 或真实模型质量评测。warnings 为已有依赖弃用提示。

## 实际网页

- 隔离 uvicorn `127.0.0.1:8768` 使用临时项目/SQLite 和脚本化终态，无外部模型请求。预置旧 Refused/Failed 正文，真实 GET 展示新提示；发送一次问题验证新 SSE 拒答保存和刷新后恢复。
- 拒答已有一条 README 资料，卡片能打开 Sources；新/旧“补充问题”只恢复正确问题到输入框，未自动提交。超时记录显示专门标题和恢复建议。临时 DB 仅因手动发送的一轮增加两条消息。
- 390×844 下两个卡片边界均位于视口内，document width 375 / viewport 390，无横向溢出，随后恢复默认 viewport。截图在工作区旁 `.codex-test-runs/engineering-feedback/mobile-feedback.png`。
- 实际 `127.0.0.1:8000` 读取已有真实拒答历史，确认中文提示与原资料/成功历史保留；不发送问题、不改写旧记录。managed 知识库仍为 37 文档/215 分块/ready，实际服务保留运行，隔离服务停止。
- 实际页面截图为工作区旁 `.codex-test-runs/engineering-feedback/user-feedback.png`，包含真实旧追问拒答的中文说明、原先资料、补充入口与会话绑定。

实际旧记录包含正常“展示代码片段”请求被模型标为 UNSUPPORTED 的例子，以及正常追问被判信息不足的情况。提示注明系统本次判断，不断言请求本身确实超出能力；本切片改善用户解释与恢复路径，不修复或证明核心误拒答率改善。源码语义、定位与引用支持质量继续按现有技术债维护。
