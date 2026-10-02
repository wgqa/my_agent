# Jev 预期证据路由接入 v1（已暂缓）

更新日期：2026-10-02。项目所有者决定暂缓外部模型判定证据要求，当前产品主链已经撤掉 Jev 接入，恢复原有关键词路由；本轮没有运行测试或调用 Jev / DeepSeek。

## 当前状态与恢复内容

`api/app.py` 不再导入或注入 Jev。`UnifiedEngineeringRuntime` 直接调用原有 `route_engineering_evidence_requirement`，随后继续原来的检索、工具执行和证据验证。`.env.example` 已移除 Jev 开关、Gateway 密钥占位和参数；本地 `.env` 没有修改，其中即使曾配置这些变量，当前主链也不会读取它们。

未验证的 Jev 实现保存在同目录的 [engineering_jev.py.txt](engineering_jev.py.txt)，从 `core/` 移出，不参与运行时导入。没有接入另一个模型替代它。后续是否重新引入语义路由，要另行评估需求与方案。

**以下为 2026-10-01 的历史方案。配置、注入点和共同测试清单均已搁置，不表示当前系统支持启用 Jev。历史实现从未运行测试或真实模型验证。**

## 目标与实施顺序

当前 Engineering 主链根据关键词选择预期证据要求。同一意图换一种说法时，可能无法激活仓库证据获取。本轮让 Jev 对解析后的问题做一次语义分类，输出已有的 requirement profile，作为可选路由实现。

实施顺序：先固定接入边界和回退策略，再实现 HTTP 适配与响应校验，然后注入 UnifiedEngineeringRuntime，最后补充配置及后续联调步骤。本轮到代码与文档修改为止。

Jev 只选择证据要求；具体证据组与最少代码路径数仍从 `FROZEN_PROFILE_SPECS` 生成。当前 Planner、知识检索、工具注册表、5/4/2 预算、证据验证和最终回答流程继续由原有组件负责。

## 接入位置

```text
Context Resolver → Evidence Planner → Requirement Router
                                         ├─ lexical（默认，无 Jev 请求）
                                         └─ Jev choice → 校验 / 概率门槛
                                                       ├─ 采用已有 profile
                                                       └─ 回退 lexical
                   → Planned Retrieval → bounded Tool Execution → Evidence Verifier
```

仅在 API 启动时为 Engineering 产品主链注入路由。`/engineering/query`、两个 Engineering SSE 入口和会话消息共用此路径。独立的 Basic / Agentic / Tool Agent 入口不启用 Jev。直接构造 Runtime 且不注入路由时保持原行为。

## HTTP 合约与分类选项

采用用户提供的 Vercel AI Gateway 入口：`POST https://ai-gateway.vercel.sh/v1/evaluate`，模型固定为 `typesafe-ai/jev`，使用 `AI_GATEWAY_API_KEY`。复用项目已有的 `requests` 依赖；初始化只读配置，不发送请求。

请求的 `state` 只包含解析后的问题，`questions.evidence_profile` 是一个 `choice` 问题，`criteria` 列出下面七个选项。每轮至多发送一次请求，客户端不重试、不配置另一个付费模型作为兜底，不发送仓库文件或检索证据。

| profile | 问题意图 | 原有证据要求 |
|---|---|---|
| `THEORY_CODE_V1` | 原理与当前项目实现对照 | Knowledge + Project Code/Doc，至少 1 个代码路径 |
| `CHANGE_TEST_V1` | 改动与相关测试分析 | Change + Test |
| `DIAGNOSIS_SINGLE_V1` | 单文件故障诊断 | Code，至少 1 个代码路径 |
| `DIAGNOSIS_CROSS_FILE_V1` | 跨文件故障或数据流诊断 | Code，至少 2 个代码路径 |
| `DOCS_CODE_V1` | 文档与代码一致性检查 | Doc + Code，至少 1 个代码路径 |
| `PROJECT_CODE_V1` | 当前仓库源码、定位或调用关系 | Code，至少 1 个代码路径 |
| `NO_ADDITIONAL_REQUIREMENT` | 通用解释、普通知识问答、计算等 | 不增加项目证据组 |

响应必须包含合法 `choice` 和完整的七选项概率分布；拒绝未知选项、错误类型、NaN/Infinity、超范围概率及明显不归一的分布，并检查 choice 对应最高概率。HTTP 用量读取 Gateway 的 `inputTokens` / `outputTokens`；未知用量保持未知。

Gateway 的选项概率与 TypeSafe 的原生 `confidence` 是不同指标。本版采用**所选选项的概率**作为回退门槛，不自行合成 confidence，也不把概率解释成正确率。默认 0.80 只是联调初值，尚未用本项目数据校准。

## 配置与降级

从 `.env.example` 复制变量到本地 `.env`，待联调时再填写真实密钥并启用：

```dotenv
ENGINEERING_REQUIREMENT_ROUTER=jev
AI_GATEWAY_API_KEY=
ENGINEERING_JEV_TIMEOUT_SECONDS=5
ENGINEERING_JEV_MIN_PROBABILITY=0.80
```

默认 `ENGINEERING_REQUIREMENT_ROUTER=lexical`，不使用 Jev。切换配置后重启 API。切回 `lexical` 即可停用集成。

缺少密钥、问题过长、网络超时、HTTP 错误、无效 JSON / choice 或低于概率门槛时，使用已有关键词路由并记录固定回退原因。配置值本身错误会报初始化错误，避免把拼错的开关当作已启用。超时是 HTTP connect/read 的等待上限，不是新的全链路强制截止时间；执行引擎的现有 deadline 保持原语义。

服务端 `core.engineering_jev` 日志记录实际 source、最终 profile、Jev 候选、候选概率、回退原因、耗时和独立 token 用量。成功路由为 INFO，回退为 WARNING；联调时开启此 logger 的 INFO 级别。日志不包含密钥、问题正文、响应正文或原始异常文本。原来的 `execution.decision_llm_calls` 和 token 统计继续表示执行引擎的 Decision 调用，Jev 用量单独记录。

`EngineeringEvidenceRequirement.router_version` 仍是冻结的结构合约版本。实际 Jev 选择器用日志中的 `selector_version=engineering_jev_requirement_router_v1` 区分，避免把历史 profile 合约与新选择器混为一谈。

## 后续共同测试清单（本轮未执行）

1. 先做离线适配检查：默认路由、七种 profile 映射、非法响应、低概率、缺少密钥、超时和 HTTP 错误回退。这一步无需付费额度。
2. 准备 Vercel AI Gateway 密钥后，单独调用路由组件，确认真实 HTTP 响应字段、分类、日志和用量；这一步不依赖 DeepSeek。重点检查“代码在哪、调用链、文档一致性、改动影响、跨文件问题”的不同表达，以及通用问题是否误触发项目证据。
3. DeepSeek 可用后，联调 Engineering API、SSE 和会话路径，确认 profile 进入证据获取与最终验证；用同一批问题对照 lexical，分别比较路由准确率、完成率、回退率、耗时和成本。
4. 根据对照结果调整概率门槛与分类 rubric。通过后再决定是否默认开启；接入代码本身不证明回答质量已经提高。

准备好 Gateway 密钥后，下面的 Python 示例可以单独观察 Jev 路由，不初始化 DeepSeek、检索后端或整个 API。本轮没有执行此示例。密钥缺失时只返回 lexical，并在日志标明 `missing_api_key`；不能把这种输出记为 Jev 成功。

```python
import logging
import os

from dotenv import load_dotenv
from core.engineering_jev import JevEngineeringRequirementRouter

load_dotenv()
logging.basicConfig(level=logging.INFO)
router = JevEngineeringRequirementRouter(api_key=os.getenv("AI_GATEWAY_API_KEY"))
requirement = router.route("从请求入口到答案返回，中间经过了哪些函数？")
print(requirement.requirement_profile.value)
```

## 官方依据

- [Jev 模型入口](https://vercel.com/ai-gateway/models/jev)
- [Vercel Evaluation HTTP 接口、choice 和用量](https://vercel.com/docs/ai-gateway/modalities/evaluation)
- [TypeSafe choice 定义](https://docs.typesafe.ai/primitives/choice)
- [confidence 与概率的区别](https://docs.typesafe.ai/confidence)
