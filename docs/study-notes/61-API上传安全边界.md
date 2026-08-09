# 61 - API 上传安全边界

> SEC-P0-01A：把 POST /index/file 收紧为 安全文件名 + 唯一临时目录 + 分块读取 + 20 MiB 上限 + 可靠清理 + 通用错误响应。
> 日期：2026-08-09

## 1. 原实现的缺陷

旧 `index_file`：

- `os.path.join(tempfile.gettempdir(), f"rag_{file.filename}")` 把客户端文件名直接拼进系统临时目录；
- 同名上传复用同一路径 → 覆盖与并发冲突；
- `file.file.read()` 无参全量读入内存；
- 无上传大小限制；
- 空文件仍会进入 Pipeline；
- 索引异常时 `str(e)` 直接回给客户端；
- 临时文件只靠 `finally` 里手工删除单个固定路径。

## 2. 路径穿越是什么

文件名里如果带 `../` 或 `..\`，在 `临时目录 + 原始文件名` 拼接时，路径解析会跳出临时目录，写到服务端不希望的位置。攻击者用 `../evil.md`、`..\evil.md` 可让文件落到临时目录之外。

修复不靠"信任客户端"，而是：**服务端自己校验文件名，拒绝任何路径分隔符；文件只放进服务端创建的、每次独立的临时目录。**

## 3. 为什么扩展名白名单不能防路径穿越

`.md` 白名单只拦"扩展名是否合法"，拦不住名字里的 `../`。`../evil.md` 扩展名合法（`.md`），旧代码照样把它拼进路径，穿越依然成立。扩展名白名单与路径安全是两个独立维度，必须各自校验。

## 4. 为什么独立临时目录优于共享固定路径

- 每次请求 `TemporaryDirectory()` 生成随机目录，天然避免同名文件互相覆盖与并发冲突；
- 目录归属清晰：成功、400、413、500、Pipeline 异常都随上下文退出自动清理，不依赖手工 `finally` 删除单个路径；
- 不再 `tempfile.gettempdir() + 原始文件名`，即使文件名被绕过也写不进共享区。

## 5. 为什么不能信任 Content-Length

- 请求头由客户端控制，可缺失、可伪造；
- 部分客户端/代理不发送 Content-Length（如 chunked transfer）；
- 真正的限制必须以"实际读了多少字节"为准，在分块读取循环里累计判超限，而不是只查请求头。

## 6. 分块读取如何限制内存

旧代码 `read()` 一次性把整个文件读进内存，大文件直接打爆内存。

新代码固定 `read(1 MiB)` 循环写盘：

- 每次只缓冲 1 MiB；
- 累计超过 `MAX_UPLOAD_BYTES`（20 MiB）立即抛 413 停止；
- 内存占用只与块大小有关，与文件总大小无关。

## 7. HTTP 400、413、500 的区别

- **400 Bad Request**：请求本身不合法，服务端不该收——如非法文件名、空文件、不支持扩展名；
- **413 Content Too Large**：请求体超过服务端上限，直接拒，不再读；
- **500 Internal Server Error**：请求合法但服务端处理中出错（如 Pipeline 索引异常）。

语义：400/413 是"客户端可修正的输入问题"；500 是"服务端问题"，详情不该泄露给客户端。

## 8. 为什么 HTTPException 不能被 broad except 转成 500

`except Exception` 会捕获我们自己主动抛出的 `HTTPException(400/413)`。如果统一转成 500，非法文件名、超大文件都会变成"服务端内部错误"，语义错误且误导排查。

正确姿势：

```python
try:
    ...
except HTTPException:
    raise          # 业务 HTTP 错误原样上抛
except Exception:
    logger.exception(...)
    raise HTTPException(500, "Internal indexing error")   # 只转真正未知异常
```

## 9. 如何测试临时文件清理

- 在 Pipeline 的 mock 上用 `side_effect` 记录收到的临时路径，并在调用瞬间断言 `os.path.exists(path)` 为真（证明 Pipeline 执行期间文件确实存在）；
- 响应返回后断言 `not os.path.exists(path)` 且 `not os.path.exists(os.path.dirname(path))`（临时目录也一并删除）；
- 再叠加"连续两个同名文件 → 两次路径不同"，证明不是固定路径复用。

## 10. 本任务没有解决的边界

- CORS、认证/授权（未处理）；
- `/query` 的异常泄露（留给 SEC-P0-01B）；
- QueryRequest、Citation、Pipeline、document_id 设计均未改动；
- 不做 MIME 深度检测（只按扩展名）；
- 不做 PDF 解压炸弹检测；
- 未做限流、IP 封禁、上传鉴权；
- 20 MiB 是硬编码上限，未做成可配置。
