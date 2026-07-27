# File: evaluation/report.py

## 作用

将 Evaluator 返回的实验结果列表渲染为 Markdown 格式的对比报告，包含表格和最佳配置分析。

## 完整代码（逐行讲解）

```python
from typing import List, Dict


def generate_report(results: List[Dict]) -> str:
    """生成 Markdown 格式的对比报告"""
    if not results:
        return "No results."
```

- 输入是 `evaluator.run()` 返回的实验结果列表，输出是 Markdown 字符串。
- 空结果直接返回 `"No results."`。

---

```python
    report = ["# 评估对比报告\n"]
    report.append(f"共 {len(results)} 组实验\n")
```

- 用列表收集 Markdown 行，最后 `"\n".join(report)` 一次性拼接。比字符串拼接更高效（Python 字符串不可变，`+=` 会产生大量临时对象）。

---

```python
    headers = list(results[0].keys())
    report.append("| " + " | ".join(headers) + " |")
    report.append("| " + " | ".join(["---"] * len(headers)) + " |")
```

**Markdown 表格头：**
- 第一行是列名。
- 第二行是 `|---|...|` 分隔线。
- `["---"] * len(headers)` 生成 `["---", "---", "---"]`，然后用 `" | ".join(...)` 拼成 `--- | --- | ---`。

> **Python 语法提示：** `" | ".join(list)` 用 `" | "` 作为分隔符连接列表。`[x] * n` 复制列表 n 次。

---

```python
    sorted_results = sorted(results, key=lambda r: r.get("hit_rate", 0), reverse=True)
```

- 按 hit_rate 降序排列，最好的配置在前面。
- `key=lambda r: r.get("hit_rate", 0)` — 匿名函数，取每个结果的 hit_rate 作为排序键。
- `reverse=True` — 降序。

---

```python
    for r in sorted_results:
        row = []
        for h in headers:
            val = r.get(h, "")
            if isinstance(val, float):
                row.append(f"{val:.3f}")
            else:
                row.append(str(val))
        report.append("| " + " | ".join(row) + " |")
```

- 遍历每行数据，格式化每个单元格。
- `isinstance(val, float)` — 检查值是否是浮点数，如果是则格式化为 3 位小数。

---

```python
    report.append(f"\n## 最佳配置\n")
    best = sorted_results[0]
    report.append(f"- Hit Rate: {best.get('hit_rate', 0):.3f}")
    report.append(f"- MRR: {best.get('mrr', 0):.3f}")
    report.append(f"- NDCG@5: {best.get('ndcg', 0):.3f}")

    return "\n".join(report)
```

- 最后用 `"\n".join(report)` 把列表拼成字符串返回。
- 最佳配置就是排序后的第一个。

## 重点总结

1. **Markdown 表格生成：** 通过列表拼接，手动构造 `| col1 | col2 |` 格式。
2. **排序展示：** 按 hit_rate 降序排列，让面试官/读者一眼看到最佳配置。
3. **格式控制：** 浮点数保留 3 位小数，保证表格整齐。

## 大厂面试可能问

- **Q: 为什么用 `isinstance` 而不是 `type(val) == float`？** — `isinstance` 支持继承关系检查。如果 val 是 `np.float64`，`isinstance(val, float)` 返回 True（numpy 的浮点类型继承自 Python float），但 `type(val) == float` 返回 False。所以我们用 `isinstance` 保证兼容性。

- **Q: 这个报告的局限性？** — 只有数据表格，没有可视化图表。生产环境通常会用 matplotlib/seaborn 生成柱状图。

- **Q: Python 中字符串拼接的几种方式？** — ① `+` 号（不推荐循环内用）；② `" ".join(list)`（推荐，高效）；③ f-string（最可读）；④ `format()` 方法。
