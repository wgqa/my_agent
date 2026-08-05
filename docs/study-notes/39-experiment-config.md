# ExperimentRunner 第一步：ExperimentConfig 强类型实验配置

> 2026-08-05 — 180 → 199 passed
> 评测阻塞项修复全部结束，进入新功能开发。第一步不重建 Pipeline、
> 不创建向量库，只做一件事：把"实验配置"从无约束的 dict 变成
> 构造即校验、ID 稳定可复现的强类型模型。

## 为什么需要它

现有 `Evaluator.run(config_grid)` 接受 `Dict[str, List]`：字段名拼错静默
通过、非法值（`top_k=0`、`chunk_size=-1`）运行时才炸、两个"看起来相同"
的配置无法判断是否同一实验。ExperimentRunner 要在实验目录里留下可复现
的记录——第一步就是让配置本身可校验、可寻址（ID）。

## 设计

### 1. frozen dataclass：字段即契约

```python
@dataclass(frozen=True)
class ExperimentConfig:
    chunk_strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    retriever_strategy: str = "hybrid"
    top_k: int = 5
    dense_candidate_k: int = 30
    sparse_candidate_k: int = 30
    rrf_k: float = 60.0
```

`frozen=True` 的第二个作用常被忽略：**ID 稳定性**。如果配置可变，
同一个 ID 可能指向两种不同配置；frozen 保证"ID 确定后配置不会变"。

### 2. __post_init__ 构造即校验（fail-fast 前移）

```python
def __post_init__(self):
    if self.chunk_strategy not in VALID_CHUNK_STRATEGIES:
        raise ValueError(...)
    ...
```

- 策略枚举与 `core/config.py` 的 `_VALID_STRATEGIES` 保持一致
  （chunker: fixed/recursive/semantic；retriever: simple/hybrid/mmr）；
- 正数约束用**字段名循环**而不是 4 段重复代码——
  新增正数字段时校验自动覆盖，不会漏；
- `chunk_overlap ∈ [0, chunk_size)`：`< 0` 与 `>= chunk_size` 合并为
  一个条件，边界语义（0 允许、等于 size 拒绝）一目了然。

### 3. experiment_id：确定性哈希，三个设计原则

```python
@property
def experiment_id(self) -> str:
    payload = "|".join(
        f"{name}={getattr(self, name)}" for name in self.__dataclass_fields__
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
```

| 原则 | 实现方式 | 违背它会怎样 |
|------|---------|-------------|
| 确定性 | 按 dataclass 字段**名序**序列化 + SHA-256 | 相同配置产生不同 ID |
| 敏感性 | 全部字段进 payload | 改任一字段 ID 不变 → 实验互相覆盖 |
| 顺序无关 | 字段序固定，不用 dict/repr | ID 依赖插入顺序 → 同一配置两 ID |

不用 `id()`（对象地址）、不用 `repr(dict)`（插入顺序敏感）、不用
`str(config)`（repr 顺序不保证）。12 位 hex = 48 bit 碰撞概率，
对实验寻址足够。

## 测试要点

- **非法边界参数化**：`pytest.mark.parametrize` 对 4 个正数字段 ×
  {0, -1} 展开——校验逻辑是"循环"，测试也要是"矩阵"；
- **逐字段 ID 敏感性**：遍历全部 8 个字段，每个取一个不同的合法值，
  断言 ID 变化——覆盖"新增字段忘进 ID"的回归；
- **顺序无关**：`ExperimentConfig(top_k=9, chunk_size=200)` 与
  `ExperimentConfig(chunk_size=200, top_k=9)`（关键字顺序不同）ID 相同。

## 教训

1. **配置类把校验前移到构造时**：dict 的非法值延迟到运行时才暴露，
   强类型 + `__post_init__` 让"写错配置"在第一步就炸，而不是跑完
   整个实验才发现。
2. **frozen 不只是不可变，还是 ID 的前提**：可变配置的 ID 没有意义。
3. **ID 设计三原则（确定性/敏感性/顺序无关）要写进测试**：
   三个测试各自锁一条，防止"ID 算法重构后悄悄破坏某个原则"。
