# 当前演示、交付和版本一致性检查

第四项的开发版展示/交付切片已完成。当前版本为 **2.0.0-dev / development**，
不宣布Release 2.0正式验收；第一项核心可靠性仍部分完成。没有修改Planner、
Decision、Reader、Verifier、Runtime循环或5/4/2预算，也没有新增按题放行条件。

## 修改

| 原缺口 | 本轮结果 |
|---|---|
| 当前路线为Release 2.0开发，OpenAPI仍显示1.0.0 | 单一`core/product_version.py`作为产品版本源；OpenAPI、`GET /version`、UI Settings和当前Demo共用。产品版本与v1/v2 transport schema分开 |
| 现有固定Demo仅演示旧Basic/Agentic/Tool接口 | 新增三类Engineering场景，复用主页问题生成、Conversation API和SSE reducer，保留历史Release 1.0脚本 |
| 演示需手工准备变更，容易碰到已有项目 | 新目录复制公开fixture，建立本地Git基线后只将默认值4改6；已有目录直接拒绝，不reset/push或执行目标代码 |
| 通用启动检查主要证明legacy可用 | OpenAPI路由/产品版本检查补齐；Full App可显式提供verified corpus，要求Engineering ready、实际三个卡片和聊天入口可用 |
| smoke会继承开发者的挂载配置 | 显式隔离项目、数据库、语料和凭据；默认检查不读取真实语料，带corpus参数的检查只使用指定只读语料 |
| 当前演示与历史评测的展示边界不清楚 | README/运行/演示手册注明开发版，保留旧冻结记录，真实结果不自动变成正确率，输出不覆盖已有证据 |

演示入口见 [操作手册](../demo_engineering_runbook.md)。`prepare/check`零模型，
`run --live`每场景只提交一条消息、无任务级重试，故障停止并保留部分记录。
三条消息仍会经过原Planner/Decision及原有有界解析修复，不等于三次provider
调用。每个新会话保存结果与SSE final相等；不会删除会话或掩盖拒答。

版本标识能发现不同版本标签，但不证明相同标签下源码完全一样。当前质量报告
继续保存逐文件SHA和与最近实测的差异，没有重写历史来源或模型结果。

## 局部测试

三个不重叠的测试集合共 **100 passed / 3 warnings**，12模块：

```powershell
python -m pytest -q tests/test_product_delivery.py tests/test_ui_api_client.py tests/test_core_workflow_entry.py tests/test_core_workflow_streamlit.py tests/test_engineering_startup_isolation.py tests/test_current_quality_report.py --basetemp=<fresh-temp>
# 57 passed / 3 warnings
python -m pytest -q tests/test_release_startup.py tests/test_release_app_startup.py tests/test_release_demo.py --basetemp=<other-fresh-temp>
# 13 passed
python -m pytest -q tests/test_ui_chat_first.py tests/test_ui_productization_18a.py tests/test_reproducibility_contract.py --basetemp=<another-fresh-temp>
# 30 passed
```

产品专项包括无runtime时版本/OpenAPI可达、UI版本差异提示、smoke配置隔离、
fixture真实Git diff、版本/项目/可用性失败时零模型请求、拒答原样保存、不覆盖
旧输出、SSE故障不重试，以及三个场景的真实工具与会话/SSE/SQLite贯通。

最后一项使用真实UnifiedRuntime、Reader v4、Git diff/test tools和HTTP API，
由脚本化决策指定步骤，三个终止结果completed并验证保存一致；不是LLM正确率
或未见验收。首轮脚本化测试把git_diff参数误写为`scope`，工具按原契约正确
拒绝；修正测试为`mode`后通过，没有修改生产工具或放宽Guard。后续只调整
演示记录的任务重试字段说明，专项再复验，不与上述数量累加。

## 实际进程与页面

```powershell
python scripts/smoke_local_app.py --corpus-root <existing-verified-corpus>
python scripts/smoke_engineering_isolation.py --corpus-root <existing-verified-corpus>
```

前者实际启动uvicorn和Streamlit两个服务，在临时Git样例/数据库、dummy key和
指定既有verified corpus下，由实际页面AppTest连接HTTP服务。结果
**FULL_APP_SMOKE_OK**，`engineering_readiness_checked=True`，同时验证当前Demo
预检查、三张任务卡片、聊天可用、UI/API版本一致。旧默认startup/full-app
smoke也在上述13项测试中通过；默认模式没有验证主Engineering ready。

后者重新验证旧Pipeline配置失败时主链与实际页面仍可用，结果
**ENGINEERING_ISOLATION_SMOKE_OK**。这些检查没有提交模型问题，不下载模型，
不重启开发者已有服务，不使用已有项目或会话数据库，也不等于浏览器视觉E2E。

CI/运行手册清单44→**48模块**，加入产品交付与已有startup/full-app/legacy-demo
回归；本轮没有执行全部48模块、全量pytest、GitHub Actions或付费Live Demo。
没有commit/push、正式发版、依赖升级、目录大重构或长期v2契约实现。
