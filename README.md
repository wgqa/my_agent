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

- Python 3.11+
- BGE-small-zh-v1.5 模型缓存 (~33MB)
- BGE-reranker-v2-m3 模型缓存 (~2.2GB，可选)
- DeepSeek API Key（生成答案需要）

## 安装

```bash
pip install -r requirements.txt
```

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

## 启动服务

**API：**
```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

**UI（新终端）：**
```bash
streamlit run ui/app.py
```

浏览器访问 `http://localhost:8501`。

## 已知限制

- BM25 索引重启后需从 ChromaDB 重建（已实现自动重建）
- 多轮对话仅 API 支持（`history` 字段 + 指代改写），UI 暂未接入
- 未实现流式输出

## Roadmap

见 `docs/status.md`（实时状态）。历史大规划见 `docs/archive/`。
