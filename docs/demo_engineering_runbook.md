# Engineering 演示手册（开发版）

当前展示版本为 **2.0.0-dev / development**，版本源是 `core/product_version.py`。
OpenAPI、`GET /version`、页面Settings和当前Demo共用该标识。Release 1.0的历史
冻结记录保持原身份；Release 2.0尚未正式验收，核心任务可靠性仍部分完成。

这份手册演示当前三个只读核心任务、真实引用、会话保存和SSE进度。样例是公开且
事先知道的，方便复现和讲解，不是未见测试集，不输出模型正确率。

## 1. 准备独立样例项目

先按 [本地运行手册](release2_local_runbook.md) 安装锁定依赖，准备已验证语料。
在主仓库目录执行：

```powershell
python scripts/demo_engineering.py prepare --workspace ../.codex-test-runs/engineering-demo
```

命令只在新目录复制 `demo/engineering_project`，初始化本地Git基线，再将
`DEFAULT_RESULT_LIMIT = 4` 改为6；README和已有默认值测试仍写4。打印的项目路径
用于下一步。目录已存在时直接退出，请选择另一个新目录；不会reset已有仓库，
不会执行样例源码或测试，也不会push。样例目录可以长期保留供演示。

## 2. 启动同一份代码的前后端

在后端终端绑定刚打印的样例路径，语料和DeepSeek配置仍按运行手册设置。
DeepSeek key只需要配置在后端；以下命令不会改写已有 `.env`：

```powershell
$env:ENGINEERING_PROJECT_ROOT = (Resolve-Path ../.codex-test-runs/engineering-demo).Path
$env:ENGINEERING_CONVERSATION_DB = Join-Path $env:ENGINEERING_PROJECT_ROOT "demo_conversations.sqlite3"
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

数据库在演示目录中，会成为一个未跟踪文件；变更任务只调查明确的
`support_search/settings.py`，不会把数据库当代码变更。正常项目继续使用自己的
数据库，不迁移已有会话。项目切换需要重新启动后端才能重新绑定。

在另一个终端、同一仓库/环境启动：

```powershell
$env:RAG_API_URL = "http://127.0.0.1:8000"
python -m streamlit run ui/app.py --server.port 8501
```

在第三个终端做零模型预检查：

```powershell
python scripts/demo_engineering.py check --base-url http://127.0.0.1:8000
```

要求后端版本等于当前Demo版本、Engineering ready/verified=true、绑定的公开
项目名为`engineering-demo`。使用不同目录名时加`--expected-project <目录名>`。
预检查不验证API额度，也不证明答案质量；它不使用legacy `/health`作为主链门槛。
页面Settings显示UI/API版本，版本不同会提示重启同一份代码；版本标识不替代
逐文件代码身份，最新质量报告仍会展示当前源码与实测快照的差异。

## 3. 展示三个入口

每个场景开一个新会话，按以下目标填写卡片；实际题目与脚本共用
`build_core_workflow_question`，避免演示入口和主页入口各写一套行为。

| 卡片 | 目标与补充来源 | 应核对的材料与行为 |
|---|---|---|
| 配置到行为追踪 | `SUPPORT_RESULT_LIMIT`；`support_search/settings.py`和`support_search/service.py` | 默认6、环境覆盖、合法范围1..20、向retriever传递limit；来源是否实际读取 |
| 变更与测试定位 | `support_search/settings.py` | Git diff的4→6、已有默认测试断言4、环境覆盖测试断言9；建议真实测试命令，注明未执行 |
| 文档与实现核对 | README中的默认值、覆盖和范围；`support_search/settings.py` | 文档4与实现6冲突，两边覆盖与范围一致，分别引用文档/源码 |

打开Evidence检查路径、行号和正文；有“未核实”、拒答或证据范围不足时，直接
展示实际结果和限制。当前系统没有编辑、执行测试或沙箱能力，建议命令不等于
已经运行。支持材料正确也不自动代表整份答案语义正确。

## 4. 可选：记录三次真实会话

下面的`run --live`才会发模型请求，最多三条消息、每场景一次，无任务级重试。
backend持有凭据，CLI不要求本机另外设置一份key：

```powershell
python scripts/demo_engineering.py run --live --base-url http://127.0.0.1:8000 --output ../.codex-test-runs/engineering-demo-result.json
```

脚本创建三个服务端会话，使用主页相同的消息/SSE接口和reducer，检查终止事件、
5/4/2预算、已保存两条消息及最终response一致。记录会话ID、题目、真实公共结果
和`content_review=not_evaluated`。completed/refused/failed都原样保存，不自动评为
正确。正常拒答不重试；HTTP/SSE/持久化故障即停止并保留已完成的记录。

三条消息不等于三次provider调用：每条仍经过原Planner和最多五次逻辑Decision，
原有有界解析修复也保留，实际调用和token应按观测统计。演示脚本不扩大预算。

输出文件必须是新文件，已有结果不会覆盖。保存的三个会话可在页面刷新后查看；
脚本不删除它们。要重新运行请指定新的结果文件，并将新结果视为新演示。

## 5. 无模型的交付检查

```powershell
# 不需要语料或真实key：隔离启动、版本/OpenAPI和UI基本连接
python scripts/smoke_local_api.py
python scripts/smoke_local_app.py

# 需要已有verified corpus：真实主链装配、三个入口、聊天和版本展示
python scripts/smoke_local_app.py --corpus-root "$env:ENGINEERING_KNOWLEDGE_CORPUS_ROOT"

# 旧Pipeline配置失败时，Engineering和实际页面仍可用
python scripts/smoke_engineering_isolation.py --corpus-root "$env:ENGINEERING_KNOWLEDGE_CORPUS_ROOT"
```

这些smoke覆盖实际本地进程与页面AppTest，使用dummy key、临时项目/数据库，
不提交模型问题。它们不等于浏览器视觉测试、Live Demo或内容质量验收。
当前 [质量与成本索引](validation/2026-10-04-quality-baseline.md) 与历史Gate评测
各自保持版本和验证范围；更详细的本轮结果见 [交付检查](validation/2026-10-04-product-delivery.md)。
