# File: core/pipeline.py

## 作用

RAG 系统的核心**"管线"（Pipeline）**，串联所有模块：索引阶段（加载→分块→向量化→存储）和查询阶段（检索→重排序→生成）。是整个 RAG 系统的大脑和控制器。

## 完整代码（逐行讲解）

```python
from typing import List, Optional
import os
import yaml

from core.loader.base import Document
from core.loader.text_loader import TextLoader
from core.loader.pdf_loader import PDFLoader
from core.loader.code_loader import CodeLoader
from core.chunker.base import BaseChunker
from core.chunker.fixed_size import FixedSizeChunker
from core.chunker.recursive import RecursiveChunker
from core.embeddings.base import BaseEmbedding
from core.embeddings.openai_emb import OpenAIEmbedding
from core.vector_store.base import BaseVectorStore
from core.vector_store.chroma_store import ChromaStore
from core.retriever.base import BaseRetriever
from core.retriever.simple import SimpleRetriever
from core.retriever.hybrid import HybridRetriever
from core.reranker.base import BaseReranker
from core.reranker.bge_reranker import BGEReranker
from core.generator.base import BaseGenerator
from core.generator.deepseek_gen import DeepSeekGenerator
```

- 导入所有模块。注意这里导入的是**具体实现**（如 ChromaStore、DeepSeekGenerator），但成员变量的类型标注用的是**抽象接口**（如 `BaseVectorStore`、`BaseGenerator`）。这就是"面向接口编程"——变量的类型是接口，但实际赋值的是具体实现。

```python
class Pipeline:
    """串联索引和查询的完整 RAG 管线"""

    def __init__(self, config_path: str = "config.yaml",
                 deepseek_api_key: str = None,
                 openai_api_key: str = None):
        self.deepseek_api_key = deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
```

- `config_path` — YAML 配置文件路径，包含所有模块的参数配置。
- API Key 优先级：显式传入 > 环境变量。`a or b` 是 Python 的常见写法：如果 a 是 None/空字符串，取 b。
- `os.getenv("DEEPSEEK_API_KEY")` — 从环境变量读取 API Key，避免硬编码在代码中。

```python
        self.config = {}
        if config_path and os.path.exists(config_path):
            with open(config_path, "r") as f:
                self.config = yaml.safe_load(f) or {}
```

- `yaml.safe_load(f)` — 读取 YAML 配置文件。为什么用 safe_load 而不是 load？—— safe_load 只解析标准 YAML 标签，不会执行任意 Python 对象（防止 YAML 反序列化攻击）。
- `or {}` — 如果 YAML 文件为空（safe_load 返回 None），用空字典兜底。

```python
        self.embedding = self._init_embedding()
        self.vector_store = self._init_vector_store()
        self.chunker = self._init_chunker()
        self.retriever = self._init_retriever()
        self.reranker = self._init_reranker()
        self.generator = self._init_generator()
```

- **构造时初始化所有组件。** 按照 RAG 管线的顺序创建：Embedding → VectorStore → Chunker → Retriever → Reranker → Generator。
- 每个 `_init_*` 方法都是**工厂方法**（Factory Method），根据配置创建对应的具体实现。

```python
        self.loader_map = {
            ".txt": TextLoader(),
            ".md": TextLoader(),
            ".pdf": PDFLoader(),
            ".py": CodeLoader(language="python"),
            ".js": CodeLoader(language="javascript"),
            ".java": CodeLoader(language="java"),
        }
```

- **Loader 映射表：** 根据文件扩展名选择对应的 Loader。`.txt` 和 `.md` 都用 TextLoader。
- 字典作为"策略查找表"——比 `if-elif` 链更清晰、更易扩展。

---

### `_init_embedding` — 初始化 Embedding 模型

```python
    def _init_embedding(self) -> BaseEmbedding:
        cfg = self.config.get("embedding", {})
        provider = cfg.get("provider", "openai")
        if provider == "openai":
            return OpenAIEmbedding(
                model=cfg.get("model", "text-embedding-3-small"),
                api_key=self.openai_api_key,
            )
        from core.embeddings.bge_emb import BGEEmbedding
        return BGEEmbedding(model_name=cfg.get("model", "BAAI/bge-small-zh-v1.5"))
```

- 注意：`from core.embeddings.bge_emb import BGEEmbedding` 写在函数内部（**延迟导入**）。如果用户用 OpenAI，BGE 相关的依赖（sentence-transformers、torch）就不需要加载。加速启动 + 避免不必要的依赖报错。
- 默认 provider 是 "openai"（需要 API Key），备选是 BGE（本地模型，免费）。

---

### `_init_vector_store`

```python
    def _init_vector_store(self) -> BaseVectorStore:
        path = self.config.get("vector_store", {}).get("path", "./data/vector_store")
        return ChromaStore(path=path)
```

- 只用 ChromaDB，没有其他实现。可以从配置文件读取持久化路径。
- `self.config.get("vector_store", {})` — 两级 get，防止 `vector_store` 键不存在时报错。

---

### `_init_chunker`

```python
    def _init_chunker(self) -> BaseChunker:
        cfg = self.config.get("chunker", {})
        strategy = cfg.get("strategy", "recursive")
        chunk_size = cfg.get("chunk_size", 512)
        chunk_overlap = cfg.get("chunk_overlap", 64)

        if strategy == "fixed":
            return FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        elif strategy == "semantic":
            from core.chunker.semantic import SemanticChunker
            return SemanticChunker(embedding_fn=self.embedding.embed)
        return RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
```

- 三种分块策略：fixed / semantic / recursive（默认）。
- SemanticChunker 需要传入 `embedding_fn`（函数作为参数传递——**函数式注入**），因为语义分块需要用 embedding 判断句子之间的相似度。
- `RecursiveChunker` 是默认值，说明递归分块是最通用的选择。

---

### `_init_retriever`

```python
    def _init_retriever(self) -> BaseRetriever:
        cfg = self.config.get("retriever", {})
        strategy = cfg.get("strategy", "hybrid")
        top_k = cfg.get("top_k", 5)

        if strategy == "simple":
            return SimpleRetriever(self.embedding, self.vector_store)
        elif strategy == "hybrid":
            return HybridRetriever(self.embedding, self.vector_store)
        from core.retriever.mmr import MMRRetriever
        return MMRRetriever(self.embedding, self.vector_store)
```

- 默认策略是 "hybrid"（向量 + BM25 混合检索）。
- 所有 Retriever 都共享同一个 `self.embedding` 和 `self.vector_store` 实例。**共享 embedding 对象**——只需要加载一次模型。

---

### `_init_reranker`

```python
    def _init_reranker(self) -> BaseReranker:
        return BGEReranker()
```

- 直接返回 BGEReranker 实例（默认配置）。没有配置化是因为 Reranker 当前只有 BGE 一种实现。

---

### `_init_generator`

```python
    def _init_generator(self) -> BaseGenerator:
        cfg = self.config.get("generator", {})
        provider = cfg.get("provider", "deepseek")
        model = cfg.get("model", "deepseek-v4-flash")
        temperature = cfg.get("temperature", 0.3)

        if provider == "deepseek":
            return DeepSeekGenerator(
                api_key=self.deepseek_api_key or "",
                model=model,
                temperature=temperature,
            )
        from core.generator.openai_gen import OpenAIGenerator
        return OpenAIGenerator(
            api_key=self.openai_api_key or "",
            model=model,
            temperature=temperature,
        )
```

- 默认使用 DeepSeek（便宜、中文好）。
- `api_key=self.deepseek_api_key or ""` — 当 API Key 为 None 时传空字符串，DeepSeekGenerator 创建 `OpenAI(api_key="", ...)` 不会立即报错，只在调用 API 时才失败。这样的"延迟报错"在开发调试时更友好。

---

### `_get_loader`

```python
    def _get_loader(self, file_path: str):
        ext = os.path.splitext(file_path)[1].lower()
        loader = self.loader_map.get(ext)
        if loader is None:
            loader = TextLoader()
        return loader
```

- `os.path.splitext(file_path)` — 返回 `(filename, extension)` 元组。如 `("example", ".pdf")`。`[1]` 取扩展名部分。
- `loader_map.get(ext)` — 在映射表中查找对应的 Loader。找不到返回 None。
- **兜底策略：** 找不到对应扩展名时用 TextLoader 处理（最通用的 Loader）。

---

### `index_file` — 索引文件

```python
    def index_file(self, file_path: str) -> int:
        """索引文件：加载 → 分块 → embedding → 存储，返回 chunk 数量"""
        loader = self._get_loader(file_path)
        docs = loader.load(file_path)
        chunks = self.chunker.chunk(docs)
        texts = [d.content for d in chunks]
        embeddings = self.embedding.embed(texts)
        self.vector_store.add(chunks, embeddings)
        return len(chunks)
```

**这是索引阶段的完整流程：**
1. `loader.load(file_path)` — 加载文件，返回 Document 列表（每个文件可能有多页/多段）
2. `chunker.chunk(docs)` — 把 Document 切分成更小的块，返回更多但更小的 Document 列表
3. `texts = [d.content for d in chunks]` — 提取每个 chunk 的文本内容，准备向量化
4. `embedding.embed(texts)` — 批量生成向量
5. `vector_store.add(chunks, embeddings)` — 把文档和向量存入向量库
6. `return len(chunks)` — 返回切分后的块数量（方便调用方了解索引情况）

---

### `query` — 查询

```python
    def query(self, question: str, top_k: int = None) -> dict:
        """查询：检索 → 重排序 → 生成，返回答案和来源"""
        k = top_k or self.config.get("retriever", {}).get("top_k", 5)
        retrieved = self.retriever.retrieve(question, top_k=k)
```

1. 确定 top_k 值：如果调用方没传（None），从配置中读取，默认 5。
2. `retriever.retrieve(question, top_k=k)` — 从向量库检索 top_k 个相关文档。

```python
        try:
            retrieved = self.reranker.rerank(question, retrieved, top_k=k)
        except Exception:
            pass
```

**容错设计：** Reranker 可能因为模型加载失败、内存不足等原因报错。用 `try/except` 包裹，如果出错就**静默降级**——直接使用 Retriever 的原始结果，不中断整个查询流程。

```python
        answer = self.generator.generate(question, retrieved)
```

3. 调用 LLM 生成回答。传入原始 query 和检索到的文档。

```python
        sources = [
            {
                "content": d.content[:200],
                "source": d.metadata.get("source", "unknown"),
                "score": d.metadata.get("distance", 0.0),
            }
            for d in retrieved
        ]

        return {"answer": answer, "sources": sources}
```

4. **组装返回结果：**
   - `content[:200]` — 只返回前 200 个字符，避免前端展示时太长。
   - `d.metadata.get("distance", 0.0)` — ChromaDB 返回的距离值（越小越相关）。注意这里是 distance 而不是 score，所以"越小越好"。
   - 返回格式：`{"answer": "...", "sources": [...]}` — 标准化的查询结果，可以序列化为 JSON 供 API 返回。

## 重点总结

1. **工厂方法模式：** 每个 `_init_*` 方法根据配置文件动态创建对应的具体实现。用 if/else 做策略选择，而不是让调用方自己决定。
2. **依赖倒置：** Pipeline 所有成员变量的类型标注都是抽象接口（BaseEmbedding, BaseRetriever 等），不依赖具体实现。可以轻易替换组件而不影响 Pipeline 本身的代码。
3. **容错降级：** Reranker 失败时静默通过（退化到单纯靠 Retriever 排序），保证系统在部分组件不可用时仍能工作。
4. **默认配置：** 每个组件都有合理的默认值（如 hybrid 检索、recursive 分块、deepseek 生成），开箱即用。
5. **延迟导入：** 部分组件（BGEEmbedding、SemanticChunker、MMRRetriever、OpenAIGenerator）在工厂方法内部导入，避免在 Pipeline 构造函数中加载不必要的依赖。

## 大厂面试可能问

- **Q: Pipeline 的构造和调用流程？** — 构造：加载 YAML → 初始化 Embedding / VectorStore / Chunker / Retriever / Reranker / Generator。索引调用 `index_file`：Loader → Chunker → Embedding → VectorStore。查询调用 `query`：Retriever → Reranker → Generator → 返回 {answer, sources}。

- **Q: Factory Method 在这里解决了什么问题？** — 把"对象创建"的逻辑从调用方剥离。如果不使用工厂方法，调用方（比如 main.py）需要自己判断配置、导入模块、创建对象。工厂方法把这些集中到 Pipeline 内部，调用方只需要"创建一个 Pipeline"和"调用 query"。

- **Q: 为什么 `query` 方法返回 dict 而不是字符串？** — 前端/API 需要展示引用来源（"这个回答参考了哪些文档"）。只返回字符串会让前端无法展示来源。返回 dict 提供了结构化的信息，前端可以直接渲染。

- **Q: 为什么 `index_file` 返回 chunk 数量（int）？** — 调用方需要知道索引是否成功以及索引了多少内容。返回 int 比 void 更有信息量，但比返回完整列表更轻量。如果需要调试，调用方可以单独加日志。

- **Q: Reranker 的 `try/except: pass` 是不是太粗暴了？什么场景下会掩盖错误？** — 确实粗暴，应该至少加个 `logging.warning`。但这里的设计思路是：Reranker 是"锦上添花"的组件，不是核心路径。如果 Reranker 出错了（比如模型文件损坏、OOM），系统不应该因此中断。生产环境建议至少打印错误日志。

- **Q: config.yaml 可以用什么格式？** — 当前只支持 YAML（通过 PyYAML 解析）。也可以扩展支持 JSON / TOML，但 YAML 最常用，支持注释，可读性好。

- **Q: Pipeline 如何支持多文件批量索引？** — 当前 `index_file` 一次处理一个文件。可以写一个 `index_folder(folder_path)` 方法遍历目录下所有文件并逐个调用 `index_file`。也可以用多线程/异步加速批量索引。

- **Q: Pipeline 中的 `self.config.get("retriever", {}).get("top_k", 5)` 这种两级 get 是常见写法吗？** — 非常常见。当嵌套字典的中间键可能缺失时，用 `dict.get(key, {})` 提供空字典兜底，避免 `KeyError` 或 `AttributeError: 'NoneType' object has no attribute 'get'`。



隐患 1：BM25 是内存索引
程序重启后 BM25 清空，Chroma 磁盘持久化还在，两边不一致！
解决方案：服务启动时，从 Chroma 全量读取文档重建稀疏索引。
隐患 2：没有文档删除接口
Pipeline 只实现了新增索引，缺少删除文件、清空知识库方法。
一旦文件更新，旧 chunk 残留在向量库 + BM25 中。
隐患 3：没有并发保护
如果多线程同时调用index_file，你手写的简易 BM25 内部没有锁，会出现 DF/IDF 计算错乱。
隐患 4：缺少异常捕获
文件损坏、网络 embedding 超时、LLM 接口报错会直接抛出，建议增加 try-except。
隐患 5：重排器强制固定为 BGEReranker
代码 _init_reranker 写死，无法通过 yaml 开关关闭重排。
可以改成配置驱动：支持开启 / 关闭 rerank。
隐患 6：一次性加载整个文件
超大文件一次性载入内存，建议 loader 支持流式读取。