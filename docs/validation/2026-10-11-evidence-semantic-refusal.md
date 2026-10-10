# 缺文件拒答衔接修正

日期：2026-10-11。基于候选检查点 086ecbb（evidence-semantic-candidate-dev-20261011）。当前完成实现与离线回归，真实模型开发对比待执行。产品默认仍为 rule/legacy/legacy。

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

答案质量需要按实际工具内容和独立 Gold 人工复核；审核批准和工具路径分数不能代替第三层端到端质量。评测完成后追加原始结果、实际失败及各组用量，不择优拼接。
