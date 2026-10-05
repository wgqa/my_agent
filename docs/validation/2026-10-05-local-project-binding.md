# HTML 对话绑定本地项目验证（2026-10-05）

## 完成范围

HTML 的 New chat 提供已添加项目选择与本机绝对目录输入。项目登记在独立 SQLite，公开 id 不包含目录或内部会话 key。新对话沿用根目录身份并固定绑定，所有已登记项目的会话显示在侧栏，顶部与每条会话显示项目名。切换项目不用重启；知识库继续共享、检索整库。

API 将原有 Engineering 装配抽为函数，按项目注入根目录并复用相同 Core facade/Runtime、共享知识检索 port。默认 facade 预置在最多 4 项的缓存中，其余项目首次发消息时装配。缓存加锁防止同项目重复装配，淘汰不会使正在执行的请求丢失 facade。请求先验证会话与项目匹配，再捕获 facade 与存储 key。

本次项目功能未修改 Core、Prompt、Planner、工具协议、证据规则、5/4/2 预算或 6 条/1200 token 历史窗口。上一项知识库管理已有的 `core/knowledge_library.py` 不属于本次项目选择改动。旧 question-only API、Streamlit、`/project` 与无请求体创建会话继续使用启动默认项目。

当前只支持后端本机已有目录；未实现 GitHub URL 克隆、原生目录浏览、项目移动后的重绑定或多租户访问控制。目录消失可读历史，发消息/创建对话返回 409；运行时装配失败返回 503，均不会回退到另一个项目。

## 离线回归

在 Windows / Python 本地环境执行以下两组，测试集合不重叠：

```powershell
python -m pytest -q tests/test_local_project_binding.py tests/test_engineering_project_workspace.py tests/test_product_conversation_20.py tests/test_conversation_store_lifecycle.py tests/test_knowledge_library.py tests/test_engineering_startup_isolation.py tests/test_engineering_planner_alignment.py tests/test_g11_02_theory_code.py tests/test_g11_02_r4_knowledge.py --basetemp=./.tmp_pytest_local_projects_05 --disable-warnings
# 119 passed, 1 skipped, 3 warnings in 14.04s

python -m pytest -q tests/test_api.py tests/test_engineering_agent_api.py tests/test_engineering_stream.py tests/test_engineering_stream_v2.py tests/test_release_startup.py tests/test_release_app_startup.py tests/test_product_delivery.py --basetemp=./.tmp_pytest_local_project_regression_04 --disable-warnings
# 104 passed, 3 warnings in 163.17s
```

新增项目测试覆盖登记幂等/持久化/公开字段，拒绝相对目录、GitHub URL、缺失目录和文件，两个项目同名源码的真实只读工具读取，A→B→A 的会话与证据隔离，错误项目/会话组合在 Runtime 前返回 404，禁止消息体重新绑定，目录失效、登记/历史重开、同名项目和默认项目改变后的旧绑定保持，缓存并发复用与淘汰，进行中的 A 任务不受 B 对话创建影响，实际装配注入根目录并共享知识库，以及装配失败不保存半轮、不使用默认项目。

测试使用脚本化 Decision / Query Resolver 与真实工具、Unified Runtime、SSE 和 SQLite；实际装配测试使用 dummy key 且不调用模型。唯一 skip 为既有 Windows symlink 限制，warnings 为已有依赖弃用提示。CI 与运行手册回归列表一致，现为 51 模块；未运行完整 CI job、GitHub Actions、全量 pytest 或真实模型答案评测。

## 实际 HTML 页面

通过本地隔离 uvicorn 服务 `127.0.0.1:8767` 提供相同 HTML/API，临时目录与数据库放在工作区旁 `.codex-test-runs/local-project-binding/`，未将临时项目登记到生产数据库。模型部分替换为测试中的脚本化 resolver/provider，工具和会话链真实运行，无外部请求。

1. 默认甲项目发送配置读取，回答含 `alphaprojectmarker`。
2. New chat 中添加相对目录，窗口显示有效目录要求；填写乙项目完整路径后选中乙项目并创建。
3. 乙项目发送同一问题，回答含 `betaprojectmarker`。两个问题读取相同相对文件 `config.py`，无串读。
4. 切回甲项目旧对话，顶部与已保存回答恢复甲项目；刷新后列表恢复两个项目，最新乙对话仍绑定乙项目及其历史。
5. 390×844 的选择弹窗完整可用，dialog 左右边界在视口内，文档无横向溢出。临时 viewport 最后已恢复。
6. 实际 `127.0.0.1:8000` 页面确认顶部/列表的 `my_agent` 与 New chat 默认项目选择，未发送模型问题或登记测试项目。只读检查确认生产项目登记仅包含可用的默认 `my_agent`，知识库维持 managed / 37 文档 / 215 分块 / ready，Engineering capability 为 true。生产服务保留运行，隔离服务在检查后停止。

截图保存为工作区旁 `project-dialog.png`（实际页面）和 `mobile-project-dialog.png`（隔离小屏）。服务重新加载新代码所需的一次部署重启已完成；日常添加、选择与切换本地项目不需要重启。
