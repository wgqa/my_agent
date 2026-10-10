# 当前产品的工具调用评测 v2

本目录评测第二层：工具动作、参数、实际材料、恢复与停止行为。默认命令不调用模型。正式模型运行前按项目所有者要求告知；不通过正在运行的 8000 服务、不重启服务、不修改生产库或核心策略。

## 已提供的内容

- 48 道开发题 + 24 道新题，四组分别为六工具目标任务、多材料取证、缺失/歧义/续读/恢复、无需工具与边界。
- 固定 Requests、urllib3 源码及一个小 Git fixture。题目、源码 SHA、声明的提交和工作区 patch、Gold 行哈希一起保存。
- 实际 executor、Planner、前置检索、Decision、Verifier 的被动观测；live 时逐次观测 SDK 调用，包含解析修复和部分 usage 缺失。
- 自动逐题评分、分组指标、明确分母、成本、离线重算与独立的复核队列。
- 95 项零模型测试；CI 不下载外部源码，不调用模型。

主链沿用 `api.app._build_engineering_project_runtime -> EngineeringAgentFacade`。
2026-10-10 的运行身份已对齐 API 当前选用的 Decision current_request v5、Planner references v3 和 Context references v2；被动检索观测保留实际词法查询。每次 live 的真实调用 metadata 仍需通过冻结身份校验。
七工具注册中，当前主链可调用六工具；`knowledge_search` 在运行时禁用，知识由 Planner/前置检索处理。
它仍有七工具离线契约检查，不能据此宣称主链模型调用了七种工具。

## 运行

在项目根目录执行。需要已安装的项目依赖和 Git，不安装/升级共享环境。

```powershell
# 显式下载两个固定源码仓库；零模型调用。缓存只属于评测器。
python scripts/run_tool_call_evaluation.py --prepare-sources

# 默认：真实只读工具执行 Gold 路径，验证题目材料可达；零模型调用。
python scripts/run_tool_call_evaluation.py --run-id offline_gold_new

# 替换 Planner/Decision，用参考动作走完整产品装配；零模型调用。
python scripts/run_tool_call_evaluation.py --scripted --run-id offline_facade_new

# 只运行离线回归，不需要外部源码或实际知识语料。
python -m pytest -q tests/test_tool_call_evaluation_v2.py tests/test_tool_call_evaluation_v2_observer.py --basetemp=./.tmp_pytest_tool_call_v2_local
```

CLI 预检/主链回放构建独立 managed 库，以经验证的 37 篇基础知识文档为种子，默认读取 `.env` 的 `ENGINEERING_KNOWLEDGE_CORPUS_ROOT`；也可显式提供 `--knowledge-source <目录>`。
不读取生产 SQLite 的用户上传/删除状态。manifest 记录实际文档和 chunk 的内容 SHA，不将它称为线上当前可变知识库的完整副本。

正式运行命令：

```powershell
# 开始前告知项目所有者。四道预选试运行题属于 48 题，不再重复充数。
python scripts/run_tool_call_evaluation.py --live --split dev --run-id live_dev_VERSION

# 同一业务/题集/评分版本执行新题，不根据开发成绩改验收题。
python scripts/run_tool_call_evaluation.py --live --split validation --run-id live_validation_VERSION
```

`--case dev-001 --case dev-025` 可选子集，子集报告只声明所选范围。
live 必须显式选择 split，防止把开发与新题混成一个成功率。
runner 顺序执行，每题一次；无任务重试。生产原有一次解析修复保留，属于额外 provider 调用。
模型解析失败、重复/超预算、误拒答保留在结果里；provider 不可用、版本变化和记录器异常单列无效，不静默删除。

源码缓存和运行临时数据位于 `data/runtime/tool_call_v2/`（Git 忽略）；报告默认保存在 `evaluation/tool_calls_v2/results/<run_id>/`。
不在 D 盘根目录建临时目录。已有 run ID/状态目录不覆盖，也不清理其他任务文件。
业务和评测器文件在每题前后重新计算 SHA，变化时停止并保留已运行和未运行题目。

## 离线重算与复核

```powershell
python scripts/run_tool_call_evaluation.py --rescore evaluation/tool_calls_v2/results/RUN_ID --run-id recomputed_RUN_ID
```

重算校验冻结 cases 和 calls 的 SHA，保存新的报告，原始结果不覆盖。
规则改变时默认拒绝重算；`--allow-rule-change` 显式建立新分析，并记录新旧规则身份。

| 文件 | 内容 |
|---|---|
| `manifest.json` | 实际代码/评测器/Gold/规则/配置/工具 schema/源仓库/知识内容身份 |
| `cases.jsonl` | 本次冻结题目及 Gold（不传给模型） |
| `calls.jsonl` | 已解析动作、真实工具材料、规划/检索/Verifier、逐 provider 调用、停止事实 |
| `scores.json` | 原自动分、缺失义务、停止原因、失败/无效类别 |
| `summary.json`、`report.md` | 分组指标、分母、调用/usage 缺口、成本与逐题结果 |
| `reviews.json` | 争议/失败项及通过项抽查队列，默认 pending |

复核必须填写评审身份、理由和源码定位。`developer_assistant` 是开发助手复核，不是独立人工验收。
`validate_reviews` 验证裁决完整性；自动分始终保留，复核决定单独记录，不自动篡改 Gold 或替换自动汇总。

2026-10-10 已完成当前 R01 业务版本的 48+24 题真实模型基线，见 [正式结果与修复优先级](../../docs/validation/2026-10-10-tool-call-evaluation-v2.md)。自动成绩、开发助手复核、真实成本与未覆盖项分别列出。

## 如何判分

正文义务绑定真实行号和内容哈希，可由多次 Reader 续读合并获取。
合法等价 Reader 目标、OR 材料替代和无依赖材料的不同顺序可以通过，不锁死唯一工具序列。
只有实际必要的工具才设工具义务；`focus_tool` 只是观察机会。
候选测试/导入行/搜索单行不能满足测试正文义务；工具只读，不能证明运行了 pytest。

数值、Git 模式/路径/真实 patch/解析后的 commit ID、变更集合、具名缺失/歧义、续读和错误恢复分别检查。
Git tag/ref 与同一 commit SHA 的等价写法可以通过；支持的 Windows 相对路径按规范路径比较。
数值相同但表达式未枚举、其他未识别的合法辅助路径进入源码复核，不凭关键词判成正确。
模型不当路径尝试与护栏拦截分别计数，即使执行被拦截也不能记作模型安全通过。
解析层参数错误独立于 executor 错误统计，不从 raw model output 猜工具归属。
没有分母显示 N/A；缺 usage 保持未知，不填零。成本包含 Planner、Decision 和解析修复。

## 已知边界与离线发现

- 默认 `gold_proof` 的 terminal 是合成的可达性标记；它既不证明 Guard 允许结束，也不证明模型能自主走这条路径。
- `scripted` 真正经过 Guard，但 Planner/Decision 被替换，不证明真实规划、工具选择或最终答案质量。
- `dev-005` 的定位问法激活正文护栏；参考路径增加合法的短 Reader 跟进，仍在预算内，Gold 不强制模型采用这一序列。
- `dev-015` 只要求已删除源码清单。最小参考路径已取得所需集合，但当前主链仍可能要求源码正文而拒答。保留预期完成与缺口，不改成“应该拒答”以取得高分；真实模型表现待测。
- authoring 时 `find_tests(timeout.py)` 的前 10 个候选不含 `test/test_util.py`。这说明 bounded discovery 的覆盖限制；普通候选题改为明确的 filepost 目标，Timeout 的正文获取仍有其他题覆盖。初次预检保留，未根据模型成绩换题。
- urllib3 新题是相近 HTTP/Python 仓库迁移，不是跨领域、sealed holdout 或独立人工评审。
- 第二层不验证公共答案全部事实、claim grounding、HTML/SSE、多轮/项目切换/知识上传删除等第三层行为。

完整计划见 [评测计划](../../docs/design/tool_call_evaluation_v2_plan.md)。
