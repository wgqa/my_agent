# HTML 知识库管理验证（2026-10-05）

## 实现范围

HTML 管理页与 Engineering 主问答共用一个持久化知识库，默认整库 BM25 检索。
页面提供文档列表、文件名筛选、分页、分段正文预览、批量上传、同名更新、指定
替换和删除确认。FastAPI 提供同源静态页面及文档 CRUD 接口。内部继续分块，
没有多知识库选择器；七工具、Planner/Decision 规则与 5/4/2 预算保持。

SQLite 保存正文、文档身份、分块和 revision。新索引成功构建并提交后才发布；
异常回滚保留旧文档。已初始化库不再重新导入初始语料，删除后重启不会恢复。
历史冻结 corpus 作为可选首次导入来源或显式 verified 模式保留，managed 库
使用独立动态 identity，不声明原 benchmark 的 verified 身份。

## 自动化检查

最终新增模块：

```powershell
python -m pytest -q tests/test_knowledge_library.py --basetemp=./.tmp_pytest_knowledge_final_04 --disable-warnings
```

结果：**20 passed / 3 warnings / 4.46s**。使用真实 SQLite、RecursiveChunker、
BM25 与 FastAPI TestClient，覆盖上传/同名更新/指定替换/删除/空库、幂等、
跨实例可见性、初始化与重启、Unicode 正文分页、索引失败回滚、尺寸/名称/
编码/无正文/损坏 PDF、PDF 页码与管理接口在旧 Pipeline/模型凭据缺失时可用。
装配检查确认主 Runtime 和文档管理保留同一个 retrieval port。

启动与历史契约检查：

```powershell
python -m pytest -q tests/test_knowledge_library.py tests/test_g11_02_theory_code.py tests/test_engineering_startup_isolation.py tests/test_engineering_planner_alignment.py tests/test_g11_02_r4_knowledge.py --basetemp=./.tmp_pytest_knowledge_fix_02 --disable-warnings
```

当时结果：**62 passed / 1 skipped / 3 warnings / 8.83s**，含当时知识库模块的
18项；后续知识库模块增为20项并单独复验，不重复累加。跳过为 Windows 无法
创建 symlink 的既有边界检查。两项此前陈旧测试断言已与现有 Reader v4 和启动隔离
行为对齐，没有为通过测试修改主决策逻辑。

独立回归集合：

```powershell
python -m pytest -q tests/test_api.py tests/test_engineering_agent_api.py tests/test_product_conversation_20.py tests/test_conversation_store_lifecycle.py tests/test_engineering_retrieval.py tests/test_unified_engineering_runtime.py tests/test_engineering_stream.py tests/test_engineering_stream_v2.py tests/test_release_startup.py --basetemp=./.tmp_pytest_knowledge_regression_03 --disable-warnings
```

结果：**151 passed / 3 warnings / 178.77s**。上述最新知识库专项20项与其它
相关回归195项无重叠，共215 passed、1 skipped。Python 编译与三个 JS 文件的
`node --check` 通过，`git diff --check` 无空白错误。CI清单新增知识库模块，
与运行手册49模块逐项一致；未执行整个清单或 GitHub Actions。

## 实际页面与检索检查

在127.0.0.1:8766临时 uvicorn 上使用独立知识库和会话数据库、dummy key，
不发送模型问题。浏览器打开实际 HTML 页面，检查：

- 初始37篇/215分块；筛选 `RAG` 返回3篇，顶部仍报告整库数量和全库检索。
- 页面上传合成 `library-upload-check.md`，显示38篇/216分块、成功提示与正文。
- 页面替换该文档，数量不变，正文由旧 marker 改为新 marker。
- 删除确认显示指定文件名；点击取消保留文档。
- 本地 API 删除同一合成文档，恢复37篇/215分块。保持同一个检索 port，
  检查替换后只命中新 marker，删除后不再命中；原37篇语料保持。
- 390px 宽度检验发现并修复旧 `100vw` 在纵向滚动时的横向溢出；复验
  `documentElement.scrollWidth == clientWidth == 375`（含15px滚动条）。

最终启动正式本地实例 `127.0.0.1:8000`，读取原有37篇/215分块，
`mode=managed`、`mutable=true`、`search_scope=all_documents`，Engineering
及各既有 capability 均 ready。正式页面文档预览可用，浏览器保留供直接操作；
正式库未加入页面测试样例。仍未提交任何模型问题。

## 边界

新增模型调用为0，不据此声明新文档的模型答案质量、跨领域泛化或高并发性能。
目前面向单机；每次修改同步重建整库 BM25，小型知识库适用。PDF 只提取可读
文字，扫描件无 OCR。历史聊天答案/引用保留原样。旧 `/index/file` 的 Chroma
资料不自动迁入新库，HTML 使用新的 Engineering 文档接口。
