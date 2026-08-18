# 102-Gate5：Release 安全与仓库卫生

## 为什么 Release 前要做 secret scan

代码测试通过不等于仓库可以公开。Release 前需要扫描当前 HEAD 的 tracked files，因为真实凭据、Authorization header、private key 或非空 `.env` 一旦进入 Git 历史，单纯删除工作区文件并不能撤销泄漏。扫描报告只记录文件、行号、类别和 fake/safe/suspicious 判定，不复制原值。

## Tracked 与 Untracked

`git status` 中的 untracked 文件不属于当前提交，但仍可能污染本机工作区、误被下一次 `git add .` 带入仓库。审计要把它们分类为 runtime/temp、historical experiment artifact 或 unknown，并且不能为了得到干净状态直接删除用户文件。`.gitignore` 负责阻止未来误加入，不负责清除已经进入历史的内容。

## 为什么不能随便 git clean

`git clean`、`reset --hard` 和 `checkout .` 都可能破坏用户实验、诊断输出或尚未备份的结果。Release Hygiene 的目标是确认什么应该被提交，而不是强制把本地目录变成空白工作区。本轮只增加精确 ignore 规则，保留已有 untracked 文件。

## Frozen artifact 与仓库干净度

冻结 evidence 可能很大、很旧或包含失败结果，但它们是审计链的一部分，不能因为“仓库卫生”而删除。正确做法是检查 tracked 大文件是否属于模型、数据库、缓存、日志或 runtime vector store；正式 evidence 即使超过阈值也应保留。本轮 HEAD 没有达到 1 MiB 的 tracked 文件。

## Placeholder 与真实 secret

`sk-test`、全零 token、`sk-xxx`、dummy smoke key 和空的 `.env.example` 是测试/配置边界，不应误报成真实泄漏；但扫描仍要记录类别和判定。相反，真实长度 token、Bearer credential、私钥块或非空环境文件必须阻塞 Release，并交由 Reviewer 决定历史清理，不能自行重写 Git history。

## 技术债不等于 Release blocker

Streaming、认证、上传 timeout、Memory、MCP、GraphRAG 和更强 multi-step 等会影响后续产品能力，但不是本轮仓库卫生 blocker。Release 审计只处理安全泄漏、明显误导和持续制造噪音的卫生问题，并把其余项目明确列为 V1.1 debt。

## 面试表达

“我没有只说仓库安全，而是审计了 HEAD 的 tracked secret、`.env` 历史、绝对路径、Holdout 边界、tracked 大文件和 untracked 分类；对 fake placeholder 与真实凭据分开判定，对 frozen evidence 不删除，对用户实验不 `git clean`，并把结论写入可复核的 audit 文件。”
