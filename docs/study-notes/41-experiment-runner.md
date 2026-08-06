# ExperimentRunner 第三步：最小版 Runner——接通工作区与独立 Pipeline

> 2026-08-05 — 228 → 242 passed
> 把 `ExperimentConfig → ExperimentWorkspace → 独立 Pipeline` 三段接通，
> 并验证 Pipeline 真的跑在派生配置上。仍然不索引、不评测。

## prepare() 的顺序

```python
def prepare(self, config, run_id) -> PreparedExperiment:
    workspace = ExperimentWorkspace(base_config, workspace_root, config, run_id)
    paths = workspace.prepare()            # 1. 创建工作区 + 派生配置
    pipeline = self._pipeline_factory(paths.config_path)  # 2. 用派生配置建 Pipeline
    self._validate_pipeline(pipeline, config, paths)      # 3. 一致性校验
    return PreparedExperiment(config, paths, pipeline)
```

顺序本身就是防御：非法 run_id 在第一步（Workspace 构造）就抛，
pipeline_factory 根本不会被调用（测试用 recorder 验证了这个副作用）。

## 为什么需要一致性校验

工作区写了派生 `config.yaml`，但如果 Pipeline 没读到它（路径错、
字段键写错、Config 解析 bug），实验会**静默跑在默认配置上**——
又是"虚假实验"。校验是最后一道闸：

- 8 个实验字段逐一比对（`cfg.chunker_strategy == config.chunk_strategy` 等）；
- `vector_store.path` 解析后与 `paths.vector_store_path` 比对
  （必须 resolve：派生配置里是绝对路径，但保险起见双方都归一化）；
- 任一不一致 → `RuntimeError`（含字段名 + actual/expected），
  不产生半成品结果。

## 依赖注入测试：不加载真实模型

测试绝不加载 BGE、ChromaDB、Reranker。Fake pipeline_factory：

```python
def _make_factory(recorder, mutate=None):
    def factory(config_path):
        recorder.append(str(config_path))   # 验证收到的是派生 config.yaml
        cfg = FakeConfig(config_path)       # 从 yaml 读字段（属性名与 Config 一致）
        if mutate:
            mutate(cfg)                     # 注入字段不一致
        return FakePipeline(cfg)
    return factory
```

- `FakeConfig` 从派生 yaml 读取字段——既验证了"factory 收到的路径正确"，
  又模拟了真实 Config 的属性契约，还不用碰外部依赖；
- **8 字段逐一注入不一致**（参数化）：字符串字段换合法策略、
  数值 +1，断言每个都触发 `RuntimeError`——校验循环是统一的，
  测试必须是矩阵；
- factory 抛异常 → 测试断言向上传播（不吞、不返回半成品）。

## 与 E-02 的关系

E-02 在 Evaluator 里**拒绝**跨 chunk_strategy 实验（因为没有实验隔离）；
ER-01/02/03 提供真正的隔离（独立索引 + 独立 Pipeline）。等 ExperimentRunner
完整后，E-02 的保护可以从"拒绝"升级为"支持"——这就是 staged 演进：
先诚实拒绝，再补能力，最后放开。

## 教训

1. **注入点就是测试点**：`pipeline_factory` 参数化让"真实 Pipeline
   构建"与"配置流验证"解耦，单测跑在毫秒级且无外部依赖。
2. **一致性校验是配置流的真相之源**：字段名拼写错误、解析 bug、
   路径漂移——一律在跑实验前暴露，而不是跑完 100 条 QA 后才发现
   指标不可信。
3. **顺序即契约**：prepare() 的每一步都有可测的副作用（recorder、
   FileExistsError、factory 不被调用），测试把顺序锁死。
