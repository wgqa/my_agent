# 给 Engineering Agent 挂载新项目

当前产品面向 AI / RAG / Agent 研发分析。挂载的是**本机已有的项目目录**，Agent 用只读工具查看其中的源码、文档、Git 变更和测试文件。它不会替新项目安装依赖、修改源码或执行测试。

HTML 页面已支持按对话选择本地项目，切换不需要重启。2026-10-05 的隔离、持久化与实际页面检查见 [项目绑定验证](validation/2026-10-05-local-project-binding.md)。完整安装和启动环境见 [本地运行手册](release2_local_runbook.md)。

## 在 HTML 页面添加项目

1. 把项目 clone 或放到后端所在的本机，例如 `D:\projects\my-new-agent`。
2. 打开 `http://127.0.0.1:8000/`，点击左侧 **New chat**。
3. 在“添加其他本地项目”填写完整目录，点击“添加项目”；也可直接填写后点击“创建对话”。已添加的项目可从下拉框选择。
4. 创建后，顶部显示“项目：名称”，每条会话下方也显示项目名。点击旧会话会恢复它原来绑定的项目和历史。

项目在创建对话时固定绑定。添加或切换项目不会修改启动时的默认项目，不会改变其他页面正在运行的任务。后端首次使用项目时装配现有 Runtime，最多缓存 4 个项目的 facade；缓存淘汰只影响下次装配，不影响运行中的请求。

目录必须是后端本机已有的绝对目录，支持中文和空格。普通目录也能读取源码；需要 Git 工具时，该目录须属于 Git 仓库。当前填写路径，不提供浏览器目录选择器或 GitHub URL 克隆。

项目登记默认保存在 `data/runtime/engineering_projects.sqlite3`（如设置会话 DB，则默认放在其旁边），可用 `ENGINEERING_PROJECT_DB` 指定路径。会话仍使用已有 SQLite 存储和根目录身份，不迁移旧表；原默认项目的历史会自动出现在 HTML 列表中。项目登记与会话数据库需要一起保留，重启可恢复绑定。

## 两个目录各自负责什么

| 配置 | 用途 | 更换新项目时的操作 |
|---|---|---|
| HTML 对话所选本地项目 | 该对话的源码、项目文档、Git 变更、测试文件的根目录 | 新建对话时选择，切换不重启 |
| `ENGINEERING_PROJECT_ROOT` | 启动时的默认项目，供旧 question-only API 和 Streamlit 使用 | 只在要改变启动默认值时修改并重启 |
| `ENGINEERING_KNOWLEDGE_CORPUS_ROOT` | Engineering 的 AI 技术知识库 | 同领域源码项目可继续使用当前已验证语料 |

当前默认知识库是可维护的 SQLite 库，可通过 HTML 页面上传、替换、删除，
并供 Engineering 主会话全库检索。`ENGINEERING_KNOWLEDGE_CORPUS_ROOT` 仅在
首次初始化时用于导入验证过的 `870e5864df67` 语料；它不是任意业务文件夹
导入接口。日常管理及历史只读模式见 [知识库说明](knowledge_library_runbook.md)。

`POST /index/file` 和 Streamlit Settings 的旧导入仍属于 legacy Pipeline。
HTML 页面的知识库管理使用 `/engineering/knowledge/documents`，直接更新
Engineering 使用的产品库。切换源码项目不会拆分或切换这份全库。

## 设置启动默认项目（PowerShell，可选）

先把新项目 clone 或放到本机，例如 `D:\projects\my-new-agent`。需要查看 Git 变更时，该目录应属于 Git 仓库；普通目录也能读取源码，但 Git 工具会报告无法使用。

在后端终端使用本项目已配置好依赖的 Python 环境：

```powershell
Set-Location 'D:\学习\rag实战项目\rag-knowledge-base'
$env:ENGINEERING_PROJECT_ROOT = 'D:\projects\my-new-agent'
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

只有修改启动默认项目需要先用 Ctrl+C 停止后端再执行命令。HTML 新对话的项目选择无需执行这些步骤。模型与聊天消息体不能提供或覆盖项目根目录。

本机 `.env` 已配置 DeepSeek key 和经过验证的知识库路径；上面的命令只切换项目。也可把 `ENGINEERING_PROJECT_ROOT` 写入本机 `.env` 后重启，但已设置的进程环境变量优先于 `.env`。

HTML 页面直接访问后端根地址。需要保留的 Streamlit Demo 时，在另一个终端启动：

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

预期 `/project` 的 `project_name` 是启动默认目录名、`source` 为 `configured`；知识状态 `ready` 为 true，`engineering_agent` capability 为 true。默认 managed 知识库不声明历史 `verified` 身份。`/project` 始终描述启动默认项目；HTML 顶部描述当前对话的项目。`/health` 为 200 只说明旧 Pipeline 可用，不能代替这些检查。

首次调查可以直接指定真实存在的项目相对路径，例如：“请读取当前仓库 src/my_agent/config.py，说明这个文件的配置默认值，并引用源码。”工具按需读目录，不需要预先把全部源码导入向量库。之后再调查调用关系、跨文件实现、文档一致性和变更相关测试。

## API 与兼容性

- `GET /engineering/projects` 列出已登记项目；`POST /engineering/projects` 接收 `{"path":"本机绝对目录"}`，返回公开 `id`。列表不返回绝对路径或内部根目录 key。
- `POST /engineering/conversations` 可接收 `{"project_id":"公开 id"}`；不带请求体时继续绑定启动默认项目。
- 会话列表默认仍只列默认项目。`?project_id=...` 列指定项目；`?scope=all` 列全部已登记项目的会话，HTML 使用这个入口。
- 指定项目的会话详情、删除、消息 SSE 请求附带 `?project_id=...`。消息体仍只接收 `message`，不接收路径或客户端历史。错误项目 id 与会话组合返回 404。

## 切换、恢复与限制

- 一个 API 进程支持多个已登记本地项目，按对话装配和复用原有 Runtime；Core 工具、Prompt、Planner、取证与运行预算未因本次绑定功能改变。这仍是本机产品，不提供多租户访问控制。
- 不同根目录的会话隔离，即使两个项目同名；同名项目在选择框中附加短 id。移动项目到另一个路径会被视为新的项目身份。已登记目录消失时仍可查看历史，但创建对话和发消息返回 409，不会回退到默认项目。
- 搜索只处理允许的文本文件，忽略隐藏目录、依赖目录、超大文件和受保护文件。当前是有界字面搜索，不能把“没搜到”直接当成“整个项目没有实现”。
- 长函数、跨文件、多轮追问仍可能取证不完整；`find_tests` 只发现候选测试，不执行测试，也不证明测试一定受影响。项目选择功能不等于模型答案质量提升。

切换源码项目继续共享当前整份知识库。HTML 可上传或更新领域资料，但新领域的答案质量仍须配合评估验证；仅更换源码目录不能完成知识领域迁移。已知模型质量缺口见 [系统评估](validation/2026-10-02-system-assessment.md)。
