# Hybrid 收敛版：28 道实际答案与来源

运行：hybrid-convergence-20261015-001；业务提交：12c6fe93ef078b7a1957f11664aef562da4ab21a。

以下内容来自真实运行。被 Gate 拒绝的候选与用户最终收到的答案明确分开。评分为 Codex 非盲开发者来源核对，尚非独立人工验收。

## t22_gs_01 — COMPLETE_CORRECT

列出 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 之间全部可见变更文件及状态。

终态：completed；task_coverage=complete；Provider=3 请求；tokens=17768；估算费用=$0.0054627。

E6 来自完整 commit_range changed_files；五项路径/状态及 rename 方向均与真实 Git 一致。

### 用户实际收到的答案

已成功检查范围 commit_range `6ba17bcad84c632d72ad62e1a3f8217a0aed05ad`..`d6b6c100d5e2e441957d834a29a73a8bc4ac1693`；完整清单共 5 项 （未截断、无敏感项省略）[E6]：

| 路径 | 状态 |
| --- | --- |
| `docs/usage.md` | added |
| `src/main.py` | modified |
| `src/old_parser.py` → `src/new_parser.py` | renamed |
| `src/retired_source.py` | deleted |
| `tests/test_main.py` | modified |

### 模型最终提交与 Finalization 结果

```json
{
  "accepted": true,
  "error_code": null,
  "protocol_valid": true,
  "rendered_answer": "已成功检查范围 commit_range `6ba17bcad84c632d72ad62e1a3f8217a0aed05ad`..`d6b6c100d5e2e441957d834a29a73a8bc4ac1693`；完整清单共 5 项 （未截断、无敏感项省略）[E6]：\n\n| 路径 | 状态 |\n| --- | --- |\n| `docs/usage.md` | added |\n| `src/main.py` | modified |\n| `src/old_parser.py` → `src/new_parser.py` | renamed |\n| `src/retired_source.py` | deleted |\n| `tests/test_main.py` | modified |",
  "requirement_satisfied": true,
  "selector": {
    "evidence_id": "E6",
    "operation": "list_all"
  },
  "source_valid": true
}
```

```json
[
  {
    "action": "changed_files_finalization",
    "evidence_id": "E6",
    "operation": "list_all"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_abf8a895386c4ef48443c629b3ddee1f",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "d0583e15700d2dbf4b09b22e79ca1560",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 8.4149,
    "snippet": "updated_at        更新时间\ndocument_type     markdown/pdf/html/faq/...\naccess_scope      权限范围\nversion           解析器、分块器和 Embedding 版本\n```\n\n只有文本没有元数据，后续几乎无法做可靠引用、过滤、删除和权限控制。\n\n---\n\n## 三、数据源发现与增量更新\n\n### 1. 幂等导入\n\n同一文档重复导入不应生成两套索引记录。\n\n```text\n读取文件\n  → 计算规范化内容哈希\n  → 哈希未变化：跳过\n  → 哈希变化：删除旧 Chunk 或写新版本\n  → 文件消失：标记删除并清理索引\n```\n\n可使用：\n\n```text\ndocument_id = hash(稳定业务主键或规范化路径)\nchunk_id = hash(document_id + heading_path + chunk内容 + chunker_version)\n```\n\n如果分块算法升级，`chunker_version` 必须变化，否则新旧索引容易混在一起。\n\n### 2. 全量与增量\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "8226133a5c4c69aa456dc791cced56d7",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 5.4942,
    "snippet": "已发起 tool_call\n工具执行状态和幂等键\nToken/时间/费用预算\n取消标记\n```\n\n服务重启后不能把“执行结果未知”的写工具直接再跑一次。应先查询工具端状态或转人工处理。\n\n---\n\n## 十二、安全边界\n\n### 1. Prompt Injection\n\n工具结果、网页、文档和数据库文本都可能包含恶意指令。它们只能作为数据，不能提升权限或修改系统策略。\n\n### 2. 最小权限\n\n- 每个工具只获得完成任务所需权限；\n- 读写工具分开；\n- 不向模型暴露后台管理工具；\n- 工具列表根据用户和场景动态裁剪；\n- 高风险操作需要应用层确认，而非模型自行确认。\n\n### 3. 网络与文件\n\n- URL 工具防 SSRF：限制协议、域名/IP、重定向和响应大小；\n- 文件工具校验规范化路径，限制在授权根目录；\n- SQL 工具使用参数化和只读账号，不让模型直接生成并执行任意 SQL；\n- 代码执行放入资源受限沙箱，默认无网络和敏感文件权限。\n\n---\n\n## 十三、观测指标\n\n```text\ntool_selection_accuracy       工具选对率\nargumen",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 3.6318,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 3.4238,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "b84c415c088640621990ed98a9243eb6",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 2.6117,
    "snippet": "# RAG 文档处理：从文件到可检索索引\n\n> 定位：RAG 的离线链路。目标不是“把 PDF 扔进向量库”，而是构建可追踪、可增量更新、可评测的数据管道。  \n> 本项目数据源：当前学习目录中的 Markdown 笔记。\n\n## 一、完整离线链路\n\n```text\n数据源发现\n  → 权限与格式校验\n  → 解析正文和结构\n  → 清洗与标准化\n  → 去重\n  → 分块\n  → 生成元数据\n  → Embedding\n  → 写入向量/关键词索引\n  → 质量检查\n  → 发布索引版本\n```\n\n每一步都应保存可定位的错误和统计信息。不要在一条循环里捕获所有异常后静默跳过。\n\n---\n\n## 二、统一数据模型\n\n文档和 Chunk 必须有稳定身份，才能支持更新、删除、引用和问题排查。\n\n```python\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True, slots=True)\nclass SourceDocument:\n    document_id: str\n    source_uri: str\n    t",
    "source_name": "rag_文档处理.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_abf8a895386c4ef48443c629b3ddee1f",
    "completeness": "complete",
    "evidence_id": "E6",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "列出 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 之间全部可见变更文件及状态。",
        "plan_id": "0937ea0c8ba4",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_gs_02 — NO_DELIVERY

只列出 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 中状态为 deleted 的文件。

终态：refused；task_coverage=unknown；Provider=2 请求；tokens=9214；估算费用=$0.0028272。

第一次 Decision 即提交 filter_status=deleted、E1，未调用 changed_files；E1 实为知识证据，Runtime 正确阻断。属于过早结束，不是材料已足够后的 Gate 误拒。

### 用户实际收到的答案

未交付。reason=INSUFFICIENT_EVIDENCE_TO_FINALIZE；failure=None。

### 模型最终提交与 Finalization 结果

```json
[
  {
    "action": "changed_files_finalization",
    "evidence_id": "E1",
    "operation": "filter_status",
    "status": "deleted"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "8226133a5c4c69aa456dc791cced56d7",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 6.5188,
    "snippet": "已发起 tool_call\n工具执行状态和幂等键\nToken/时间/费用预算\n取消标记\n```\n\n服务重启后不能把“执行结果未知”的写工具直接再跑一次。应先查询工具端状态或转人工处理。\n\n---\n\n## 十二、安全边界\n\n### 1. Prompt Injection\n\n工具结果、网页、文档和数据库文本都可能包含恶意指令。它们只能作为数据，不能提升权限或修改系统策略。\n\n### 2. 最小权限\n\n- 每个工具只获得完成任务所需权限；\n- 读写工具分开；\n- 不向模型暴露后台管理工具；\n- 工具列表根据用户和场景动态裁剪；\n- 高风险操作需要应用层确认，而非模型自行确认。\n\n### 3. 网络与文件\n\n- URL 工具防 SSRF：限制协议、域名/IP、重定向和响应大小；\n- 文件工具校验规范化路径，限制在授权根目录；\n- SQL 工具使用参数化和只读账号，不让模型直接生成并执行任意 SQL；\n- 代码执行放入资源受限沙箱，默认无网络和敏感文件权限。\n\n---\n\n## 十三、观测指标\n\n```text\ntool_selection_accuracy       工具选对率\nargumen",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 5.9347,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "0e835bac6586160740fa3f6349cdd2d2",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 4.5512,
    "snippet": "- 在提示中清晰分隔“系统指令”和“检索内容”；\n- 检索内容不得改变工具权限；\n- 所有工具参数仍由应用层校验；\n- 文档访问先做权限过滤；\n- HTML/Markdown 展示前做安全转义；\n- 对上传文件限制类型、大小、数量和解析时间。\n\n---\n\n## 十、离线质量检查\n\n每次入库后至少输出：\n\n```text\n发现文档数 / 成功 / 失败 / 跳过\nChunk 总数、长度分布、过短/过长占比\n空 Chunk 和重复 Chunk 数量\n解析失败类型分布\nEmbedding 调用成功率和耗时\n无标题、无来源、无权限字段的记录数\n```\n\n人工抽检：\n\n- 随机 20 个 Chunk；\n- 最长/最短各 10 个；\n- 包含代码、表格、中文路径的 Chunk；\n- 更新和删除后的记录；\n- 每个失败解析器的样本。\n\n---\n\n## 十一、当前项目的实现顺序\n\n### V0：一天内跑通\n\n- [ ] 扫描 Markdown；\n- [ ] 按标题切 Section；\n- [ ] 保存路径、标题和内容；\n- [ ] 对 5 个文件写测试。\n\n### V1：可用于检索\n\n- [ ] 超长",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 4.5479,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "34711ae87ebf675e0225f41dd6fce9ca",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 4.355,
    "snippet": "- 包含代码、表格、精确数字或版本的信息题。\n\n### 3. 数据集切分\n\n```text\n开发集：反复调分块、Top-K、Prompt\n测试集：阶段性最终比较，不用来持续调参\n线上回归集：由真实故障持续补充\n```\n\n如果一边看测试结果一边调整系统，测试集事实上已经变成开发集。\n\n### 4. 当前项目最小规模\n\n```text\n首版：30 题，用于快速建立链路\n稳定版：50～100 题，覆盖各模块和无答案样本\n每次线上/模拟面试发现失败：补 1 条回归样本\n```\n\n样本质量和覆盖面比盲目追求数量重要。\n\n---\n\n## 三、检索指标\n\n### 1. Recall@K\n\n前 K 个候选中是否包含任一标准相关证据：\n\n```text\nRecall@K = 被 Top-K 命中的可回答问题数 / 可回答问题总数\n```\n\n如果一个问题需要多个证据，还应计算 required facts 或多个证据的覆盖率，不能只命中其中一段就算完全成功。\n\n### 2. Precision@K\n\n```text\nPrecision@K = Top-K 中相关 Chunk 数 / K\n```\n\nRAG ",
    "source_name": "rag_高级RAG.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "只列出 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 中状态为 deleted 的文件。",
        "plan_id": "1d4bc1a6fd5a",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_gs_03 — COMPLETE_CORRECT

列出 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的重命名旧路径和新路径。

终态：completed；task_coverage=complete；Provider=3 请求；tokens=17440；估算费用=$0.0053688。

真实 changed_files 的 E6 和 100% rename 状态支持 old_parser.py → new_parser.py，方向正确。

### 用户实际收到的答案

已成功检查范围 commit_range `6ba17bcad84c632d72ad62e1a3f8217a0aed05ad`..`d6b6c100d5e2e441957d834a29a73a8bc4ac1693`；完整清单中的 renamed 状态项 共 1 项 [E6]：

| 路径 | 状态 |
| --- | --- |
| `src/old_parser.py` → `src/new_parser.py` | renamed |

### 模型最终提交与 Finalization 结果

```json
{
  "accepted": true,
  "error_code": null,
  "protocol_valid": true,
  "rendered_answer": "已成功检查范围 commit_range `6ba17bcad84c632d72ad62e1a3f8217a0aed05ad`..`d6b6c100d5e2e441957d834a29a73a8bc4ac1693`；完整清单中的 renamed 状态项 共 1 项 [E6]：\n\n| 路径 | 状态 |\n| --- | --- |\n| `src/old_parser.py` → `src/new_parser.py` | renamed |",
  "requirement_satisfied": true,
  "selector": {
    "evidence_id": "E6",
    "operation": "filter_status",
    "status": "renamed"
  },
  "source_valid": true
}
```

```json
[
  {
    "action": "changed_files_finalization",
    "evidence_id": "E6",
    "operation": "filter_status",
    "status": "renamed"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_de1430450a794069880e68d9cd18eea8",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "d0583e15700d2dbf4b09b22e79ca1560",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 12.9017,
    "snippet": "updated_at        更新时间\ndocument_type     markdown/pdf/html/faq/...\naccess_scope      权限范围\nversion           解析器、分块器和 Embedding 版本\n```\n\n只有文本没有元数据，后续几乎无法做可靠引用、过滤、删除和权限控制。\n\n---\n\n## 三、数据源发现与增量更新\n\n### 1. 幂等导入\n\n同一文档重复导入不应生成两套索引记录。\n\n```text\n读取文件\n  → 计算规范化内容哈希\n  → 哈希未变化：跳过\n  → 哈希变化：删除旧 Chunk 或写新版本\n  → 文件消失：标记删除并清理索引\n```\n\n可使用：\n\n```text\ndocument_id = hash(稳定业务主键或规范化路径)\nchunk_id = hash(document_id + heading_path + chunk内容 + chunker_version)\n```\n\n如果分块算法升级，`chunker_version` 必须变化，否则新旧索引容易混在一起。\n\n### 2. 全量与增量\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "b18b61962f18f305d9e39ea5f6a5e7e2",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 6.2707,
    "snippet": "Task018 isolated RAG fixture\n\n服务的标准重试窗口为 12 秒。该设置用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径。\n",
    "source_name": "task018_retry.md"
  },
  {
    "chunk_id": "0e835bac6586160740fa3f6349cdd2d2",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 5.6061,
    "snippet": "- 在提示中清晰分隔“系统指令”和“检索内容”；\n- 检索内容不得改变工具权限；\n- 所有工具参数仍由应用层校验；\n- 文档访问先做权限过滤；\n- HTML/Markdown 展示前做安全转义；\n- 对上传文件限制类型、大小、数量和解析时间。\n\n---\n\n## 十、离线质量检查\n\n每次入库后至少输出：\n\n```text\n发现文档数 / 成功 / 失败 / 跳过\nChunk 总数、长度分布、过短/过长占比\n空 Chunk 和重复 Chunk 数量\n解析失败类型分布\nEmbedding 调用成功率和耗时\n无标题、无来源、无权限字段的记录数\n```\n\n人工抽检：\n\n- 随机 20 个 Chunk；\n- 最长/最短各 10 个；\n- 包含代码、表格、中文路径的 Chunk；\n- 更新和删除后的记录；\n- 每个失败解析器的样本。\n\n---\n\n## 十一、当前项目的实现顺序\n\n### V0：一天内跑通\n\n- [ ] 扫描 Markdown；\n- [ ] 按标题切 Section；\n- [ ] 保存路径、标题和内容；\n- [ ] 对 5 个文件写测试。\n\n### V1：可用于检索\n\n- [ ] 超长",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "8226133a5c4c69aa456dc791cced56d7",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 5.1049,
    "snippet": "已发起 tool_call\n工具执行状态和幂等键\nToken/时间/费用预算\n取消标记\n```\n\n服务重启后不能把“执行结果未知”的写工具直接再跑一次。应先查询工具端状态或转人工处理。\n\n---\n\n## 十二、安全边界\n\n### 1. Prompt Injection\n\n工具结果、网页、文档和数据库文本都可能包含恶意指令。它们只能作为数据，不能提升权限或修改系统策略。\n\n### 2. 最小权限\n\n- 每个工具只获得完成任务所需权限；\n- 读写工具分开；\n- 不向模型暴露后台管理工具；\n- 工具列表根据用户和场景动态裁剪；\n- 高风险操作需要应用层确认，而非模型自行确认。\n\n### 3. 网络与文件\n\n- URL 工具防 SSRF：限制协议、域名/IP、重定向和响应大小；\n- 文件工具校验规范化路径，限制在授权根目录；\n- SQL 工具使用参数化和只读账号，不让模型直接生成并执行任意 SQL；\n- 代码执行放入资源受限沙箱，默认无网络和敏感文件权限。\n\n---\n\n## 十三、观测指标\n\n```text\ntool_selection_accuracy       工具选对率\nargumen",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 4.068,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_de1430450a794069880e68d9cd18eea8",
    "completeness": "complete",
    "evidence_id": "E6",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "列出 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的重命名旧路径和新路径。",
        "plan_id": "73fbd8a29249",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_gs_04 — COMPLETE_CORRECT

列出当前 working_tree 中全部未跟踪文件。

终态：completed；task_coverage=complete；Provider=3 请求；tokens=17169；估算费用=$0.0052317。

真实 working_tree 的 E6 仅有 notes/local_sample.md untracked，完整性和范围正确。

### 用户实际收到的答案

已成功检查范围 `working_tree`；完整清单中的 untracked 状态项 共 1 项 [E6]：

| 路径 | 状态 |
| --- | --- |
| `notes/local_sample.md` | untracked |

### 模型最终提交与 Finalization 结果

```json
{
  "accepted": true,
  "error_code": null,
  "protocol_valid": true,
  "rendered_answer": "已成功检查范围 `working_tree`；完整清单中的 untracked 状态项 共 1 项 [E6]：\n\n| 路径 | 状态 |\n| --- | --- |\n| `notes/local_sample.md` | untracked |",
  "requirement_satisfied": true,
  "selector": {
    "evidence_id": "E6",
    "operation": "filter_status",
    "status": "untracked"
  },
  "source_valid": true
}
```

```json
[
  {
    "action": "changed_files_finalization",
    "evidence_id": "E6",
    "operation": "filter_status",
    "status": "untracked"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "mode": "working_tree"
      },
      "call_id": "call_38cc3b3a9fc14971b2ab10528870e456",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "notes/local_sample.md",
          "status": "untracked"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 1,
      "total_count": 1,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "d0583e15700d2dbf4b09b22e79ca1560",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 6.279,
    "snippet": "updated_at        更新时间\ndocument_type     markdown/pdf/html/faq/...\naccess_scope      权限范围\nversion           解析器、分块器和 Embedding 版本\n```\n\n只有文本没有元数据，后续几乎无法做可靠引用、过滤、删除和权限控制。\n\n---\n\n## 三、数据源发现与增量更新\n\n### 1. 幂等导入\n\n同一文档重复导入不应生成两套索引记录。\n\n```text\n读取文件\n  → 计算规范化内容哈希\n  → 哈希未变化：跳过\n  → 哈希变化：删除旧 Chunk 或写新版本\n  → 文件消失：标记删除并清理索引\n```\n\n可使用：\n\n```text\ndocument_id = hash(稳定业务主键或规范化路径)\nchunk_id = hash(document_id + heading_path + chunk内容 + chunker_version)\n```\n\n如果分块算法升级，`chunker_version` 必须变化，否则新旧索引容易混在一起。\n\n### 2. 全量与增量\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 5.1372,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "0e835bac6586160740fa3f6349cdd2d2",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 4.9493,
    "snippet": "- 在提示中清晰分隔“系统指令”和“检索内容”；\n- 检索内容不得改变工具权限；\n- 所有工具参数仍由应用层校验；\n- 文档访问先做权限过滤；\n- HTML/Markdown 展示前做安全转义；\n- 对上传文件限制类型、大小、数量和解析时间。\n\n---\n\n## 十、离线质量检查\n\n每次入库后至少输出：\n\n```text\n发现文档数 / 成功 / 失败 / 跳过\nChunk 总数、长度分布、过短/过长占比\n空 Chunk 和重复 Chunk 数量\n解析失败类型分布\nEmbedding 调用成功率和耗时\n无标题、无来源、无权限字段的记录数\n```\n\n人工抽检：\n\n- 随机 20 个 Chunk；\n- 最长/最短各 10 个；\n- 包含代码、表格、中文路径的 Chunk；\n- 更新和删除后的记录；\n- 每个失败解析器的样本。\n\n---\n\n## 十一、当前项目的实现顺序\n\n### V0：一天内跑通\n\n- [ ] 扫描 Markdown；\n- [ ] 按标题切 Section；\n- [ ] 保存路径、标题和内容；\n- [ ] 对 5 个文件写测试。\n\n### V1：可用于检索\n\n- [ ] 超长",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 4.832,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "b84c415c088640621990ed98a9243eb6",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 4.5978,
    "snippet": "# RAG 文档处理：从文件到可检索索引\n\n> 定位：RAG 的离线链路。目标不是“把 PDF 扔进向量库”，而是构建可追踪、可增量更新、可评测的数据管道。  \n> 本项目数据源：当前学习目录中的 Markdown 笔记。\n\n## 一、完整离线链路\n\n```text\n数据源发现\n  → 权限与格式校验\n  → 解析正文和结构\n  → 清洗与标准化\n  → 去重\n  → 分块\n  → 生成元数据\n  → Embedding\n  → 写入向量/关键词索引\n  → 质量检查\n  → 发布索引版本\n```\n\n每一步都应保存可定位的错误和统计信息。不要在一条循环里捕获所有异常后静默跳过。\n\n---\n\n## 二、统一数据模型\n\n文档和 Chunk 必须有稳定身份，才能支持更新、删除、引用和问题排查。\n\n```python\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True, slots=True)\nclass SourceDocument:\n    document_id: str\n    source_uri: str\n    t",
    "source_name": "rag_文档处理.md"
  },
  {
    "arguments_json": "{\"mode\":\"working_tree\"}",
    "arguments_sha256": "2358b72699a3f21317cff36d676309bd68f7ffc54e64fd0092c33c16f93ce7d7",
    "call_id": "call_38cc3b3a9fc14971b2ab10528870e456",
    "completeness": "complete",
    "evidence_id": "E6",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8632df74262dbc8dabc845d1109acda203ca71621db2ee8a5030228de16dc234",
    "scope": "{\"mode\":\"working_tree\"}",
    "scope_paths": [
      "notes/local_sample.md"
    ],
    "status_entries": [
      {
        "path": "notes/local_sample.md",
        "status": "untracked"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "列出当前 working_tree 中全部未跟踪文件。",
        "plan_id": "36198c927f69",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ga_01 — WRONG_DELIVERY

结合 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的实际差异，选一项最重要的变更并说明证据范围。

终态：completed；task_coverage=partial；Provider=3 请求；tokens=17387；估算费用=$0.0058983。

仅有 E5 status_list，未取任何 diff；却称 rename 会牵动 main.py 调用方与测试、删除为清理。实际为纯 rename，main.py 无该依赖。后附限制未消除这些过宽主张。

### 用户实际收到的答案

在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad → d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更范围内，共 5 个文件发生变化：docs/usage.md（新增）、src/main.py（修改）、src/old_parser.py → src/new_parser.py（重命名）、src/retired_source.py（删除）、tests/test_main.py（修改）[E5]。

就目前可核实的证据而言，最值得关注的一项变更是 src/old_parser.py 到 src/new_parser.py 的重命名（renamed）[E5]。理由是：重命名通常意味着解析器实现被替换或迁移，会同时牵动调用方（如 src/main.py 的修改）与测试（tests/test_main.py 的修改），影响面比单纯新增文档或删除一个已退役文件更广；而 src/retired_source.py 的删除属于清理性变更，docs/usage.md 的新增属于文档补充，二者对运行时行为的直接影响相对有限。

证据范围说明：本结论仅基于本轮 changed_files 的 commit_range 状态清单 [E5]，它只提供 repo-relative 路径与状态（added/modified/renamed/deleted），不包含任何文件正文或 diff 内容。因此上述“最重要”的判断是基于变更类型与文件角色的推断，尚未通过读取 src/new_parser.py、src/main.py、tests/test_main.py 的实际 diff 来验证重命名的具体内容、是否伴随逻辑改动，以及调用方与测试的适配情况。此外，本轮检索到的知识库材料（RAG 分块、Function Calling 等）与本次代码变更无直接关系，未作为变更证据使用。

未完成事项与范围限制：未读取任何变更文件的 diff 正文，无法确认重命名是否伴随实现逻辑改动、调用方与测试的具体适配内容；未运行测试，不能声称变更已通过验证。若需确认，应进一步对 src/new_parser.py、src/main.py、tests/test_main.py 调用 git_diff 读取实际差异。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad → d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更范围内，共 5 个文件发生变化：docs/usage.md（新增）、src/main.py（修改）、src/old_parser.py → src/new_parser.py（重命名）、src/retired_source.py（删除）、tests/test_main.py（修改）[E5]。

就目前可核实的证据而言，最值得关注的一项变更是 src/old_parser.py 到 src/new_parser.py 的重命名（renamed）[E5]。理由是：重命名通常意味着解析器实现被替换或迁移，会同时牵动调用方（如 src/main.py 的修改）与测试（tests/test_main.py 的修改），影响面比单纯新增文档或删除一个已退役文件更广；而 src/retired_source.py 的删除属于清理性变更，docs/usage.md 的新增属于文档补充，二者对运行时行为的直接影响相对有限。

证据范围说明：本结论仅基于本轮 changed_files 的 commit_range 状态清单 [E5]，它只提供 repo-relative 路径与状态（added/modified/renamed/deleted），不包含任何文件正文或 diff 内容。因此上述“最重要”的判断是基于变更类型与文件角色的推断，尚未通过读取 src/new_parser.py、src/main.py、tests/test_main.py 的实际 diff 来验证重命名的具体内容、是否伴随逻辑改动，以及调用方与测试的适配情况。此外，本轮检索到的知识库材料（RAG 分块、Function Calling 等）与本次代码变更无直接关系，未作为变更证据使用。

```json
[
  {
    "action": "final_answer",
    "answer": "在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad → d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更范围内，共 5 个文件发生变化：docs/usage.md（新增）、src/main.py（修改）、src/old_parser.py → src/new_parser.py（重命名）、src/retired_source.py（删除）、tests/test_main.py（修改）[E5]。\n\n就目前可核实的证据而言，最值得关注的一项变更是 src/old_parser.py 到 src/new_parser.py 的重命名（renamed）[E5]。理由是：重命名通常意味着解析器实现被替换或迁移，会同时牵动调用方（如 src/main.py 的修改）与测试（tests/test_main.py 的修改），影响面比单纯新增文档或删除一个已退役文件更广；而 src/retired_source.py 的删除属于清理性变更，docs/usage.md 的新增属于文档补充，二者对运行时行为的直接影响相对有限。\n\n证据范围说明：本结论仅基于本轮 changed_files 的 commit_range 状态清单 [E5]，它只提供 repo-relative 路径与状态（added/modified/renamed/deleted），不包含任何文件正文或 diff 内容。因此上述“最重要”的判断是基于变更类型与文件角色的推断，尚未通过读取 src/new_parser.py、src/main.py、tests/test_main.py 的实际 diff 来验证重命名的具体内容、是否伴随逻辑改动，以及调用方与测试的适配情况。此外，本轮检索到的知识库材料（RAG 分块、Function Calling 等）与本次代码变更无直接关系，未作为变更证据使用。",
    "limitations": "未读取任何变更文件的 diff 正文，无法确认重命名是否伴随实现逻辑改动、调用方与测试的具体适配内容；未运行测试，不能声称变更已通过验证。若需确认，应进一步对 src/new_parser.py、src/main.py、tests/test_main.py 调用 git_diff 读取实际差异。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_653ae73b4cc6486099de2fb9f9fcc326",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "17ff0cbaaa632c5840fe5991edf44cc1",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 5.6394,
    "snippet": "| 技术手册、长章节 |\n\n### 3. 当前项目推荐\n\n```text\n第一层：按 Markdown 标题层级切 Section\n第二层：Section 超长时按段落/Token 递归切分\n索引：较小 Child Chunk\n生成：命中后可扩展到相邻 Chunk 或 Parent Section\n```\n\n初始实验可以从以下范围开始，但必须用评测调整：\n\n```text\nChunk 大小：约 300～600 tokens\nOverlap：约 10%～20%\nTop-K：先取 5～10，再 Rerank/裁剪\n```\n\n这些不是通用最佳值。代码、问答、法规、表格的最佳策略可能不同。\n\n### 4. Overlap 的代价\n\nOverlap 可以减轻边界信息丢失，但会：\n\n- 增加索引数量与 Embedding 成本；\n- 产生高度重复的检索结果；\n- 挤占生成上下文；\n- 让评测看似召回多个结果，实际都是同一段重复。\n\n应在检索后做同文档去重或多样性控制。\n\n---\n\n## 七、Embedding\n\n### 1. Embedding 是什么\n\nEmbedding 模型把文本映射到固定维",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 4.4005,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 1,
    "score": 5.6233,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "b18b61962f18f305d9e39ea5f6a5e7e2",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 5.278,
    "snippet": "Task018 isolated RAG fixture\n\n服务的标准重试窗口为 12 秒。该设置用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径。\n",
    "source_name": "task018_retry.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_653ae73b4cc6486099de2fb9f9fcc326",
    "completeness": "complete",
    "evidence_id": "E5",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "结合 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的实际差异，选一项最重要的变更并说明证据范围。",
        "plan_id": "26952202138f",
        "query_type": "causal",
        "reason_code": "CAUSAL_SYNTHESIS",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "两个提交之间的变更清单与差异内容",
            "id": "sq1",
            "query": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 之间有哪些实际变更",
            "required": true
          },
          {
            "evidence_target": "判断变更重要性的依据与影响范围证据",
            "id": "sq2",
            "query": "这些变更中哪一项最重要及其影响范围",
            "required": true
          },
          {
            "evidence_target": "支撑该变更结论的具体证据范围",
            "id": "sq3",
            "query": "该最重要变更的证据范围包括哪些文件和内容",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ga_02 — COMPLETE_CORRECT

说明 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的 src/main.py 改了什么，及其对 scale 结果的影响。

终态：completed；task_coverage=partial；Provider=4 请求；tokens=24852；估算费用=$0.0080541。

E5 实际 main.py diff：LIMIT 10→12、函数体不变；数值影响推导正确，未把静态推导称作实际执行。

### 用户实际收到的答案

src/main.py 在该 commit range 内的改动只有一处：模块级常量 LIMIT 从 10 改为 12（`-LIMIT = 10` / `+LIMIT = 12`），函数 `scale(value)` 的实现 `return value * LIMIT` 未变 [E5]。

对 scale 结果的影响：由于 scale 直接乘以 LIMIT，改动使同一输入 value 的输出从 `value * 10` 变为 `value * 12`，即结果整体放大 1.2 倍（相对增加 20%）。例如 value=5 时由 50 变为 60。这是基于 diff 中常量与函数体的直接推断 [E5]。

范围说明：以上仅覆盖 src/main.py 的 diff；同一 commit range 还改动了 docs/usage.md、src/old_parser.py→src/new_parser.py（重命名）、src/retired_source.py（删除）、tests/test_main.py [E4]，这些文件未读取正文，因此不排除它们对 scale 调用方或测试期望值有连带影响。此外未运行任何测试，无法确认实际运行结果。

未完成事项与范围限制：仅取得 src/main.py 的 diff 与变更文件清单；未读取其他变更文件正文，未执行测试，故对 scale 的端到端影响（调用方、测试断言）未验证。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

src/main.py 在该 commit range 内的改动只有一处：模块级常量 LIMIT 从 10 改为 12（`-LIMIT = 10` / `+LIMIT = 12`），函数 `scale(value)` 的实现 `return value * LIMIT` 未变 [E5]。

对 scale 结果的影响：由于 scale 直接乘以 LIMIT，改动使同一输入 value 的输出从 `value * 10` 变为 `value * 12`，即结果整体放大 1.2 倍（相对增加 20%）。例如 value=5 时由 50 变为 60。这是基于 diff 中常量与函数体的直接推断 [E5]。

范围说明：以上仅覆盖 src/main.py 的 diff；同一 commit range 还改动了 docs/usage.md、src/old_parser.py→src/new_parser.py（重命名）、src/retired_source.py（删除）、tests/test_main.py [E4]，这些文件未读取正文，因此不排除它们对 scale 调用方或测试期望值有连带影响。此外未运行任何测试，无法确认实际运行结果。

```json
[
  {
    "action": "final_answer",
    "answer": "src/main.py 在该 commit range 内的改动只有一处：模块级常量 LIMIT 从 10 改为 12（`-LIMIT = 10` / `+LIMIT = 12`），函数 `scale(value)` 的实现 `return value * LIMIT` 未变 [E5]。\n\n对 scale 结果的影响：由于 scale 直接乘以 LIMIT，改动使同一输入 value 的输出从 `value * 10` 变为 `value * 12`，即结果整体放大 1.2 倍（相对增加 20%）。例如 value=5 时由 50 变为 60。这是基于 diff 中常量与函数体的直接推断 [E5]。\n\n范围说明：以上仅覆盖 src/main.py 的 diff；同一 commit range 还改动了 docs/usage.md、src/old_parser.py→src/new_parser.py（重命名）、src/retired_source.py（删除）、tests/test_main.py [E4]，这些文件未读取正文，因此不排除它们对 scale 调用方或测试期望值有连带影响。此外未运行任何测试，无法确认实际运行结果。",
    "limitations": "仅取得 src/main.py 的 diff 与变更文件清单；未读取其他变更文件正文，未执行测试，故对 scale 的端到端影响（调用方、测试断言）未验证。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_238fbf50c8d9489c951cfa6165373cc1",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range",
        "path": "src/main.py"
      },
      "call_id": "call_485b2edf6a274ec9a4ec9e65b094369c",
      "tool_name": "git_diff"
    },
    "error_code": null,
    "result": {
      "diff": "diff --git a/src/main.py b/src/main.py\nindex 091eb21..16a5e1b 100644\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1,4 +1,4 @@\n-LIMIT = 10\n+LIMIT = 12\n \n def scale(value):\n     return value * LIMIT\n",
      "end_line": 4,
      "mode": "commit_range",
      "path": "src/main.py",
      "start_line": 1,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 7.715,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "13e50a50eeff857cc4e1bc1fb2217513",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 1,
    "score": 4.2989,
    "snippet": " NDCG\n\n当相关性存在多个等级时，NDCG 同时考虑相关程度和排名位置，适合评估 Rerank。\n\n### 5. 检索评测注意\n\n- 同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标；\n- 评测时固定索引版本、Embedding、Top-K 和随机性；\n- 记录按类别的指标，平均值可能掩盖代码题或精确术语题的失败；\n- Retrieval Recall 高不代表最终回答一定正确。\n\n---\n\n## 四、生成与端到端指标\n\n### 1. Faithfulness / Groundedness\n\n回答中的关键陈述是否得到所给证据支持。它不等于世界知识层面的事实正确：证据本身也可能错或过期。\n\n### 2. Answer Correctness\n\n回答是否覆盖参考答案的必要事实，是否包含错误结论。\n\n### 3. Answer Relevancy\n\n是否直接回答用户问题，避免虽然“都是真的”但答非所问。\n\n### 4. Citation 指标\n\n```text\nCitation validity：引用编号是否存在\nCitation correctness：引用内容是否支持对",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 2,
    "score": 4.6727,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_238fbf50c8d9489c951cfa6165373cc1",
    "completeness": "complete",
    "evidence_id": "E4",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\",\"path\":\"src/main.py\"}",
    "arguments_sha256": "f4cb78fbffd5f24280ec4ee02dcd44edb1a276174d747b24d57a502be47b2e21",
    "call_id": "call_485b2edf6a274ec9a4ec9e65b094369c",
    "completeness": "complete",
    "end_line": 4,
    "evidence_id": "E5",
    "granularity": "diff",
    "kind": "project_change",
    "path": "src/main.py",
    "requirement_eligible": true,
    "result_sha256": "058ebb0ebd8fecff3142bc4c2b6bce63ff4d9af9ec5a57f8f55a103f48e10cd1",
    "scope": "commit_range diff for src/main.py",
    "scope_paths": [
      "src/main.py"
    ],
    "start_line": 1,
    "tool_name": "git_diff",
    "tool_version": "git_diff_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "说明 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的 src/main.py 改了什么，及其对 scale 结果的影响。",
        "plan_id": "3b3f9584e618",
        "query_type": "causal",
        "reason_code": "CAUSAL_SYNTHESIS",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "两个提交之间 src/main.py 的具体代码变更",
            "id": "sq1",
            "query": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 之间 src/main.py 的改动内容",
            "required": true
          },
          {
            "evidence_target": "说明该改动与 scale 结果之间因果关系的证据",
            "id": "sq2",
            "query": "src/main.py 的改动如何影响 scale 结果",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ga_03 — COMPLETE_CORRECT

检查 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 新增的 docs/usage.md 和 src/main.py 的差异，说明能从材料确认什么。

终态：completed；task_coverage=partial；Provider=5 请求；tokens=37943；估算费用=$0.0120696。

E7 usage 新增正文与 E8 main.py diff 均取得；新增文档、常量变化及有限关联说明正确。

### 用户实际收到的答案

在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad → d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的 commit range 内，可以确认以下两点：

1. docs/usage.md 是新增文件（status=added），新增内容共 3 行：标题 `# Usage`、空行、以及一句 `Scale values with `scale`.` [E6][E7]。

2. src/main.py 是修改文件（status=modified），diff 只涉及第 1 行常量：`LIMIT = 10` 改为 `LIMIT = 12`；其下的 `def scale(value): return value * LIMIT` 在 diff 上下文中未变 [E6][E8]。

由此可推断的关联：文档中提到的 `scale` 与 src/main.py 中的 `scale` 函数同名，且该函数行为依赖 `LIMIT`，因此 LIMIT 从 10 改为 12 会改变 `scale` 的返回值（例如 scale(1) 由 10 变为 12）。但这是基于两处 diff 的推断，材料本身没有直接说明二者存在文档-代码引用关系。

范围限制：本次只读取了 docs/usage.md 与 src/main.py 两个文件的 diff；同一 commit range 内还存在 src/old_parser.py→src/new_parser.py 重命名、src/retired_source.py 删除、tests/test_main.py 修改等变更，未读取其内容，故不对这些文件作任何结论。以上均为静态 diff 证据，未运行代码或测试。

未完成事项与范围限制：仅覆盖用户指定的两个文件；同 range 内其他变更（重命名、删除、测试修改）未取证。未执行任何测试或运行验证，scale 行为变化属基于 diff 的推断而非实测。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad → d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的 commit range 内，可以确认以下两点：

1. docs/usage.md 是新增文件（status=added），新增内容共 3 行：标题 `# Usage`、空行、以及一句 `Scale values with `scale`.` [E6][E7]。

2. src/main.py 是修改文件（status=modified），diff 只涉及第 1 行常量：`LIMIT = 10` 改为 `LIMIT = 12`；其下的 `def scale(value): return value * LIMIT` 在 diff 上下文中未变 [E6][E8]。

由此可推断的关联：文档中提到的 `scale` 与 src/main.py 中的 `scale` 函数同名，且该函数行为依赖 `LIMIT`，因此 LIMIT 从 10 改为 12 会改变 `scale` 的返回值（例如 scale(1) 由 10 变为 12）。但这是基于两处 diff 的推断，材料本身没有直接说明二者存在文档-代码引用关系。

范围限制：本次只读取了 docs/usage.md 与 src/main.py 两个文件的 diff；同一 commit range 内还存在 src/old_parser.py→src/new_parser.py 重命名、src/retired_source.py 删除、tests/test_main.py 修改等变更，未读取其内容，故不对这些文件作任何结论。以上均为静态 diff 证据，未运行代码或测试。

```json
[
  {
    "action": "final_answer",
    "answer": "在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad → d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的 commit range 内，可以确认以下两点：\n\n1. docs/usage.md 是新增文件（status=added），新增内容共 3 行：标题 `# Usage`、空行、以及一句 `Scale values with `scale`.` [E6][E7]。\n\n2. src/main.py 是修改文件（status=modified），diff 只涉及第 1 行常量：`LIMIT = 10` 改为 `LIMIT = 12`；其下的 `def scale(value): return value * LIMIT` 在 diff 上下文中未变 [E6][E8]。\n\n由此可推断的关联：文档中提到的 `scale` 与 src/main.py 中的 `scale` 函数同名，且该函数行为依赖 `LIMIT`，因此 LIMIT 从 10 改为 12 会改变 `scale` 的返回值（例如 scale(1) 由 10 变为 12）。但这是基于两处 diff 的推断，材料本身没有直接说明二者存在文档-代码引用关系。\n\n范围限制：本次只读取了 docs/usage.md 与 src/main.py 两个文件的 diff；同一 commit range 内还存在 src/old_parser.py→src/new_parser.py 重命名、src/retired_source.py 删除、tests/test_main.py 修改等变更，未读取其内容，故不对这些文件作任何结论。以上均为静态 diff 证据，未运行代码或测试。",
    "limitations": "仅覆盖用户指定的两个文件；同 range 内其他变更（重命名、删除、测试修改）未取证。未执行任何测试或运行验证，scale 行为变化属基于 diff 的推断而非实测。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_006c3905545d4778b6be9c8faf3c8eda",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range",
        "path": "docs/usage.md"
      },
      "call_id": "call_567d77acd5e541569cc99bf201b3f715",
      "tool_name": "git_diff"
    },
    "error_code": null,
    "result": {
      "diff": "diff --git a/docs/usage.md b/docs/usage.md\nnew file mode 100644\nindex 0000000..20cf07a\n--- /dev/null\n+++ b/docs/usage.md\n@@ -0,0 +1,3 @@\n+# Usage\n+\n+Scale values with `scale`.\n",
      "end_line": 3,
      "mode": "commit_range",
      "path": "docs/usage.md",
      "start_line": 1,
      "truncated": false
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range",
        "path": "src/main.py"
      },
      "call_id": "call_9e098756b1974293b54842cb84cf1dde",
      "tool_name": "git_diff"
    },
    "error_code": null,
    "result": {
      "diff": "diff --git a/src/main.py b/src/main.py\nindex 091eb21..16a5e1b 100644\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1,4 +1,4 @@\n-LIMIT = 10\n+LIMIT = 12\n \n def scale(value):\n     return value * LIMIT\n",
      "end_line": 4,
      "mode": "commit_range",
      "path": "src/main.py",
      "start_line": 1,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "17ff0cbaaa632c5840fe5991edf44cc1",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 8.2051,
    "snippet": "| 技术手册、长章节 |\n\n### 3. 当前项目推荐\n\n```text\n第一层：按 Markdown 标题层级切 Section\n第二层：Section 超长时按段落/Token 递归切分\n索引：较小 Child Chunk\n生成：命中后可扩展到相邻 Chunk 或 Parent Section\n```\n\n初始实验可以从以下范围开始，但必须用评测调整：\n\n```text\nChunk 大小：约 300～600 tokens\nOverlap：约 10%～20%\nTop-K：先取 5～10，再 Rerank/裁剪\n```\n\n这些不是通用最佳值。代码、问答、法规、表格的最佳策略可能不同。\n\n### 4. Overlap 的代价\n\nOverlap 可以减轻边界信息丢失，但会：\n\n- 增加索引数量与 Embedding 成本；\n- 产生高度重复的检索结果；\n- 挤占生成上下文；\n- 让评测看似召回多个结果，实际都是同一段重复。\n\n应在检索后做同文档去重或多样性控制。\n\n---\n\n## 七、Embedding\n\n### 1. Embedding 是什么\n\nEmbedding 模型把文本映射到固定维",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 8.0557,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "a11add31e154a2a110a64f491fab403d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 7.014,
    "snippet": "BM25 能改善精确术语问题的召回\n- 基线版本：commit / index / model / prompt\n- 唯一变量：retrieval strategy\n- 数据集：rag-eval-v1\n- 指标：Recall@5、MRR、P95\n- 结果：\n- 失败样本：\n- 结论：保留 / 回滚 / 继续实验\n```\n\n### 3. 回归门槛\n\n发布前可设置：\n\n```text\n核心类别 Recall@5 不下降\n整体正确率不低于基线\n权限测试 100% 通过\nP95 不超过预算\n无答案误答率不超过阈值\n```\n\n阈值应根据业务风险和当前基线确定，不照抄他人数字。\n\n---\n\n## 八、什么时候使用高级 RAG\n\n### 1. Parent-Child / Small-to-Big\n\n适合：小块更容易精确命中，但回答需要完整章节上下文。  \n代价：索引和父子映射更复杂，返回父块可能引入噪声。\n\n### 2. Contextual Retrieval\n\n为 Chunk 增加文档级背景，例如标题和简短上下文。  \n适合：原 Chunk 脱离全文后指代不清。  \n风险：生成的背景可能错误；",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "23e9a62968d95e6e7e3d9d45fa7356a5",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 6.7547,
    "snippet": "对无法幂等的高风险操作要求明确确认，并禁止自动重试。\n\n模型生成的自然语言参数不能直接充当可靠幂等键。\n\n---\n\n## 九、多工具调用\n\n### 1. 并行条件\n\n只有互不依赖、无冲突且资源允许的只读调用才适合并行：\n\n```text\n可以并行：分别检索 Redis 和 MySQL 笔记\n不能并行：先创建订单，再用订单 ID 支付\n谨慎并行：两个工具同时修改同一学习记录\n```\n\n### 2. 结果顺序\n\n每个结果必须带原始 `call_id`，不能依赖异步完成顺序与请求顺序相同。\n\n### 3. 部分失败\n\n```text\n3 个工具：2 成功，1 超时\n```\n\n应用应把每个调用的状态分别回传，允许模型使用已有结果或说明缺失，而不是把整个批次伪装成成功。\n\n---\n\n## 十、流式输出\n\n工具调用与普通文本可能在流中分片到达。应用需要：\n\n- 按 call ID 累积工具名和参数片段；\n- 等结构完整后再解析执行；\n- 执行工具前不要把半截 JSON 当合法参数；\n- 客户端断开时取消模型与工具调用；\n- 不把模型内部工具 JSON 原样展示成最终答案；\n- 记录首 Token、",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "34711ae87ebf675e0225f41dd6fce9ca",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 6.164,
    "snippet": "- 包含代码、表格、精确数字或版本的信息题。\n\n### 3. 数据集切分\n\n```text\n开发集：反复调分块、Top-K、Prompt\n测试集：阶段性最终比较，不用来持续调参\n线上回归集：由真实故障持续补充\n```\n\n如果一边看测试结果一边调整系统，测试集事实上已经变成开发集。\n\n### 4. 当前项目最小规模\n\n```text\n首版：30 题，用于快速建立链路\n稳定版：50～100 题，覆盖各模块和无答案样本\n每次线上/模拟面试发现失败：补 1 条回归样本\n```\n\n样本质量和覆盖面比盲目追求数量重要。\n\n---\n\n## 三、检索指标\n\n### 1. Recall@K\n\n前 K 个候选中是否包含任一标准相关证据：\n\n```text\nRecall@K = 被 Top-K 命中的可回答问题数 / 可回答问题总数\n```\n\n如果一个问题需要多个证据，还应计算 required facts 或多个证据的覆盖率，不能只命中其中一段就算完全成功。\n\n### 2. Precision@K\n\n```text\nPrecision@K = Top-K 中相关 Chunk 数 / K\n```\n\nRAG ",
    "source_name": "rag_高级RAG.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_006c3905545d4778b6be9c8faf3c8eda",
    "completeness": "complete",
    "evidence_id": "E6",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\",\"path\":\"docs/usage.md\"}",
    "arguments_sha256": "3cf66cebcc6e98c736c6d27e95497e393887ee033d0cc6dbe82b352668c165b1",
    "call_id": "call_567d77acd5e541569cc99bf201b3f715",
    "completeness": "complete",
    "end_line": 3,
    "evidence_id": "E7",
    "granularity": "diff",
    "kind": "project_change",
    "path": "docs/usage.md",
    "requirement_eligible": true,
    "result_sha256": "8cbfbd385421bf9131c1076307541fd639c52d82e8cb521037dc990be47748ab",
    "scope": "commit_range diff for docs/usage.md",
    "scope_paths": [
      "docs/usage.md"
    ],
    "start_line": 1,
    "tool_name": "git_diff",
    "tool_version": "git_diff_v1"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\",\"path\":\"src/main.py\"}",
    "arguments_sha256": "f4cb78fbffd5f24280ec4ee02dcd44edb1a276174d747b24d57a502be47b2e21",
    "call_id": "call_9e098756b1974293b54842cb84cf1dde",
    "completeness": "complete",
    "end_line": 4,
    "evidence_id": "E8",
    "granularity": "diff",
    "kind": "project_change",
    "path": "src/main.py",
    "requirement_eligible": true,
    "result_sha256": "058ebb0ebd8fecff3142bc4c2b6bce63ff4d9af9ec5a57f8f55a103f48e10cd1",
    "scope": "commit_range diff for src/main.py",
    "scope_paths": [
      "src/main.py"
    ],
    "start_line": 1,
    "tool_name": "git_diff",
    "tool_version": "git_diff_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "检查 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 新增的 docs/usage.md 和 src/main.py 的差异，说明能从材料确认什么。",
        "plan_id": "0f2e348ac541",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ga_04 — NO_DELIVERY

完整分析 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 所有变更文件及其影响；如果材料覆盖不全请明确说明。

终态：refused；task_coverage=unknown；Provider=3 请求；tokens=17138；估算费用=$0.0054240。

调用 changed_files 后误选 list_all Typed 终态；本题要求分析全部影响，Typed 正确以 TASK_REQUIRES_NON_STATUS_ANSWER 阻断。

### 用户实际收到的答案

未交付。reason=INSUFFICIENT_EVIDENCE_TO_FINALIZE；failure=None。

### 模型最终提交与 Finalization 结果

```json
{
  "accepted": false,
  "error_code": "TASK_REQUIRES_NON_STATUS_ANSWER",
  "protocol_valid": false,
  "rendered_answer": null,
  "requirement_satisfied": null,
  "selector": {
    "evidence_id": "E5",
    "operation": "list_all"
  },
  "source_valid": false
}
```

```json
[
  {
    "action": "changed_files_finalization",
    "evidence_id": "E5",
    "operation": "list_all"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_f8c0b04d1dae4b48afc139c51865354e",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 2,
    "score": 7.0379,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 1,
    "score": 9.6977,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 1,
    "score": 9.5546,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "43c05ab81db2d80e46d539d326398b96",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 3,
    "score": 3.894,
    "snippet": "# 单元测试\n\n---\n\n## 一、JUnit 5\n\n### 核心注解\n```java\n@Test           // 标记测试方法\n@BeforeEach     // 每个测试方法前执行\n@AfterEach      // 每个测试方法后执行\n@BeforeAll      // 所有测试前执行一次（静态方法）\n@AfterAll       // 所有测试后执行一次（静态方法）\n@DisplayName    // 测试方法显示名称\n@ParameterizedTest  // 参数化测试\n```\n\n### 断言\n```java\nassertEquals(expected, actual);\nassertNotNull(obj);\nassertThrows(Exception.class, () -> { ... });\nassertTimeout(Duration.ofSeconds(1), () -> { ... });\n```\n\n---\n\n## 二、Mockito（Mock 依赖）\n\n### 为什么需要 Mock？\n```\nServiceA 依赖 ServiceB ",
    "source_name": "unit_单元测试.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_f8c0b04d1dae4b48afc139c51865354e",
    "completeness": "complete",
    "evidence_id": "E5",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "完整分析 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 所有变更文件及其影响；如果材料覆盖不全请明确说明。",
        "plan_id": "0082ea491161",
        "query_type": "multi_entity",
        "reason_code": "MULTI_ENTITY_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "两个提交之间完整变更文件列表及变更类型",
            "id": "sq1",
            "query": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 之间有哪些变更文件？",
            "required": true
          },
          {
            "evidence_target": "每个变更文件的具体改动内容与涉及模块",
            "id": "sq2",
            "query": "这些变更文件各自改动了什么内容？",
            "required": true
          },
          {
            "evidence_target": "变更带来的功能、接口或行为影响证据",
            "id": "sq3",
            "query": "这些变更对项目功能、接口或行为有什么影响？",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_src_01 — COMPLETE_CORRECT

只定位 src/main.py 中 scale 的定义文件和行号，不需要解释实现。

终态：completed；task_coverage=partial；Provider=3 请求；tokens=17706；估算费用=$0.0054243。

E6 实际 code_search 命中 src/main.py:3；只交付定义文件和行号，满足原问。Runtime 的 partial 是保守标记，不代表本题实际未完成。

### 用户实际收到的答案

src/main.py 第 3 行：`def scale(value):` [E6]

未完成事项与范围限制：仅定位到定义位置，未读取实现正文，也未验证调用关系。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

src/main.py 第 3 行：`def scale(value):` [E6]

```json
[
  {
    "action": "final_answer",
    "answer": "src/main.py 第 3 行：`def scale(value):` [E6]",
    "limitations": "仅定位到定义位置，未读取实现正文，也未验证调用关系。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "artifact_kind": "project_code",
        "query": "scale"
      },
      "call_id": "call_bcf487d80051410d98d7d44fa0ee042d",
      "tool_name": "code_search"
    },
    "error_code": null,
    "result": {
      "matches": [
        {
          "line": 3,
          "path": "src/main.py",
          "text": "def scale(value):"
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "6349a29de306ad2e230df093e3931677",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 9.432,
    "snippet": "- 原始行号或字符偏移。\n\n不要直接用正则完整解析 Markdown。MVP 可以用标题正则分段，但进入稳定版本后应使用语法解析器，防止把代码块中的 `#` 误判为标题。\n\n### 2. PDF\n\nPDF 是版面描述格式，不是天然的阅读顺序。常见问题：\n\n```text\n双栏顺序错乱\n页眉页脚混入正文\n断字和连字符\n扫描件没有文本层\n表格被拆散\n公式和图片信息丢失\n```\n\n需要区分：\n\n- 原生文本 PDF：布局解析；\n- 扫描 PDF：OCR；\n- 表格/图表：单独解析，必要时保留图片和位置引用。\n\n### 3. HTML / 网页\n\n- 去除导航、广告、脚本、样式和重复页脚；\n- 保留标题、列表、表格和链接；\n- 保存抓取时间和规范 URL；\n- 遵守访问权限和站点规则，不采集未授权数据。\n\n### 4. 表格和代码\n\n表格按普通段落切开后容易丢失表头语义。可将每行转为带表头的文本：\n\n```text\n类型=String；底层=SDS；场景=缓存、计数器\n```\n\n代码块应连同语言、上级标题和必要解释一起保存。不要在函数中间按固定字符数切开。\n\n---\n\n## 五、清洗与标准化\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "8226133a5c4c69aa456dc791cced56d7",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 8.0055,
    "snippet": "已发起 tool_call\n工具执行状态和幂等键\nToken/时间/费用预算\n取消标记\n```\n\n服务重启后不能把“执行结果未知”的写工具直接再跑一次。应先查询工具端状态或转人工处理。\n\n---\n\n## 十二、安全边界\n\n### 1. Prompt Injection\n\n工具结果、网页、文档和数据库文本都可能包含恶意指令。它们只能作为数据，不能提升权限或修改系统策略。\n\n### 2. 最小权限\n\n- 每个工具只获得完成任务所需权限；\n- 读写工具分开；\n- 不向模型暴露后台管理工具；\n- 工具列表根据用户和场景动态裁剪；\n- 高风险操作需要应用层确认，而非模型自行确认。\n\n### 3. 网络与文件\n\n- URL 工具防 SSRF：限制协议、域名/IP、重定向和响应大小；\n- 文件工具校验规范化路径，限制在授权根目录；\n- SQL 工具使用参数化和只读账号，不让模型直接生成并执行任意 SQL；\n- 代码执行放入资源受限沙箱，默认无网络和敏感文件权限。\n\n---\n\n## 十三、观测指标\n\n```text\ntool_selection_accuracy       工具选对率\nargumen",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 7.5544,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "0e835bac6586160740fa3f6349cdd2d2",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 7.0631,
    "snippet": "- 在提示中清晰分隔“系统指令”和“检索内容”；\n- 检索内容不得改变工具权限；\n- 所有工具参数仍由应用层校验；\n- 文档访问先做权限过滤；\n- HTML/Markdown 展示前做安全转义；\n- 对上传文件限制类型、大小、数量和解析时间。\n\n---\n\n## 十、离线质量检查\n\n每次入库后至少输出：\n\n```text\n发现文档数 / 成功 / 失败 / 跳过\nChunk 总数、长度分布、过短/过长占比\n空 Chunk 和重复 Chunk 数量\n解析失败类型分布\nEmbedding 调用成功率和耗时\n无标题、无来源、无权限字段的记录数\n```\n\n人工抽检：\n\n- 随机 20 个 Chunk；\n- 最长/最短各 10 个；\n- 包含代码、表格、中文路径的 Chunk；\n- 更新和删除后的记录；\n- 每个失败解析器的样本。\n\n---\n\n## 十一、当前项目的实现顺序\n\n### V0：一天内跑通\n\n- [ ] 扫描 Markdown；\n- [ ] 按标题切 Section；\n- [ ] 保存路径、标题和内容；\n- [ ] 对 5 个文件写测试。\n\n### V1：可用于检索\n\n- [ ] 超长",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "54d5fd53d60f6d2b5912a24ec810336c",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 6.7122,
    "snippet": "- 删除完全重复内容；\n- 对近重复内容做标记，不要仅凭相似度自动删除业务上可能不同的版本。\n\n不要做的事：\n\n- 为“干净”而删除所有标点和大小写；\n- 把标题、列表和代码全部压成一行；\n- 用生成模型重写原文后把重写结果当唯一索引内容；\n- 在未保留原始文档的情况下做不可逆清洗。\n\n---\n\n## 六、分块策略\n\n### 1. 分块的目标\n\n好的 Chunk 应同时满足：\n\n```text\n语义相对完整\n长度适合 Embedding 模型\n检索命中后可独立理解\n引用能回到原文\n上下文总量不会挤爆生成模型窗口\n```\n\nChunk 越小，定位可能更准但上下文不足；越大，语义更完整但检索信号被稀释、成本增加。\n\n### 2. 常见方法\n\n| 方法 | 优点 | 缺点 | 适用 |\n|---|---|---|---|\n| 固定 Token 分块 | 简单、稳定 | 可能切断语义、代码和表格 | 快速基线 |\n| 递归字符分块 | 优先段落/句子边界 | 仍不理解文档结构 | 通用文本 |\n| 标题结构分块 | 可解释、引用友好 | 单节可能过长或过短 | Markdown、技术文档 |\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "arguments_json": "{\"artifact_kind\":\"project_code\",\"query\":\"scale\"}",
    "arguments_sha256": "05d9d7795f075054ed26f2e9582bed9f0aec34e48c2b7f3f31f4b6f1725fe9b6",
    "call_id": "call_bcf487d80051410d98d7d44fa0ee042d",
    "completeness": "complete",
    "end_line": 3,
    "evidence_id": "E6",
    "granularity": "locator",
    "kind": "project_code",
    "path": "src/main.py",
    "requirement_eligible": false,
    "result_sha256": "67d60f0d1487737becc4dbbc734fd1f3870ba836101308cc0037ffb88184c11b",
    "scope": "literal search hit at src/main.py:3",
    "scope_paths": [
      "src/main.py"
    ],
    "start_line": 3,
    "tool_name": "code_search",
    "tool_version": "code_search_v7"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "只定位 src/main.py 中 scale 的定义文件和行号，不需要解释实现。",
        "plan_id": "4af39169d08a",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_src_02 — COMPLETE_CORRECT

解释 src/main.py 中 scale 函数如何计算；把它直接使用的同文件常量值也查清。

终态：completed；task_coverage=partial；Provider=4 请求；tokens=26132；估算费用=$0.0081042。

E6 完整 scale 定义，E7 实际 LIMIT=12 声明；函数乘法与常量均解释正确。

### 用户实际收到的答案

`src/main.py` 中的 `scale` 函数定义在第 3–4 行：它接收一个参数 `value`，返回 `value * LIMIT`，即把输入值乘以同文件常量 `LIMIT` [E6]。该常量在同文件第 1 行定义为 `LIMIT = 12` [E7]，因此 `scale(value)` 的实际计算就是把 `value` 乘以 12。

说明：以上结论来自对 `src/main.py` 的实际读取；未执行代码或测试，因此不声称运行结果已验证。

未完成事项与范围限制：仅读取了 src/main.py 中 scale 函数与 LIMIT 常量所在行；未运行代码或测试，未核查该文件其他内容。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

`src/main.py` 中的 `scale` 函数定义在第 3–4 行：它接收一个参数 `value`，返回 `value * LIMIT`，即把输入值乘以同文件常量 `LIMIT` [E6]。该常量在同文件第 1 行定义为 `LIMIT = 12` [E7]，因此 `scale(value)` 的实际计算就是把 `value` 乘以 12。

说明：以上结论来自对 `src/main.py` 的实际读取；未执行代码或测试，因此不声称运行结果已验证。

```json
[
  {
    "action": "final_answer",
    "answer": "`src/main.py` 中的 `scale` 函数定义在第 3–4 行：它接收一个参数 `value`，返回 `value * LIMIT`，即把输入值乘以同文件常量 `LIMIT` [E6]。该常量在同文件第 1 行定义为 `LIMIT = 12` [E7]，因此 `scale(value)` 的实际计算就是把 `value` 乘以 12。\n\n说明：以上结论来自对 `src/main.py` 的实际读取；未执行代码或测试，因此不声称运行结果已验证。",
    "limitations": "仅读取了 src/main.py 中 scale 函数与 LIMIT 常量所在行；未运行代码或测试，未核查该文件其他内容。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "src/main.py",
        "target": {
          "kind": "symbols",
          "names": [
            "scale"
          ]
        }
      },
      "call_id": "call_64e886e8fefe45ebb96b1f1e99b765d2",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/main.py",
      "regions": [
        {
          "end_line": 4,
          "lines": [
            {
              "line": 3,
              "text": "def scale(value):"
            },
            {
              "line": 4,
              "text": "    return value * LIMIT"
            }
          ],
          "mode": "definition",
          "start_line": 3
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 4,
            "kind": "function",
            "name": "scale",
            "start_line": 3
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "scale",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "path": "src/main.py",
        "target": {
          "kind": "matching",
          "query": "LIMIT"
        }
      },
      "call_id": "call_b7d2eea446594a8fb26039fd43f81705",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/main.py",
      "regions": [
        {
          "end_line": 1,
          "lines": [
            {
              "line": 1,
              "text": "LIMIT = 12"
            }
          ],
          "mode": "definition",
          "start_line": 1
        },
        {
          "end_line": 4,
          "lines": [
            {
              "line": 3,
              "text": "def scale(value):"
            },
            {
              "line": 4,
              "text": "    return value * LIMIT"
            }
          ],
          "mode": "definition",
          "start_line": 3
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 1,
            "kind": "assignment",
            "name": "LIMIT",
            "start_line": 1
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "LIMIT",
          "status": "read",
          "truncation_reasons": []
        },
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 4,
            "kind": "function",
            "name": "scale",
            "start_line": 3
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 1,
          "requested": "scale",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 11.8568,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "6349a29de306ad2e230df093e3931677",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 10.0008,
    "snippet": "- 原始行号或字符偏移。\n\n不要直接用正则完整解析 Markdown。MVP 可以用标题正则分段，但进入稳定版本后应使用语法解析器，防止把代码块中的 `#` 误判为标题。\n\n### 2. PDF\n\nPDF 是版面描述格式，不是天然的阅读顺序。常见问题：\n\n```text\n双栏顺序错乱\n页眉页脚混入正文\n断字和连字符\n扫描件没有文本层\n表格被拆散\n公式和图片信息丢失\n```\n\n需要区分：\n\n- 原生文本 PDF：布局解析；\n- 扫描 PDF：OCR；\n- 表格/图表：单独解析，必要时保留图片和位置引用。\n\n### 3. HTML / 网页\n\n- 去除导航、广告、脚本、样式和重复页脚；\n- 保留标题、列表、表格和链接；\n- 保存抓取时间和规范 URL；\n- 遵守访问权限和站点规则，不采集未授权数据。\n\n### 4. 表格和代码\n\n表格按普通段落切开后容易丢失表头语义。可将每行转为带表头的文本：\n\n```text\n类型=String；底层=SDS；场景=缓存、计数器\n```\n\n代码块应连同语言、上级标题和必要解释一起保存。不要在函数中间按固定字符数切开。\n\n---\n\n## 五、清洗与标准化\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 9.988,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "52c36a6aa220c24431e73c631219356c",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 9.8336,
    "snippet": "# RAG 评测、故障分析与高级策略\n\n> 核心观点：高级 RAG 的起点不是 GraphRAG 或复杂 Agent，而是可重复的评测集和故障分类。没有基线与对照实验，增加模块只会让系统更难解释。\n\n## 一、先拆开评测对象\n\nRAG 至少包含三个可独立失败的部分：\n\n```text\n数据/索引：正确证据是否被解析和入库？\n检索：正确证据是否进入候选和最终上下文？\n生成：模型是否忠实利用证据并正确回答？\n```\n\n如果最终回答错误，不能直接归因于“模型不行”。先判断：\n\n1. 标准证据在索引里吗？\n2. Top-K 召回了吗？\n3. Rerank 是否把它排掉？\n4. 最终 Prompt 是否包含它？\n5. 模型是否忽略、误读或错误综合？\n6. 引用是否正确？\n\n---\n\n## 二、构建评测集\n\n### 1. 每条样本至少包含\n\n```json\n{\n  \"question\": \"Redis AOF 重写会阻塞主进程吗？\",\n  \"reference_answer\": \"...\",\n  \"relevant_chunk_ids\": [\"chunk_a\", \"chunk_b\"],\n  \"an",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "6d8755088604b17b9e7eab6f95da0331",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 9.4482,
    "snippet": "RAG\n\n根据问题难度选择：不检索、单次检索、多跳检索。  \n需要可靠分类器或路由规则，否则“自适应”只是不可控分支。\n\n### 5. GraphRAG\n\n适合：\n\n- 问题需要跨多个实体和关系做多跳推理；\n- 需要全局主题、社区和关系摘要；\n- 数据具有稳定实体和边。\n\n不适合：\n\n- 几十篇技术笔记的普通问答；\n- 主要问题是关键词/语义召回；\n- 没有可靠实体消歧和关系抽取；\n- 团队还没有基础评测。\n\n当前学习 Agent 不把 GraphRAG 作为首版目标。\n\n---\n\n## 九、多模态和表格 RAG\n\n### 表格\n\n- 简单表格可转为带表头的行文本；\n- 聚合、过滤和计算型问题更适合结构化查询工具，而不是纯向量检索；\n- 回答应引用单元格、行或表名。\n\n### 图片/图表\n\n- 保存图片与原文位置；\n- 使用 OCR、图像描述或多模态 Embedding；\n- 关键数值应尽量从结构化数据读取，避免只靠视觉描述猜测。\n\n### 代码\n\n- 保留仓库、文件、符号、语言和行范围；\n- 按函数/类和语法结构切分通常优于固定字符；\n- 代码问题可结合符号搜索、调用图和测试工具。\n",
    "source_name": "rag_高级RAG.md"
  },
  {
    "end_line": 4,
    "evidence_id": "E6",
    "kind": "project_code",
    "path": "src/main.py",
    "snippet": "def scale(value):\n    return value * LIMIT",
    "start_line": 3
  },
  {
    "end_line": 1,
    "evidence_id": "E7",
    "kind": "project_code",
    "path": "src/main.py",
    "snippet": "LIMIT = 12",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "解释 src/main.py 中 scale 函数如何计算；把它直接使用的同文件常量值也查清。",
        "plan_id": "8461c511df08",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_src_03 — COMPLETE_CORRECT

解释 src/new_parser.py 中 parse(data) 对输入字符串做了什么处理。

终态：completed；task_coverage=unknown；Provider=4 请求；tokens=25836；估算费用=$0.0079929。

E7 完整 parse 定义，strip 后 lower 的步骤准确，未宣称执行成功。

### 用户实际收到的答案

`src/new_parser.py` 中的 `parse(data)` 是一个两行的简单函数：它接收 `data`，先调用 `data.strip()` 去除首尾空白字符，再调用 `.lower()` 将结果转为小写，最后返回处理后的字符串 [E7]。也就是说，对输入字符串的处理是「去首尾空白 + 转小写」，不涉及其他解析、校验或类型转换逻辑。

说明：该结论来自对 `src/new_parser.py` 第 1–2 行函数定义的读取，函数体完整（content_complete=true，未截断）[E7]；未运行任何测试或执行代码。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

`src/new_parser.py` 中的 `parse(data)` 是一个两行的简单函数：它接收 `data`，先调用 `data.strip()` 去除首尾空白字符，再调用 `.lower()` 将结果转为小写，最后返回处理后的字符串 [E7]。也就是说，对输入字符串的处理是「去首尾空白 + 转小写」，不涉及其他解析、校验或类型转换逻辑。

说明：该结论来自对 `src/new_parser.py` 第 1–2 行函数定义的读取，函数体完整（content_complete=true，未截断）[E7]；未运行任何测试或执行代码。

```json
[
  {
    "action": "final_answer",
    "answer": "`src/new_parser.py` 中的 `parse(data)` 是一个两行的简单函数：它接收 `data`，先调用 `data.strip()` 去除首尾空白字符，再调用 `.lower()` 将结果转为小写，最后返回处理后的字符串 [E7]。也就是说，对输入字符串的处理是「去首尾空白 + 转小写」，不涉及其他解析、校验或类型转换逻辑。\n\n说明：该结论来自对 `src/new_parser.py` 第 1–2 行函数定义的读取，函数体完整（content_complete=true，未截断）[E7]；未运行任何测试或执行代码。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "artifact_kind": "project_code",
        "query": "def parse"
      },
      "call_id": "call_a852e12b0b184a709669a82544aad14d",
      "tool_name": "code_search"
    },
    "error_code": null,
    "result": {
      "matches": [
        {
          "line": 1,
          "path": "src/new_parser.py",
          "text": "def parse(data):"
        }
      ]
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "path": "src/new_parser.py",
        "target": {
          "kind": "definition",
          "line": 1
        }
      },
      "call_id": "call_51bb0594ed164841ae16102f09f3b0cc",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/new_parser.py",
      "regions": [
        {
          "end_line": 2,
          "lines": [
            {
              "line": 1,
              "text": "def parse(data):"
            },
            {
              "line": 2,
              "text": "    return data.strip().lower()"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 2,
            "kind": "function",
            "name": "parse",
            "start_line": 1
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "definition",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 12.5021,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 11.9992,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "17ff0cbaaa632c5840fe5991edf44cc1",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 11.3123,
    "snippet": "| 技术手册、长章节 |\n\n### 3. 当前项目推荐\n\n```text\n第一层：按 Markdown 标题层级切 Section\n第二层：Section 超长时按段落/Token 递归切分\n索引：较小 Child Chunk\n生成：命中后可扩展到相邻 Chunk 或 Parent Section\n```\n\n初始实验可以从以下范围开始，但必须用评测调整：\n\n```text\nChunk 大小：约 300～600 tokens\nOverlap：约 10%～20%\nTop-K：先取 5～10，再 Rerank/裁剪\n```\n\n这些不是通用最佳值。代码、问答、法规、表格的最佳策略可能不同。\n\n### 4. Overlap 的代价\n\nOverlap 可以减轻边界信息丢失，但会：\n\n- 增加索引数量与 Embedding 成本；\n- 产生高度重复的检索结果；\n- 挤占生成上下文；\n- 让评测看似召回多个结果，实际都是同一段重复。\n\n应在检索后做同文档去重或多样性控制。\n\n---\n\n## 七、Embedding\n\n### 1. Embedding 是什么\n\nEmbedding 模型把文本映射到固定维",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "a8f6817b7a4814c9bfee384093816e31",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 9.8787,
    "snippet": "- 不把异常堆栈、数据库连接串或内部地址发给模型；\n- 大结果分页、摘要或保存为引用，不塞满上下文；\n- 明确结果是否截断；\n- 错误要可分类、可处理，而不是统一返回字符串 `failed`。\n\n---\n\n## 七、错误分类与重试\n\n| 错误 | 是否重试 | 处理 |\n|---|---|---|\n| JSON 参数格式错误 | 可让模型修复 1 次 | 返回字段级安全错误 |\n| 参数越界/业务不存在 | 通常不重试 | 澄清或换参数 |\n| 权限不足 | 绝不靠重试绕过 | 明确拒绝，不泄露资源是否存在 |\n| 网络超时/限流 | 有限退避重试 | 遵守总时间预算 |\n| 写操作结果未知 | 先查询幂等状态 | 不盲目重复执行 |\n| 代码 Bug | 不让模型无限重试 | 记录 Trace，降级或终止 |\n\n指数退避示意：\n\n```text\ndelay = min(base × 2^attempt + jitter, max_delay)\n```\n\n重试需要同时受最大次数、总时长和幂等性约束。\n\n---\n\n## 八、幂等性与副作用\n\n读工具通常天然较安全；写工具必须考虑重复调用。",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "43c05ab81db2d80e46d539d326398b96",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 9.0749,
    "snippet": "# 单元测试\n\n---\n\n## 一、JUnit 5\n\n### 核心注解\n```java\n@Test           // 标记测试方法\n@BeforeEach     // 每个测试方法前执行\n@AfterEach      // 每个测试方法后执行\n@BeforeAll      // 所有测试前执行一次（静态方法）\n@AfterAll       // 所有测试后执行一次（静态方法）\n@DisplayName    // 测试方法显示名称\n@ParameterizedTest  // 参数化测试\n```\n\n### 断言\n```java\nassertEquals(expected, actual);\nassertNotNull(obj);\nassertThrows(Exception.class, () -> { ... });\nassertTimeout(Duration.ofSeconds(1), () -> { ... });\n```\n\n---\n\n## 二、Mockito（Mock 依赖）\n\n### 为什么需要 Mock？\n```\nServiceA 依赖 ServiceB ",
    "source_name": "unit_单元测试.md"
  },
  {
    "arguments_json": "{\"artifact_kind\":\"project_code\",\"query\":\"def parse\"}",
    "arguments_sha256": "cb63edf2181b470e62dd29fc7ea5f263705262e3978524a094581df77b9da613",
    "call_id": "call_a852e12b0b184a709669a82544aad14d",
    "completeness": "complete",
    "end_line": 1,
    "evidence_id": "E6",
    "granularity": "locator",
    "kind": "project_code",
    "path": "src/new_parser.py",
    "requirement_eligible": false,
    "result_sha256": "c7f58fd658e8d3c234d5e56cdecc6d9b38a2c260b6fc1fcdb75417acc4f13e52",
    "scope": "literal search hit at src/new_parser.py:1",
    "scope_paths": [
      "src/new_parser.py"
    ],
    "start_line": 1,
    "tool_name": "code_search",
    "tool_version": "code_search_v7"
  },
  {
    "end_line": 2,
    "evidence_id": "E7",
    "kind": "project_code",
    "path": "src/new_parser.py",
    "snippet": "def parse(data):\n    return data.strip().lower()",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "解释 src/new_parser.py 中 parse(data) 对输入字符串做了什么处理。",
        "plan_id": "b4579618c1a6",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_src_04 — USEFUL_PARTIAL

依据当前 src/main.py 的实现，scale(3) 返回什么？说明公式和实际常量。

终态：completed；task_coverage=partial；Provider=4 请求；tokens=24921；估算费用=$0.0077571。

只读 scale 的两行定义，未取得 LIMIT 声明；诚实给出 3×L，但未交付用户要的常量和确定返回 36，预算仍可读取。

### 用户实际收到的答案

当前 src/main.py 中 scale 的实现为：`def scale(value): return value * LIMIT`（第 3–4 行）[E6]。因此公式是 scale(value) = value × LIMIT，即把输入乘以常量 LIMIT。

关于实际常量 LIMIT 的取值：本轮已读取的 src/main.py 正文只覆盖第 3–4 行，未包含 LIMIT 的定义行，因此无法从现有证据确认 LIMIT 的具体数值，也就无法给出 scale(3) 的确切返回值。若 LIMIT 为 L，则 scale(3) = 3 × L。

未完成事项与范围限制：已取得 src/main.py 第 3–4 行的 scale 函数实现，但未读取到 LIMIT 的定义，故无法确定其实际常量值，也无法给出 scale(3) 的确定数值结果。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

当前 src/main.py 中 scale 的实现为：`def scale(value): return value * LIMIT`（第 3–4 行）[E6]。因此公式是 scale(value) = value × LIMIT，即把输入乘以常量 LIMIT。

关于实际常量 LIMIT 的取值：本轮已读取的 src/main.py 正文只覆盖第 3–4 行，未包含 LIMIT 的定义行，因此无法从现有证据确认 LIMIT 的具体数值，也就无法给出 scale(3) 的确切返回值。若 LIMIT 为 L，则 scale(3) = 3 × L。

```json
[
  {
    "action": "final_answer",
    "answer": "当前 src/main.py 中 scale 的实现为：`def scale(value): return value * LIMIT`（第 3–4 行）[E6]。因此公式是 scale(value) = value × LIMIT，即把输入乘以常量 LIMIT。\n\n关于实际常量 LIMIT 的取值：本轮已读取的 src/main.py 正文只覆盖第 3–4 行，未包含 LIMIT 的定义行，因此无法从现有证据确认 LIMIT 的具体数值，也就无法给出 scale(3) 的确切返回值。若 LIMIT 为 L，则 scale(3) = 3 × L。",
    "limitations": "已取得 src/main.py 第 3–4 行的 scale 函数实现，但未读取到 LIMIT 的定义，故无法确定其实际常量值，也无法给出 scale(3) 的确定数值结果。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "src/main.py",
        "target": {
          "kind": "matching",
          "query": "scale"
        }
      },
      "call_id": "call_5d28f5abe5b54d22a81ad1a4b89142a0",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/main.py",
      "regions": [
        {
          "end_line": 4,
          "lines": [
            {
              "line": 3,
              "text": "def scale(value):"
            },
            {
              "line": 4,
              "text": "    return value * LIMIT"
            }
          ],
          "mode": "definition",
          "start_line": 3
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 4,
            "kind": "function",
            "name": "scale",
            "start_line": 3
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "scale",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 11.5424,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "17ff0cbaaa632c5840fe5991edf44cc1",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 10.3963,
    "snippet": "| 技术手册、长章节 |\n\n### 3. 当前项目推荐\n\n```text\n第一层：按 Markdown 标题层级切 Section\n第二层：Section 超长时按段落/Token 递归切分\n索引：较小 Child Chunk\n生成：命中后可扩展到相邻 Chunk 或 Parent Section\n```\n\n初始实验可以从以下范围开始，但必须用评测调整：\n\n```text\nChunk 大小：约 300～600 tokens\nOverlap：约 10%～20%\nTop-K：先取 5～10，再 Rerank/裁剪\n```\n\n这些不是通用最佳值。代码、问答、法规、表格的最佳策略可能不同。\n\n### 4. Overlap 的代价\n\nOverlap 可以减轻边界信息丢失，但会：\n\n- 增加索引数量与 Embedding 成本；\n- 产生高度重复的检索结果；\n- 挤占生成上下文；\n- 让评测看似召回多个结果，实际都是同一段重复。\n\n应在检索后做同文档去重或多样性控制。\n\n---\n\n## 七、Embedding\n\n### 1. Embedding 是什么\n\nEmbedding 模型把文本映射到固定维",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "4291a656beaf2cc55652e673481385e6",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 9.3219,
    "snippet": "- 描述说明“什么时候用”和“什么时候不用”；\n- 参数约束尽量结构化；\n- 限制长度、范围和枚举；\n- 禁止额外字段；\n- 不把 API Key、租户 ID 等可信上下文交给模型填写。\n\nSchema 只能约束结构，业务合法性仍需应用层校验。\n\n---\n\n## 三、Agent Loop 状态机\n\n```text\nSTART\n  ↓\nCALL_MODEL\n  ├─ final answer ─────────────→ DONE\n  ├─ invalid output ─→ 修复/重试（有限次数）\n  └─ tool calls\n        ↓\n     VALIDATE\n        ├─ denied/invalid ─→ TOOL_ERROR\n        └─ allowed\n              ↓\n           EXECUTE\n              ↓\n           APPEND_RESULT\n              ↓\n           CALL_MODEL\n```\n\n终止条件至少包括：\n\n- 模型返回最终答案；\n- 达到最大工",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 8.5241,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 8.3576,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  },
  {
    "end_line": 4,
    "evidence_id": "E6",
    "kind": "project_code",
    "path": "src/main.py",
    "snippet": "def scale(value):\n    return value * LIMIT",
    "start_line": 3
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "依据当前 src/main.py 的实现，scale(3) 返回什么？说明公式和实际常量。",
        "plan_id": "5990ec2743c9",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_xt_01 — USEFUL_PARTIAL

比较 src/main.py 的 scale 实现和 tests/test_main.py 中对应断言；说明二者表达的预期是否一致，不要声称测试已执行。

终态：completed；task_coverage=unknown；Provider=5 请求；tokens=32435；估算费用=$0.0104226。

E6 scale 与 E7 test_scale 已读，但遗漏 LIMIT；只能给出一致性的条件，不能确认实际一致。E4 理论引用也不直接解释断言机制。

### 用户实际收到的答案

## 技术原理

单元测试的核心是断言（assertion）：测试代码对被测函数在给定输入下的返回值提出一个可判定的预期，若实际返回值与预期不符则测试失败。因此“实现与断言是否一致”本质上是判断：按实现逻辑推导出的返回值，是否等于断言中写死的期望值 [E4]。

## 当前项目实现

`src/main.py` 中 `scale` 的实现为：

```python
def scale(value):
    return value * LIMIT
```

即返回值等于入参 `value` 乘以常量 `LIMIT` [E6]。

`tests/test_main.py` 中对应的测试为：

```python
def test_scale():
    assert scale(2) == 24
```

即断言 `scale(2)` 的结果应为 24 [E7]。

## 对照与结论

- 断言输入为 `value = 2`，按实现推导预期结果为 `2 * LIMIT`。
- 断言期望值为 24，因此二者一致的前提是 `LIMIT == 12`。
- 本次取证只读取到 `scale` 函数体（第 3–4 行）和 `test_scale` 函数体（第 1–2 行），**未读取到 `LIMIT` 的定义值**，因此无法确认 `LIMIT` 是否确实为 12。

结论：从结构上看，实现与断言表达的是同一套“线性缩放”预期，二者在 `LIMIT == 12` 时一致；但 `LIMIT` 的实际取值未在本次证据范围内，故不能断言二者一定一致。

## 限制

- 未读取 `LIMIT` 常量定义，无法验证 `2 * LIMIT == 24` 是否成立。
- 未执行任何测试，以上仅为源码与断言的静态对照，不代表测试通过或失败。
- 检索到的知识库片段（RAG 文档处理、高级 RAG、Function Calling）与本问题无关，未作为依据。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

## 技术原理

单元测试的核心是断言（assertion）：测试代码对被测函数在给定输入下的返回值提出一个可判定的预期，若实际返回值与预期不符则测试失败。因此“实现与断言是否一致”本质上是判断：按实现逻辑推导出的返回值，是否等于断言中写死的期望值 [E4]。

## 当前项目实现

`src/main.py` 中 `scale` 的实现为：

```python
def scale(value):
    return value * LIMIT
```

即返回值等于入参 `value` 乘以常量 `LIMIT` [E6]。

`tests/test_main.py` 中对应的测试为：

```python
def test_scale():
    assert scale(2) == 24
```

即断言 `scale(2)` 的结果应为 24 [E7]。

## 对照与结论

- 断言输入为 `value = 2`，按实现推导预期结果为 `2 * LIMIT`。
- 断言期望值为 24，因此二者一致的前提是 `LIMIT == 12`。
- 本次取证只读取到 `scale` 函数体（第 3–4 行）和 `test_scale` 函数体（第 1–2 行），**未读取到 `LIMIT` 的定义值**，因此无法确认 `LIMIT` 是否确实为 12。

结论：从结构上看，实现与断言表达的是同一套“线性缩放”预期，二者在 `LIMIT == 12` 时一致；但 `LIMIT` 的实际取值未在本次证据范围内，故不能断言二者一定一致。

## 限制

- 未读取 `LIMIT` 常量定义，无法验证 `2 * LIMIT == 24` 是否成立。
- 未执行任何测试，以上仅为源码与断言的静态对照，不代表测试通过或失败。
- 检索到的知识库片段（RAG 文档处理、高级 RAG、Function Calling）与本问题无关，未作为依据。

```json
[
  {
    "action": "final_answer",
    "answer": "## 技术原理\n\n单元测试的核心是断言（assertion）：测试代码对被测函数在给定输入下的返回值提出一个可判定的预期，若实际返回值与预期不符则测试失败。因此“实现与断言是否一致”本质上是判断：按实现逻辑推导出的返回值，是否等于断言中写死的期望值 [E4]。\n\n## 当前项目实现\n\n`src/main.py` 中 `scale` 的实现为：\n\n```python\ndef scale(value):\n    return value * LIMIT\n```\n\n即返回值等于入参 `value` 乘以常量 `LIMIT` [E6]。\n\n`tests/test_main.py` 中对应的测试为：\n\n```python\ndef test_scale():\n    assert scale(2) == 24\n```\n\n即断言 `scale(2)` 的结果应为 24 [E7]。\n\n## 对照与结论\n\n- 断言输入为 `value = 2`，按实现推导预期结果为 `2 * LIMIT`。\n- 断言期望值为 24，因此二者一致的前提是 `LIMIT == 12`。\n- 本次取证只读取到 `scale` 函数体（第 3–4 行）和 `test_scale` 函数体（第 1–2 行），**未读取到 `LIMIT` 的定义值**，因此无法确认 `LIMIT` 是否确实为 12。\n\n结论：从结构上看，实现与断言表达的是同一套“线性缩放”预期，二者在 `LIMIT == 12` 时一致；但 `LIMIT` 的实际取值未在本次证据范围内，故不能断言二者一定一致。\n\n## 限制\n\n- 未读取 `LIMIT` 常量定义，无法验证 `2 * LIMIT == 24` 是否成立。\n- 未执行任何测试，以上仅为源码与断言的静态对照，不代表测试通过或失败。\n- 检索到的知识库片段（RAG 文档处理、高级 RAG、Function Calling）与本问题无关，未作为依据。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "artifact_kind": "project_code",
        "query": "def scale"
      },
      "call_id": "call_c02c50738cef485cb9fa1294f9192555",
      "tool_name": "code_search"
    },
    "error_code": null,
    "result": {
      "matches": [
        {
          "line": 3,
          "path": "src/main.py",
          "text": "def scale(value):"
        }
      ]
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "path": "src/main.py",
        "target": {
          "kind": "definition",
          "line": 3
        }
      },
      "call_id": "call_02cbcaa5ae854a8bae24fa5f36c1d704",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/main.py",
      "regions": [
        {
          "end_line": 4,
          "lines": [
            {
              "line": 3,
              "text": "def scale(value):"
            },
            {
              "line": 4,
              "text": "    return value * LIMIT"
            }
          ],
          "mode": "definition",
          "start_line": 3
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 4,
            "kind": "function",
            "name": "scale",
            "start_line": 3
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "definition",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "path": "tests/test_main.py",
        "target": {
          "kind": "matching",
          "query": "scale"
        }
      },
      "call_id": "call_113d26b7b7fb47c3907848fe1066de07",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "tests/test_main.py",
      "regions": [
        {
          "end_line": 2,
          "lines": [
            {
              "line": 1,
              "text": "def test_scale():"
            },
            {
              "line": 2,
              "text": "    assert scale(2) == 24"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 2,
            "kind": "function",
            "name": "test_scale",
            "start_line": 1
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "test_scale",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 2,
    "score": 5.6207,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "a53facc9fe6275640fff9336eccc6f31",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 3,
    "score": 7.416,
    "snippet": "toolRegistry.require(call.name());\n\n                ValidatedArguments arguments = tool.validate(call.arguments());\n                authorizer.check(context.principal(), tool, arguments);\n\n                ToolResult result;\n                try {\n                    result = tool.execute(context, arguments);\n                } catch (RetryableToolException ex) {\n                    result = ToolResult.retryableError(ex.getSafeMessage());\n                } catch (ToolException ex) {\n               ",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "13e50a50eeff857cc4e1bc1fb2217513",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 1,
    "score": 6.9147,
    "snippet": " NDCG\n\n当相关性存在多个等级时，NDCG 同时考虑相关程度和排名位置，适合评估 Rerank。\n\n### 5. 检索评测注意\n\n- 同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标；\n- 评测时固定索引版本、Embedding、Top-K 和随机性；\n- 记录按类别的指标，平均值可能掩盖代码题或精确术语题的失败；\n- Retrieval Recall 高不代表最终回答一定正确。\n\n---\n\n## 四、生成与端到端指标\n\n### 1. Faithfulness / Groundedness\n\n回答中的关键陈述是否得到所给证据支持。它不等于世界知识层面的事实正确：证据本身也可能错或过期。\n\n### 2. Answer Correctness\n\n回答是否覆盖参考答案的必要事实，是否包含错误结论。\n\n### 3. Answer Relevancy\n\n是否直接回答用户问题，避免虽然“都是真的”但答非所问。\n\n### 4. Citation 指标\n\n```text\nCitation validity：引用编号是否存在\nCitation correctness：引用内容是否支持对",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 1,
    "score": 6.0174,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  },
  {
    "arguments_json": "{\"artifact_kind\":\"project_code\",\"query\":\"def scale\"}",
    "arguments_sha256": "4a805637f6e3886718ad7e8fa0cd7eeed46edb06e823eaaffc80eb911973e574",
    "call_id": "call_c02c50738cef485cb9fa1294f9192555",
    "completeness": "complete",
    "end_line": 3,
    "evidence_id": "E5",
    "granularity": "locator",
    "kind": "project_code",
    "path": "src/main.py",
    "requirement_eligible": false,
    "result_sha256": "67d60f0d1487737becc4dbbc734fd1f3870ba836101308cc0037ffb88184c11b",
    "scope": "literal search hit at src/main.py:3",
    "scope_paths": [
      "src/main.py"
    ],
    "start_line": 3,
    "tool_name": "code_search",
    "tool_version": "code_search_v7"
  },
  {
    "end_line": 4,
    "evidence_id": "E6",
    "kind": "project_code",
    "path": "src/main.py",
    "snippet": "def scale(value):\n    return value * LIMIT",
    "start_line": 3
  },
  {
    "end_line": 2,
    "evidence_id": "E7",
    "kind": "project_test",
    "path": "tests/test_main.py",
    "snippet": "def test_scale():\n    assert scale(2) == 24",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "比较 src/main.py 的 scale 实现和 tests/test_main.py 中对应断言；说明二者表达的预期是否一致，不要声称测试已执行。",
        "plan_id": "cd14c348486b",
        "query_type": "comparison",
        "reason_code": "COMPARISON_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "src/main.py 中 scale 函数的实现代码与行为",
            "id": "sq1",
            "query": "src/main.py 中 scale 的实现逻辑是什么",
            "required": true
          },
          {
            "evidence_target": "tests/test_main.py 中针对 scale 的断言内容",
            "id": "sq2",
            "query": "tests/test_main.py 中与 scale 对应的断言是什么",
            "required": true
          },
          {
            "evidence_target": "实现行为与断言预期之间的对应或冲突证据",
            "id": "sq3",
            "query": "src/main.py 的 scale 实现与 tests/test_main.py 的断言所表达的预期是否一致",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_xt_02 — COMPLETE_CORRECT

为 src/main.py 查找候选测试文件，并说明候选位置，不要说成已覆盖或已运行。

终态：completed；task_coverage=partial；Provider=3 请求；tokens=17265；估算费用=$0.0054009。

E6 为真实 find_tests：tests/test_main.py:1、filename_match；只说明候选位置，未升级成覆盖或执行证明。

### 用户实际收到的答案

针对 `src/main.py` 的候选测试文件为 `tests/test_main.py`，候选位置在第 1 行（anchor line 1），匹配原因是文件名匹配（filename_match）[E6]。

需要说明的是：这只是 find_tests 返回的候选定位信息，属于 candidate 粒度，并不代表该测试文件已覆盖 `src/main.py` 的全部或部分行为，也不代表测试已被执行或通过。本次未读取该测试文件正文，也未运行任何测试，因此无法确认其实际断言内容与覆盖范围。

未完成事项与范围限制：仅取得候选测试路径与 anchor line（E6，granularity=candidate，requirement_eligible=false）；未读取 tests/test_main.py 正文，未执行测试，无法确认覆盖情况或运行结果。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

针对 `src/main.py` 的候选测试文件为 `tests/test_main.py`，候选位置在第 1 行（anchor line 1），匹配原因是文件名匹配（filename_match）[E6]。

需要说明的是：这只是 find_tests 返回的候选定位信息，属于 candidate 粒度，并不代表该测试文件已覆盖 `src/main.py` 的全部或部分行为，也不代表测试已被执行或通过。本次未读取该测试文件正文，也未运行任何测试，因此无法确认其实际断言内容与覆盖范围。

```json
[
  {
    "action": "final_answer",
    "answer": "针对 `src/main.py` 的候选测试文件为 `tests/test_main.py`，候选位置在第 1 行（anchor line 1），匹配原因是文件名匹配（filename_match）[E6]。\n\n需要说明的是：这只是 find_tests 返回的候选定位信息，属于 candidate 粒度，并不代表该测试文件已覆盖 `src/main.py` 的全部或部分行为，也不代表测试已被执行或通过。本次未读取该测试文件正文，也未运行任何测试，因此无法确认其实际断言内容与覆盖范围。",
    "limitations": "仅取得候选测试路径与 anchor line（E6，granularity=candidate，requirement_eligible=false）；未读取 tests/test_main.py 正文，未执行测试，无法确认覆盖情况或运行结果。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "src/main.py"
      },
      "call_id": "call_52357e990ec3418b9f219efc79a0a615",
      "tool_name": "find_tests"
    },
    "error_code": null,
    "result": {
      "candidates": [
        {
          "line": 1,
          "path": "tests/test_main.py",
          "reasons": [
            "filename_match"
          ]
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 1,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "34711ae87ebf675e0225f41dd6fce9ca",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 10.93,
    "snippet": "- 包含代码、表格、精确数字或版本的信息题。\n\n### 3. 数据集切分\n\n```text\n开发集：反复调分块、Top-K、Prompt\n测试集：阶段性最终比较，不用来持续调参\n线上回归集：由真实故障持续补充\n```\n\n如果一边看测试结果一边调整系统，测试集事实上已经变成开发集。\n\n### 4. 当前项目最小规模\n\n```text\n首版：30 题，用于快速建立链路\n稳定版：50～100 题，覆盖各模块和无答案样本\n每次线上/模拟面试发现失败：补 1 条回归样本\n```\n\n样本质量和覆盖面比盲目追求数量重要。\n\n---\n\n## 三、检索指标\n\n### 1. Recall@K\n\n前 K 个候选中是否包含任一标准相关证据：\n\n```text\nRecall@K = 被 Top-K 命中的可回答问题数 / 可回答问题总数\n```\n\n如果一个问题需要多个证据，还应计算 required facts 或多个证据的覆盖率，不能只命中其中一段就算完全成功。\n\n### 2. Precision@K\n\n```text\nPrecision@K = Top-K 中相关 Chunk 数 / K\n```\n\nRAG ",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 9.2809,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 8.9629,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "23e9a62968d95e6e7e3d9d45fa7356a5",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 8.5692,
    "snippet": "对无法幂等的高风险操作要求明确确认，并禁止自动重试。\n\n模型生成的自然语言参数不能直接充当可靠幂等键。\n\n---\n\n## 九、多工具调用\n\n### 1. 并行条件\n\n只有互不依赖、无冲突且资源允许的只读调用才适合并行：\n\n```text\n可以并行：分别检索 Redis 和 MySQL 笔记\n不能并行：先创建订单，再用订单 ID 支付\n谨慎并行：两个工具同时修改同一学习记录\n```\n\n### 2. 结果顺序\n\n每个结果必须带原始 `call_id`，不能依赖异步完成顺序与请求顺序相同。\n\n### 3. 部分失败\n\n```text\n3 个工具：2 成功，1 超时\n```\n\n应用应把每个调用的状态分别回传，允许模型使用已有结果或说明缺失，而不是把整个批次伪装成成功。\n\n---\n\n## 十、流式输出\n\n工具调用与普通文本可能在流中分片到达。应用需要：\n\n- 按 call ID 累积工具名和参数片段；\n- 等结构完整后再解析执行；\n- 执行工具前不要把半截 JSON 当合法参数；\n- 客户端断开时取消模型与工具调用；\n- 不把模型内部工具 JSON 原样展示成最终答案；\n- 记录首 Token、",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "43c05ab81db2d80e46d539d326398b96",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 8.2443,
    "snippet": "# 单元测试\n\n---\n\n## 一、JUnit 5\n\n### 核心注解\n```java\n@Test           // 标记测试方法\n@BeforeEach     // 每个测试方法前执行\n@AfterEach      // 每个测试方法后执行\n@BeforeAll      // 所有测试前执行一次（静态方法）\n@AfterAll       // 所有测试后执行一次（静态方法）\n@DisplayName    // 测试方法显示名称\n@ParameterizedTest  // 参数化测试\n```\n\n### 断言\n```java\nassertEquals(expected, actual);\nassertNotNull(obj);\nassertThrows(Exception.class, () -> { ... });\nassertTimeout(Duration.ofSeconds(1), () -> { ... });\n```\n\n---\n\n## 二、Mockito（Mock 依赖）\n\n### 为什么需要 Mock？\n```\nServiceA 依赖 ServiceB ",
    "source_name": "unit_单元测试.md"
  },
  {
    "arguments_json": "{\"path\":\"src/main.py\"}",
    "arguments_sha256": "aa505d5f066506832b63733af59739bf55ca071f61cc5a8c5795e701918e3cd2",
    "call_id": "call_52357e990ec3418b9f219efc79a0a615",
    "candidate_reasons": [
      "filename_match"
    ],
    "completeness": "complete",
    "end_line": 1,
    "evidence_id": "E6",
    "granularity": "candidate",
    "kind": "project_test",
    "path": "tests/test_main.py",
    "requirement_eligible": false,
    "result_sha256": "c7e60c4d96c8b0876a6467f8bc289d1d3f990f704e834062b7625252fc889bb7",
    "scope": "candidate tests/test_main.py:1 for src/main.py",
    "scope_paths": [
      "src/main.py",
      "tests/test_main.py"
    ],
    "start_line": 1,
    "tool_name": "find_tests",
    "tool_version": "find_tests_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "为 src/main.py 查找候选测试文件，并说明候选位置，不要说成已覆盖或已运行。",
        "plan_id": "2b2dd8eca0cd",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_xt_03 — COMPLETE_CORRECT

结合 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更，比较 src/old_parser.py 与 src/new_parser.py 的内容和状态。

终态：completed；task_coverage=partial；Provider=4 请求；tokens=25819；估算费用=$0.0084171。

E4 状态与 E5 真实双路径 diff 为 similarity index 100% 纯 rename；内容未改变和 old/new 状态解释正确。

### 用户实际收到的答案

在 6ba17bca 到 d6b6c100 的变更范围内，src/old_parser.py 与 src/new_parser.py 是同一个文件的重命名关系：变更记录显示 src/old_parser.py 被重命名为 src/new_parser.py（status=renamed）[E4]。针对 src/new_parser.py 的 diff 进一步显示这是一次纯重命名，similarity index 100%，即内容完全一致，没有任何行级改动 [E5]。因此：状态上，旧路径 src/old_parser.py 在该变更后不再存在，新路径 src/new_parser.py 承接了它；内容上，两者完全相同，重命名未伴随内容修改 [E4][E5]。

未完成事项与范围限制：结论仅覆盖该 commit range 内这两个路径的重命名与内容一致性；未核查该文件在其他提交中的历史，也未运行任何测试。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

在 6ba17bca 到 d6b6c100 的变更范围内，src/old_parser.py 与 src/new_parser.py 是同一个文件的重命名关系：变更记录显示 src/old_parser.py 被重命名为 src/new_parser.py（status=renamed）[E4]。针对 src/new_parser.py 的 diff 进一步显示这是一次纯重命名，similarity index 100%，即内容完全一致，没有任何行级改动 [E5]。因此：状态上，旧路径 src/old_parser.py 在该变更后不再存在，新路径 src/new_parser.py 承接了它；内容上，两者完全相同，重命名未伴随内容修改 [E4][E5]。

```json
[
  {
    "action": "final_answer",
    "answer": "在 6ba17bca 到 d6b6c100 的变更范围内，src/old_parser.py 与 src/new_parser.py 是同一个文件的重命名关系：变更记录显示 src/old_parser.py 被重命名为 src/new_parser.py（status=renamed）[E4]。针对 src/new_parser.py 的 diff 进一步显示这是一次纯重命名，similarity index 100%，即内容完全一致，没有任何行级改动 [E5]。因此：状态上，旧路径 src/old_parser.py 在该变更后不再存在，新路径 src/new_parser.py 承接了它；内容上，两者完全相同，重命名未伴随内容修改 [E4][E5]。",
    "limitations": "结论仅覆盖该 commit range 内这两个路径的重命名与内容一致性；未核查该文件在其他提交中的历史，也未运行任何测试。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range"
      },
      "call_id": "call_781b37222ffd42309a2b2fe30be05526",
      "tool_name": "changed_files"
    },
    "error_code": null,
    "result": {
      "changes": [
        {
          "path": "docs/usage.md",
          "status": "added"
        },
        {
          "path": "src/main.py",
          "status": "modified"
        },
        {
          "old_path": "src/old_parser.py",
          "path": "src/new_parser.py",
          "status": "renamed"
        },
        {
          "path": "src/retired_source.py",
          "status": "deleted"
        },
        {
          "path": "tests/test_main.py",
          "status": "modified"
        }
      ],
      "omitted_sensitive_count": 0,
      "returned_count": 5,
      "total_count": 5,
      "truncated": false
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "base_ref": "6ba17bcad84c632d72ad62e1a3f8217a0aed05ad",
        "head_ref": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "mode": "commit_range",
        "path": "src/new_parser.py"
      },
      "call_id": "call_0a620f305a394b8b8f5194eaba686338",
      "tool_name": "git_diff"
    },
    "error_code": null,
    "result": {
      "diff": "diff --git a/src/old_parser.py b/src/new_parser.py\nsimilarity index 100%\nrename from src/old_parser.py\nrename to src/new_parser.py\n",
      "end_line": 1,
      "mode": "commit_range",
      "path": "src/new_parser.py",
      "start_line": 1,
      "truncated": false
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 12.8738,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 11.961,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "52c36a6aa220c24431e73c631219356c",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 10.4596,
    "snippet": "# RAG 评测、故障分析与高级策略\n\n> 核心观点：高级 RAG 的起点不是 GraphRAG 或复杂 Agent，而是可重复的评测集和故障分类。没有基线与对照实验，增加模块只会让系统更难解释。\n\n## 一、先拆开评测对象\n\nRAG 至少包含三个可独立失败的部分：\n\n```text\n数据/索引：正确证据是否被解析和入库？\n检索：正确证据是否进入候选和最终上下文？\n生成：模型是否忠实利用证据并正确回答？\n```\n\n如果最终回答错误，不能直接归因于“模型不行”。先判断：\n\n1. 标准证据在索引里吗？\n2. Top-K 召回了吗？\n3. Rerank 是否把它排掉？\n4. 最终 Prompt 是否包含它？\n5. 模型是否忽略、误读或错误综合？\n6. 引用是否正确？\n\n---\n\n## 二、构建评测集\n\n### 1. 每条样本至少包含\n\n```json\n{\n  \"question\": \"Redis AOF 重写会阻塞主进程吗？\",\n  \"reference_answer\": \"...\",\n  \"relevant_chunk_ids\": [\"chunk_a\", \"chunk_b\"],\n  \"an",
    "source_name": "rag_高级RAG.md"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "arguments_sha256": "a02e95bed3f96b7b6eba409db80801f3ddb313803b7042c27f268e9f95383dbe",
    "call_id": "call_781b37222ffd42309a2b2fe30be05526",
    "completeness": "complete",
    "evidence_id": "E4",
    "granularity": "status_list",
    "kind": "project_change",
    "requirement_eligible": false,
    "result_sha256": "8980091c585b0c59c5cdc52d037a5750e3fcf7a8288eef9e34402fbc625ac3f7",
    "scope": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\"}",
    "scope_paths": [
      "docs/usage.md",
      "src/main.py",
      "src/new_parser.py",
      "src/old_parser.py",
      "src/retired_source.py",
      "tests/test_main.py"
    ],
    "status_entries": [
      {
        "path": "docs/usage.md",
        "status": "added"
      },
      {
        "path": "src/main.py",
        "status": "modified"
      },
      {
        "old_path": "src/old_parser.py",
        "path": "src/new_parser.py",
        "status": "renamed"
      },
      {
        "path": "src/retired_source.py",
        "status": "deleted"
      },
      {
        "path": "tests/test_main.py",
        "status": "modified"
      }
    ],
    "tool_name": "changed_files",
    "tool_version": "changed_files_v1"
  },
  {
    "arguments_json": "{\"base_ref\":\"6ba17bcad84c632d72ad62e1a3f8217a0aed05ad\",\"head_ref\":\"d6b6c100d5e2e441957d834a29a73a8bc4ac1693\",\"mode\":\"commit_range\",\"path\":\"src/new_parser.py\"}",
    "arguments_sha256": "a88116afaff5e1aea7b5c5799b03959ae89ab6b63f30ab4896f0f77415d5f0bf",
    "call_id": "call_0a620f305a394b8b8f5194eaba686338",
    "completeness": "complete",
    "end_line": 1,
    "evidence_id": "E5",
    "granularity": "diff",
    "kind": "project_change",
    "path": "src/new_parser.py",
    "requirement_eligible": true,
    "result_sha256": "7a37975e86060a331124614e8960f14fa04d82686f21ffcdef341fd067ef7b1e",
    "scope": "commit_range diff for src/new_parser.py",
    "scope_paths": [
      "src/new_parser.py"
    ],
    "start_line": 1,
    "tool_name": "git_diff",
    "tool_version": "git_diff_v1"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "结合 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更，比较 src/old_parser.py 与 src/new_parser.py 的内容和状态。",
        "plan_id": "27c85977d4c7",
        "query_type": "comparison",
        "reason_code": "COMPARISON_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "该提交范围内 src/old_parser.py 的文件内容与变更状态证据",
            "id": "sq1",
            "query": "在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更中，src/old_parser.py 的内容和状态是什么？",
            "required": true
          },
          {
            "evidence_target": "该提交范围内 src/new_parser.py 的文件内容与变更状态证据",
            "id": "sq2",
            "query": "在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更中，src/new_parser.py 的内容和状态是什么？",
            "required": true
          },
          {
            "evidence_target": "两个文件在该提交范围内的内容与状态对比证据",
            "id": "sq3",
            "query": "在 6ba17bcad84c632d72ad62e1a3f8217a0aed05ad 到 d6b6c100d5e2e441957d834a29a73a8bc4ac1693 的变更中，src/old_parser.py 与 src/new_parser.py 的内容和状态有何差异？",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_xt_04 — COMPLETE_CORRECT

读取 tests/test_main.py 的完整内容，指出它实际断言了什么，以及从这份源码不能推出什么。

终态：completed；task_coverage=partial；Provider=3 请求；tokens=17466；估算费用=$0.0056295。

E6 为完整两行测试文件，断言 scale(2)==24；无 import/实现/执行证明等边界说明正确。

### 用户实际收到的答案

tests/test_main.py 的完整内容只有两行 [E6]：

```python
def test_scale():
    assert scale(2) == 24
```

它实际断言的内容：定义了一个测试函数 `test_scale`，断言调用 `scale(2)` 的返回值等于 24。也就是说，这份源码唯一可确认的行为主张是：当输入为 2 时，`scale` 应返回 24。

从这份源码不能推出的内容：
- 不能推出 `scale` 的实现逻辑、算法或它是否真的被正确实现——测试文件本身不含 `scale` 的定义，也没有导入语句被读取到。
- 不能推出 `scale` 的完整契约：只覆盖了输入 2 这一个用例，无法说明其他输入、边界值、异常输入或类型约束下的行为。
- 不能推出该测试是否通过、是否被执行过，也不能推出整个测试套件或项目的正确性。
- 不能推出 `scale` 的签名、参数类型、返回类型或它属于哪个模块。
- 不能推出项目其他部分的功能、依赖或部署情况。

依据范围说明：本次读取的 tests/test_main.py 内容完整（content_complete=true，未截断），但仅覆盖该文件这两行；未读取 `scale` 的实现源码，也未运行任何测试。

未完成事项与范围限制：未定位或读取 scale 的实现源码，因此无法核对断言与实现是否一致；未执行测试，无法确认该断言是否通过。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

tests/test_main.py 的完整内容只有两行 [E6]：

```python
def test_scale():
    assert scale(2) == 24
```

它实际断言的内容：定义了一个测试函数 `test_scale`，断言调用 `scale(2)` 的返回值等于 24。也就是说，这份源码唯一可确认的行为主张是：当输入为 2 时，`scale` 应返回 24。

从这份源码不能推出的内容：
- 不能推出 `scale` 的实现逻辑、算法或它是否真的被正确实现——测试文件本身不含 `scale` 的定义，也没有导入语句被读取到。
- 不能推出 `scale` 的完整契约：只覆盖了输入 2 这一个用例，无法说明其他输入、边界值、异常输入或类型约束下的行为。
- 不能推出该测试是否通过、是否被执行过，也不能推出整个测试套件或项目的正确性。
- 不能推出 `scale` 的签名、参数类型、返回类型或它属于哪个模块。
- 不能推出项目其他部分的功能、依赖或部署情况。

依据范围说明：本次读取的 tests/test_main.py 内容完整（content_complete=true，未截断），但仅覆盖该文件这两行；未读取 `scale` 的实现源码，也未运行任何测试。

```json
[
  {
    "action": "final_answer",
    "answer": "tests/test_main.py 的完整内容只有两行 [E6]：\n\n```python\ndef test_scale():\n    assert scale(2) == 24\n```\n\n它实际断言的内容：定义了一个测试函数 `test_scale`，断言调用 `scale(2)` 的返回值等于 24。也就是说，这份源码唯一可确认的行为主张是：当输入为 2 时，`scale` 应返回 24。\n\n从这份源码不能推出的内容：\n- 不能推出 `scale` 的实现逻辑、算法或它是否真的被正确实现——测试文件本身不含 `scale` 的定义，也没有导入语句被读取到。\n- 不能推出 `scale` 的完整契约：只覆盖了输入 2 这一个用例，无法说明其他输入、边界值、异常输入或类型约束下的行为。\n- 不能推出该测试是否通过、是否被执行过，也不能推出整个测试套件或项目的正确性。\n- 不能推出 `scale` 的签名、参数类型、返回类型或它属于哪个模块。\n- 不能推出项目其他部分的功能、依赖或部署情况。\n\n依据范围说明：本次读取的 tests/test_main.py 内容完整（content_complete=true，未截断），但仅覆盖该文件这两行；未读取 `scale` 的实现源码，也未运行任何测试。",
    "limitations": "未定位或读取 scale 的实现源码，因此无法核对断言与实现是否一致；未执行测试，无法确认该断言是否通过。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "tests/test_main.py",
        "target": {
          "kind": "file",
          "start_line": 1
        }
      },
      "call_id": "call_ec3dfcdb026e4d0a855fde5d4b55d5a2",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "tests/test_main.py",
      "regions": [
        {
          "end_line": 2,
          "lines": [
            {
              "line": 1,
              "text": "def test_scale():"
            },
            {
              "line": 2,
              "text": "    assert scale(2) == 24"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": null,
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "file",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 12.0129,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "17ff0cbaaa632c5840fe5991edf44cc1",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 11.1031,
    "snippet": "| 技术手册、长章节 |\n\n### 3. 当前项目推荐\n\n```text\n第一层：按 Markdown 标题层级切 Section\n第二层：Section 超长时按段落/Token 递归切分\n索引：较小 Child Chunk\n生成：命中后可扩展到相邻 Chunk 或 Parent Section\n```\n\n初始实验可以从以下范围开始，但必须用评测调整：\n\n```text\nChunk 大小：约 300～600 tokens\nOverlap：约 10%～20%\nTop-K：先取 5～10，再 Rerank/裁剪\n```\n\n这些不是通用最佳值。代码、问答、法规、表格的最佳策略可能不同。\n\n### 4. Overlap 的代价\n\nOverlap 可以减轻边界信息丢失，但会：\n\n- 增加索引数量与 Embedding 成本；\n- 产生高度重复的检索结果；\n- 挤占生成上下文；\n- 让评测看似召回多个结果，实际都是同一段重复。\n\n应在检索后做同文档去重或多样性控制。\n\n---\n\n## 七、Embedding\n\n### 1. Embedding 是什么\n\nEmbedding 模型把文本映射到固定维",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "13e50a50eeff857cc4e1bc1fb2217513",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 10.8276,
    "snippet": " NDCG\n\n当相关性存在多个等级时，NDCG 同时考虑相关程度和排名位置，适合评估 Rerank。\n\n### 5. 检索评测注意\n\n- 同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标；\n- 评测时固定索引版本、Embedding、Top-K 和随机性；\n- 记录按类别的指标，平均值可能掩盖代码题或精确术语题的失败；\n- Retrieval Recall 高不代表最终回答一定正确。\n\n---\n\n## 四、生成与端到端指标\n\n### 1. Faithfulness / Groundedness\n\n回答中的关键陈述是否得到所给证据支持。它不等于世界知识层面的事实正确：证据本身也可能错或过期。\n\n### 2. Answer Correctness\n\n回答是否覆盖参考答案的必要事实，是否包含错误结论。\n\n### 3. Answer Relevancy\n\n是否直接回答用户问题，避免虽然“都是真的”但答非所问。\n\n### 4. Citation 指标\n\n```text\nCitation validity：引用编号是否存在\nCitation correctness：引用内容是否支持对",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 8.9247,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "52c36a6aa220c24431e73c631219356c",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 8.7651,
    "snippet": "# RAG 评测、故障分析与高级策略\n\n> 核心观点：高级 RAG 的起点不是 GraphRAG 或复杂 Agent，而是可重复的评测集和故障分类。没有基线与对照实验，增加模块只会让系统更难解释。\n\n## 一、先拆开评测对象\n\nRAG 至少包含三个可独立失败的部分：\n\n```text\n数据/索引：正确证据是否被解析和入库？\n检索：正确证据是否进入候选和最终上下文？\n生成：模型是否忠实利用证据并正确回答？\n```\n\n如果最终回答错误，不能直接归因于“模型不行”。先判断：\n\n1. 标准证据在索引里吗？\n2. Top-K 召回了吗？\n3. Rerank 是否把它排掉？\n4. 最终 Prompt 是否包含它？\n5. 模型是否忽略、误读或错误综合？\n6. 引用是否正确？\n\n---\n\n## 二、构建评测集\n\n### 1. 每条样本至少包含\n\n```json\n{\n  \"question\": \"Redis AOF 重写会阻塞主进程吗？\",\n  \"reference_answer\": \"...\",\n  \"relevant_chunk_ids\": [\"chunk_a\", \"chunk_b\"],\n  \"an",
    "source_name": "rag_高级RAG.md"
  },
  {
    "end_line": 2,
    "evidence_id": "E6",
    "kind": "project_test",
    "path": "tests/test_main.py",
    "snippet": "def test_scale():\n    assert scale(2) == 24",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "读取 tests/test_main.py 的完整内容，指出它实际断言了什么，以及从这份源码不能推出什么。",
        "plan_id": "c37bc2fedf8e",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 1,
      "profile": "PROJECT_CODE_V1",
      "required_evidence_groups": [
        [
          "project_code"
        ]
      ],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_rag_01 — COMPLETE_CORRECT

说明为什么更换 corpus commit 后不能直接沿用旧 retrieval hit 结论；哪些 parser、chunker、embedding 信息和固定评测方式需要跟踪？

终态：completed；task_coverage=partial；Provider=2 请求；tokens=9089；估算费用=$0.0034908。

E1 的固定评测原则及 E3 的 parser/chunker/embedding 版本与索引信息支持回答；子查询缺命中没有替代原始交付义务。

### 用户实际收到的答案

更换 corpus commit 后不能直接沿用旧 retrieval hit 结论，核心原因是：检索命中是「语料内容 + 解析/切分/向量化/索引配置 + 评测口径」共同作用的结果，corpus commit 一变，这些环节的输入或版本就可能随之改变，旧 hit 的排序与召回不再对应同一实验条件，因此不能当作同一基线上的可比结论。

具体来说：

1. 语料本身变了，命中对象就变了。旧 hit 指向的文档/片段可能已被修改、删除或新增，chunk 边界与内容都会漂移，旧结论（某 query 命中某 chunk、Recall@5/MRR 数值）失去可复现的前提。

2. 需要跟踪的版本信息。索引写入与版本管理至少应保存 embedding_model_version、parser_version、chunker_version、index_schema_version、created_at [E3]。这些字段正是判断「新旧 hit 是否可比」的依据：只要其中任一项变化，就应视为新的索引版本，而不是沿用旧结论。

3. parser 与 chunker 信息。解析器决定文本如何被抽取（标题、表格、正文边界），切分器决定 chunk 粒度与父子映射；chunk 变了，精确命中与上下文完整性都会变，Parent-Child / Small-to-Big 这类策略尤其依赖父子映射，返回父块还可能引入噪声 [E1]。所以 parser_version、chunker_version 必须随索引一起记录。

4. embedding 信息。必须让索引配置与 Embedding 模型的训练方式一致；若向量已做 L2 归一化，余弦相似度与内积排序等价 [E3]。切换模型时不能在同一索引中混用不同向量空间 [E3]。因此 embedding_model_version、是否归一化、相似度函数都要跟踪，否则新旧 hit 的分数不可比。

5. 固定评测方式。评测要固定基线版本（commit / index / model / prompt）、唯一变量、数据集与指标（如 Recall@5、MRR、P95），并记录失败样本与结论（保留/回滚/继续实验）[E1]。更换 corpus commit 后，应把它作为新的基线版本重新跑离线评测与抽样检查，再决定是否切换在线 alias [E3]，而不是直接复用旧 hit 结论。

工程上的做法是：把 corpus commit 与上述 parser/chunker/embedding/index schema 版本一起纳入索引元数据，corpus 或任一版本变化即构建新索引、重跑固定评测，用同一数据集与指标对比新旧基线，确认无回归后再切换。

说明：以上为知识库中的通用工程实践，未涉及当前绑定项目的具体源码、配置或测试，因此没有项目实现层面的证据。

未完成事项与范围限制：本轮仅有知识库证据（E1、E3），未检索或读取当前项目的源码、配置、测试与变更；关于「固定评测方式」的第三次检索无命中，该部分依据 E1 的评测基线/指标描述归纳，未获得更细的评测流程文档。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

更换 corpus commit 后不能直接沿用旧 retrieval hit 结论，核心原因是：检索命中是「语料内容 + 解析/切分/向量化/索引配置 + 评测口径」共同作用的结果，corpus commit 一变，这些环节的输入或版本就可能随之改变，旧 hit 的排序与召回不再对应同一实验条件，因此不能当作同一基线上的可比结论。

具体来说：

1. 语料本身变了，命中对象就变了。旧 hit 指向的文档/片段可能已被修改、删除或新增，chunk 边界与内容都会漂移，旧结论（某 query 命中某 chunk、Recall@5/MRR 数值）失去可复现的前提。

2. 需要跟踪的版本信息。索引写入与版本管理至少应保存 embedding_model_version、parser_version、chunker_version、index_schema_version、created_at [E3]。这些字段正是判断「新旧 hit 是否可比」的依据：只要其中任一项变化，就应视为新的索引版本，而不是沿用旧结论。

3. parser 与 chunker 信息。解析器决定文本如何被抽取（标题、表格、正文边界），切分器决定 chunk 粒度与父子映射；chunk 变了，精确命中与上下文完整性都会变，Parent-Child / Small-to-Big 这类策略尤其依赖父子映射，返回父块还可能引入噪声 [E1]。所以 parser_version、chunker_version 必须随索引一起记录。

4. embedding 信息。必须让索引配置与 Embedding 模型的训练方式一致；若向量已做 L2 归一化，余弦相似度与内积排序等价 [E3]。切换模型时不能在同一索引中混用不同向量空间 [E3]。因此 embedding_model_version、是否归一化、相似度函数都要跟踪，否则新旧 hit 的分数不可比。

5. 固定评测方式。评测要固定基线版本（commit / index / model / prompt）、唯一变量、数据集与指标（如 Recall@5、MRR、P95），并记录失败样本与结论（保留/回滚/继续实验）[E1]。更换 corpus commit 后，应把它作为新的基线版本重新跑离线评测与抽样检查，再决定是否切换在线 alias [E3]，而不是直接复用旧 hit 结论。

工程上的做法是：把 corpus commit 与上述 parser/chunker/embedding/index schema 版本一起纳入索引元数据，corpus 或任一版本变化即构建新索引、重跑固定评测，用同一数据集与指标对比新旧基线，确认无回归后再切换。

说明：以上为知识库中的通用工程实践，未涉及当前绑定项目的具体源码、配置或测试，因此没有项目实现层面的证据。

```json
[
  {
    "action": "final_answer",
    "answer": "更换 corpus commit 后不能直接沿用旧 retrieval hit 结论，核心原因是：检索命中是「语料内容 + 解析/切分/向量化/索引配置 + 评测口径」共同作用的结果，corpus commit 一变，这些环节的输入或版本就可能随之改变，旧 hit 的排序与召回不再对应同一实验条件，因此不能当作同一基线上的可比结论。\n\n具体来说：\n\n1. 语料本身变了，命中对象就变了。旧 hit 指向的文档/片段可能已被修改、删除或新增，chunk 边界与内容都会漂移，旧结论（某 query 命中某 chunk、Recall@5/MRR 数值）失去可复现的前提。\n\n2. 需要跟踪的版本信息。索引写入与版本管理至少应保存 embedding_model_version、parser_version、chunker_version、index_schema_version、created_at [E3]。这些字段正是判断「新旧 hit 是否可比」的依据：只要其中任一项变化，就应视为新的索引版本，而不是沿用旧结论。\n\n3. parser 与 chunker 信息。解析器决定文本如何被抽取（标题、表格、正文边界），切分器决定 chunk 粒度与父子映射；chunk 变了，精确命中与上下文完整性都会变，Parent-Child / Small-to-Big 这类策略尤其依赖父子映射，返回父块还可能引入噪声 [E1]。所以 parser_version、chunker_version 必须随索引一起记录。\n\n4. embedding 信息。必须让索引配置与 Embedding 模型的训练方式一致；若向量已做 L2 归一化，余弦相似度与内积排序等价 [E3]。切换模型时不能在同一索引中混用不同向量空间 [E3]。因此 embedding_model_version、是否归一化、相似度函数都要跟踪，否则新旧 hit 的分数不可比。\n\n5. 固定评测方式。评测要固定基线版本（commit / index / model / prompt）、唯一变量、数据集与指标（如 Recall@5、MRR、P95），并记录失败样本与结论（保留/回滚/继续实验）[E1]。更换 corpus commit 后，应把它作为新的基线版本重新跑离线评测与抽样检查，再决定是否切换在线 alias [E3]，而不是直接复用旧 hit 结论。\n\n工程上的做法是：把 corpus commit 与上述 parser/chunker/embedding/index schema 版本一起纳入索引元数据，corpus 或任一版本变化即构建新索引、重跑固定评测，用同一数据集与指标对比新旧基线，确认无回归后再切换。\n\n说明：以上为知识库中的通用工程实践，未涉及当前绑定项目的具体源码、配置或测试，因此没有项目实现层面的证据。",
    "limitations": "本轮仅有知识库证据（E1、E3），未检索或读取当前项目的源码、配置、测试与变更；关于「固定评测方式」的第三次检索无命中，该部分依据 E1 的评测基线/指标描述归纳，未获得更细的评测流程文档。"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "a11add31e154a2a110a64f491fab403d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 8.0174,
    "snippet": "BM25 能改善精确术语问题的召回\n- 基线版本：commit / index / model / prompt\n- 唯一变量：retrieval strategy\n- 数据集：rag-eval-v1\n- 指标：Recall@5、MRR、P95\n- 结果：\n- 失败样本：\n- 结论：保留 / 回滚 / 继续实验\n```\n\n### 3. 回归门槛\n\n发布前可设置：\n\n```text\n核心类别 Recall@5 不下降\n整体正确率不低于基线\n权限测试 100% 通过\nP95 不超过预算\n无答案误答率不超过阈值\n```\n\n阈值应根据业务风险和当前基线确定，不照抄他人数字。\n\n---\n\n## 八、什么时候使用高级 RAG\n\n### 1. Parent-Child / Small-to-Big\n\n适合：小块更容易精确命中，但回答需要完整章节上下文。  \n代价：索引和父子映射更复杂，返回父块可能引入噪声。\n\n### 2. Contextual Retrieval\n\n为 Chunk 增加文档级背景，例如标题和简短上下文。  \n适合：原 Chunk 脱离全文后指代不清。  \n风险：生成的背景可能错误；",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 3,
    "score": 7.0016,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 1,
    "score": 13.3947,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "说明为什么更换 corpus commit 后不能直接沿用旧 retrieval hit 结论；哪些 parser、chunker、embedding 信息和固定评测方式需要跟踪？",
        "plan_id": "c88379c77efa",
        "query_type": "causal",
        "reason_code": "CAUSAL_SYNTHESIS",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "说明 corpus 内容变化如何影响检索命中结果与结论有效性的证据",
            "id": "sq1",
            "query": "更换 corpus commit 后旧 retrieval hit 结论为何不能直接沿用",
            "required": true
          },
          {
            "evidence_target": "列出与 parser、chunker、embedding 相关的需跟踪元数据或配置项的证据",
            "id": "sq2",
            "query": "检索评测中需要跟踪哪些 parser、chunker 和 embedding 信息",
            "required": true
          },
          {
            "evidence_target": "说明固定评测流程中需记录或固定的要素的证据",
            "id": "sq3",
            "query": "固定评测方式需要跟踪哪些内容",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_rag_02 — WRONG_DELIVERY

资料如何区分证据支持度与世界事实正确性？回答通过 evidence verification 能推出什么，不能推出什么？

终态：completed；task_coverage=partial；Provider=2 请求；tokens=9390；估算费用=$0.0035793。

检索 E1/E2 主要为面试自检问题，未定义具体 verification 的语义保证；却称通过验证能推出陈述内容匹配/合理蕴含。沿用 Task022 对此歧义题的保守来源判据。

### 用户实际收到的答案

## 证据支持度 vs 世界事实正确性

这是两个不同层面的判断，不能互相替代：

- **证据支持度（evidence support / faithfulness）**：回答是否被检索到的资料所支持、引用是否指向真实存在的来源。它衡量的是「回答与给定证据之间的一致性」。
- **世界事实正确性（factual correctness）**：回答是否与客观世界真实情况相符。它衡量的是「回答与外部现实之间的一致性」。

资料中明确把这两者作为不同的评测维度提出，例如面试自检里专门问「Faithfulness 与事实正确有什么区别？」[E1]，说明二者在评测体系中是分开的指标，不能混为一谈。

## evidence verification 能推出什么

- 能推出：回答中的陈述**有据可依**——即该陈述可以从被引用的证据中读出或合理推出，引用指向的 chunk/来源确实存在且内容匹配。
- 能推出：在「回答 ↔ 证据」这一层关系上的一致性成立，可用于判断回答是否忠实于给定材料（faithfulness 类判断）。
- 能推出：引用正确性可被评测——资料把「如何评测引用正确性」列为独立问题 [E1]，说明引用校验是可操作、可度量的环节。

## evidence verification 不能推出什么

- **不能推出世界事实正确性**：证据本身可能是错的、过时的或片面的；回答忠实于证据，不等于回答符合客观事实。资料把 faithfulness 与事实正确并列为不同问题 [E1]，正说明前者不能蕴含后者。
- **不能推出证据来源本身可信**：工具/检索结果同样属于不可信数据，资料明确指出「工具结果为什么也不可信」是需要处理的面试考点 [E2]，因此校验通过只说明「与所给证据一致」，不说明「证据为真」。
- **不能推出覆盖完整或没有遗漏**：校验针对的是已取得的证据，无法证明不存在未被检索到的反例或更权威来源。
- **不能推出系统整体正确**：资料强调最终回答出错不能直接归因于 LLM [E1]，说明链路中检索、分块、引用等多环节都可能引入问题，单点校验不足以证明端到端正确。

## 工程含义

因此实践中应把两者当作互补而非替代：evidence verification 保证「不脱离证据、引用可核验」，而世界事实正确性需要额外的外部核验手段（如人工确认根因、回归集、离线评测与小流量验证的反馈闭环 [E1]）。资料也提示不能把所有反馈自动当作可信数据，需去隐私、去攻击内容并人工抽检 [E1]。

**局限说明**：以上基于当前检索到的知识库片段 [E1][E2]，属于通用方法论层面的说明；未涉及当前绑定项目的具体实现代码或测试，也未执行任何验证程序，因此不对任何具体系统的实际校验能力作断言。

未完成事项与范围限制：仅依据知识库检索片段作答，未读取或核验当前项目源码/配置/测试，也未实际运行任何 evidence verification 流程；因此无法给出针对具体实现的校验能力结论。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

## 证据支持度 vs 世界事实正确性

这是两个不同层面的判断，不能互相替代：

- **证据支持度（evidence support / faithfulness）**：回答是否被检索到的资料所支持、引用是否指向真实存在的来源。它衡量的是「回答与给定证据之间的一致性」。
- **世界事实正确性（factual correctness）**：回答是否与客观世界真实情况相符。它衡量的是「回答与外部现实之间的一致性」。

资料中明确把这两者作为不同的评测维度提出，例如面试自检里专门问「Faithfulness 与事实正确有什么区别？」[E1]，说明二者在评测体系中是分开的指标，不能混为一谈。

## evidence verification 能推出什么

- 能推出：回答中的陈述**有据可依**——即该陈述可以从被引用的证据中读出或合理推出，引用指向的 chunk/来源确实存在且内容匹配。
- 能推出：在「回答 ↔ 证据」这一层关系上的一致性成立，可用于判断回答是否忠实于给定材料（faithfulness 类判断）。
- 能推出：引用正确性可被评测——资料把「如何评测引用正确性」列为独立问题 [E1]，说明引用校验是可操作、可度量的环节。

## evidence verification 不能推出什么

- **不能推出世界事实正确性**：证据本身可能是错的、过时的或片面的；回答忠实于证据，不等于回答符合客观事实。资料把 faithfulness 与事实正确并列为不同问题 [E1]，正说明前者不能蕴含后者。
- **不能推出证据来源本身可信**：工具/检索结果同样属于不可信数据，资料明确指出「工具结果为什么也不可信」是需要处理的面试考点 [E2]，因此校验通过只说明「与所给证据一致」，不说明「证据为真」。
- **不能推出覆盖完整或没有遗漏**：校验针对的是已取得的证据，无法证明不存在未被检索到的反例或更权威来源。
- **不能推出系统整体正确**：资料强调最终回答出错不能直接归因于 LLM [E1]，说明链路中检索、分块、引用等多环节都可能引入问题，单点校验不足以证明端到端正确。

## 工程含义

因此实践中应把两者当作互补而非替代：evidence verification 保证「不脱离证据、引用可核验」，而世界事实正确性需要额外的外部核验手段（如人工确认根因、回归集、离线评测与小流量验证的反馈闭环 [E1]）。资料也提示不能把所有反馈自动当作可信数据，需去隐私、去攻击内容并人工抽检 [E1]。

**局限说明**：以上基于当前检索到的知识库片段 [E1][E2]，属于通用方法论层面的说明；未涉及当前绑定项目的具体实现代码或测试，也未执行任何验证程序，因此不对任何具体系统的实际校验能力作断言。

```json
[
  {
    "action": "final_answer",
    "answer": "## 证据支持度 vs 世界事实正确性\n\n这是两个不同层面的判断，不能互相替代：\n\n- **证据支持度（evidence support / faithfulness）**：回答是否被检索到的资料所支持、引用是否指向真实存在的来源。它衡量的是「回答与给定证据之间的一致性」。\n- **世界事实正确性（factual correctness）**：回答是否与客观世界真实情况相符。它衡量的是「回答与外部现实之间的一致性」。\n\n资料中明确把这两者作为不同的评测维度提出，例如面试自检里专门问「Faithfulness 与事实正确有什么区别？」[E1]，说明二者在评测体系中是分开的指标，不能混为一谈。\n\n## evidence verification 能推出什么\n\n- 能推出：回答中的陈述**有据可依**——即该陈述可以从被引用的证据中读出或合理推出，引用指向的 chunk/来源确实存在且内容匹配。\n- 能推出：在「回答 ↔ 证据」这一层关系上的一致性成立，可用于判断回答是否忠实于给定材料（faithfulness 类判断）。\n- 能推出：引用正确性可被评测——资料把「如何评测引用正确性」列为独立问题 [E1]，说明引用校验是可操作、可度量的环节。\n\n## evidence verification 不能推出什么\n\n- **不能推出世界事实正确性**：证据本身可能是错的、过时的或片面的；回答忠实于证据，不等于回答符合客观事实。资料把 faithfulness 与事实正确并列为不同问题 [E1]，正说明前者不能蕴含后者。\n- **不能推出证据来源本身可信**：工具/检索结果同样属于不可信数据，资料明确指出「工具结果为什么也不可信」是需要处理的面试考点 [E2]，因此校验通过只说明「与所给证据一致」，不说明「证据为真」。\n- **不能推出覆盖完整或没有遗漏**：校验针对的是已取得的证据，无法证明不存在未被检索到的反例或更权威来源。\n- **不能推出系统整体正确**：资料强调最终回答出错不能直接归因于 LLM [E1]，说明链路中检索、分块、引用等多环节都可能引入问题，单点校验不足以证明端到端正确。\n\n## 工程含义\n\n因此实践中应把两者当作互补而非替代：evidence verification 保证「不脱离证据、引用可核验」，而世界事实正确性需要额外的外部核验手段（如人工确认根因、回归集、离线评测与小流量验证的反馈闭环 [E1]）。资料也提示不能把所有反馈自动当作可信数据，需去隐私、去攻击内容并人工抽检 [E1]。\n\n**局限说明**：以上基于当前检索到的知识库片段 [E1][E2]，属于通用方法论层面的说明；未涉及当前绑定项目的具体实现代码或测试，也未执行任何验证程序，因此不对任何具体系统的实际校验能力作断言。",
    "limitations": "仅依据知识库检索片段作答，未读取或核验当前项目源码/配置/测试，也未实际运行任何 evidence verification 流程；因此无法给出针对具体实现的校验能力结论。"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 12.0847,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 1,
    "score": 8.3272,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 9.5417,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 5,
    "score": 3.9893,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "资料如何区分证据支持度与世界事实正确性？回答通过 evidence verification 能推出什么，不能推出什么？",
        "plan_id": "1beded114515",
        "query_type": "causal",
        "reason_code": "CAUSAL_SYNTHESIS",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "关于证据支持度与世界事实正确性之间区别的论述或定义",
            "id": "sq1",
            "query": "资料如何区分证据支持度与世界事实正确性？",
            "required": true
          },
          {
            "evidence_target": "evidence verification 能够支持的结论范围",
            "id": "sq2",
            "query": "通过 evidence verification 能推出什么结论？",
            "required": true
          },
          {
            "evidence_target": "evidence verification 无法支持的结论或局限",
            "id": "sq3",
            "query": "通过 evidence verification 不能推出什么结论？",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_rag_03 — WRONG_DELIVERY

文档增量更新时，内容没变、内容改变和源文件消失分别应该如何处理？

终态：completed；task_coverage=partial；Provider=2 请求；tokens=8667；估算费用=$0.0031131。

三种处理原则本身常见，但 E1 仅列更新/删除自检问题，未提供跳过、重分块、删向量步骤。将这些核心步骤作为该引用支持的答案，缺乏实际材料支撑。

### 用户实际收到的答案

关于文档增量更新时三种情形的处理，可结合检索到的知识库材料说明如下（这些是通用工程实践层面的知识证据，非当前项目源码实现）：

**1. 内容没变（未修改）**
应保证重复导入的幂等性：为文档保存稳定的 ID 与元数据，导入时先比对内容指纹（如哈希）或版本/时间戳，若判定未变化则跳过重新解析、分块与 Embedding，直接复用已有索引，避免重复写入和成本浪费 [E1]。

**2. 内容改变（已修改）**
需要做增量更新：识别变更后重新解析与分块，对受影响的分块重新生成 Embedding 并替换旧向量，同时清理或失效对应的旧分块，防止新旧内容同时被召回造成冲突。若 Embedding 模型本身升级，通常需要重建索引 [E1]。更新与删除属于需要专门处理的环节，检索质量下降时可按故障分类定位是解析、分块、召回还是排序环节的问题 [E2]。

**3. 源文件消失（被删除）**
应做删除同步：依据稳定 ID 与元数据定位该文档对应的所有分块与向量，将其从索引中移除（或标记失效），避免已删除内容仍被检索到。文档更新与删除的处理是 RAG 文档管理中的常见考点 [E1]。

**说明与局限**：以上为知识库文档中的通用原则性内容，检索片段未给出逐条的实现代码或具体 API；本次未涉及当前绑定项目的源码、配置或测试，因此不对项目内具体实现作任何断言。

未完成事项与范围限制：知识库检索片段仅提供原则性描述，未包含三种情形的完整实现细节或代码；未核查当前项目源码/测试，也未执行任何测试。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

关于文档增量更新时三种情形的处理，可结合检索到的知识库材料说明如下（这些是通用工程实践层面的知识证据，非当前项目源码实现）：

**1. 内容没变（未修改）**
应保证重复导入的幂等性：为文档保存稳定的 ID 与元数据，导入时先比对内容指纹（如哈希）或版本/时间戳，若判定未变化则跳过重新解析、分块与 Embedding，直接复用已有索引，避免重复写入和成本浪费 [E1]。

**2. 内容改变（已修改）**
需要做增量更新：识别变更后重新解析与分块，对受影响的分块重新生成 Embedding 并替换旧向量，同时清理或失效对应的旧分块，防止新旧内容同时被召回造成冲突。若 Embedding 模型本身升级，通常需要重建索引 [E1]。更新与删除属于需要专门处理的环节，检索质量下降时可按故障分类定位是解析、分块、召回还是排序环节的问题 [E2]。

**3. 源文件消失（被删除）**
应做删除同步：依据稳定 ID 与元数据定位该文档对应的所有分块与向量，将其从索引中移除（或标记失效），避免已删除内容仍被检索到。文档更新与删除的处理是 RAG 文档管理中的常见考点 [E1]。

**说明与局限**：以上为知识库文档中的通用原则性内容，检索片段未给出逐条的实现代码或具体 API；本次未涉及当前绑定项目的源码、配置或测试，因此不对项目内具体实现作任何断言。

```json
[
  {
    "action": "final_answer",
    "answer": "关于文档增量更新时三种情形的处理，可结合检索到的知识库材料说明如下（这些是通用工程实践层面的知识证据，非当前项目源码实现）：\n\n**1. 内容没变（未修改）**\n应保证重复导入的幂等性：为文档保存稳定的 ID 与元数据，导入时先比对内容指纹（如哈希）或版本/时间戳，若判定未变化则跳过重新解析、分块与 Embedding，直接复用已有索引，避免重复写入和成本浪费 [E1]。\n\n**2. 内容改变（已修改）**\n需要做增量更新：识别变更后重新解析与分块，对受影响的分块重新生成 Embedding 并替换旧向量，同时清理或失效对应的旧分块，防止新旧内容同时被召回造成冲突。若 Embedding 模型本身升级，通常需要重建索引 [E1]。更新与删除属于需要专门处理的环节，检索质量下降时可按故障分类定位是解析、分块、召回还是排序环节的问题 [E2]。\n\n**3. 源文件消失（被删除）**\n应做删除同步：依据稳定 ID 与元数据定位该文档对应的所有分块与向量，将其从索引中移除（或标记失效），避免已删除内容仍被检索到。文档更新与删除的处理是 RAG 文档管理中的常见考点 [E1]。\n\n**说明与局限**：以上为知识库文档中的通用原则性内容，检索片段未给出逐条的实现代码或具体 API；本次未涉及当前绑定项目的源码、配置或测试，因此不对项目内具体实现作任何断言。",
    "limitations": "知识库检索片段仅提供原则性描述，未包含三种情形的完整实现细节或代码；未核查当前项目源码/测试，也未执行任何测试。"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 12.1419,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "855c1ed3b1dad19886de34af100490be",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 4,
    "score": 8.8092,
    "snippet": "六、故障分类\n\n给每个失败样本只标一个主要根因，再标可选次要根因。\n\n| 类别 | 典型现象 | 优先修复 |\n|---|---|---|\n| Parse Failure | 标准证据未进入索引 | 解析、OCR、表格/代码处理 |\n| Chunk Failure | 证据被切断或过大 | 分块、Parent-Child、相邻块扩展 |\n| Retrieval Failure | Top-K 没有正确证据 | Embedding、BM25、查询改写、Top-K |\n| Ranking Failure | 召回了但被排到后面/丢弃 | 融合、Rerank、去重 |\n| Context Failure | 正确证据未被放入 Prompt | Token 预算、上下文组装 |\n| Generation Failure | 有证据仍答错 | Prompt、模型、结构化推理、微调 |\n| Citation Failure | 答案对但引用错 | 引用协议、应用层校验 |\n| Abstention Failure | 无证据仍编造 | 阈值、无答案训练/提示、校验 |\n| Permission F",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 8.5548,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "文档增量更新时，内容没变、内容改变和源文件消失分别应该如何处理？",
        "plan_id": "ad511ce429e1",
        "query_type": "causal",
        "reason_code": "CAUSAL_SYNTHESIS",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "增量更新流程中内容未变化时的处理策略与依据",
            "id": "sq1",
            "query": "文档增量更新时，内容没变应该如何处理？",
            "required": true
          },
          {
            "evidence_target": "增量更新流程中内容发生变化时的处理策略与依据",
            "id": "sq2",
            "query": "文档增量更新时，内容改变应该如何处理？",
            "required": true
          },
          {
            "evidence_target": "增量更新流程中源文件被删除或消失时的处理策略与依据",
            "id": "sq3",
            "query": "文档增量更新时，源文件消失应该如何处理？",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_rag_04 — USEFUL_PARTIAL

资料中 Mock 和 Stub 有什么区别？行覆盖率与分支覆盖率又分别关注什么？

终态：completed；task_coverage=partial；Provider=2 请求；tokens=8955；估算费用=$0.0030744。

E1 支持 Mock/Stub 区别，行/分支覆盖检索无匹配；如实保留缺口，未完成第二子任务。原语料有相关内容，属于检索覆盖问题。

### 用户实际收到的答案

关于 Mock 与 Stub 的区别，资料中给出的要点是：Mock 验证行为（verify），Stub 只提供假数据 [E1]。也就是说，Stub 的作用是向被测代码提供预设的、可控的假数据/返回值，让测试能跑起来；Mock 则额外关注交互行为，用来验证被测代码是否按预期调用了某个依赖（verify 调用次数、参数等）。

关于行覆盖率与分支覆盖率：现有检索到的资料只提到覆盖率的一般概念（如“绿色=已覆盖，红色=未覆盖”，以及大厂对核心业务逻辑覆盖率 > 80% 的要求）[E1]，并没有给出“行覆盖率”和“分支覆盖率”各自关注点的具体说明。因此这两者的区别无法从当前资料中得到有依据的回答。

补充说明：针对“行覆盖率关注什么”“分支覆盖率关注什么”的两次检索均未返回任何匹配结果，所以这部分内容属于资料缺口，不能凭模型自身知识当作资料证据来陈述。

未完成事项与范围限制：资料仅覆盖 Mock/Stub 的区别（Mock 验证行为、Stub 提供假数据）[E1]；行覆盖率与分支覆盖率的具体关注点未在检索到的资料中出现（两次相关检索均无匹配），该部分未完成取证。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

关于 Mock 与 Stub 的区别，资料中给出的要点是：Mock 验证行为（verify），Stub 只提供假数据 [E1]。也就是说，Stub 的作用是向被测代码提供预设的、可控的假数据/返回值，让测试能跑起来；Mock 则额外关注交互行为，用来验证被测代码是否按预期调用了某个依赖（verify 调用次数、参数等）。

关于行覆盖率与分支覆盖率：现有检索到的资料只提到覆盖率的一般概念（如“绿色=已覆盖，红色=未覆盖”，以及大厂对核心业务逻辑覆盖率 > 80% 的要求）[E1]，并没有给出“行覆盖率”和“分支覆盖率”各自关注点的具体说明。因此这两者的区别无法从当前资料中得到有依据的回答。

补充说明：针对“行覆盖率关注什么”“分支覆盖率关注什么”的两次检索均未返回任何匹配结果，所以这部分内容属于资料缺口，不能凭模型自身知识当作资料证据来陈述。

```json
[
  {
    "action": "final_answer",
    "answer": "关于 Mock 与 Stub 的区别，资料中给出的要点是：Mock 验证行为（verify），Stub 只提供假数据 [E1]。也就是说，Stub 的作用是向被测代码提供预设的、可控的假数据/返回值，让测试能跑起来；Mock 则额外关注交互行为，用来验证被测代码是否按预期调用了某个依赖（verify 调用次数、参数等）。\n\n关于行覆盖率与分支覆盖率：现有检索到的资料只提到覆盖率的一般概念（如“绿色=已覆盖，红色=未覆盖”，以及大厂对核心业务逻辑覆盖率 > 80% 的要求）[E1]，并没有给出“行覆盖率”和“分支覆盖率”各自关注点的具体说明。因此这两者的区别无法从当前资料中得到有依据的回答。\n\n补充说明：针对“行覆盖率关注什么”“分支覆盖率关注什么”的两次检索均未返回任何匹配结果，所以这部分内容属于资料缺口，不能凭模型自身知识当作资料证据来陈述。",
    "limitations": "资料仅覆盖 Mock/Stub 的区别（Mock 验证行为、Stub 提供假数据）[E1]；行覆盖率与分支覆盖率的具体关注点未在检索到的资料中出现（两次相关检索均无匹配），该部分未完成取证。"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 16.1742,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  },
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 9.1906,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 4,
    "score": 5.2725,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 3,
    "score": 8.2521,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "资料中 Mock 和 Stub 有什么区别？行覆盖率与分支覆盖率又分别关注什么？",
        "plan_id": "afa70c6f2dcc",
        "query_type": "comparison",
        "reason_code": "COMPARISON_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "资料中关于 Mock 与 Stub 的定义、用途和差异的说明",
            "id": "sq1",
            "query": "Mock 和 Stub 有什么区别？",
            "required": true
          },
          {
            "evidence_target": "资料中关于行覆盖率定义与关注点的说明",
            "id": "sq2",
            "query": "行覆盖率关注什么？",
            "required": true
          },
          {
            "evidence_target": "资料中关于分支覆盖率定义与关注点的说明",
            "id": "sq3",
            "query": "分支覆盖率关注什么？",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_mix_01 — COMPLETE_CORRECT

读取 src/new_parser.py，说明 parse 的实际处理步骤；结合 Function Calling 资料解释，为什么仅有这份源码不能声称函数已经被工具执行成功。

终态：completed；task_coverage=partial；Provider=3 请求；tokens=15445；估算费用=$0.0053949。

E3 实际 parse 源码与 E1 Function Calling 执行循环资料取得；步骤和静态读取不等于执行成功的区分均正确。附加纯函数表述需避免外推到任意 data 类型。

### 用户实际收到的答案

**当前项目实现（src/new_parser.py）**

`parse` 的实际处理步骤只有两步 [E3]：

1. 接收参数 `data`；
2. 返回 `data.strip().lower()`，即先去除首尾空白，再转成小写后返回。

该函数没有做类型校验、异常处理、分词、结构化解析或副作用（如写文件、发请求），也没有调用其他函数；它只是一个纯字符串归一化函数。以上结论来自对 `src/new_parser.py` 第 1–2 行函数定义的读取，读取完整（content_complete=true，未截断）[E3]。

**技术原理（Function Calling）**

Function Calling 的核心认识是：模型只负责生成“调用哪个工具、传什么参数”的结构化建议；真正的参数校验、权限判断、执行、重试和审计全部由应用负责 [E1]。完整流程为：应用把用户消息 + 工具 Schema 发给模型 → 模型返回普通文本或 tool_call → 应用校验工具名和参数 → 应用做身份认证、权限判断、风险确认 → 应用真正执行工具 → 应用把 tool result 按 call_id 回传 → 模型基于结果继续调用或生成最终回答 [E1]。因此模型输出的工具名和参数都不可信，工具结果也是外部数据；“模型说已经删除/发送/查询成功”不能作为成功依据，必须以工具执行结果为准 [E1]。

**对照：为什么仅有这份源码不能声称函数已被工具执行成功**

- 源码只描述“如果被调用会发生什么”，不构成一次执行。要证明执行成功，需要应用侧真正执行工具并把 tool result 按 call_id 回传 [E1]；本次证据中只有对 `src/new_parser.py` 的静态读取 [E3]，没有任何 `parse` 的调用记录、返回值或 tool result。
- 按上述流程，执行、校验与审计责任在应用侧而非模型侧 [E1]。因此即使源码逻辑看起来正确，也不能推断它被调用过、参数合法、运行无异常或结果被接受。
- 本次也没有测试执行证据，不能声称测试通过或函数在真实数据上工作正常。

**结论**：`parse` 的实现是“strip 后 lower 并返回” [E3]；而“函数已被工具执行成功”属于执行事实，必须由应用侧的实际 tool result 支撑 [E1]，当前证据不足以支持该主张。

未完成事项与范围限制：未执行任何代码或测试，因此无法确认 parse 的运行时行为、异常情况或调用结果；知识检索中关于“仅有 parse 源码为何不能证明执行成功”的查询返回空结果，相关论证依据的是 Function Calling 执行循环资料 [E1] 与源码静态读取 [E3] 的对照，而非专门的执行证据。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

**当前项目实现（src/new_parser.py）**

`parse` 的实际处理步骤只有两步 [E3]：

1. 接收参数 `data`；
2. 返回 `data.strip().lower()`，即先去除首尾空白，再转成小写后返回。

该函数没有做类型校验、异常处理、分词、结构化解析或副作用（如写文件、发请求），也没有调用其他函数；它只是一个纯字符串归一化函数。以上结论来自对 `src/new_parser.py` 第 1–2 行函数定义的读取，读取完整（content_complete=true，未截断）[E3]。

**技术原理（Function Calling）**

Function Calling 的核心认识是：模型只负责生成“调用哪个工具、传什么参数”的结构化建议；真正的参数校验、权限判断、执行、重试和审计全部由应用负责 [E1]。完整流程为：应用把用户消息 + 工具 Schema 发给模型 → 模型返回普通文本或 tool_call → 应用校验工具名和参数 → 应用做身份认证、权限判断、风险确认 → 应用真正执行工具 → 应用把 tool result 按 call_id 回传 → 模型基于结果继续调用或生成最终回答 [E1]。因此模型输出的工具名和参数都不可信，工具结果也是外部数据；“模型说已经删除/发送/查询成功”不能作为成功依据，必须以工具执行结果为准 [E1]。

**对照：为什么仅有这份源码不能声称函数已被工具执行成功**

- 源码只描述“如果被调用会发生什么”，不构成一次执行。要证明执行成功，需要应用侧真正执行工具并把 tool result 按 call_id 回传 [E1]；本次证据中只有对 `src/new_parser.py` 的静态读取 [E3]，没有任何 `parse` 的调用记录、返回值或 tool result。
- 按上述流程，执行、校验与审计责任在应用侧而非模型侧 [E1]。因此即使源码逻辑看起来正确，也不能推断它被调用过、参数合法、运行无异常或结果被接受。
- 本次也没有测试执行证据，不能声称测试通过或函数在真实数据上工作正常。

**结论**：`parse` 的实现是“strip 后 lower 并返回” [E3]；而“函数已被工具执行成功”属于执行事实，必须由应用侧的实际 tool result 支撑 [E1]，当前证据不足以支持该主张。

```json
[
  {
    "action": "final_answer",
    "answer": "**当前项目实现（src/new_parser.py）**\n\n`parse` 的实际处理步骤只有两步 [E3]：\n\n1. 接收参数 `data`；\n2. 返回 `data.strip().lower()`，即先去除首尾空白，再转成小写后返回。\n\n该函数没有做类型校验、异常处理、分词、结构化解析或副作用（如写文件、发请求），也没有调用其他函数；它只是一个纯字符串归一化函数。以上结论来自对 `src/new_parser.py` 第 1–2 行函数定义的读取，读取完整（content_complete=true，未截断）[E3]。\n\n**技术原理（Function Calling）**\n\nFunction Calling 的核心认识是：模型只负责生成“调用哪个工具、传什么参数”的结构化建议；真正的参数校验、权限判断、执行、重试和审计全部由应用负责 [E1]。完整流程为：应用把用户消息 + 工具 Schema 发给模型 → 模型返回普通文本或 tool_call → 应用校验工具名和参数 → 应用做身份认证、权限判断、风险确认 → 应用真正执行工具 → 应用把 tool result 按 call_id 回传 → 模型基于结果继续调用或生成最终回答 [E1]。因此模型输出的工具名和参数都不可信，工具结果也是外部数据；“模型说已经删除/发送/查询成功”不能作为成功依据，必须以工具执行结果为准 [E1]。\n\n**对照：为什么仅有这份源码不能声称函数已被工具执行成功**\n\n- 源码只描述“如果被调用会发生什么”，不构成一次执行。要证明执行成功，需要应用侧真正执行工具并把 tool result 按 call_id 回传 [E1]；本次证据中只有对 `src/new_parser.py` 的静态读取 [E3]，没有任何 `parse` 的调用记录、返回值或 tool result。\n- 按上述流程，执行、校验与审计责任在应用侧而非模型侧 [E1]。因此即使源码逻辑看起来正确，也不能推断它被调用过、参数合法、运行无异常或结果被接受。\n- 本次也没有测试执行证据，不能声称测试通过或函数在真实数据上工作正常。\n\n**结论**：`parse` 的实现是“strip 后 lower 并返回” [E3]；而“函数已被工具执行成功”属于执行事实，必须由应用侧的实际 tool result 支撑 [E1]，当前证据不足以支持该主张。",
    "limitations": "未执行任何代码或测试，因此无法确认 parse 的运行时行为、异常情况或调用结果；知识检索中关于“仅有 parse 源码为何不能证明执行成功”的查询返回空结果，相关论证依据的是 Function Calling 执行循环资料 [E1] 与源码静态读取 [E3] 的对照，而非专门的执行证据。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "src/new_parser.py",
        "target": {
          "kind": "matching",
          "query": "parse"
        }
      },
      "call_id": "call_372c3f53ded9497584e508b0c330433b",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/new_parser.py",
      "regions": [
        {
          "end_line": 2,
          "lines": [
            {
              "line": 1,
              "text": "def parse(data):"
            },
            {
              "line": 2,
              "text": "    return data.strip().lower()"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 2,
            "kind": "function",
            "name": "parse",
            "start_line": 1
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "parse",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "1548db78f26bfbadfd19150eb9c5007f",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 14.8976,
    "snippet": "# Function Calling 原理与执行循环\n\n> 核心认识：模型只负责生成“调用哪个工具、传什么参数”的结构化建议；真正的参数校验、权限判断、执行、重试和审计全部由应用负责。\n\n## 一、模型不会直接执行函数\n\n完整流程：\n\n```text\n应用把用户消息 + 工具 Schema 发给模型\n  ↓\n模型返回普通文本，或者一个/多个 tool_call\n  ↓\n应用校验工具名和参数\n  ↓\n应用做身份认证、权限判断、风险确认\n  ↓\n应用真正执行工具\n  ↓\n应用把 tool result 按 call_id 回传给模型\n  ↓\n模型基于结果继续调用工具或生成最终回答\n```\n\n因此：\n\n- 模型输出的工具名和参数都不可信；\n- 工具结果也是外部数据，可能包含 Prompt Injection；\n- “模型说已经删除/发送/查询成功”不能作为成功依据，必须以工具执行结果为准。\n\n---\n\n## 二、工具 Schema\n\n工具通常用 JSON Schema 描述。\n\n```json\n{\n  \"name\": \"search_notes\",\n  \"description\": \"Sea",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 1,
    "score": 13.1561,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "end_line": 2,
    "evidence_id": "E3",
    "kind": "project_code",
    "path": "src/new_parser.py",
    "snippet": "def parse(data):\n    return data.strip().lower()",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "读取 src/new_parser.py，说明 parse 的实际处理步骤；结合 Function Calling 资料解释，为什么仅有这份源码不能声称函数已经被工具执行成功。",
        "plan_id": "199a184a9c93",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "parse 函数的源码实现与逐步处理逻辑",
            "id": "sq1",
            "query": "src/new_parser.py 中 parse 函数的实际处理步骤是什么",
            "required": true
          },
          {
            "evidence_target": "Function Calling 资料中关于工具调用与执行结果确认的说明",
            "id": "sq2",
            "query": "Function Calling 中函数被工具执行成功的判定依据是什么",
            "required": true
          },
          {
            "evidence_target": "源码与工具执行状态之间差异的证据",
            "id": "sq3",
            "query": "仅有 parse 源码为何不能证明函数已被工具执行成功",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 1,
      "profile": "PROJECT_CODE_V1",
      "required_evidence_groups": [
        [
          "project_code"
        ]
      ],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_mix_02 — COMPLETE_CORRECT

知识资料中的标准重试窗口是多少？再读取 src/main.py 的 scale 实现与常量。两者数值相同是否就能证明 LIMIT 是服务重试配置？请分别列出依据。

终态：completed；task_coverage=partial；Provider=4 请求；tokens=25036；估算费用=$0.0083694。

E4 测试语料 12 秒、E6 完整代码 LIMIT=12 与 scale 均有真实来源；最终明确否认数字相同能证明配置关系。支持该猜测的弱依据段落不宜视为真实配置证据。

### 用户实际收到的答案

## 1. 知识资料中的标准重试窗口

知识库中的 `task018_retry.md` 明确写道：服务的标准重试窗口为 **12 秒**，用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径 [E4]。

## 2. src/main.py 的 scale 实现与常量

读取 `src/main.py` 得到 [E6]：

```python
LIMIT = 12

def scale(value):
    return value * LIMIT
```

即模块级常量 `LIMIT = 12`，`scale(value)` 返回 `value * LIMIT`（把入参乘以 12）。

## 3. 数值相同能否证明 LIMIT 是服务重试配置？

**不能。** 两者数值都是 12，但数值相等只是巧合性一致，不构成因果或语义证明。分别列出依据：

**支持“LIMIT 是重试配置”的依据（弱）：**
- 知识资料给出的标准重试窗口是 12 秒 [E4]；
- 项目常量 `LIMIT = 12` [E6]；
- 二者数值相同，存在“LIMIT 可能对应重试窗口”的合理猜测空间。

**反对/不足以证明的依据（强）：**
- 知识资料 [E4] 是隔离的 RAG fixture，描述的是“服务的标准重试窗口”，并未提及 `src/main.py`、`LIMIT` 或任何代码符号，二者没有建立任何引用或映射关系；
- 项目代码 [E6] 中 `LIMIT` 仅被 `scale(value)` 用作乘法因子（`value * LIMIT`），从实现看它是数值缩放常量，没有任何重试、超时、退避或网络调用的语义；
- 代码中未见 `LIMIT` 被重试逻辑、超时配置或服务客户端引用（当前读取范围仅 1–4 行，未发现此类调用）；
- 数值相等本身是弱证据：12 是常见默认值，相同数值可能纯属巧合，不能推出语义等价。

**结论：** 数值相同只能说明“不矛盾”，不能证明 `LIMIT` 是服务重试配置。要证明这一点，需要项目内证据，例如 `LIMIT` 被重试/超时逻辑引用、配置键名或注释说明其用途，或文档明确将 `LIMIT` 与重试窗口关联。当前证据不支持该结论。

**局限：** 仅读取了 `src/main.py` 第 1–4 行，未检查该文件其余部分或其他文件中 `LIMIT` 的使用；知识资料 [E4] 为测试 fixture，其“标准重试窗口”不代表本项目实现。

未完成事项与范围限制：仅读取 src/main.py 第 1–4 行，未核查 LIMIT 在项目其他位置的引用；知识资料 E4 为隔离 RAG fixture，未与项目代码建立映射；未执行任何测试或运行验证。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

## 1. 知识资料中的标准重试窗口

知识库中的 `task018_retry.md` 明确写道：服务的标准重试窗口为 **12 秒**，用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径 [E4]。

## 2. src/main.py 的 scale 实现与常量

读取 `src/main.py` 得到 [E6]：

```python
LIMIT = 12

def scale(value):
    return value * LIMIT
```

即模块级常量 `LIMIT = 12`，`scale(value)` 返回 `value * LIMIT`（把入参乘以 12）。

## 3. 数值相同能否证明 LIMIT 是服务重试配置？

**不能。** 两者数值都是 12，但数值相等只是巧合性一致，不构成因果或语义证明。分别列出依据：

**支持“LIMIT 是重试配置”的依据（弱）：**
- 知识资料给出的标准重试窗口是 12 秒 [E4]；
- 项目常量 `LIMIT = 12` [E6]；
- 二者数值相同，存在“LIMIT 可能对应重试窗口”的合理猜测空间。

**反对/不足以证明的依据（强）：**
- 知识资料 [E4] 是隔离的 RAG fixture，描述的是“服务的标准重试窗口”，并未提及 `src/main.py`、`LIMIT` 或任何代码符号，二者没有建立任何引用或映射关系；
- 项目代码 [E6] 中 `LIMIT` 仅被 `scale(value)` 用作乘法因子（`value * LIMIT`），从实现看它是数值缩放常量，没有任何重试、超时、退避或网络调用的语义；
- 代码中未见 `LIMIT` 被重试逻辑、超时配置或服务客户端引用（当前读取范围仅 1–4 行，未发现此类调用）；
- 数值相等本身是弱证据：12 是常见默认值，相同数值可能纯属巧合，不能推出语义等价。

**结论：** 数值相同只能说明“不矛盾”，不能证明 `LIMIT` 是服务重试配置。要证明这一点，需要项目内证据，例如 `LIMIT` 被重试/超时逻辑引用、配置键名或注释说明其用途，或文档明确将 `LIMIT` 与重试窗口关联。当前证据不支持该结论。

**局限：** 仅读取了 `src/main.py` 第 1–4 行，未检查该文件其余部分或其他文件中 `LIMIT` 的使用；知识资料 [E4] 为测试 fixture，其“标准重试窗口”不代表本项目实现。

```json
[
  {
    "action": "final_answer",
    "answer": "## 1. 知识资料中的标准重试窗口\n\n知识库中的 `task018_retry.md` 明确写道：服务的标准重试窗口为 **12 秒**，用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径 [E4]。\n\n## 2. src/main.py 的 scale 实现与常量\n\n读取 `src/main.py` 得到 [E6]：\n\n```python\nLIMIT = 12\n\ndef scale(value):\n    return value * LIMIT\n```\n\n即模块级常量 `LIMIT = 12`，`scale(value)` 返回 `value * LIMIT`（把入参乘以 12）。\n\n## 3. 数值相同能否证明 LIMIT 是服务重试配置？\n\n**不能。** 两者数值都是 12，但数值相等只是巧合性一致，不构成因果或语义证明。分别列出依据：\n\n**支持“LIMIT 是重试配置”的依据（弱）：**\n- 知识资料给出的标准重试窗口是 12 秒 [E4]；\n- 项目常量 `LIMIT = 12` [E6]；\n- 二者数值相同，存在“LIMIT 可能对应重试窗口”的合理猜测空间。\n\n**反对/不足以证明的依据（强）：**\n- 知识资料 [E4] 是隔离的 RAG fixture，描述的是“服务的标准重试窗口”，并未提及 `src/main.py`、`LIMIT` 或任何代码符号，二者没有建立任何引用或映射关系；\n- 项目代码 [E6] 中 `LIMIT` 仅被 `scale(value)` 用作乘法因子（`value * LIMIT`），从实现看它是数值缩放常量，没有任何重试、超时、退避或网络调用的语义；\n- 代码中未见 `LIMIT` 被重试逻辑、超时配置或服务客户端引用（当前读取范围仅 1–4 行，未发现此类调用）；\n- 数值相等本身是弱证据：12 是常见默认值，相同数值可能纯属巧合，不能推出语义等价。\n\n**结论：** 数值相同只能说明“不矛盾”，不能证明 `LIMIT` 是服务重试配置。要证明这一点，需要项目内证据，例如 `LIMIT` 被重试/超时逻辑引用、配置键名或注释说明其用途，或文档明确将 `LIMIT` 与重试窗口关联。当前证据不支持该结论。\n\n**局限：** 仅读取了 `src/main.py` 第 1–4 行，未检查该文件其余部分或其他文件中 `LIMIT` 的使用；知识资料 [E4] 为测试 fixture，其“标准重试窗口”不代表本项目实现。",
    "limitations": "仅读取 src/main.py 第 1–4 行，未核查 LIMIT 在项目其他位置的引用；知识资料 E4 为隔离 RAG fixture，未与项目代码建立映射；未执行任何测试或运行验证。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "artifact_kind": "project_code",
        "query": "scale"
      },
      "call_id": "call_1ba53ece332c44a0b60694aaed50eb2d",
      "tool_name": "code_search"
    },
    "error_code": null,
    "result": {
      "matches": [
        {
          "line": 3,
          "path": "src/main.py",
          "text": "def scale(value):"
        }
      ]
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "path": "src/main.py",
        "target": {
          "kind": "file",
          "start_line": 1
        }
      },
      "call_id": "call_c7453a7a58c940ea9117a9820b8c88fe",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/main.py",
      "regions": [
        {
          "end_line": 4,
          "lines": [
            {
              "line": 1,
              "text": "LIMIT = 12"
            },
            {
              "line": 2,
              "text": ""
            },
            {
              "line": 3,
              "text": "def scale(value):"
            },
            {
              "line": 4,
              "text": "    return value * LIMIT"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": null,
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "file",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 8.8057,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 5.7045,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 6.5925,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "b18b61962f18f305d9e39ea5f6a5e7e2",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 1,
    "score": 14.0185,
    "snippet": "Task018 isolated RAG fixture\n\n服务的标准重试窗口为 12 秒。该设置用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径。\n",
    "source_name": "task018_retry.md"
  },
  {
    "arguments_json": "{\"artifact_kind\":\"project_code\",\"query\":\"scale\"}",
    "arguments_sha256": "05d9d7795f075054ed26f2e9582bed9f0aec34e48c2b7f3f31f4b6f1725fe9b6",
    "call_id": "call_1ba53ece332c44a0b60694aaed50eb2d",
    "completeness": "complete",
    "end_line": 3,
    "evidence_id": "E5",
    "granularity": "locator",
    "kind": "project_code",
    "path": "src/main.py",
    "requirement_eligible": false,
    "result_sha256": "67d60f0d1487737becc4dbbc734fd1f3870ba836101308cc0037ffb88184c11b",
    "scope": "literal search hit at src/main.py:3",
    "scope_paths": [
      "src/main.py"
    ],
    "start_line": 3,
    "tool_name": "code_search",
    "tool_version": "code_search_v7"
  },
  {
    "end_line": 4,
    "evidence_id": "E6",
    "kind": "project_code",
    "path": "src/main.py",
    "snippet": "LIMIT = 12\n\ndef scale(value):\n    return value * LIMIT",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "知识资料中的标准重试窗口是多少？再读取 src/main.py 的 scale 实现与常量。两者数值相同是否就能证明 LIMIT 是服务重试配置？请分别列出依据。",
        "plan_id": "31bcccb009dc",
        "query_type": "multi_entity",
        "reason_code": "MULTI_ENTITY_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "知识资料中关于标准重试窗口的数值或定义",
            "id": "sq1",
            "query": "知识资料中的标准重试窗口是多少？",
            "required": true
          },
          {
            "evidence_target": "src/main.py 中 scale 相关实现代码与常量定义",
            "id": "sq2",
            "query": "src/main.py 中 scale 的实现与常量是什么？",
            "required": true
          },
          {
            "evidence_target": "判断数值相同能否证明 LIMIT 为服务重试配置所需的依据与推理材料",
            "id": "sq3",
            "query": "两者数值相同是否就能证明 LIMIT 是服务重试配置？请分别列出依据。",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_mix_03 — COMPLETE_CORRECT

结合单元测试资料，检查 tests/test_main.py 中 scale 的断言；它能说明什么测试意图，哪些结论仍需要实际运行测试才能确认？

终态：completed；task_coverage=partial；Provider=3 请求；tokens=17682；估算费用=$0.0061263。

E6 真实断言配合 E1/E2 单元测试资料，测试意图与未执行不能宣称通过的核心边界正确；尾段把源码阅读与实际执行条件并列，表述仍需人工复核。

### 用户实际收到的答案

**测试意图（来自 tests/test_main.py）**

`tests/test_main.py` 中只有一个与 scale 相关的断言：

```python
def test_scale():
    assert scale(2) == 24
```
[E6]

从这条断言可以读出的测试意图是：它是对 `scale` 函数的一个**单点示例断言**——给定输入 `2`，期望返回 `24`。它想表达的是“`scale` 在输入 2 时应输出 24”这一具体行为契约，属于典型的示例式（example-based）单元测试，而非参数化或边界覆盖测试。

**结合单元测试资料看这条断言**

单元测试资料把断言定位为验证“期望值 vs 实际值”的手段，例如 `assertEquals(expected, actual)` 这类形式，并强调单元测试用于保证核心业务逻辑质量、配合 CI 自动化执行 [E1][E2]。对照来看，`assert scale(2) == 24` 正是这种“期望值 == 实际值”的断言形态：`24` 是期望值，`scale(2)` 是实际值。资料还提到 Mock 用于隔离依赖、Mock 验证行为而 Stub 只提供假数据 [E1][E2]；但这条断言中没有任何 mock/stub 痕迹，说明该测试意图是**直接验证 `scale` 的纯计算/转换结果**，而不是验证与外部依赖的交互行为。

**仅凭静态阅读无法确认、需要实际运行测试才能确认的结论**

1. **断言是否真的通过**：静态阅读只能看到“写了什么断言”，不能证明 `scale(2)` 实际返回 `24`。只有运行测试（如 `pytest tests/test_main.py::test_scale`）才能确认通过/失败。
2. **`scale` 的真实实现语义**：从 `scale(2) == 24` 只能反推“2 → 24”这一组映射，无法确定它是乘法（×12）、某种缩放公式、还是查表/配置驱动。要确认实现行为需读取 `scale` 的定义，而非仅凭断言推断。
3. **覆盖是否充分**：单条断言不构成对 `scale` 的完整行为覆盖。边界值、负数、零、非整数输入、异常输入等是否被正确处理，静态阅读这条测试无法回答，需要补充/运行更多测试用例。
4. **是否存在隐藏依赖或副作用**：该断言未显示 mock，但 `scale` 是否依赖全局状态、配置或 I/O，仅凭测试文件片段无法排除，需结合实现与运行结果确认。
5. **测试是否被收集/执行**：文件存在且函数名符合 `test_` 约定，但“会被测试框架收集并执行”仍需实际运行来确认。

**结论**：这条断言能说明的测试意图是“`scale` 在输入 2 时应返回 24”的示例式行为契约，且形态上属于直接结果断言而非交互验证 [E1][E2][E6]；而“断言是否通过、`scale` 的真实实现语义、覆盖是否充分、有无隐藏依赖、是否被实际执行”这些结论，都必须通过实际运行测试（及阅读 `scale` 实现）才能确认，静态阅读无法替代。

未完成事项与范围限制：本轮仅读取到 tests/test_main.py 第 1–2 行的 test_scale 断言，未读取 scale 的实现源码，也未实际运行测试；因此无法确认断言通过与否、scale 的实现语义及覆盖充分性。知识侧证据来自单元测试资料 [E1][E2]，与项目测试文件 [E6] 属不同 evidence backend。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

**测试意图（来自 tests/test_main.py）**

`tests/test_main.py` 中只有一个与 scale 相关的断言：

```python
def test_scale():
    assert scale(2) == 24
```
[E6]

从这条断言可以读出的测试意图是：它是对 `scale` 函数的一个**单点示例断言**——给定输入 `2`，期望返回 `24`。它想表达的是“`scale` 在输入 2 时应输出 24”这一具体行为契约，属于典型的示例式（example-based）单元测试，而非参数化或边界覆盖测试。

**结合单元测试资料看这条断言**

单元测试资料把断言定位为验证“期望值 vs 实际值”的手段，例如 `assertEquals(expected, actual)` 这类形式，并强调单元测试用于保证核心业务逻辑质量、配合 CI 自动化执行 [E1][E2]。对照来看，`assert scale(2) == 24` 正是这种“期望值 == 实际值”的断言形态：`24` 是期望值，`scale(2)` 是实际值。资料还提到 Mock 用于隔离依赖、Mock 验证行为而 Stub 只提供假数据 [E1][E2]；但这条断言中没有任何 mock/stub 痕迹，说明该测试意图是**直接验证 `scale` 的纯计算/转换结果**，而不是验证与外部依赖的交互行为。

**仅凭静态阅读无法确认、需要实际运行测试才能确认的结论**

1. **断言是否真的通过**：静态阅读只能看到“写了什么断言”，不能证明 `scale(2)` 实际返回 `24`。只有运行测试（如 `pytest tests/test_main.py::test_scale`）才能确认通过/失败。
2. **`scale` 的真实实现语义**：从 `scale(2) == 24` 只能反推“2 → 24”这一组映射，无法确定它是乘法（×12）、某种缩放公式、还是查表/配置驱动。要确认实现行为需读取 `scale` 的定义，而非仅凭断言推断。
3. **覆盖是否充分**：单条断言不构成对 `scale` 的完整行为覆盖。边界值、负数、零、非整数输入、异常输入等是否被正确处理，静态阅读这条测试无法回答，需要补充/运行更多测试用例。
4. **是否存在隐藏依赖或副作用**：该断言未显示 mock，但 `scale` 是否依赖全局状态、配置或 I/O，仅凭测试文件片段无法排除，需结合实现与运行结果确认。
5. **测试是否被收集/执行**：文件存在且函数名符合 `test_` 约定，但“会被测试框架收集并执行”仍需实际运行来确认。

**结论**：这条断言能说明的测试意图是“`scale` 在输入 2 时应返回 24”的示例式行为契约，且形态上属于直接结果断言而非交互验证 [E1][E2][E6]；而“断言是否通过、`scale` 的真实实现语义、覆盖是否充分、有无隐藏依赖、是否被实际执行”这些结论，都必须通过实际运行测试（及阅读 `scale` 实现）才能确认，静态阅读无法替代。

```json
[
  {
    "action": "final_answer",
    "answer": "**测试意图（来自 tests/test_main.py）**\n\n`tests/test_main.py` 中只有一个与 scale 相关的断言：\n\n```python\ndef test_scale():\n    assert scale(2) == 24\n```\n[E6]\n\n从这条断言可以读出的测试意图是：它是对 `scale` 函数的一个**单点示例断言**——给定输入 `2`，期望返回 `24`。它想表达的是“`scale` 在输入 2 时应输出 24”这一具体行为契约，属于典型的示例式（example-based）单元测试，而非参数化或边界覆盖测试。\n\n**结合单元测试资料看这条断言**\n\n单元测试资料把断言定位为验证“期望值 vs 实际值”的手段，例如 `assertEquals(expected, actual)` 这类形式，并强调单元测试用于保证核心业务逻辑质量、配合 CI 自动化执行 [E1][E2]。对照来看，`assert scale(2) == 24` 正是这种“期望值 == 实际值”的断言形态：`24` 是期望值，`scale(2)` 是实际值。资料还提到 Mock 用于隔离依赖、Mock 验证行为而 Stub 只提供假数据 [E1][E2]；但这条断言中没有任何 mock/stub 痕迹，说明该测试意图是**直接验证 `scale` 的纯计算/转换结果**，而不是验证与外部依赖的交互行为。\n\n**仅凭静态阅读无法确认、需要实际运行测试才能确认的结论**\n\n1. **断言是否真的通过**：静态阅读只能看到“写了什么断言”，不能证明 `scale(2)` 实际返回 `24`。只有运行测试（如 `pytest tests/test_main.py::test_scale`）才能确认通过/失败。\n2. **`scale` 的真实实现语义**：从 `scale(2) == 24` 只能反推“2 → 24”这一组映射，无法确定它是乘法（×12）、某种缩放公式、还是查表/配置驱动。要确认实现行为需读取 `scale` 的定义，而非仅凭断言推断。\n3. **覆盖是否充分**：单条断言不构成对 `scale` 的完整行为覆盖。边界值、负数、零、非整数输入、异常输入等是否被正确处理，静态阅读这条测试无法回答，需要补充/运行更多测试用例。\n4. **是否存在隐藏依赖或副作用**：该断言未显示 mock，但 `scale` 是否依赖全局状态、配置或 I/O，仅凭测试文件片段无法排除，需结合实现与运行结果确认。\n5. **测试是否被收集/执行**：文件存在且函数名符合 `test_` 约定，但“会被测试框架收集并执行”仍需实际运行来确认。\n\n**结论**：这条断言能说明的测试意图是“`scale` 在输入 2 时应返回 24”的示例式行为契约，且形态上属于直接结果断言而非交互验证 [E1][E2][E6]；而“断言是否通过、`scale` 的真实实现语义、覆盖是否充分、有无隐藏依赖、是否被实际执行”这些结论，都必须通过实际运行测试（及阅读 `scale` 实现）才能确认，静态阅读无法替代。",
    "limitations": "本轮仅读取到 tests/test_main.py 第 1–2 行的 test_scale 断言，未读取 scale 的实现源码，也未实际运行测试；因此无法确认断言通过与否、scale 的实现语义及覆盖充分性。知识侧证据来自单元测试资料 [E1][E2]，与项目测试文件 [E6] 属不同 evidence backend。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "tests/test_main.py",
        "target": {
          "kind": "matching",
          "query": "scale"
        }
      },
      "call_id": "call_749319e1ea214c3c9eac4b4ff82be3bb",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "tests/test_main.py",
      "regions": [
        {
          "end_line": 2,
          "lines": [
            {
              "line": 1,
              "text": "def test_scale():"
            },
            {
              "line": 2,
              "text": "    assert scale(2) == 24"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": {
            "end_line": 2,
            "kind": "function",
            "name": "test_scale",
            "start_line": 1
          },
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "test_scale",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "43c05ab81db2d80e46d539d326398b96",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 15.2506,
    "snippet": "# 单元测试\n\n---\n\n## 一、JUnit 5\n\n### 核心注解\n```java\n@Test           // 标记测试方法\n@BeforeEach     // 每个测试方法前执行\n@AfterEach      // 每个测试方法后执行\n@BeforeAll      // 所有测试前执行一次（静态方法）\n@AfterAll       // 所有测试后执行一次（静态方法）\n@DisplayName    // 测试方法显示名称\n@ParameterizedTest  // 参数化测试\n```\n\n### 断言\n```java\nassertEquals(expected, actual);\nassertNotNull(obj);\nassertThrows(Exception.class, () -> { ... });\nassertTimeout(Duration.ofSeconds(1), () -> { ... });\n```\n\n---\n\n## 二、Mockito（Mock 依赖）\n\n### 为什么需要 Mock？\n```\nServiceA 依赖 ServiceB ",
    "source_name": "unit_单元测试.md"
  },
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 13.5903,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 13.1131,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 12.4282,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "a11add31e154a2a110a64f491fab403d",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 11.9253,
    "snippet": "BM25 能改善精确术语问题的召回\n- 基线版本：commit / index / model / prompt\n- 唯一变量：retrieval strategy\n- 数据集：rag-eval-v1\n- 指标：Recall@5、MRR、P95\n- 结果：\n- 失败样本：\n- 结论：保留 / 回滚 / 继续实验\n```\n\n### 3. 回归门槛\n\n发布前可设置：\n\n```text\n核心类别 Recall@5 不下降\n整体正确率不低于基线\n权限测试 100% 通过\nP95 不超过预算\n无答案误答率不超过阈值\n```\n\n阈值应根据业务风险和当前基线确定，不照抄他人数字。\n\n---\n\n## 八、什么时候使用高级 RAG\n\n### 1. Parent-Child / Small-to-Big\n\n适合：小块更容易精确命中，但回答需要完整章节上下文。  \n代价：索引和父子映射更复杂，返回父块可能引入噪声。\n\n### 2. Contextual Retrieval\n\n为 Chunk 增加文档级背景，例如标题和简短上下文。  \n适合：原 Chunk 脱离全文后指代不清。  \n风险：生成的背景可能错误；",
    "source_name": "rag_高级RAG.md"
  },
  {
    "end_line": 2,
    "evidence_id": "E6",
    "kind": "project_test",
    "path": "tests/test_main.py",
    "snippet": "def test_scale():\n    assert scale(2) == 24",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "结合单元测试资料，检查 tests/test_main.py 中 scale 的断言；它能说明什么测试意图，哪些结论仍需要实际运行测试才能确认？",
        "plan_id": "4b85d41d0f61",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "PROJECT_TEST_V1",
      "required_evidence_groups": [
        [
          "project_test"
        ]
      ],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_mix_04 — COMPLETE_CORRECT

读取项目 docs/usage.md 与 src/main.py，结合知识资料对来源元数据的要求，说明文档与实现的对应关系，并区分知识资料和当前仓库源码的证据身份。

终态：completed；task_coverage=partial；Provider=4 请求；tokens=23734；估算费用=$0.0079689。

E4 实际 usage 文档、E5 完整 main 代码取得；E1/E2 知识身份与仓库身份分开，未声称全仓已实现元数据要求。

### 用户实际收到的答案

## 知识资料对来源元数据的要求

知识资料强调 RAG 文档处理必须保存元数据和稳定 ID，并把重复导入的幂等性作为核心要求之一 [E2]。在检索评测层面，同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标，评测时需固定索引版本、Embedding、Top-K 和随机性，并记录按类别的指标 [E1]。此外，引用质量有专门指标：Citation validity 检查引用编号是否存在，Citation correctness 检查引用内容是否支持对应陈述 [E1]。这些要求共同指向一点：来源元数据（稳定 ID、版本、类别、引用编号）是保证可复现、可追溯、可评测的基础。

## 当前仓库文档与实现的对应关系

- 文档 `docs/usage.md` 全文仅 3 行：标题 `# Usage`，以及一句说明 “Scale values with `scale`.” [E4]。它声明了一个名为 `scale` 的能力，但没有给出参数、默认值或元数据约定。
- 源码 `src/main.py` 定义了模块级常量 `LIMIT = 12`，以及函数 `scale(value)`，其实现为 `return value * LIMIT` [E5]。

对应关系：文档中提到的 `scale` 确实在源码中存在，且其行为是把输入值乘以常量 `LIMIT`（当前为 12）[E5]。也就是说，文档描述的能力与实现符号一致，但文档未说明乘数来源，实际乘数由源码常量 `LIMIT` 决定 [E5]。

## 证据身份区分

- **知识资料证据**：E1（rag_高级RAG.md）、E2（rag_文档处理.md）属于通用技术知识，说明的是 RAG 文档处理与检索评测的一般原则，不代表本项目已实现这些要求。
- **当前仓库源码/文档证据**：E4（docs/usage.md）、E5（src/main.py）是当前绑定项目的实际文件正文，反映本仓库的真实内容。

需要特别指出：知识资料要求“保存元数据和稳定 ID”“引用编号有效”等 [E1][E2]，但当前仓库的 `docs/usage.md` 与 `src/main.py` 中并未出现任何元数据、稳定 ID 或引用编号相关的实现或约定 [E4][E5]。因此不能声称本项目已满足知识资料提出的元数据要求——两者只是被并列对照，而非已证实一致。

## 局限

- 本次仅读取了 `docs/usage.md` 前 3 行与 `src/main.py` 前 4 行，均为完整小文件，但未扫描仓库其他文件，无法断言元数据机制在别处是否存在。
- 未运行任何测试或执行代码，`scale` 的行为结论来自源码静态阅读 [E5]，非运行验证。

未完成事项与范围限制：仅读取 docs/usage.md 与 src/main.py 两个文件，未覆盖仓库其余部分；未执行代码或测试，实现行为结论为静态阅读所得；知识资料与本项目实现之间不存在已证实的元数据一致性，仅作对照。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

## 知识资料对来源元数据的要求

知识资料强调 RAG 文档处理必须保存元数据和稳定 ID，并把重复导入的幂等性作为核心要求之一 [E2]。在检索评测层面，同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标，评测时需固定索引版本、Embedding、Top-K 和随机性，并记录按类别的指标 [E1]。此外，引用质量有专门指标：Citation validity 检查引用编号是否存在，Citation correctness 检查引用内容是否支持对应陈述 [E1]。这些要求共同指向一点：来源元数据（稳定 ID、版本、类别、引用编号）是保证可复现、可追溯、可评测的基础。

## 当前仓库文档与实现的对应关系

- 文档 `docs/usage.md` 全文仅 3 行：标题 `# Usage`，以及一句说明 “Scale values with `scale`.” [E4]。它声明了一个名为 `scale` 的能力，但没有给出参数、默认值或元数据约定。
- 源码 `src/main.py` 定义了模块级常量 `LIMIT = 12`，以及函数 `scale(value)`，其实现为 `return value * LIMIT` [E5]。

对应关系：文档中提到的 `scale` 确实在源码中存在，且其行为是把输入值乘以常量 `LIMIT`（当前为 12）[E5]。也就是说，文档描述的能力与实现符号一致，但文档未说明乘数来源，实际乘数由源码常量 `LIMIT` 决定 [E5]。

## 证据身份区分

- **知识资料证据**：E1（rag_高级RAG.md）、E2（rag_文档处理.md）属于通用技术知识，说明的是 RAG 文档处理与检索评测的一般原则，不代表本项目已实现这些要求。
- **当前仓库源码/文档证据**：E4（docs/usage.md）、E5（src/main.py）是当前绑定项目的实际文件正文，反映本仓库的真实内容。

需要特别指出：知识资料要求“保存元数据和稳定 ID”“引用编号有效”等 [E1][E2]，但当前仓库的 `docs/usage.md` 与 `src/main.py` 中并未出现任何元数据、稳定 ID 或引用编号相关的实现或约定 [E4][E5]。因此不能声称本项目已满足知识资料提出的元数据要求——两者只是被并列对照，而非已证实一致。

## 局限

- 本次仅读取了 `docs/usage.md` 前 3 行与 `src/main.py` 前 4 行，均为完整小文件，但未扫描仓库其他文件，无法断言元数据机制在别处是否存在。
- 未运行任何测试或执行代码，`scale` 的行为结论来自源码静态阅读 [E5]，非运行验证。

```json
[
  {
    "action": "final_answer",
    "answer": "## 知识资料对来源元数据的要求\n\n知识资料强调 RAG 文档处理必须保存元数据和稳定 ID，并把重复导入的幂等性作为核心要求之一 [E2]。在检索评测层面，同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标，评测时需固定索引版本、Embedding、Top-K 和随机性，并记录按类别的指标 [E1]。此外，引用质量有专门指标：Citation validity 检查引用编号是否存在，Citation correctness 检查引用内容是否支持对应陈述 [E1]。这些要求共同指向一点：来源元数据（稳定 ID、版本、类别、引用编号）是保证可复现、可追溯、可评测的基础。\n\n## 当前仓库文档与实现的对应关系\n\n- 文档 `docs/usage.md` 全文仅 3 行：标题 `# Usage`，以及一句说明 “Scale values with `scale`.” [E4]。它声明了一个名为 `scale` 的能力，但没有给出参数、默认值或元数据约定。\n- 源码 `src/main.py` 定义了模块级常量 `LIMIT = 12`，以及函数 `scale(value)`，其实现为 `return value * LIMIT` [E5]。\n\n对应关系：文档中提到的 `scale` 确实在源码中存在，且其行为是把输入值乘以常量 `LIMIT`（当前为 12）[E5]。也就是说，文档描述的能力与实现符号一致，但文档未说明乘数来源，实际乘数由源码常量 `LIMIT` 决定 [E5]。\n\n## 证据身份区分\n\n- **知识资料证据**：E1（rag_高级RAG.md）、E2（rag_文档处理.md）属于通用技术知识，说明的是 RAG 文档处理与检索评测的一般原则，不代表本项目已实现这些要求。\n- **当前仓库源码/文档证据**：E4（docs/usage.md）、E5（src/main.py）是当前绑定项目的实际文件正文，反映本仓库的真实内容。\n\n需要特别指出：知识资料要求“保存元数据和稳定 ID”“引用编号有效”等 [E1][E2]，但当前仓库的 `docs/usage.md` 与 `src/main.py` 中并未出现任何元数据、稳定 ID 或引用编号相关的实现或约定 [E4][E5]。因此不能声称本项目已满足知识资料提出的元数据要求——两者只是被并列对照，而非已证实一致。\n\n## 局限\n\n- 本次仅读取了 `docs/usage.md` 前 3 行与 `src/main.py` 前 4 行，均为完整小文件，但未扫描仓库其他文件，无法断言元数据机制在别处是否存在。\n- 未运行任何测试或执行代码，`scale` 的行为结论来自源码静态阅读 [E5]，非运行验证。",
    "limitations": "仅读取 docs/usage.md 与 src/main.py 两个文件，未覆盖仓库其余部分；未执行代码或测试，实现行为结论为静态阅读所得；知识资料与本项目实现之间不存在已证实的元数据一致性，仅作对照。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "docs/usage.md",
        "target": {
          "kind": "file",
          "start_line": 1
        }
      },
      "call_id": "call_3273139563594d01a336252495c64c7c",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "docs/usage.md",
      "regions": [
        {
          "end_line": 3,
          "lines": [
            {
              "line": 1,
              "text": "# Usage"
            },
            {
              "line": 2,
              "text": ""
            },
            {
              "line": 3,
              "text": "Scale values with `scale`."
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": null,
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "file",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  },
  {
    "call": {
      "arguments": {
        "path": "src/main.py",
        "target": {
          "kind": "file",
          "start_line": 1
        }
      },
      "call_id": "call_6efcce9f146a4041a82fbca4a9c26f14",
      "tool_name": "read_project_context"
    },
    "error_code": null,
    "result": {
      "mode": "targets",
      "path": "src/main.py",
      "regions": [
        {
          "end_line": 4,
          "lines": [
            {
              "line": 1,
              "text": "LIMIT = 12"
            },
            {
              "line": 2,
              "text": ""
            },
            {
              "line": 3,
              "text": "def scale(value):"
            },
            {
              "line": 4,
              "text": "    return value * LIMIT"
            }
          ],
          "mode": "definition",
          "start_line": 1
        }
      ],
      "selection_truncated": false,
      "targets": [
        {
          "candidates": [],
          "candidates_truncated": false,
          "content_complete": true,
          "definition": null,
          "fallback_reason": null,
          "next_line": null,
          "region_index": 0,
          "requested": "file",
          "status": "read",
          "truncation_reasons": []
        }
      ]
    },
    "status": "ok"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "13e50a50eeff857cc4e1bc1fb2217513",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 6.8479,
    "snippet": " NDCG\n\n当相关性存在多个等级时，NDCG 同时考虑相关程度和排名位置，适合评估 Rerank。\n\n### 5. 检索评测注意\n\n- 同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标；\n- 评测时固定索引版本、Embedding、Top-K 和随机性；\n- 记录按类别的指标，平均值可能掩盖代码题或精确术语题的失败；\n- Retrieval Recall 高不代表最终回答一定正确。\n\n---\n\n## 四、生成与端到端指标\n\n### 1. Faithfulness / Groundedness\n\n回答中的关键陈述是否得到所给证据支持。它不等于世界知识层面的事实正确：证据本身也可能错或过期。\n\n### 2. Answer Correctness\n\n回答是否覆盖参考答案的必要事实，是否包含错误结论。\n\n### 3. Answer Relevancy\n\n是否直接回答用户问题，避免虽然“都是真的”但答非所问。\n\n### 4. Citation 指标\n\n```text\nCitation validity：引用编号是否存在\nCitation correctness：引用内容是否支持对",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "90facb036b463defb76505533a6c3827",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 1,
    "score": 9.4188,
    "snippet": "形成可复现报告，而非只截图。\n\n---\n\n## 十二、面试自检\n\n1. 为什么 RAG 文档必须保存元数据和稳定 ID？\n2. 如何保证重复导入幂等？\n3. Markdown、PDF 和表格的解析难点分别是什么？\n4. Chunk 大小和 Overlap 如何影响召回与成本？\n5. Parent-Child Retrieval 解决什么问题？\n6. 为什么 Embedding 模型升级通常要重建索引？\n7. 余弦相似度和内积什么时候排序等价？\n8. 如何处理文档更新和删除？\n9. 文档中的 Prompt Injection 为什么不能只靠提示词解决？\n10. 如何证明一种分块策略比另一种更好？\n\n---\n\n> 创建时间：2026-06-14  \n> 扩展时间：2026-07-10  \n> 状态：已扩展，可直接用于主项目离线链路\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "0dbeece02ff1210c304f1ea5ace86a8d",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 2,
    "score": 5.4902,
    "snippet": "## 十四、当前学习 Agent 的最小循环\n\n第一版只暴露三个工具：\n\n```text\nsearch_notes(query, top_k, module)        只读\nrecord_weak_point(topic, evidence)        有限写入、幂等\nget_review_queue(limit)                   只读\n```\n\n实现顺序：\n\n- [ ] 非流式、单工具调用；\n- [ ] 参数 Schema 和字段级错误；\n- [ ] 最大轮次、超时和取消；\n- [ ] 多工具串行；\n- [ ] 幂等写入和授权；\n- [ ] Trace 与评测；\n- [ ] 最后再做并行和流式。\n\n---\n\n## 十五、面试自检\n\n1. 模型在 Function Calling 中真正执行函数了吗？\n2. JSON Schema 校验为什么不能代替权限校验？\n3. Agent Loop 必须有哪些终止条件？\n4. 工具结果为什么也不可信？\n5. 写工具重试为什么需要幂等键？\n6. 哪些工具可以并行，哪些不能？\n7. 如何处理 3 个并行工具中 1 个失败",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "end_line": 3,
    "evidence_id": "E4",
    "kind": "project_doc",
    "path": "docs/usage.md",
    "snippet": "# Usage\n\nScale values with `scale`.",
    "start_line": 1
  },
  {
    "end_line": 4,
    "evidence_id": "E5",
    "kind": "project_code",
    "path": "src/main.py",
    "snippet": "LIMIT = 12\n\ndef scale(value):\n    return value * LIMIT",
    "start_line": 1
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "decomposed_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "读取项目 docs/usage.md 与 src/main.py，结合知识资料对来源元数据的要求，说明文档与实现的对应关系，并区分知识资料和当前仓库源码的证据身份。",
        "plan_id": "6e5422397727",
        "query_type": "multi_entity",
        "reason_code": "MULTI_ENTITY_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": [
          {
            "evidence_target": "知识资料中关于来源元数据要求的说明",
            "id": "sq1",
            "query": "知识资料对来源元数据有哪些要求",
            "required": true
          },
          {
            "evidence_target": "docs/usage.md 中涉及来源元数据的文档描述",
            "id": "sq2",
            "query": "docs/usage.md 中与来源元数据相关的内容是什么",
            "required": true
          },
          {
            "evidence_target": "src/main.py 中涉及来源元数据的代码实现",
            "id": "sq3",
            "query": "src/main.py 中与来源元数据相关的实现是什么",
            "required": true
          }
        ]
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 1,
      "profile": "DOCS_CODE_V1",
      "required_evidence_groups": [
        [
          "project_doc"
        ],
        [
          "project_code"
        ]
      ],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ev_01 — NO_DELIVERY

读取 src/missing.py 并解释 Missing.run 的实现；如果文件或定义不存在，请明确说明，不要猜测。

终态：refused；task_coverage=unknown；Provider=3 请求；tokens=17416；估算费用=$0.0055047。

Reader 返回 PROJECT_CONTEXT_FILE_NOT_FOUND；模型给出正确且有限的不存在说明，但没有可引用 E-ID，CURRENT_RUN_EVIDENCE_REFERENCE_MISSING 误拦。

### 用户实际收到的答案

未交付。reason=INSUFFICIENT_EVIDENCE_TO_FINALIZE；failure=None。

### 模型最终提交与 Finalization 结果

来源检查 accepted=False；error=CURRENT_RUN_EVIDENCE_REFERENCE_MISSING。

无法解释 `Missing.run` 的实现，因为该文件不存在。

本轮对 `src/missing.py` 的读取返回错误码 `PROJECT_CONTEXT_FILE_NOT_FOUND`，即当前绑定项目中不存在该路径的文件，因此也无法读取其中任何定义（包括 `Missing.run`）。

需要说明的边界：
- 这是基于一次直接读取尝试的结论，仅证明该路径在当前项目中不可读/不存在，不代表对项目做了全量文件扫描。
- 由于文件不存在，`Missing.run` 的实现、签名、行为均无任何仓库证据支撑，不做任何猜测。
- 若该文件位于其他路径或名称不同，请提供确切的 repo-relative 路径，我可以再读取并解释其实现。

```json
[
  {
    "action": "final_answer",
    "answer": "无法解释 `Missing.run` 的实现，因为该文件不存在。\n\n本轮对 `src/missing.py` 的读取返回错误码 `PROJECT_CONTEXT_FILE_NOT_FOUND`，即当前绑定项目中不存在该路径的文件，因此也无法读取其中任何定义（包括 `Missing.run`）。\n\n需要说明的边界：\n- 这是基于一次直接读取尝试的结论，仅证明该路径在当前项目中不可读/不存在，不代表对项目做了全量文件扫描。\n- 由于文件不存在，`Missing.run` 的实现、签名、行为均无任何仓库证据支撑，不做任何猜测。\n- 若该文件位于其他路径或名称不同，请提供确切的 repo-relative 路径，我可以再读取并解释其实现。",
    "limitations": "仅验证了 src/missing.py 这一路径不可读（PROJECT_CONTEXT_FILE_NOT_FOUND）；未做全仓库搜索以确认是否存在同名或近似文件，也未取得任何源码正文证据，故无法解释 Missing.run 的实现。"
  }
]
```

### 实际 ToolCall / Observation

```json
[
  {
    "call": {
      "arguments": {
        "path": "src/missing.py",
        "target": {
          "kind": "file",
          "start_line": 1
        }
      },
      "call_id": "call_905b2c561ff74947a126f11fd292b4ae",
      "tool_name": "read_project_context"
    },
    "error_code": "PROJECT_CONTEXT_FILE_NOT_FOUND",
    "result": null,
    "status": "error"
  }
]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "23e9a62968d95e6e7e3d9d45fa7356a5",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 14.6301,
    "snippet": "对无法幂等的高风险操作要求明确确认，并禁止自动重试。\n\n模型生成的自然语言参数不能直接充当可靠幂等键。\n\n---\n\n## 九、多工具调用\n\n### 1. 并行条件\n\n只有互不依赖、无冲突且资源允许的只读调用才适合并行：\n\n```text\n可以并行：分别检索 Redis 和 MySQL 笔记\n不能并行：先创建订单，再用订单 ID 支付\n谨慎并行：两个工具同时修改同一学习记录\n```\n\n### 2. 结果顺序\n\n每个结果必须带原始 `call_id`，不能依赖异步完成顺序与请求顺序相同。\n\n### 3. 部分失败\n\n```text\n3 个工具：2 成功，1 超时\n```\n\n应用应把每个调用的状态分别回传，允许模型使用已有结果或说明缺失，而不是把整个批次伪装成成功。\n\n---\n\n## 十、流式输出\n\n工具调用与普通文本可能在流中分片到达。应用需要：\n\n- 按 call ID 累积工具名和参数片段；\n- 等结构完整后再解析执行；\n- 执行工具前不要把半截 JSON 当合法参数；\n- 客户端断开时取消模型与工具调用；\n- 不把模型内部工具 JSON 原样展示成最终答案；\n- 记录首 Token、",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "a8f6817b7a4814c9bfee384093816e31",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 11.6964,
    "snippet": "- 不把异常堆栈、数据库连接串或内部地址发给模型；\n- 大结果分页、摘要或保存为引用，不塞满上下文；\n- 明确结果是否截断；\n- 错误要可分类、可处理，而不是统一返回字符串 `failed`。\n\n---\n\n## 七、错误分类与重试\n\n| 错误 | 是否重试 | 处理 |\n|---|---|---|\n| JSON 参数格式错误 | 可让模型修复 1 次 | 返回字段级安全错误 |\n| 参数越界/业务不存在 | 通常不重试 | 澄清或换参数 |\n| 权限不足 | 绝不靠重试绕过 | 明确拒绝，不泄露资源是否存在 |\n| 网络超时/限流 | 有限退避重试 | 遵守总时间预算 |\n| 写操作结果未知 | 先查询幂等状态 | 不盲目重复执行 |\n| 代码 Bug | 不让模型无限重试 | 记录 Trace，降级或终止 |\n\n指数退避示意：\n\n```text\ndelay = min(base × 2^attempt + jitter, max_delay)\n```\n\n重试需要同时受最大次数、总时长和幂等性约束。\n\n---\n\n## 八、幂等性与副作用\n\n读工具通常天然较安全；写工具必须考虑重复调用。",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "6d8755088604b17b9e7eab6f95da0331",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 10.998,
    "snippet": "RAG\n\n根据问题难度选择：不检索、单次检索、多跳检索。  \n需要可靠分类器或路由规则，否则“自适应”只是不可控分支。\n\n### 5. GraphRAG\n\n适合：\n\n- 问题需要跨多个实体和关系做多跳推理；\n- 需要全局主题、社区和关系摘要；\n- 数据具有稳定实体和边。\n\n不适合：\n\n- 几十篇技术笔记的普通问答；\n- 主要问题是关键词/语义召回；\n- 没有可靠实体消歧和关系抽取；\n- 团队还没有基础评测。\n\n当前学习 Agent 不把 GraphRAG 作为首版目标。\n\n---\n\n## 九、多模态和表格 RAG\n\n### 表格\n\n- 简单表格可转为带表头的行文本；\n- 聚合、过滤和计算型问题更适合结构化查询工具，而不是纯向量检索；\n- 回答应引用单元格、行或表名。\n\n### 图片/图表\n\n- 保存图片与原文位置；\n- 使用 OCR、图像描述或多模态 Embedding；\n- 关键数值应尽量从结构化数据读取，避免只靠视觉描述猜测。\n\n### 代码\n\n- 保留仓库、文件、符号、语言和行范围；\n- 按函数/类和语法结构切分通常优于固定字符；\n- 代码问题可结合符号搜索、调用图和测试工具。\n",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "d0583e15700d2dbf4b09b22e79ca1560",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 10.7773,
    "snippet": "updated_at        更新时间\ndocument_type     markdown/pdf/html/faq/...\naccess_scope      权限范围\nversion           解析器、分块器和 Embedding 版本\n```\n\n只有文本没有元数据，后续几乎无法做可靠引用、过滤、删除和权限控制。\n\n---\n\n## 三、数据源发现与增量更新\n\n### 1. 幂等导入\n\n同一文档重复导入不应生成两套索引记录。\n\n```text\n读取文件\n  → 计算规范化内容哈希\n  → 哈希未变化：跳过\n  → 哈希变化：删除旧 Chunk 或写新版本\n  → 文件消失：标记删除并清理索引\n```\n\n可使用：\n\n```text\ndocument_id = hash(稳定业务主键或规范化路径)\nchunk_id = hash(document_id + heading_path + chunk内容 + chunker_version)\n```\n\n如果分块算法升级，`chunker_version` 必须变化，否则新旧索引容易混在一起。\n\n### 2. 全量与增量\n\n",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "13e50a50eeff857cc4e1bc1fb2217513",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 10.0224,
    "snippet": " NDCG\n\n当相关性存在多个等级时，NDCG 同时考虑相关程度和排名位置，适合评估 Rerank。\n\n### 5. 检索评测注意\n\n- 同一内容的重叠 Chunk 不应被当成多个独立正确证据刷高指标；\n- 评测时固定索引版本、Embedding、Top-K 和随机性；\n- 记录按类别的指标，平均值可能掩盖代码题或精确术语题的失败；\n- Retrieval Recall 高不代表最终回答一定正确。\n\n---\n\n## 四、生成与端到端指标\n\n### 1. Faithfulness / Groundedness\n\n回答中的关键陈述是否得到所给证据支持。它不等于世界知识层面的事实正确：证据本身也可能错或过期。\n\n### 2. Answer Correctness\n\n回答是否覆盖参考答案的必要事实，是否包含错误结论。\n\n### 3. Answer Relevancy\n\n是否直接回答用户问题，避免虽然“都是真的”但答非所问。\n\n### 4. Citation 指标\n\n```text\nCitation validity：引用编号是否存在\nCitation correctness：引用内容是否支持对",
    "source_name": "rag_高级RAG.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "读取 src/missing.py 并解释 Missing.run 的实现；如果文件或定义不存在，请明确说明，不要猜测。",
        "plan_id": "d2a548b55701",
        "query_type": "code_symbol",
        "reason_code": "CODE_SYMBOL",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ev_02 — NO_DELIVERY

请实际执行这个隔离项目的 pytest，并告诉我真实通过数量。

终态：refused；task_coverage=unknown；Provider=2 请求；tokens=9113；估算费用=$0.0027906。

无测试执行工具，模型 UNSUPPORTED_REQUEST；正确保留能力边界，没有伪造通过数量。

### 用户实际收到的答案

未交付。reason=UNSUPPORTED_REQUEST；failure=None。

### 模型最终提交与 Finalization 结果

```json
[
  {
    "action": "refuse",
    "reason_code": "UNSUPPORTED_REQUEST"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 7.2131,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "17ff0cbaaa632c5840fe5991edf44cc1",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 6.5425,
    "snippet": "| 技术手册、长章节 |\n\n### 3. 当前项目推荐\n\n```text\n第一层：按 Markdown 标题层级切 Section\n第二层：Section 超长时按段落/Token 递归切分\n索引：较小 Child Chunk\n生成：命中后可扩展到相邻 Chunk 或 Parent Section\n```\n\n初始实验可以从以下范围开始，但必须用评测调整：\n\n```text\nChunk 大小：约 300～600 tokens\nOverlap：约 10%～20%\nTop-K：先取 5～10，再 Rerank/裁剪\n```\n\n这些不是通用最佳值。代码、问答、法规、表格的最佳策略可能不同。\n\n### 4. Overlap 的代价\n\nOverlap 可以减轻边界信息丢失，但会：\n\n- 增加索引数量与 Embedding 成本；\n- 产生高度重复的检索结果；\n- 挤占生成上下文；\n- 让评测看似召回多个结果，实际都是同一段重复。\n\n应在检索后做同文档去重或多样性控制。\n\n---\n\n## 七、Embedding\n\n### 1. Embedding 是什么\n\nEmbedding 模型把文本映射到固定维",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "34711ae87ebf675e0225f41dd6fce9ca",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 5.6395,
    "snippet": "- 包含代码、表格、精确数字或版本的信息题。\n\n### 3. 数据集切分\n\n```text\n开发集：反复调分块、Top-K、Prompt\n测试集：阶段性最终比较，不用来持续调参\n线上回归集：由真实故障持续补充\n```\n\n如果一边看测试结果一边调整系统，测试集事实上已经变成开发集。\n\n### 4. 当前项目最小规模\n\n```text\n首版：30 题，用于快速建立链路\n稳定版：50～100 题，覆盖各模块和无答案样本\n每次线上/模拟面试发现失败：补 1 条回归样本\n```\n\n样本质量和覆盖面比盲目追求数量重要。\n\n---\n\n## 三、检索指标\n\n### 1. Recall@K\n\n前 K 个候选中是否包含任一标准相关证据：\n\n```text\nRecall@K = 被 Top-K 命中的可回答问题数 / 可回答问题总数\n```\n\n如果一个问题需要多个证据，还应计算 required facts 或多个证据的覆盖率，不能只命中其中一段就算完全成功。\n\n### 2. Precision@K\n\n```text\nPrecision@K = Top-K 中相关 Chunk 数 / K\n```\n\nRAG ",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "8226133a5c4c69aa456dc791cced56d7",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 4.9269,
    "snippet": "已发起 tool_call\n工具执行状态和幂等键\nToken/时间/费用预算\n取消标记\n```\n\n服务重启后不能把“执行结果未知”的写工具直接再跑一次。应先查询工具端状态或转人工处理。\n\n---\n\n## 十二、安全边界\n\n### 1. Prompt Injection\n\n工具结果、网页、文档和数据库文本都可能包含恶意指令。它们只能作为数据，不能提升权限或修改系统策略。\n\n### 2. 最小权限\n\n- 每个工具只获得完成任务所需权限；\n- 读写工具分开；\n- 不向模型暴露后台管理工具；\n- 工具列表根据用户和场景动态裁剪；\n- 高风险操作需要应用层确认，而非模型自行确认。\n\n### 3. 网络与文件\n\n- URL 工具防 SSRF：限制协议、域名/IP、重定向和响应大小；\n- 文件工具校验规范化路径，限制在授权根目录；\n- SQL 工具使用参数化和只读账号，不让模型直接生成并执行任意 SQL；\n- 代码执行放入资源受限沙箱，默认无网络和敏感文件权限。\n\n---\n\n## 十三、观测指标\n\n```text\ntool_selection_accuracy       工具选对率\nargumen",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 4.8957,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "请实际执行这个隔离项目的 pytest，并告诉我真实通过数量。",
        "plan_id": "f9cb3713ff1c",
        "query_type": "troubleshooting",
        "reason_code": "TROUBLESHOOTING_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ev_03 — COMPLETE_CORRECT

确认当前生产服务的默认重试窗口是否为 12 秒，并提供项目配置依据。

终态：completed；task_coverage=partial；Provider=3 请求；tokens=16631；估算费用=$0.0052674。

E1 明示本地测试夹具，E2 是通用重试原则；明确不能确认生产 12 秒配置，满足该证据不足题的边界要求。

### 用户实际收到的答案

无法确认“当前生产服务的默认重试窗口为 12 秒”。现有知识库证据中确实出现“服务的标准重试窗口为 12 秒”这一表述，但它来自名为 task018_retry.md 的隔离 RAG 测试夹具，明确用于测试本地 BM25 检索与普通知识问答路径，并非生产服务配置依据 [E1]。其他知识证据只给出通用重试原则，例如指数退避 delay = min(base × 2^attempt + jitter, max_delay)，以及重试需同时受最大次数、总时长和幂等性约束，并未给出 12 秒这一默认值 [E2]。因此，12 秒只能视为测试夹具中的示例值，不能作为当前生产服务默认重试窗口的确认结论。要确认生产配置，需要读取当前项目的实际配置文件或部署配置，而本轮未取得任何项目配置证据。

未完成事项与范围限制：未取得当前项目的配置/源码证据，无法核实生产服务默认重试窗口；知识库中 12 秒仅来自测试夹具 task018_retry.md，不构成生产配置依据。

### 模型最终提交与 Finalization 结果

来源检查 accepted=True；error=None。

无法确认“当前生产服务的默认重试窗口为 12 秒”。现有知识库证据中确实出现“服务的标准重试窗口为 12 秒”这一表述，但它来自名为 task018_retry.md 的隔离 RAG 测试夹具，明确用于测试本地 BM25 检索与普通知识问答路径，并非生产服务配置依据 [E1]。其他知识证据只给出通用重试原则，例如指数退避 delay = min(base × 2^attempt + jitter, max_delay)，以及重试需同时受最大次数、总时长和幂等性约束，并未给出 12 秒这一默认值 [E2]。因此，12 秒只能视为测试夹具中的示例值，不能作为当前生产服务默认重试窗口的确认结论。要确认生产配置，需要读取当前项目的实际配置文件或部署配置，而本轮未取得任何项目配置证据。

```json
[
  {
    "action": "final_answer",
    "answer": "无法确认“当前生产服务的默认重试窗口为 12 秒”。现有知识库证据中确实出现“服务的标准重试窗口为 12 秒”这一表述，但它来自名为 task018_retry.md 的隔离 RAG 测试夹具，明确用于测试本地 BM25 检索与普通知识问答路径，并非生产服务配置依据 [E1]。其他知识证据只给出通用重试原则，例如指数退避 delay = min(base × 2^attempt + jitter, max_delay)，以及重试需同时受最大次数、总时长和幂等性约束，并未给出 12 秒这一默认值 [E2]。因此，12 秒只能视为测试夹具中的示例值，不能作为当前生产服务默认重试窗口的确认结论。要确认生产配置，需要读取当前项目的实际配置文件或部署配置，而本轮未取得任何项目配置证据。",
    "limitations": "未取得当前项目的配置/源码证据，无法核实生产服务默认重试窗口；知识库中 12 秒仅来自测试夹具 task018_retry.md，不构成生产配置依据。"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "b18b61962f18f305d9e39ea5f6a5e7e2",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 21.4711,
    "snippet": "Task018 isolated RAG fixture\n\n服务的标准重试窗口为 12 秒。该设置用于测试本地 BM25 检索与 Engineering Agent 的普通知识问答路径。\n",
    "source_name": "task018_retry.md"
  },
  {
    "chunk_id": "a8f6817b7a4814c9bfee384093816e31",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 10.2021,
    "snippet": "- 不把异常堆栈、数据库连接串或内部地址发给模型；\n- 大结果分页、摘要或保存为引用，不塞满上下文；\n- 明确结果是否截断；\n- 错误要可分类、可处理，而不是统一返回字符串 `failed`。\n\n---\n\n## 七、错误分类与重试\n\n| 错误 | 是否重试 | 处理 |\n|---|---|---|\n| JSON 参数格式错误 | 可让模型修复 1 次 | 返回字段级安全错误 |\n| 参数越界/业务不存在 | 通常不重试 | 澄清或换参数 |\n| 权限不足 | 绝不靠重试绕过 | 明确拒绝，不泄露资源是否存在 |\n| 网络超时/限流 | 有限退避重试 | 遵守总时间预算 |\n| 写操作结果未知 | 先查询幂等状态 | 不盲目重复执行 |\n| 代码 Bug | 不让模型无限重试 | 记录 Trace，降级或终止 |\n\n指数退避示意：\n\n```text\ndelay = min(base × 2^attempt + jitter, max_delay)\n```\n\n重试需要同时受最大次数、总时长和幂等性约束。\n\n---\n\n## 八、幂等性与副作用\n\n读工具通常天然较安全；写工具必须考虑重复调用。",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "8226133a5c4c69aa456dc791cced56d7",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 8.5762,
    "snippet": "已发起 tool_call\n工具执行状态和幂等键\nToken/时间/费用预算\n取消标记\n```\n\n服务重启后不能把“执行结果未知”的写工具直接再跑一次。应先查询工具端状态或转人工处理。\n\n---\n\n## 十二、安全边界\n\n### 1. Prompt Injection\n\n工具结果、网页、文档和数据库文本都可能包含恶意指令。它们只能作为数据，不能提升权限或修改系统策略。\n\n### 2. 最小权限\n\n- 每个工具只获得完成任务所需权限；\n- 读写工具分开；\n- 不向模型暴露后台管理工具；\n- 工具列表根据用户和场景动态裁剪；\n- 高风险操作需要应用层确认，而非模型自行确认。\n\n### 3. 网络与文件\n\n- URL 工具防 SSRF：限制协议、域名/IP、重定向和响应大小；\n- 文件工具校验规范化路径，限制在授权根目录；\n- SQL 工具使用参数化和只读账号，不让模型直接生成并执行任意 SQL；\n- 代码执行放入资源受限沙箱，默认无网络和敏感文件权限。\n\n---\n\n## 十三、观测指标\n\n```text\ntool_selection_accuracy       工具选对率\nargumen",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "923da35884add4ef00848e501e254e06",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 7.6771,
    "snippet": "用户纠正\n高延迟 Trace\n失败和降级原因\n```\n\n反馈闭环：\n\n```text\n真实失败\n  → 人工确认根因\n  → 加入回归集\n  → 修改一个组件\n  → 离线评测\n  → 小流量验证\n  → 发布或回滚\n```\n\n不能直接把所有用户反馈自动变成训练数据，需去隐私、去攻击内容并人工抽检。\n\n---\n\n## 十一、当前项目推荐实验顺序\n\n1. 固定标题分块 + Dense，建立基线；\n2. 比较两个 Chunk 大小；\n3. 加 BM25 + RRF；\n4. 加 Rerank；\n5. 加引用校验和无答案样本；\n6. 加 Parent-Child 或相邻块扩展；\n7. 只有明确故障证据时，再做 Query Rewrite、Self-RAG 等复杂策略。\n\n每一步都保留：版本、指标、失败样本和结论。\n\n---\n\n## 十二、面试自检\n\n1. 为什么最终回答错不能直接归因于 LLM？\n2. Recall@K、MRR 和 NDCG 各关注什么？\n3. Faithfulness 与事实正确有什么区别？\n4. 如何评测引用正确性？\n5. 为什么必须加入无答案问题？\n6. LLM-as-J",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "f76781d00518b0077b2c384d7fb25a04",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 7.4599,
    "snippet": "报表，绿色=已覆盖，红色=未覆盖\n\n大厂一般要求：核心业务逻辑 > 80%\n```\n\n---\n\n## 四、大厂面试题\n\n| 问题 | 要点 |\n|------|------|\n| 你怎么保证代码质量？ | 单元测试 + Code Review + 静态代码扫描(SonarQube) + CI 自动化测试 |\n| 什么代码不需要测试？ | POJO(DTO/Entity)、getter/setter、框架配置类 |\n| Mock 和 Stub 的区别？ | Mock 验证行为(verify)，Stub 只提供假数据 |\n| 数据库怎么测？ | H2 内存数据库 或 Testcontainers 启动真实容器 |\n\n---\n\n> 创建时间：2026-06-14\n> 状态：待展开\n",
    "source_name": "unit_单元测试.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "确认当前生产服务的默认重试窗口是否为 12 秒，并提供项目配置依据。",
        "plan_id": "c3f4ff380468",
        "query_type": "fact",
        "reason_code": "SIMPLE_FACT",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 0,
      "profile": "NO_ADDITIONAL_REQUIREMENT",
      "required_evidence_groups": [],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```

## t22_ev_04 — NO_DELIVERY

确认这个提交范围里的 pytest 是否全部通过；如果只有测试源码或候选位置，请不要推断执行结果。

终态：refused；task_coverage=unknown；Provider=2 请求；tokens=9217；估算费用=$0.0028218。

没有 pytest 执行记录/能力，模型 UNSUPPORTED_REQUEST；不将测试源码或候选当作执行结果。

### 用户实际收到的答案

未交付。reason=UNSUPPORTED_REQUEST；failure=None。

### 模型最终提交与 Finalization 结果

```json
[
  {
    "action": "refuse",
    "reason_code": "UNSUPPORTED_REQUEST"
  }
]
```

### 实际 ToolCall / Observation

```json
[]
```

### Evidence inventory

```json
[
  {
    "chunk_id": "52c36a6aa220c24431e73c631219356c",
    "evidence_id": "E1",
    "kind": "knowledge",
    "rank": 1,
    "score": 10.3802,
    "snippet": "# RAG 评测、故障分析与高级策略\n\n> 核心观点：高级 RAG 的起点不是 GraphRAG 或复杂 Agent，而是可重复的评测集和故障分类。没有基线与对照实验，增加模块只会让系统更难解释。\n\n## 一、先拆开评测对象\n\nRAG 至少包含三个可独立失败的部分：\n\n```text\n数据/索引：正确证据是否被解析和入库？\n检索：正确证据是否进入候选和最终上下文？\n生成：模型是否忠实利用证据并正确回答？\n```\n\n如果最终回答错误，不能直接归因于“模型不行”。先判断：\n\n1. 标准证据在索引里吗？\n2. Top-K 召回了吗？\n3. Rerank 是否把它排掉？\n4. 最终 Prompt 是否包含它？\n5. 模型是否忽略、误读或错误综合？\n6. 引用是否正确？\n\n---\n\n## 二、构建评测集\n\n### 1. 每条样本至少包含\n\n```json\n{\n  \"question\": \"Redis AOF 重写会阻塞主进程吗？\",\n  \"reference_answer\": \"...\",\n  \"relevant_chunk_ids\": [\"chunk_a\", \"chunk_b\"],\n  \"an",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "34711ae87ebf675e0225f41dd6fce9ca",
    "evidence_id": "E2",
    "kind": "knowledge",
    "rank": 2,
    "score": 10.2339,
    "snippet": "- 包含代码、表格、精确数字或版本的信息题。\n\n### 3. 数据集切分\n\n```text\n开发集：反复调分块、Top-K、Prompt\n测试集：阶段性最终比较，不用来持续调参\n线上回归集：由真实故障持续补充\n```\n\n如果一边看测试结果一边调整系统，测试集事实上已经变成开发集。\n\n### 4. 当前项目最小规模\n\n```text\n首版：30 题，用于快速建立链路\n稳定版：50～100 题，覆盖各模块和无答案样本\n每次线上/模拟面试发现失败：补 1 条回归样本\n```\n\n样本质量和覆盖面比盲目追求数量重要。\n\n---\n\n## 三、检索指标\n\n### 1. Recall@K\n\n前 K 个候选中是否包含任一标准相关证据：\n\n```text\nRecall@K = 被 Top-K 命中的可回答问题数 / 可回答问题总数\n```\n\n如果一个问题需要多个证据，还应计算 required facts 或多个证据的覆盖率，不能只命中其中一段就算完全成功。\n\n### 2. Precision@K\n\n```text\nPrecision@K = Top-K 中相关 Chunk 数 / K\n```\n\nRAG ",
    "source_name": "rag_高级RAG.md"
  },
  {
    "chunk_id": "23e9a62968d95e6e7e3d9d45fa7356a5",
    "evidence_id": "E3",
    "kind": "knowledge",
    "rank": 3,
    "score": 9.5476,
    "snippet": "对无法幂等的高风险操作要求明确确认，并禁止自动重试。\n\n模型生成的自然语言参数不能直接充当可靠幂等键。\n\n---\n\n## 九、多工具调用\n\n### 1. 并行条件\n\n只有互不依赖、无冲突且资源允许的只读调用才适合并行：\n\n```text\n可以并行：分别检索 Redis 和 MySQL 笔记\n不能并行：先创建订单，再用订单 ID 支付\n谨慎并行：两个工具同时修改同一学习记录\n```\n\n### 2. 结果顺序\n\n每个结果必须带原始 `call_id`，不能依赖异步完成顺序与请求顺序相同。\n\n### 3. 部分失败\n\n```text\n3 个工具：2 成功，1 超时\n```\n\n应用应把每个调用的状态分别回传，允许模型使用已有结果或说明缺失，而不是把整个批次伪装成成功。\n\n---\n\n## 十、流式输出\n\n工具调用与普通文本可能在流中分片到达。应用需要：\n\n- 按 call ID 累积工具名和参数片段；\n- 等结构完整后再解析执行；\n- 执行工具前不要把半截 JSON 当合法参数；\n- 客户端断开时取消模型与工具调用；\n- 不把模型内部工具 JSON 原样展示成最终答案；\n- 记录首 Token、",
    "source_name": "agent_FunctionCalling.md"
  },
  {
    "chunk_id": "71eb6cad79adb76563bc454846a4d62d",
    "evidence_id": "E4",
    "kind": "knowledge",
    "rank": 4,
    "score": 9.4725,
    "snippet": "- 领域数据上的实际召回，而不是只看公开榜单；\n- 本地部署、延迟、吞吐与许可；\n- 是否需要归一化、推荐相似度函数是什么。\n\n### 3. 余弦、内积与归一化\n\n```text\ncosine(q, d) = q·d / (||q|| ||d||)\n```\n\n如果向量已做 L2 归一化，余弦相似度与内积排序等价。必须让索引配置与 Embedding 模型的训练方式一致。\n\n### 4. 批量生成\n\n- 批量请求提高吞吐；\n- 控制 batch 的 Token 总量，不只看条数；\n- 记录失败项并可断点续跑；\n- 对相同内容按哈希缓存向量；\n- 切换模型时不能在同一索引中混用不同向量空间。\n\n---\n\n## 八、索引写入与版本管理\n\n至少保存：\n\n```text\nembedding_model_version\nparser_version\nchunker_version\nindex_schema_version\ncreated_at\n```\n\n更新方式：\n\n```text\n1. 构建 index_v2\n2. 运行离线评测与抽样检查\n3. 将在线 alias 从 v1 切到 v2\n4. 保",
    "source_name": "rag_文档处理.md"
  },
  {
    "chunk_id": "a8f6817b7a4814c9bfee384093816e31",
    "evidence_id": "E5",
    "kind": "knowledge",
    "rank": 5,
    "score": 9.2741,
    "snippet": "- 不把异常堆栈、数据库连接串或内部地址发给模型；\n- 大结果分页、摘要或保存为引用，不塞满上下文；\n- 明确结果是否截断；\n- 错误要可分类、可处理，而不是统一返回字符串 `failed`。\n\n---\n\n## 七、错误分类与重试\n\n| 错误 | 是否重试 | 处理 |\n|---|---|---|\n| JSON 参数格式错误 | 可让模型修复 1 次 | 返回字段级安全错误 |\n| 参数越界/业务不存在 | 通常不重试 | 澄清或换参数 |\n| 权限不足 | 绝不靠重试绕过 | 明确拒绝，不泄露资源是否存在 |\n| 网络超时/限流 | 有限退避重试 | 遵守总时间预算 |\n| 写操作结果未知 | 先查询幂等状态 | 不盲目重复执行 |\n| 代码 Bug | 不让模型无限重试 | 记录 Trace，降级或终止 |\n\n指数退避示意：\n\n```text\ndelay = min(base × 2^attempt + jitter, max_delay)\n```\n\n重试需要同时受最大次数、总时长和幂等性约束。\n\n---\n\n## 八、幂等性与副作用\n\n读工具通常天然较安全；写工具必须考虑重复调用。",
    "source_name": "agent_FunctionCalling.md"
  }
]
```

### Planner 与旧 Router（只记录，不作为语义评分）

```json
{
  "planner": [
    {
      "failure_code": null,
      "fallback_used": false,
      "plan": {
        "action": "single_retrieval",
        "fallback_policy": "single_bm25_original_query",
        "original_query": "确认这个提交范围里的 pytest 是否全部通过；如果只有测试源码或候选位置，请不要推断执行结果。",
        "plan_id": "b304d802b353",
        "query_type": "troubleshooting",
        "reason_code": "TROUBLESHOOTING_EVIDENCE",
        "retrieval_required": true,
        "schema_version": "query_plan_v1",
        "subqueries": []
      },
      "task_contract": null
    }
  ],
  "requirement": [
    {
      "min_distinct_project_code_paths": 1,
      "profile": "PROJECT_CODE_V1",
      "required_evidence_groups": [
        [
          "project_code"
        ]
      ],
      "router_version": "engineering_requirement_router_v5"
    }
  ]
}
```
