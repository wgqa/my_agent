# File: evaluation/evaluator.py

## 作用

定义评估框架：接收一个 Pipeline 实例和测试集，自动遍历配置网格，对每种组合运行检索并计算指标，返回可对比的实验结果。

## 完整代码（逐行讲解）

```python
from typing import List, Dict
import itertools
from tqdm import tqdm

from core.pipeline import Pipeline
from evaluation.metrics import hit_rate, mrr, ndcg
```

- `itertools` — Python 标准库的迭代工具模块。`product` 函数计算笛卡尔积。
- `tqdm` — 第三方进度条库，在终端显示进度。

---

```python
class QAPair:
    def __init__(self, question: str, relevant_ids: List[str]):
        self.question = question
        self.relevant_ids = relevant_ids
```

**测试数据单元：** 一条 QA 对 = 问题 + 该问题相关的文档 ID 列表。`relevant_ids` 是人工标注的 ground truth。

> **为什么不用 dataclass？** 这里简单用了自定义类。也可以用 `@dataclass`，但手动写 `__init__` 更显式，方便扩展。

---

```python
class Evaluator:
    """跨配置运行评估实验"""

    def __init__(self, pipeline: Pipeline, test_set: List[QAPair]):
        self.pipeline = pipeline
        self.test_set = test_set
```

**Evaluator 构造：** 接收一个已配置好的 Pipeline 和测试集。注意 Pipeline 是**同一个实例**，后续通过 `_apply_config` 修改其配置。

---

```python
    def run(self, config_grid: Dict[str, List]) -> List[Dict]:
        results = []
        keys = list(config_grid.keys())
        values = list(config_grid.values())
```

- `config_grid` 是一个字典，key=参数名，value=可选值列表。
- 例如 `{"chunk_strategy": ["fixed", "recursive"], "top_k": [3, 5]}` 会生成 2×2=4 种组合。
- `keys` 和 `values` 分别提取出来，保持顺序对应。

```python
        for combo in tqdm(list(itertools.product(*values)), desc="Running experiments"):
            config = dict(zip(keys, combo))
            self._apply_config(config)
```

- `itertools.product(*values)` — **笛卡尔积**。`*values` 是**解包操作符**，把 `[[a,b], [c,d]]` 展开成 `product([a,b], [c,d])`，生成 `[(a,c), (a,d), (b,c), (b,d)]`。
- `zip(keys, combo)` — 把参数名和值配对。`zip(["strategy", "top_k"], ("recursive", 5))` → `[("strategy", "recursive"), ("top_k", 5)]`。
- `dict(zip(...))` — 转成字典。这是 Python 中把两个列表合并成字典的经典写法。

```python
            all_hits, all_mrrs, all_ndcgs = [], [], []

            for qa in self.test_set:
                retrieved = self.pipeline.retriever.retrieve(qa.question, top_k=5)
                retrieved_ids = [
                    d.metadata.get("id", str(i))
                    for i, d in enumerate(retrieved)
                ]

                all_hits.append(hit_rate(retrieved_ids, qa.relevant_ids))
                all_mrrs.append(mrr(retrieved_ids, qa.relevant_ids))
                all_ndcgs.append(ndcg(retrieved_ids, qa.relevant_ids, k=5))
```

- 对测试集中每条 QA，用当前配置的检索器查，提取文档 ID，计算三个指标，累加。
- `d.metadata.get("id", str(i))` — 优先取 metadata 中的 id，没有则用 `str(i)` 作为 fallback。

```python
            results.append({
                **config,
                "hit_rate": sum(all_hits) / len(all_hits),
                "mrr": sum(all_mrrs) / len(all_mrrs),
                "ndcg": sum(all_ndcgs) / len(all_ndcgs),
            })
```

- `**config` — **字典解包**。把 config dict 的键值对展开到结果 dict 中。
- 三个指标取平均值（在测试集上平均）。

---

```python
    def _apply_config(self, config: Dict):
        if "chunk_strategy" in config:
            self.pipeline.config.setdefault("chunker", {})["strategy"] = config["chunk_strategy"]
        if "retriever_strategy" in config:
            self.pipeline.config.setdefault("retriever", {})["strategy"] = config["retriever_strategy"]
        if "top_k" in config:
            self.pipeline.config.setdefault("retriever", {})["top_k"] = config["top_k"]
        self.pipeline.retriever = self.pipeline._init_retriever()
```

- 根据配置参数修改 Pipeline 的 config，然后重建检索器。
- `setdefault("chunker", {})` — 如果 `"chunker"` 不存在，先创建空字典。
- **局限性：** 这个方法只更新了检索器，如果 chunk 策略变了，需要重新索引文档。这个版本的 Evaluator 没有自动重索引功能。

## 重点总结

1. **笛卡尔积遍历：** `itertools.product(*values)` 生成所有配置组合，是消融实验的核心。
2. **字典解包 `**config`：** 把配置参数和实验结果合并到同一个字典中，方便后续生成表格。
3. **局限性：** 当前 Evaluator 只在检索层评估，不涉及生成质量。且没有自动重索引能力。

## 大厂面试可能问

- **Q: 为什么用笛卡尔积而不是手动写循环？** — 可扩展性。如果后续要加新的参数（比如 reranker 开关），只需要往 config_grid 里加一行，不需要改循环逻辑。

- **Q: 这个 Evaluator 有什么缺陷？** — ①不能自动重索引（chunk 策略变了需要重建向量库）；②只测检索不测生成；③没有缓存机制，相同配置会重复跑。

- **Q: Python 的 `**dict` 是什么语法？** — 字典解包（dictionary unpacking）。`{**{"a": 1}, "b": 2}` 等价于 `{"a": 1, "b": 2}`。常用于合并多个字典。
