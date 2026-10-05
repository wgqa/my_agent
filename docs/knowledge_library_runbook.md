# HTML 知识库管理

Engineering 默认使用单个可维护知识库。HTML 页面的“知识库”入口、文档管理
接口、主会话的 planned retrieval 和工具检索共用这一份数据。问答默认检索
全部文档；管理页的文件名筛选只影响列表。内部仍按 512/64 token 分块，以
复用现有 BM25 和证据引用链，不把不同文档拆成独立知识库。

## 启动与页面

在项目目录启动后端：

```powershell
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/`，点击左侧“知识库”，或直接打开
`http://127.0.0.1:8000/#knowledge`。HTML、CSS、JS 由同一后端提供。
独立静态服务器展示 HTML 时，需在页面 URL 加上
`?api=http://127.0.0.1:8000`，并使用后端允许的跨域来源；默认推荐同源部署。

页面提供文档列表、文件名筛选、数量及分块统计、分页、正文预览、上传、
替换和删除确认。较长正文可以继续加载，不会将截断预览当作完整文档。
预览作为文本显示；PDF 显示提取出的文字，不提供扫描件 OCR。

## 上传、更新、删除

- 支持 `.txt`、`.md`、`.pdf`、`.py`、`.js`、`.java`，单文件最多 20 MiB。
  文本文件需为 UTF-8；PDF 需有可读取文字。空文件、无正文或超限文件会拒绝。
- 可一次选择多篇文档。每篇独立提交，失败的文件会明确显示，不影响已经
  成功的文件。文本正文最多 2,000,000 字符。
- 同名文档重新上传会更新；名称和正文都不变时返回 `no_change`。也可以在
  预览中点击“替换文件”更新指定文档，包括首次导入的初始文档。
- 删除前展示文件名。删除文档与全部分块一起提交；随后新的检索不再召回
  该文档。历史聊天中的回答和引用不会被改写。
- 文档、分块和索引更新成功后才返回成功；索引构建或数据库提交失败时
  保留原版本。重启后恢复数据库中的现状，不重新添加已经删除的初始文档。

## 数据与冻结语料

`ENGINEERING_KNOWLEDGE_MODE=managed` 是默认模式。
`ENGINEERING_KNOWLEDGE_DB` 可指定 SQLite 路径，默认
`data/runtime/engineering_knowledge.sqlite3`。这是运行时数据，不提交 Git。

第一次创建库时，如果配置了 `ENGINEERING_KNOWLEDGE_CORPUS_ROOT`，会先按
原有规则验证 37 篇冻结语料，再将它们导入产品库。未配置则从空库开始。
已初始化的库不再依赖这份源目录，之后通过页面管理文档。
旧版 `/index/file` 的 Chroma 数据不自动迁入新库；新的 HTML 上传入口使用
`/engineering/knowledge/documents`，会直接影响 Engineering 主会话。

管理接口不需要模型调用、embedding 下载或旧 Pipeline 就绪。主会话的生成
仍需要配置有效模型凭据。产品库的 `verified=false` 表示它不再声明与历史
冻结 corpus 相同；`ready`、`mutable` 和 `mode` 分别报告当前状态及管理能力。

历史 benchmark 和原冻结语料 smoke 应显式配置：

```powershell
$env:ENGINEERING_KNOWLEDGE_MODE = "verified"
```

此模式保持原始 verified backend，文档管理接口返回 409，拒绝改变冻结语料。
切换模式需要重启后端。两种模式是产品与历史验证的启动方式，日常页面不
提供多个知识库或按库选择检索范围。

## API

| 接口 | 用途 |
|---|---|
| `GET /engineering/knowledge` | 当前模式、可管理性、文档和分块数量 |
| `GET /engineering/knowledge/documents?q=&limit=50&offset=0` | 文件名筛选和分页列表 |
| `GET /engineering/knowledge/documents/{id}?offset=0&limit=20000` | 分段正文预览 |
| `POST /engineering/knowledge/documents` | multipart `file` 上传或同名更新 |
| `PUT /engineering/knowledge/documents/{id}` | multipart `file` 替换指定文档 |
| `DELETE /engineering/knowledge/documents/{id}` | 删除文档及分块 |

本地单机部署，无新多租户权限模型或向量数据库。保留原有七工具、Agent
预算、Planner 和 finalization 逻辑；可编辑文档作为不可信检索内容处理。

离线验证：

```powershell
python -m pytest -q tests/test_knowledge_library.py
```
