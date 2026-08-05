# REWORK-P0-03-R2：审计返工——假阳性测试、死代码 overlap 与二次复杂度

> 2026-08-05 — 163 → 169 passed
> 审计（外部）验证 R1 的"死循环修复"后给出返工单：overlap 从未生效（测试假阳性）、
> 指数探测绝对下标翻倍、ContextAssembler 放不下直接 break。静态编译过、缺 pytest 未跑全量。

## 三个问题与根因

### 1. RecursiveChunker 的 overlap 是死代码

```python
s = max(s, prev_end - self.chunk_overlap)   # 修复前
```

merged 块原本就连续（下一块起点 == 上一块终点），`s == prev_end` 恒成立，
`max(s, ...)` 永远取 `s`，重叠恒为 0。而旧测试只断言 `ov_tokens <= overlap`：
零重叠也通过 → 假阳性测试。

**根因是切块时机**：overlap 不能在"块都切完了"再回退（回退会让块突破
chunk_size），必须在**切下一片的瞬间**回退起点，且新内容预算相应减量
（max_substring 从回退后的起点重新装 chunk_size，重叠区自然占用预算）。

### 2. max_substring 指数探测用绝对下标

```python
probe = min(hi, probe * 2)   # 修复前：start=5000 时第一次加倍就跳 5000 字符
```

`start=5000`、预算 1 时实测调用长度 `1, 5000, 2500, 1250, 625...`——极小
chunk_size 的长文本接近二次复杂度（也解释了测试慢）。指数试探的意图是
"窗口相对起点扩张"，但 `probe * 2` 翻倍的是**绝对下标**。

### 3. ContextAssembler 说"跳过"实际直接 break

```python
if remaining > 0:
    cut = max_substring(...)
    if truncated: result.append(...)
break   # 修复前：cut==0 也 break，后面能放下的短块全被牺牲
```

高分块连一个字符都放不下时，预算内其实还空着，后续低分短块本可填入。
审计构造：预算 1，"缓"=3 token 放不下，后面 "a"=1 token 能放下——当前输出空列表。

## 修复设计

### TokenCounter.substring_start：token 级 overlap 回退

与 max_substring 对称的新 API：`substring_start(text, end, limit, min_start)`
返回**最小的 start** 使 `count(text[start:end]) <= limit`，即从 end 往前
最多回退 limit 个 token。指数探测窗口相对 end 回退扩张 + 二分，小 limit
只 count 小窗口。返回 `[min_start, end]`，`limit<=0` 时返回 end（无重叠）。

### RecursiveChunker：切片时回退，块终点取"上一片终点"

```python
overlap_limit = min(self.chunk_overlap, self.chunk_size - 1)  # 防死循环
...
p = self._counter.substring_start(text, q, overlap_limit, min_start=s)
```

- 硬切循环：下一片起点从上一片终点回退 overlap 个 token（不越语义段）；
  `chunk_size <= overlap` 时退化为无重叠，否则新片无前进空间会死循环。
- merged 组装：超预算时块终点 = **上一片终点**（重叠区保留在前一块），
  起点 = 本片起点。原逻辑块终点 = 本片起点，会把重叠区丢给后块。
- 删除 final 阶段的死代码循环。
- `i == 0` 保护：`pieces[-1]` 在 Python 里是负索引回绕，第一片超预算
  （allow_oversize 单字符）时不能引用"上一片终点"。

### 相对跨度探测

```python
step *= 2
probe = min(hi, start + step)
```

探测窗口长度 = step（相对起点），start=5000 时序列 1,2,4,8... 而非 1,5000。

### ContextAssembler：放不下就 continue

```python
if truncated:
    result.append(...)
    used += count(truncated)   # 关键：continue 后必须同步 used
continue                       # 修复前 break
```

截断成功也要更新 `used`，否则后续块会按"空预算"误判。

## 测试设计教训

- **假阳性测试**：`ov_tokens <= overlap` 对零重叠也通过。R2 改为
  `0 < ov_tokens <= overlap`（overlap>0 时必须存在真实重叠），并补
  审计复现场景 `chunk_size=12、overlap=6、每字符 3 token` 的硬切断言。
- **确定性计数器误导**：Char3TokenCounter（每字符 3 token）下 ASCII
  单字符 "a" 也是 3 token，审计场景"第二块 a 占 1 token"必须用**真实
  tiktoken**（"缓"=3、"a"=1）。写测试时先想清楚"token 单位"由谁定义。
- **窗口探测量化**：RecordingCounter 记录每次 count 的窗口长度，断言
  `max_window <= 4`，把"接近二次复杂度"变成可回归的断言。start=0 场景
  天然通过（绝对翻倍 == 相对翻倍），说明回归测试要覆盖 start>0。

## 验收对照（审计返工单）

| 验收项 | 结果 |
|--------|------|
| 相邻块条件允许时真实 overlap | ✅ 硬切块间 `0 < ov <= configured` |
| overlap 按 token 计算、块不突破 chunk_size | ✅ substring_start + 片预算重新计数 |
| 测试同时验证 `0 < overlap_tokens <= configured` | ✅ |
| 指数探测相对跨度 | ✅ `step *= 2; probe = start + step` |
| start=5000、limit=1 窗口测试 | ✅ RecordingCounter max_window <= 4 |
| 放不下当前块时继续尝试后续候选 | ✅ continue + used 同步 |
| 中文块放不下、后续 ASCII 块能放下的测试 | ✅ 真实 tiktoken |
| status.md 保持 🔄 | ✅ 等下轮复审改 ✅ |
