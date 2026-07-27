# 学习流程

> 每个核心文件的通关三部曲

## Step 1：写注释

目标文件（按顺序，由简到难）：

| 顺序 | 文件 | 难度 | 理由 |
|------|------|------|------|
| 1 | `core/loader/base.py` | ⭐ | 最简单的数据类，热身 |
| 2 | `core/chunker/fixed_size.py` | ⭐ | 最简单的 chunker，看懂切分原理 |
| 3 | `core/chunker/recursive.py` | ⭐⭐ | 递归分割 + overlap 真实生效 |
| 4 | `core/chunker/token_counter.py` | ⭐ | 统一计量工具，先看这个再看 chunker |
| 5 | `core/embeddings/base.py` | ⭐ | 接口定义，没几行 |
| 6 | `core/vector_store/chroma_store.py` | ⭐⭐ | ChromaDB 怎么增删查 |
| 7 | `core/retriever/simple.py` | ⭐ | 最简单的检索 |
| 8 | `core/retriever/hybrid.py` | ⭐⭐⭐ | RRF 融合，面试高频 |
| 9 | `core/retriever/base.py` | ⭐ | 接口定义 |
| 10 | `core/reranker/bge_reranker.py` | ⭐ | reranker 封装 |
| 11 | `core/generator/base.py` | ⭐ | 接口定义 |
| 12 | `core/generator/deepseek_gen.py` | ⭐ | LLM 调用封装 |
| 13 | `core/pipeline.py` | ⭐⭐⭐ | 骨架文件，串联所有组件 |
| 14 | `api/app.py` | ⭐⭐ | FastAPI 端点 |
| 15 | `api/schemas.py` | ⭐ | 请求响应模型 |

做法：
- 在每段逻辑上面写注释，用你自己的话解释这段在干什么
- 写不出来或不确定的地方，标记 `# ?? 这里不太确定` 然后问我
- 重点写：输入是什么、输出是什么、中间做了什么判断

## Step 2：动手验证

每个文件看完后，选做一项：

- **改参数**：修改一个关键参数，预测输出变化，然后跑代码验证
- **搞炸它**：故意传错误参数，看报错信息，找到根因
- **手算**：拿笔算一个例子，对比代码输出

推荐做的动手项目：

| 文件 | 动手项目 |
|------|---------|
| `fixed_size.py` | 把 chunk_size 从 100 改成 200，预测块数变化 |
| `hybrid.py` | 手算 k=60 时 RRF 融合结果 |
| `chroma_store.py` | 增→查→删→再增，看 ID 是否冲突 |
| `metrics.py` | 手算 recall_at_k 的结果 |

## Step 3：闭卷复述

合上代码，拿白纸画出模块的输入、输出、内部流程。

画不出来或画错了的地方就是你还没真懂的地方。

## 常用命令

```bash
python -c "from core.retriever.hybrid import BM25Index; b=BM25Index(); b.add_document('d1','你好世界'); print(b.search('世界',5))"
python -m pytest tests/test_metrics.py -v --tb=short
```

## 每次 session 的节奏

```
30min：给一个文件写注释
30min：动手验证（改参数/搞炸/手算）
30min：闭卷复述
30min：问我卡住的问题
```
