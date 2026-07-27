# 基线记录

## 日期
2026-07-24

## 环境
- Python: 3.14.0
- 操作系统: Windows 11 Home China 10.0.26200
- Shell: PowerShell

## 测试结果
61 passed, 0 failed, 6 errors

6 个 errors 均为 Windows 临时目录权限问题（PermissionError: pytest-of-tu me manques），非代码缺陷。

## 依赖警告
- starlette.testclient → httpx2 deprecation（FastAPI TestClient 相关）
- asyncio.iscoroutinefunction deprecation（ChromaDB 相关）
- pkg_resources deprecated（jieba 依赖）
