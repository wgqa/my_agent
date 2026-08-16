# 95-Gate5 服务启动与 API-Smoke

> **任务**：G5-RUN-04-STARTUP-AND-LOCAL-API-SMOKE
> **日期**：2026-08-16
> **产物**：`scripts/smoke_local_api.py`（真实 uvicorn 子进程）+ `tests/test_release_startup.py`
> **本笔记定位**：从学习角度讲清"启动 smoke"这一层工程证据，并说明它和 unit / integration / formal benchmark 的分工。

---

## 1. 什么是 startup smoke test

Startup smoke（启动冒烟）= **最小、最快、最真实的"服务能不能立起来"验证**。

它的目标很窄：

```
Python 环境 → uvicorn 真进程启动 → FastAPI lifespan 成功 → Pipeline 基础初始化成功
→ /health 可访问 → OpenAPI 暴露预期 API → 干净退出
```

**不证明**：回答质量、检索效果、模型好坏。它只回答一个二值问题：**"把仓库拿到干净环境，服务能不能启动？"**

比喻：smoke 是"开机自检"——屏幕亮了、系统能进桌面，就算过；它不测你写文档写得对不对。

---

## 2. unit test / integration test / process-level smoke 的区别

| 层级 | 测什么 | 典型工具 | 速度 |
|---|---|---|---|
| **unit test** | 单个函数/类的行为 | pytest 直接调函数 | 毫秒级 |
| **integration test** | 多个组件协同（如 Pipeline→VectorStore） | pytest + fixture/mock | 秒级 |
| **process-level smoke** | **真进程从零启动到对外可用** | 起 uvicorn 子进程 + 真实 HTTP | 秒~分钟级 |

本项目三条都测了不同东西：

- **unit**：`test_pipeline.py` 测 `index_file` 幂等、BM25 更新、query 组装（用 fake embedding）。
- **integration**：`test_api.py` 用 `TestClient` 测路由/schema（仍 mock 掉 Pipeline）。
- **smoke**（本轮新增）：`scripts/smoke_local_api.py` 起**真 uvicorn**，真 lifespan，真 HTTP 到 `/health` 和 `/openapi.json`。

三者缺一不可：unit 抓逻辑、integration 抓接线、smoke 抓"**最外层能不能跑起来**"。

---

## 3. 为什么 TestClient 不能完全替代真实 uvicorn 进程启动

`fastapi.testclient.TestClient` 很好用，但它是**进程内**的：它在当前 Python 进程里直接调 ASGI 应用，不经过：

- **真实 socket 监听**（有没有端口冲突、绑定错误）
- **真实 lifespan 启动/关闭**（TestClient 也触发 lifespan，但异常处理路径与真进程不完全一致）
- **真实子进程环境**（cwd、PYTHONPATH、env 是否真的对）
- **uvicorn 作为进程的启动/退出**（能不能被拉起、能不能被干净终止）

TestClient 测的是"**ASGI 应用逻辑**"，smoke 测的是"**作为服务部署起来**"。两者差在"进程"和"环境"。本轮特意要求：**不能只用 TestClient 假装服务启动**。

这也是为什么 `tests/test_release_startup.py` 直接用 `subprocess` 调 `python scripts/smoke_local_api.py`——**pytest 测的和用户手工执行的，是同一条命令**。

---

## 4. 为什么 release smoke 不应该依赖真实 API key

- 真实 key 是**机密**，不该出现在 CI / smoke 里；放进仓库或 workflow 会泄露。
- smoke 只验证"启动 + /health + OpenAPI"，**不需要生成回答**，所以不需要 key。
- 更严格的是**显式覆盖**而不是"不设置"：smoke 子进程强制 `DEEPSEEK_API_KEY=dummy-placeholder`，即使开发者机器 `.env` 里有真 key，**smoke 也不能偷偷用它**。这样才能保证 smoke 结果与"有无 key"无关、可复现。

一句话：**smoke 的成功标准 = 不依赖任何外部机密就能复现**。

---

## 5. 为什么不能依赖开发机的 Hugging Face cache

开发机缓存了 BGE 模型，不代表 CI / 同学电脑有。若 smoke 悄悄用了 cache：

- 本地全绿、CI 全红（跟本项目 26 failures 同款教训）；
- smoke 结果不可复现。

所以 smoke 子进程强制：

```
HF_HOME=<新的空临时目录>
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

即使机器真的缓存了模型，也**不得使用**。Pipeline 初始化本来就是**惰性**加载 embedding/reranker（构造不加载），所以不碰缓存也能完成 lifespan。这让 smoke 在"零模型缓存"的干净 CI 上也能过。

---

## 6. 什么叫 localhost-only verification

Smoke 允许的网络访问只有 `127.0.0.1`（本机回环）。任何 `0.0.0.0` 外部地址、公网 API 调用都是禁止的：

- `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` = dummy → 任何真实 LLM 调用必然失败（这正是我们想要的：**不真调用**）；
- `HF_HUB_OFFLINE=1` → 模型不下载；
- 请求只打到 `http://127.0.0.1:<port>/...`。

意义：**验证在完全离线、无外部依赖的环境里成立**。如果哪天 smoke 偷偷联网了，它就会失败——本地回环检查就是守住这条边界的手段。

---

## 7. 为什么用临时 cwd 隔离 vector store

生产 `config.yaml` 里 `vector_store.path: ./data/vector_store` 是**相对路径**。如果 smoke 在仓库根启动 uvicorn，就会污染真实的 `data/vector_store/`。

解决：smoke 把 `config.yaml` **复制到临时工作目录**，让 uvicorn 以临时目录为 cwd 启动 → 它的 `./data/vector_store/` 落在 `<temp>/data/vector_store/`，测试完 `TemporaryDirectory` 自动删除。

好处：**验证用的是真实配置语义（相对路径相对 cwd），又不污染任何真实数据**。也不为 smoke 去改生产 `api/app.py` 或 `config.yaml`。

---

## 8. health check 与模型质量评测的边界

`/health` 返回的是**系统健康**（进程活着、Pipeline 初始化成功、Provider 配置正确），**不是**模型效果。

- `/health` 校验 `embedding_provider=bge / retriever_strategy=hybrid / generator_provider=deepseek` → 证明"**配置对上了、服务起来了**"。
- `docs_count` 0/非0 都允许 → 因为文档数是运行态数据，不是启动正确性的身份字段。
- **模型质量**（检索命中率、回答正确率、引用有效性）由正式 frozen benchmark 测（Gate 2/3/4），**跟启动是否成功是两回事**。

边界不清的常见错误：把"服务起来了"当"模型好用"，或反过来用 benchmark 去当启动检查。两者频率、成本、目的完全不同。

---

## 9. 这个项目里 CI → startup smoke → formal frozen benchmark 三层证据

| 层 | 跑什么 | 频率 | 证明什么 |
|---|---|---|---|
| **CI** | 全量 unit/integration（Fake/离线） | 每次 push | 代码逻辑没坏、无回归 |
| **startup smoke** | 真实 uvicorn 进程启动 + /health + OpenAPI | 每次 push（test_release_startup） | 服务作为部署形态能启动、可访问 |
| **formal frozen benchmark** | 真实模型 + Gold + 冻结语料（Gate 2/3/4） | 受控一次性 | 效果数字可信、证据冻结 |

三层各司其职：

- CI 抓"**代码对不对**"（本地 1724 测试）；
- smoke 抓"**服务能不能立起来**"（本轮新增，进 CI 自动跑）；
- benchmark 抓"**效果好不好**"（冻结，不重跑）。

面试官问"你怎么保证项目可信"——答案不是一句"我测过"，而是**分层的证据链**：逻辑→部署→效果，每层用对的工具、对的频率。

---

## 10. 面试怎么讲这次 Gate5 工程化

推荐一段 1 分钟讲法：

> "项目有一个真实的启动 smoke：`scripts/smoke_local_api.py` 起一个真正的 uvicorn 子进程，在临时工作目录跑，用 dummy key + 强制 Hugging Face 离线，验证 `/health` 和 `/openapi.json` 都正常、四条真实路由都在。它不依赖我电脑上的任何东西——没有真实 API key、没有模型缓存、不访问公网。pytest 里 `test_release_startup.py` 直接调这条命令，所以每次 push 到 GitHub CI 都会在干净的 Ubuntu runner 上验证服务真能启动。"

加分点（如果被追问）：

- **为什么不用 TestClient**：它测的是 ASGI 逻辑，测不到真实进程/socket/lifespan/环境。
- **为什么用临时 cwd**：`config.yaml` 的 vector store 是相对路径，临时目录让 smoke 不污染真实数据。
- **三层证据**：CI（逻辑）→ smoke（部署）→ frozen benchmark（效果），各有各的边界。
- **离线保证**：smoke 连 dummy key 都显式覆盖，保证结果与"开发者有没有 key"无关。

---

## 附：本轮零副作用声明

- 未改 `api/app.py`、`core/**`、`config.yaml`、`requirements.*`、`.github/workflows/ci.yml`、Gate2/3/4 frozen artifacts、evaluation datasets、UI。
- 未调 DeepSeek / OpenAI / HF Hub / 公网；仅 127.0.0.1。
- smoke 成功输出：`STARTUP_SMOKE_OK / health=200 / openapi=200 / required_routes=present / external_network=disabled`。
