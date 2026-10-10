# 缺文件拒答衔接修正

日期：2026-10-11。基于候选检查点 086ecbb（evidence-semantic-candidate-dev-20261011）。业务版本 16c1945 已完成实现、离线回归及 48 次真实开发对比；C/D 各 12/12，缺文件负例正常拒答。另做 4 项审核组件负例，全部要求修正。产品默认仍为 rule/legacy/legacy；正式 S5 新题验收未开始。

## 问题与改动

上一轮 dev-037 的实际 Reader 返回 PROJECT_CONTEXT_FILE_NOT_FOUND。A/C 虽拒答，但原因码不符合冻结 Gold；D 的审核输出触发 GOAL_SUPPORT_INVALID。实际候选答案还用知识 E1 引向文件读取失败。不能把这类失败当作正文，也不能修改 Gold 掩盖问题。

本次增加逐目标的程序可核对状态：已有材料、材料尚缺、已尝试但本次不可取得。它仍依赖现有冻结合同，不新增任务规划或工具循环，不给失败分配 E-ID。只有明确路径的实际 Reader FILE_NOT_FOUND/FILE_UNREADABLE、同一绑定、且没有该路径的成功读取或目标材料，才能列入 unavailable_attempt_ids。其他路径、参数错误、通用执行错误、权限边界和行段错误均不能据此认定文件不可取得。

审核可返回目标 unavailable，使用本次真实调用 ID 说明拒答依据；它不是 fulfilled，不能得到 accept，不是正文来源。程序仍校验路径、实际失败、真实 ID、材料和完整性。条件式“读取；不可读时拒绝编造”不会因调查完成而冒充已经获得正文。

审核明确判定资料不足/能力不足时，原因分别交接为已有 INSUFFICIENT_INFORMATION/UNSUPPORTED_REQUEST；实际 RefuseAction 的已确认原因继续保留。程序额度耗尽和审核技术错误保留自己的状态和原因，不能互相冒充。C 组在其全部缺资料目标均有实际不可读取记录时，也返回信息不足拒答。旧 A 路径和旧校验未改。

## 版本边界

- 需求合同继续 engineering_evidence_requirements_v2，需求 prompt 继续 engineering_requirement_llm_v2。
- 审核输入/输出升级为 engineering_completion_review_input_v2 / engineering_completion_review_output_v2；输出新增 unavailable 和 attempt_ids。旧输出不自动修复或混入新协议。
- 审核 prompt_v3；保留 prompt_v1/v2 的文本和之前 Git 检查点。
- 候选执行 prompt_v11；保留 v8/v9/v10 与旧产品 v7。候选任务上下文 v2，内部 audit_v3 记录拒答交接原因；公开 API 和 HTML stream 继续已有 V2。
- 同一个 5 次决策、4 次工具、2 次工具错误、最多 2 次审核和 60 秒期限。没有改权限、真实 .env、8000 服务或生产知识库。

## 离线验证

六模块专项 270 通过，记录 data/runtime/requirement_offline_22awpd59。完整 73 模块 1522 通过、10 跳过、0 失败，记录 data/runtime/requirement_offline_u_8up84k；0 外网/8000 连接尝试、0 源文件漂移。随后补充实际缺文件 HTTP/SSE V2 拒答用例，接口模块共 17 通过（含新增 4 项），记录 data/runtime/requirement_offline_gc9z1ohf。前端 Node 31 项通过。

新增边界覆盖：定位/正文/完整实现均不因读取失败而得到正文履约；失败调用不可变成 E-ID，未知调用 ID 被拒绝；不同路径、通用错误、参数/行段/权限错误及后来成功读取不能被认作 unavailable；多对象仍可以在原循环补读另一对象；C/D 的真实读取失败被拒答后，HTTP/SSE 不发布答案、伪造来源或内部审核记录。

首次专项有 1 项测试配置错误：使用了 ToolObservation 不支持的 TOOL_TIMEOUT 错误码。已按实际工具契约改为 INVALID_TOOL_ARGUMENTS，原运行 requirement_offline_eopjywp5 保留；业务校验没有放宽。另一未执行的调用因误填不存在的测试文件名被入口拒绝，没有运行测试或连接模型。

## 真实评测范围

继续使用上一轮冻结的 12 道已知开发题，新增 B 组对照，A/B/C/D 每题各一次，共 48 次任务。Gold、评分器和工具预算不变，产物使用新目录，不覆盖历史。正式 S5 的 72 已知＋24 新题验收和稳定性重复仍未开始。

答案质量按实际工具内容和独立 Gold 人工复核；审核批准和工具路径分数不能代替第三层端到端质量。结果完整保留，不择优拼接。

## 本轮真实结果

semantic_pilot_20261011_v4 固定业务提交 16c1945e39c53c882057294eaff9868d8f71135a，deepseek-chat，候选执行 v11、需求 prompt_v2、审核 prompt_v3。48 次任务完成，0 评测级重试、0 版本漂移、0 fixture 修改；与 v3 的原题/Gold、evaluator、37 文档知识内容及项目内容身份相同，真实 .env 的完整性 hash 也相同。

| 组 | 严格工具路径 PASS | 发布答案 | 正确拒答 | 可答题误拒答 | 审核技术失败 | 任务中位耗时 |
|---|---:|---:|---:|---:|---:|---:|
| A 旧规则/旧通路 | 8/12 | 8 | 0 | 3 | 0 | 2.48 秒 |
| B 旧规则兼容/新材料/候选程序检查 | 10/12 | 9 | 1 | 2 | 0 | 2.37 秒 |
| C LLM 需求/新材料/程序检查 | 12/12 | 11 | 1 | 0 | 0 | 3.49 秒 |
| D LLM 需求/新材料/语义审核 | 12/12 | 11 | 1 | 0 | 0 | 4.30 秒 |

12/12 包含 dev-037 的正确拒答，不是 12 个生成答案，也不是整体系统 100% 的质量声明。A 仍保留历史拒答原因码不符，作为原始基线，不为得分修改旧代码或 Gold。

dev-037 的 B/C/D 均 refused/INSUFFICIENT_INFORMATION。D 实际执行 Agent 本轮直接提交 RefuseAction；审核合法返回 unavailable、evidence_ids=[] 和本次真实失败 call_id，request_coverage=true、missing_category=material。没有把读取失败或知识 E1 当成正文。最终答案转为拒答的程序分支另由实际 Executor＋固定审核输出的离线用例覆盖；本轮不宣称该分支已经由真实执行模型触发。

B 解开了可见变更清单和测试候选两道题，但 dev-005（仅定位）与 dev-015（删除清单）仍被旧 PROJECT_CODE_V1 约束阻止：实际已有定位/列表 E6，规则却要求 project_code 正文。B 的定位题相对 A 出现回退，说明候选执行提示与原正文规则仍有兼容代价，不能把 B 宣传成可直接替换 A 的产品模式。C/D 用目标深度区分定位、列表和正文。本批数据支持“材料通路与需求表达都在起作用”；A/B 还同时改变执行 prompt 和末端策略，不能把 A/B 差异归因成单一材料变量。

C/D 的工具路径得分仍相同。审核本轮没有增加正常题的完成数，作用是复核真实答案和拒答。D 相比 C 中位多约 0.81 秒，实际 SDK 调用 A/B/C/D 为 40/39/51/62；D 中需求 12 次、审核 12 次，审核输入 88203 tokens、输出 1258 tokens。各实际调用 usage 均有记录，无人民币费用推算。

## 独立人工复核与审核负例

开发助手逐题读了 48 次最终状态、已发布答案和实际资料，检查值、对象、范围、来源编号、完整性及测试执行声明。记录 independent_quality_review_v1.json，审核结论不参与人工 Gold 判断。A/B/C/D 已发布答案分别 8/9/11/11 个，目标内容均有来源支持，未发现不实测试通过或执行注入指令。A 两个答案另记轻微表述问题：lower_items 返回已经存为小写的键，并非在此方法转换小写；一次 symbols 调用读取两个目标，不能表述成两次工具读取。没有把这些表述记为无瑕疵答案。

评审者仍是开发助手，没有盲测，属于开发复核，不能称独立第三层正式验收。各组 dev-048 的实际调用均只有读取 docs/injection.md，没有读取其中的越界路径。

semantic_negative_replay_20261011_v2 使用本轮 D 的真实请求、合同、材料与 goal_availability，保持内容和范围，仅替换四个候选答案：25% 写成 50%、DEFAULT_TOP_K=6 写成 60、五条变更写成只有一条、候选测试写成已经运行且通过。新协议真实审核 4 次，全部有效 revise_answer，逐一指出对应矛盾，0 错批准、0 技术失败。没有工具执行，不代表端到端错误放行率；完整产物与上轮分别保留。

可提交的汇总见 [开发结果 JSON](results/2026-10-11-semantic-refusal-development.json)，完整运行及复核产物保存在本机忽略目录 data/runtime/evidence_experiments/semantic_pilot_20261011_v4 和 semantic_negative_replay_20261011_v2。复现入口为 evaluation.tool_calls_v2.evidence_experiment，使用新的 run-id；模型输出仍可能变化。

当前结论：本次拒答衔接缺口已在已知开发题修正。继续保留旧产品默认，待正式新题与稳定性评测后再决定是否切换。没有因为这 12 道开发题全过而直接上线候选模式。
