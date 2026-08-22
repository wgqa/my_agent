# Git 变更证据与只读工程 Agent

## 1. 为什么需要 Change Evidence

`code_search` 与 Git change evidence 回答的是两类不同问题：

- `code_search` 在当前仓库中定位匹配文本，返回 repo-relative path、line 和有限匹配行。
- `changed_files` 从 Git 状态或 commit range 定位发生变化的文件，只返回 path 与 change status。
- `git_diff` 在已经定位到的单个 changed path 上读取 bounded unified diff。

搜索匹配行只是定位线索。它说明某个字符串出现在哪里，不说明这个实现实际做了什么。Change Evidence 说明某个文件相对某个 Git 比较端点发生了什么变化，但也不替代源码上下文。二者可以同时进入 Agent 的事实上下文，最终答案仍必须建立在成功 Tool Observation 上。

## 2. Git 的比较对象

Git 工作区可以粗略分成四个观察点：

- working tree：磁盘上的当前文件。
- index：已经 `git add` 的暂存快照。
- `HEAD`：当前提交指向的提交快照。
- 其他 commit 或 ref：用于历史范围比较的已解析提交。

`working_tree` 模式使用 `HEAD` 与当前 tracked working tree 的差异，并额外列出未跟踪文件。`commit_range` 模式比较 `base_ref` 与 `head_ref` 两个提交。`git diff base head -- path` 的两端是两个提交快照；working-tree 模式则省略第二个提交端点，让 Git 比较 `HEAD` 与当前工作区。

暂存和未暂存的 tracked 修改都属于从 `HEAD` 出发的工作区变化。未跟踪文件没有可供普通 `git diff` 比较的 `HEAD` blob，因此只能由 `changed_files` 标记为 `untracked`，不能被 `git_diff` 当作已读取的源码返回。

## 3. 两阶段 Tool 链路

标准调用顺序是：

```text
changed_files(mode, [base_ref, head_ref])
        |
        +-- repo-relative path + status
        v
git_diff(mode, path, [base_ref, head_ref])
        |
        +-- one bounded unified diff
        v
final_answer
```

`changed_files` 是定位阶段，不读取 untracked 文件正文，也不返回整个仓库 diff。`git_diff` 只接受一个 repo-relative path，并要求该 path 已经出现在 Git change result 中。这让 Agent 的动作是可审计的：先发现变化，再选择一个具体文件读取差异。

## 4. 为什么不允许任意 shell

让模型直接生成 shell 或完整 Git command 会把“查询仓库变化”扩大成任意进程执行能力，风险包括 command injection、任意文件读取、重定向、外部程序调用和超出仓库边界的路径访问。

工具只接受固定的 argv 模板。模型不能提交 repo root、cwd、shell command、Git flags 或任意参数。ref 会先通过固定的 `git rev-parse --verify <ref>^{commit}` 解析成 commit SHA，后续 diff 只使用已经验证的 SHA。option-like ref、空白 ref、过长 ref 会在进入 Git 前拒绝。

仓库校验还要求 `git rev-parse --show-toplevel` 与绑定的 repo root 精确一致。这样位于主仓库内部的普通目录不会被意外当成另一个合法 Engineering Project。

路径只允许 POSIX 风格 repo-relative path。绝对路径、Windows drive path、反斜杠、`.`、`..`、空路径和 symlink escape 都拒绝。敏感文件沿用现有 secret-file 判定：`changed_files` 只累计 `omitted_sensitive_count`，`git_diff` 直接返回稳定的 path-not-allowed 错误，不把 secret 内容放入 Observation。

## 5. Bounded diff

Git 输出必须有资源上界。当前契约限制：

- `changed_files` 最多返回 100 个文件。
- 每个 Git process 的保留输出有字节上限。
- `git_diff` 一次只读取一个 path。
- diff 最多 20,000 个字符、400 行。
- 输出带有 `truncated`、`start_line` 和 `end_line`，让调用方知道证据是否完整以及它覆盖的范围。
- `changed_files.total_count` 在未截断时是完整数量；截断时只代表已经安全观察到的数量，不暗示完整列表已读取。

binary diff 可以返回 Git 的 bounded unified metadata；它不会为了产生文本而把二进制文件正文读入 Agent context。Git stderr、异常正文、完整本机路径都不进入 Observation。

## 6. Change Evidence 与 Code Evidence

`read_project_context` 成功读取源码窗口后产生 `project_code` 或 `project_doc` evidence。`git_diff` 成功后产生 `project_change` evidence。后者保留 repo-relative path、bounded diff snippet 和 diff line range，不把整个 Tool Observation、Prompt 或模型推理暴露到 API。

多个 evidence 的去重 key 包含 evidence kind、path 和 line range。相同文件的代码上下文与变更 diff 是不同事实，不能因为 path 相同而互相覆盖。所有公开 evidence 都经过强类型校验并有 snippet 上限。

## 7. 为什么临时 repo 不需要 Vector DB

Git change evidence 的来源是仓库本身的 Git object database 和当前 working tree，不是持久知识检索。针对一次代码变更检查，额外建立 Vector DB 会增加索引污染、数据 provenance 和生命周期问题，却不能替代精确的 commit diff。

Knowledge RAG 仍然适合持久共享领域知识；Repository 默认按需读取。变更检查只在确实需要跨历史语义检索时考虑额外能力，当前 bounded Git tools 不引入 Project RAG、semantic search 或 AST/LSP。

## 8. Agent 完整调用链

模型只能看到 Registry 中的 `ToolSpec`：name、description、input schema 和 version。它不能看到 handler、repo root 或任意 subprocess 参数。Runtime 负责硬预算、duplicate guard 和执行顺序；Executor 负责 schema、权限、handler 和 output validation；handler 负责固定 Git argv 与文件边界；Runtime 再把成功 diff 转为 `project_change` evidence。最终 API 只序列化安全的 run result、trace 白名单和 evidence。

```text
Decision Provider
  -> ToolCall(action, tool_name, arguments)
  -> Runtime budget / duplicate guard
  -> ToolExecutor schema + permission boundary
  -> ChangedFilesHandler or GitDiffHandler
  -> ToolObservation
  -> Runtime project_change evidence
  -> final answer / safe API response
```

未知编程异常不会在 Git handler 内被伪装成某个 `GIT_*` 业务错误。经通用 Executor 执行时，既有 Executor 契约仍会把未分类 handler 异常转换为 `TOOL_EXECUTION_FAILED`；稳定的 Git 错误码只用于可预期的 repository、ref、path、diff 和 subprocess 边界失败。

## 9. 面试问题

### command injection 怎么防？

不让模型生成 command。工具使用固定 argv、固定 cwd 和固定子命令；ref、path 先做 allowlist 与边界校验，subprocess 不使用 shell。

### 为什么一次只读一个 diff 文件？

把输出规模、权限和证据归属限制在一个 path，避免模型一次请求整个仓库，也让每个变更证据都能映射回明确的 Tool call。

### Git evidence 如何进入 Agent？

`changed_files` Observation 让模型选择具体 path，`git_diff` Observation 经过 schema 验证后转成 `project_change` evidence。它作为不可信事实交给下一轮决策，不作为系统指令。

### 为什么暂不做 AST dependency graph？

当前需求是可审计的变更定位与有限 diff。AST/LSP dependency graph 会引入新的解析器、语言覆盖、缓存和 provenance 复杂度，应由独立需求和证据评测驱动，不能作为 Git change evidence 的隐式实现细节。
