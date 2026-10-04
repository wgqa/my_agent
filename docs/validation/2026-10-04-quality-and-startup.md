# 质量/成本索引与 Engineering 启动隔离

第二、三项对应切片已交付。第一项整体可靠性仍部分完成，第四项未推进。本轮仅修改API启动装配、UI连接判断与外围报告/验证材料；没有改任务规划、语义Guard、工具正文、Runtime循环或预算。

## 第二项：能查清楚当前质量与代价

`scripts/report_current_quality.py` 用标准库读取原54个请求、完整答案审查、各阶段manifest与封档材料。运行不导入API/model、不调用provider、不重新判答案。输出 [Markdown索引](2026-10-04-quality-baseline.md) 和同名JSON。

- 核心任务与预期拒答边界分开；PASS/PARTIAL/FAIL与completed/refused/failed分开，保留负实验。
- 10个阶段单列，不把原版、未晋升候选、对象Reader、改变输入与入口修订拼成成功率。
- 记录完整Planner + Decision（含解析修复）调用与usage，避免仅拿公共execution里的Decision tokens作为总成本。p50/p95为HTTP/SSE请求观测耗时，nearest-rank p95、小样本顺序检查，非SLA或并发压测。
- 校验81份历史文件的字节SHA；原始数据/审查case ID必须相等且无重复，预算和usage无缺失。已有封档索引作为完整性依据，不构成第三方签名或独立验收。
- 保存当前生产文件SHA/fingerprint，对比最近实测版本。该切片结束时差异仅`api/app.py`与`ui/app.py`，来自启动/UI隔离；主Decision/Planner/Reader/Runtime正文仍与最近实测一致。后续交付切片新增版本元数据/展示，实时差异见生成报告。旧实测不能冒充修改后的新一轮付费验收。

同题六开发题的完整正确由1题变3题，但两版各一次；输入tokens从177,140到189,856，p50从4.736到6.131秒。当前材料支持“取证改善同时付出更多上下文与耗时”，不支持“更快、更省或已经稳定可靠”。最后三个修订入口为1 PASS/2 PARTIAL，不能以completed关闭第一项。

```powershell
python scripts/report_current_quality.py --output-prefix docs/validation/2026-10-04-quality-baseline
```

该命令只覆盖当前生成报告，历史raw、审查、快照和manifest不改。历史Gate 2/3/4数字继续绑定原冻结版本。

## 第三项：旧Demo失败只影响自己的入口

原启动依赖：`Pipeline成功 → legacy Tool Agent成功 → Engineering装配`。Engineering本已有独立verified BM25后端，却被外围成功分支阻挡。此次把Engineering装配移到独立try分支，沿用全部原builder、profile、后端与API响应；不复制第二套执行循环。

| 失败位置 | 结果 |
|---|---|
| 旧Pipeline | legacy模式不可用，Engineering仍独立装配 |
| 旧Agentic RAG | 该模式不可用，其它legacy和Engineering继续装配 |
| 旧Structured Tool Agent | 该模式不可用，Engineering继续装配 |
| Engineering语料验证或主工具装配 | Engineering返回503，legacy继续按自身状态运行 |
| 会话数据库 | 会话操作503，独立查询与legacy仍保持自身状态；未将数据库错误伪装成已保存 |
| 显式非法项目根目录 | 沿用fail-fast，不绑定到其它仓库 |

UI的`api_available`由可达的`/capabilities`或正常legacy health判定。各模式仍按`features`控制，API可达不等于某个Agent就绪。`/health`和`/stats`保留legacy含义与503行为；不把旧Pipeline修成假正常。关闭生命周期的finally清理原有引用。初始化仍在同一进程顺序执行，本切片没有解决卡住不返回、import依赖或缺包的隔离问题，也没有加入后台重试。

## 验证

两组测试的模块不重叠，合计 **122 passed / 3 warnings**：

```powershell
python -m pytest -q tests/test_engineering_startup_isolation.py tests/test_api.py tests/test_ui_chat_first.py tests/test_ui_productization_18a.py tests/test_engineering_project_workspace.py --basetemp=<fresh-temp>
# 114 passed / 3 warnings
python -m pytest -q tests/test_current_quality_report.py --basetemp=<other-fresh-temp>
# 8 passed
```

新增启动专项在真实lifespan中注入旧Pipeline/Agent/Tool及主语料/工具/数据库失败，经HTTP验证能力状态和503范围；旧模块失败时，由真实UnifiedRuntime、真实calculator与脚本化决策完成`2 * 3 = 6`。脚本化决策不证明模型正确率。还验证UI在legacy health=503时保留Engineering可用、实际断网时清除旧可用状态。

另执行一项真实进程检查：

```powershell
python scripts/smoke_engineering_isolation.py --corpus-root <existing-verified-corpus>
```

临时无效legacy配置确实使Pipeline初始化失败，真实uvicorn与原verified corpus、原主runtime成功装配；`/health=503`、`features.engineering_agent=true`、知识37文件/215chunks/verified=true；实际`ui/app.py`由AppTest连接该HTTP服务，聊天输入可用，输出 **ENGINEERING_ISOLATION_SMOKE_OK**。使用dummy key、临时项目/数据库，只访问本机端口，不发送Engineering模型请求。没有启动独立Streamlit服务器或浏览器，不称作完整浏览器E2E。

CI与运行手册同步加入两项新增测试，清单42→44模块；本轮未运行完整CI清单、全量pytest、GitHub Actions、付费模型重测或并发压测。没有commit/push、依赖升级、目录大重构或长期v2契约实现。
