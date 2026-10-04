# 公共读取片段一致性实验（2026-10-03）

**保留切片，新增 provider 调用为 0。** 固定回放上轮 48 个真实用户请求中的 41 次成功读取；旧正文有 23 次二次截断，新转换 41/41 与实际返回一致。它验证公共正文保真，未生成新回答或重评分旧回答。

详情见 [验证报告](../../docs/validation/2026-10-03-evidence-excerpt-fidelity.md)。

## 输入与结果

- `initial_manifest.json` 在本切片代码修改前写入。基线包含上一轮尚未提交的 PROJECT_DOC_V1，不能仅用 Git HEAD `d937046` 替代整个工作区基线。
- `baseline/` 保存本切片六个改动模块的原始字节；`retained/` 保存最终模块与新增 shared excerpt policy，`outcome.json` 记录 SHA。
- 初始 manifest 保护 Router、Prompt、Planner、Verifier、App/SSE 与前端共 13 个文件，另保护上轮归档 33 个文件；旧实验不重标。
- `replay.py` 读取原 `evaluation/task_completion_20261003/**/raw/paired/live_results.jsonl`，核对旧前缀截断、新正文完整性和原定位身份，然后验证 API schema。输出不重复原源码正文，只保留范围、长度与正文 SHA。
- `raw/replay.json` 是固定数据的离线转换结果。不是新模型实验、Holdout 或独立语义验收。
- `raw/pytest-targeted.txt` / `test_scope.json`：相关 15 模块 303 passed / 6 skipped，完整命令与范围保留。
- `raw/pytest-real-reader-max-window.txt`：最大窗口改用真实 Reader 后，ASCII / 中文 / emoji 的三项复验，不能与 303 累加。
- `raw/pytest-initial-targeted.txt` / `initial_test_scope.json`：旧测试夹具范围不一致导致的初次失败；随后补齐夹具，生产校验未放宽。新模块最初误用字段名的测试问题也在 scope 中记录。

全套 readonly registry SHA `02649079…` 包含 knowledge_search；Engineering 的决策工具目录去掉该项，SHA 仍为 `30846e05…`。两者分别比较，不混用身份。

## 重跑

在保留实现的仓库根目录执行，使用新输出文件、现存父目录：

```bash
python evaluation/evidence_excerpt_20261003/replay.py \
  --output /tmp/evidence-excerpt-replay.json
```

Windows 可将输出替换为 `D:/ragtmp/evidence-excerpt-replay.json`，先确保父目录存在。回放不联网，不读取 API key，不启动服务，不消费额度；保护身份不符时失败，不更新原 manifest 迁就未来变更。

局部测试的完整文件清单与命令在 test_scope.json。它使用 scripted provider、真实本地 Reader 和 FastAPI TestClient；没有模型请求或 corpus 下载。重新运行请替换 basetemp 为自己的短路径。

目录使用 `-text` 保护原始字节。数据库、`.env`、provider 原始思维链、服务日志及 `__pycache__` 不归档。
