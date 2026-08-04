# REWORK-P0-03：分块静默丢字——从"修 decode"到"换数据边界模型"

> 2026-08-05 — 147 → 157 passed
> 审计要求：删除 strip("�")/errors="ignore" 掩盖类处理；fallback 单位一致；
> overlap=0 拼接精确；原文合法 U+FFFD 保留；chunk_size=1/2/3 不丢字不死循环。

## 问题链：修现象 vs 修模型

| 阶段 | 做法 | 结果 |
|------|------|------|
| 最初 | decode 出 `�` | 乱码 |
| 补丁 1 | `.strip("�")` | 隐藏错误，内容仍丢 |
| 补丁 2 | `errors="ignore"` | 看不到乱码了，但正文被静默删除 |
| 补丁 3 | tiktoken 路径也 strip | 原文合法 `�` 被误删 |
| 补丁 4（失败） | re-encode 校验窗口合法性 | **死循环**：`encode('�') == [25906, 241]`（"缓"的 token 序列），校验被碰撞骗过 |

**根因不是 decode 实现，是数据边界模型错了**：
- BPE token 只是 UTF-8 字符的字节切片，token 边界 ≠ 字符边界
- fallback 把 UTF-8 字节冒充 token，`chunk_size=2` 必切三字节汉字
- `encode(A) + encode(B) ≠ encode(A+B)`（BPE 跨边界重新合并），Recursive 位置推进会漂移

## 正确设计：原始文本是事实源，token 只做预算

```
原始文本 → 按字符位置选候选区间 → count(子串) 算 token 数
         → 二分找不超过预算的最大结束位置 → text[start:end]
```

- chunk 永远是原文的精确子串 → 无半字符、无乱码、无丢失（天然满足）
- overlap 按字符位置回退
- 记录 `char_start/char_end`，可映射回原文
- fallback 明确降级为"字符计数"（1 字符 = 1 token，count/encode/decode 一致单位）

### 核心函数：预算二分

```python
def max_substring(self, text, start, limit) -> int:
    """最大 end 使 count(text[start:end]) <= limit（二分，依赖 BPE 单调非减）"""
    lo, hi = start, len(text) + 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if self.count(text[start:mid]) <= limit:
            lo = mid
        else:
            hi = mid
    if lo == start:
        lo = start + 1   # 例外：预算小于单字符 token 跨度时放行一个字符
    return lo
```

## 过程中挖出的三个既有 bug

1. **Recursive 位置漂移**：`_split_tokens` 用 segment 重新编码长度推进 token 位置，
   BPE 跨边界合并导致位置漂移 → 尾部内容丢失。重写为字符层切段 + 预算组装。

2. **`_split_text` 丢前导分隔符**：`" 🎉".split(" ")` → `["", "🎉"]`，空 part 的
   分隔符无处附加 → 空格丢失。修复：空 part 的分隔符缓存 pending，附加到下一段开头。

3. **ContextAssembler 截断**：`tokens[:remaining]` + decode 同样切半字符，
   改为 `max_substring` 字符级截断（结果永远是原文前缀）。

## 验证（审计不变量）

- 每个 chunk 是原文精确子串（`text[char_start:char_end] == content`）
- `overlap=0` 拼接严格等于原文（中文/英文/Emoji/混排）
- 原文自带 `�` 保留且不新增
- `token_count == counter.count(chunk.content)`
- chunk_size=1/2/3 不乱码、不死循环（旧实现必挂）

## 教训（面试可讲）

1. **修现象会层层打补丁**：strip → ignore → strip(tiktoken) → re-encode 校验，每层
   都有新副作用。正确的做法是退回一步问"哪个模型假设错了"。
2. **验收条件要写强**："不能出现 �" 太弱，表面通过的实现可能数据已丢；
   要写"拼接必须精确等于原文"这种可证伪的不变量。
3. **编码可逆性不是免费的**：`encode(decode(tokens)) == tokens` 不总成立——
   不同字节序列可能编码成相同 token（`�` 撞上"缓"）。
