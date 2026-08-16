# RAG 知识库问答系统

从零实现的 RAG 管线，用于技术文档的智能检索与问答。

## 架构

```
文件上传 → Loader → Chunker → Embedding → VectorStore (ChromaDB)
用户问题 → Retriever (Dense + BM25 RRF) → Reranker → Generator (DeepSeek) → 答案 + 引用
```

### 核心组件

| 组件 | 支持 |
|------|------|
| Loader | TXT / Markdown / PDF / Python / JS / Java |
| Chunker | FixedSize / Recursive / Semantic |
| Embedding | BGE (本地) / OpenAI (云端) |
| VectorStore | ChromaDB (持久化 + 内存模式) |
| Retriever | Simple (Dense) / Hybrid (Dense+BM25 RRF) / MMR |
| Reranker | BGE Cross-Encoder |
| Generator | DeepSeek / OpenAI 兼容 |

## 环境要求

- **正式验证环境：Python 3.14**（复现入口见 `requirements.lock`；不声称"所有 Python 3.11+ 均已验证"）
- BGE-small-zh-v1.5 模型缓存 (~33MB，仅 Embedding 时使用)
- BGE-reranker-v2-m3 模型缓存 (~2.2GB，可选，Rerank 时使用)
- DeepSeek API Key（生成答案 / Agent 真调用需要；**仅启动 /health smoke 不需要**）

## 安装（复现入口）

```bash
python -m pip install -r requirements.lock
```

> `requirements.lock` 是 Release 1.0 的精确版本快照（Python 3.14 已验证）。
> `requirements.txt` 保留为宽松的开发依赖描述（范围下限），不作为复现入口。

## 配置

创建 `.env` 文件：
```
DEEPSEEK_API_KEY=sk-your-key
```

`config.yaml` 中可调整 chunker 策略、检索策略等参数。非法配置会启动即报错。

## 运行测试

```bash
python -m pytest --basetemp=.tmp_pytest
```

`--basetemp=.tmp_pytest` 是 Windows 中文用户名环境的临时目录权限规避。

## 启动自检（startup smoke）

```bash
python scripts/smoke_local_api.py
```

启动一个**真实** uvicorn 进程并验证 `/health` 与 `/openapi.json` 是否暴露预期路由；
不依赖真实 API Key、不下载模型、不访问公网（仅 `127.0.0.1`）。成功输出 `STARTUP_SMOKE_OK`。
启动 /health smoke **不需要**真实 API Key；生成回答与 Agent 真调用才需要相应 Key。

## 启动服务

**API：**
```bash
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

**UI（新终端）：**
```bash
streamlit run ui/app.py
```

浏览器访问 `http://localhost:8501`。

> **监听地址说明**：当前项目默认是本地 Demo，API 只监听 `127.0.0.1`，仅允许本机访问。`0.0.0.0` 会把服务暴露到所有网卡接口，同网段设备均可访问。如未来公开部署，必须另行增加认证、反向代理、TLS、限流和部署安全配置。

## 已知限制

- BM25 索引重启后需从 ChromaDB 重建（已实现自动重建）
- 多轮对话仅 API 支持（`history` 字段 + 指代改写），UI 暂未接入
- 未实现流式输出

## Roadmap

见 `docs/status.md`（实时状态）。历史大规划见 `docs/archive/`。
