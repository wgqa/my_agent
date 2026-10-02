# 给 Engineering Agent 挂载新项目

当前产品面向 AI / RAG / Agent 研发分析。挂载的是**本机已有的项目目录**，Agent 用只读工具查看其中的源码、文档、Git 变更和测试文件。它不会替新项目安装依赖、修改源码或执行测试。

本说明基于 2026-10-02 的实际验证，见 [系统评估](validation/2026-10-02-system-assessment.md)。完整安装和启动环境见 [本地运行手册](release2_local_runbook.md)。

## 两个目录各自负责什么

| 配置 | 用途 | 更换新项目时的操作 |
|---|---|---|
| `ENGINEERING_PROJECT_ROOT` | 源码、项目文档、Git 变更、测试文件的根目录 | 改为新项目的本机目录，重启后端 |
| `ENGINEERING_KNOWLEDGE_CORPUS_ROOT` | Engineering 的 AI 技术知识库 | 同领域源码项目可继续使用当前已验证语料 |

当前知识库固定校验 `870e5864df67`：37 个文档、215 个 chunk、Recursive + BM25。**不能把第二个配置随意改成新的业务文档目录**；内容不符合冻结 manifest 时，Engineering 不会就绪。

`POST /index/file` 和 UI 的知识库导入属于 legacy Pipeline。Engineering 使用独立的 verified backend，导入文件不会自动更新 Engineering 的知识库。

## 操作步骤（PowerShell）

先把新项目 clone 或放到本机，例如 `D:\projects\my-new-agent`。需要查看 Git 变更时，该目录应属于 Git 仓库；普通目录也能读取源码，但 Git 工具会报告无法使用。

在后端终端使用本项目已配置好依赖的 Python 环境：

```powershell
Set-Location 'D:\学习\rag实战项目\rag-knowledge-base'
$env:ENGINEERING_PROJECT_ROOT = 'D:\projects\my-new-agent'
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

如果后端已经运行，先用 Ctrl+C 停止，再执行启动命令。目录必须存在。带空格和中文的目录已验证可用；模型和请求体不能覆盖项目根目录。

本机 `.env` 已配置 DeepSeek key 和经过验证的知识库路径；上面的命令只切换项目。也可把 `ENGINEERING_PROJECT_ROOT` 写入本机 `.env` 后重启，但已设置的进程环境变量优先于 `.env`。

在另一个终端启动或重新打开前端：

```powershell
Set-Location 'D:\学习\rag实战项目\rag-knowledge-base'
$env:RAG_API_URL = 'http://127.0.0.1:8000'
python -m streamlit run ui/app.py --server.port 8501
```

然后确认后端身份和可用状态：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/project'
Invoke-RestMethod 'http://127.0.0.1:8000/engineering/knowledge'
Invoke-RestMethod 'http://127.0.0.1:8000/capabilities'
```

预期 `/project` 的 `project_name` 是新目录名、`source` 为 `configured`；知识状态的 `ready` / `verified` 为 true，`engineering_agent` capability 为 true。`/health` 为 200 只说明进程活着，不能代替这三项检查。

首次调查可以直接指定真实存在的项目相对路径，例如：“请读取当前仓库 src/my_agent/config.py，说明这个文件的配置默认值，并引用源码。”工具按需读目录，不需要预先把全部源码导入向量库。之后再调查调用关系、跨文件实现、文档一致性和变更相关测试。

## 切换、恢复与限制

- 一个 API 进程绑定一个项目，当前没有页面中的动态项目切换。修改运行中终端的环境变量不会重新绑定已有 Runtime，必须重启。
- 不同根目录的会话隔离，即使两个项目都叫同一个名字。重新挂载原路径可恢复其已保存会话；移动项目到另一个路径会被视为新的项目身份。
- 多项目同时使用时，分别启动绑定不同根目录的后端、使用不同端口，并让各前端连接对应地址。这是进程隔离的部署方式，未提供多租户项目管理功能。
- 搜索只处理允许的文本文件，忽略隐藏目录、依赖目录、超大文件和受保护文件。当前是有界字面搜索，不能把“没搜到”直接当成“整个项目没有实现”。
- 当前代码读取最多覆盖目标行前后各 30 行。长函数、跨文件、多轮追问仍可能取证不完整；`find_tests` 只发现候选测试，不执行测试，也不证明测试一定受影响。

如果新项目属于同一 AI 技术领域，先按上面的方式挂载源码。如果要支持 Java 业务、医疗、金融等全新的领域，需要另建受版本管理的领域知识配置和评估集，并让 Engineering backend 接受该配置；仅更换源码目录不能完成知识领域迁移。相关重构建议见 [系统评估](validation/2026-10-02-system-assessment.md)。
