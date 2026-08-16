# 94-Gate5 CI 与持续集成

> **任务**：G5-CI-03-CONTINUOUS-INTEGRATION
> **日期**：2026-08-16
> **本笔记定位**：从学习角度解释 CI（持续集成），并映射到本项目的 `.github/workflows/ci.yml`。

---

## 1. 一句话

CI 把"我声称能跑"变成**每次提交都被机器在干净环境里验证**。本项目 CI 只做一件事：`ubuntu-latest` + Python 3.14 + `requirements.lock` → 跑全量测试，`pytest` exit code = 0。

---

## 2. CI 是什么

CI（Continuous Integration，持续集成）= **每次代码变更后自动构建 + 自动测试**。

传统流程：改完代码 → 自己本地跑一遍 → 觉得没问题 → 提交。问题：**人肉会忘、会懒、环境不对**。

CI 流程：推送到 GitHub → GitHub 在全新 runner 上 checkout 代码 → 装依赖 → 跑测试 → 报告红/绿。**提交后机器自动验证，不需要人记得跑测试**。

本项目 workflow（`.github/workflows/ci.yml`）只有 5 步：

```
checkout → setup Python 3.14 → pip cache → pip install -r requirements.lock → pytest
```

---

## 3. 为什么本地 pytest ≠ CI

本地跑 `pytest` 全绿，不代表 CI 会绿。差异点：

| | 本地 | CI |
|---|---|---|
| 环境 | 你的机器（装了各种东西、有模型缓存、有 `.env`） | GitHub 全新 ubuntu runner（**干净**） |
| 依赖 | 可能用了一套没人知道的确切版本 | 严格按 `requirements.lock` 安装 |
| 模型 | 有 `~/.cache/huggingface` 里的 BGE | **没有**模型缓存，且 CI 禁止下载 |
| 结果 | 你有 model cache 兜底 | 只能靠测试自己 Fake/Mock |

**所以 CI 的价值就是"没有你的特权"**：它暴露"其实你的测试依赖了本机隐式状态"的问题。如果 CI 红了，通常不是 CI 的问题，而是你的测试/配置不干净。

---

## 4. GitHub-hosted runner 是干净环境

`runs-on: ubuntu-latest` 指的是 GitHub 托管的新建虚拟机：每次 job 从镜像启动，**只有基础系统，没有任何你本机的东西**。

这带来三个推论：

1. **模型缓存不存在** → 任何"加载真实 BGE/reranker"的测试都会失败（除非测试自己 Fake）。这正是本项目测试全部用 Fake/Mock 的原因（`test_pipeline.py` 注入 `_FakeEmbedding`/`FakeReranker`；`test_chunk_budget_infrastructure.py` 用 `FakeBGEEmbedding`）。
2. **`.env` 不存在** → 任何依赖真实 `DEEPSEEK_API_KEY` 的测试都跑不了。所以 CI 不该也不会有 key。
3. **干净的依赖安装** → `pip install -r requirements.lock` 装出来的是**唯一真实验证过的环境**。这才是"干净 venv 安装"的终局检验。

一句话：**CI 就是那个"换台没你特权的干净机器跑一遍"的自动化版本**。

---

## 5. CI 为什么不能放真实 API key

- runner 每次 job 都是全新机器，但**你 push 的 workflow 文件 + secrets 是对仓库有访问权的人可见的**。
- 如果把 `DEEPSEEK_API_KEY` 直接写进 yml，等于把 key 写进仓库历史——**任何拿到仓库的人（包括面试官、同学）都拿到了你的 key，可能产生费用**。
- 正确做法是 GitHub Secrets（加密存储，仅运行时注入），但本项目 CI 根本不需要 key（测试全 Fake），所以**连 secret 都不用配**。
- 这也是项目纪律：CI 只跑**离线、Fake、不花钱**的测试；真实 LLM/benchmark 是人工触发的受控动作，不放在每个 commit 里。

---

## 6. 为什么真实模型 benchmark 不应该每个 commit 都跑

真实 benchmark（Gate 3 Holdout、Gate 4 formal Tool-Agent run）需要：

- 真实 DeepSeek API → **花钱、有速率限制**；
- 真实 BGE/reranker 模型 → **几 GB 下载 + 推理时间**；
- 冻结语料 + Gold → **是冻结证据，不是日常回归**。

如果每个 commit 都跑：

- 每次 push 花几百次 LLM 调用 + 下载数 GB → **成本爆炸**；
- 结果随模型/API 漂移 → **回归信号被噪声淹没**；
- 可能污染冻结评测（Gate 3/4 的正式成绩是一次性的）。

所以分层：

- **每个 commit（CI）**：单元/集成测试（Fake、离线、快）→ 抓逻辑回归。
- **正式评测（人工/受控）**：真实模型 + Gold + 冻结语料 → 只有方法论变更时才跑一次。

CI 抓"代码有没有坏"，benchmark 测"效果有没有变"——两者频率完全不同。

---

## 7. dependency cache 是什么

每次 `pip install` 都要从网络下载 wheel，很慢。**cache** 把下载过的 wheel 存起来，下次直接用。

本项目 CI 用 `actions/setup-python@v6` 的 `cache: pip`：

```yaml
- uses: actions/setup-python@v6
  with:
    python-version: "3.14"
    cache: pip
    cache-dependency-path: requirements.lock
```

关键点：**cache 的 key 依赖 `requirements.lock` 的内容**。lock 一变，缓存自动失效重下；lock 不变，第二次之后的 job 都命中缓存，**装 119 个包从几分钟变成几秒**。

这也呼应上一卡：lock 的精确性让 cache 更有效——一个松散的 `requirements.txt` 每次可能解析出不同版本，cache 频繁失效；精确 lock 让"同样依赖 → 命中同样缓存"。

---

## 8. 为什么暂时只把 Python 3.14 作为 validated version

- 本项目唯一**真正从零装过、跑过全量测试**的版本就是 **Python 3.14**（上一卡干净 venv 1724 passed）。
- 3.11 只是 README 里的一个"声称"，**没有实际验证**。
- 在 CI 加 3.11 矩阵，等于**在没有证据的情况下承诺 3.11 也通过**——如果 3.11 真有问题（比如某个依赖没有 3.11 wheel），CI 会红，反而伤害可信度。

所以本卡只跑 3.14。**"验证过才声明"** 是原则：先让 3.14 稳定绿，未来若真需要 3.11，再以"实际跑过矩阵"为证据加入。这也避免了"声明 ≠ 验证"的假可信。

---

## 9. 验收边界

- 本地只做 `pytest -q tests/test_reproducibility_contract.py` + `git diff --check`；
- 不新建 venv、不再装 119 包、不跑 1724 全量——**真正的 clean install + full pytest 就是 GitHub CI 自己的职责**；
- **Agent 不能因为写了 workflow 就说"CI 已通过"**：只有用户 push 后 GitHub Actions 真正跑绿，才有资格签 CI 通过。
