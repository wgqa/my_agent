"""G5-APP-04: thin API client for the Streamlit RAG Agent Demo Console.

统一 HTTP 处理：base_url / timeout / JSON decoding / error classification。
页面层不再散落 requests.get/post；错误统一为 ApiError（kind 区分
connection_error / timeout / http_error / invalid_response），message 面向用户。
"""

from __future__ import annotations

import json

import requests

DEFAULT_TIMEOUT = 30.0
ENGINEERING_STREAM_SCHEMA = "engineering_query_stream_v1"


class ApiError(Exception):
    """面向 UI 的结构化错误。kind 用于页面层选择提示文案。"""

    def __init__(
        self,
        kind: str,
        message: str,
        status: int | None = None,
        detail: str | None = None,
    ):
        super().__init__(message)
        self.kind = kind  # connection_error | timeout | http_error | invalid_response
        self.message = message
        self.status = status
        self.detail = detail


class ApiClient:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, *, json_body=None, files=None, timeout=None) -> dict:
        try:
            resp = requests.request(
                method,
                self._url(path),
                json=json_body,
                files=files,
                timeout=timeout or self.timeout,
            )
        except requests.exceptions.Timeout:
            raise ApiError("timeout", "请求超时")
        except requests.exceptions.ConnectionError:
            raise ApiError("connection_error", "无法连接 API，请先启动后端")
        except requests.exceptions.RequestException as exc:
            raise ApiError("connection_error", f"请求失败: {type(exc).__name__}")

        try:
            data = resp.json()
        except ValueError:
            snippet = (resp.text or "")[:200]
            raise ApiError(
                "invalid_response",
                "API 返回了无法解析的响应",
                status=resp.status_code,
                detail=snippet,
            )

        if resp.status_code >= 400:
            detail = data.get("detail", "") if isinstance(data, dict) else ""
            if resp.status_code == 503:
                raise ApiError(
                    "http_error",
                    "运行时当前不可用（Runtime not ready）",
                    status=503,
                    detail=detail,
                )
            raise ApiError(
                "http_error",
                f"请求失败（HTTP {resp.status_code}）",
                status=resp.status_code,
                detail=detail,
            )
        return data

    # ── 端点 ──────────────────────────────────────────────
    def health(self) -> dict:
        return self._request("GET", "/health")

    def stats(self) -> dict:
        return self._request("GET", "/stats")

    def capabilities(self) -> dict:
        return self._request("GET", "/capabilities")

    def project(self) -> dict:
        return self._request("GET", "/project")

    def engineering_knowledge(self) -> dict:
        return self._request("GET", "/engineering/knowledge")

    def index_file(self, file_bytes: bytes, filename: str) -> dict:
        files = {"file": (filename, file_bytes)}
        try:
            return self._request("POST", "/index/file", files=files, timeout=60.0)
        except requests.exceptions.Timeout:
            raise ApiError("timeout", "上传超时")

    def query(self, question: str, top_k: int) -> dict:
        return self._request(
            "POST", "/query", json_body={"question": question, "top_k": top_k}
        )

    def agent_query(self, question: str, top_k: int, history=None) -> dict:
        # history is an Agentic-only conversation field; other endpoints never
        # receive it. Omit the field when there is no history for compatibility.
        body = {"question": question, "top_k": top_k}
        if history:
            body["history"] = [
                {"role": item["role"], "content": item["content"]}
                for item in history
            ]
        return self._request(
            "POST", "/agent/query", json_body=body
        )

    def tool_agent_query(self, question: str) -> dict:
        # 后端 ToolAgentQueryRequest extra=forbid：只允许 question
        return self._request(
            "POST", "/tool-agent/query", json_body={"question": question}
        )

    def engineering_query(self, question: str) -> dict:
        """Submit the public Engineering Agent request boundary.

        The backend deliberately accepts only the user's question. Project,
        prompt, budget, and evidence policy remain system-managed.
        """
        return self._request(
            "POST", "/engineering/query", json_body={"question": question}
        )

    def engineering_query_stream(self, question: str):
        """Yield decoded Engineering SSE events as they arrive.

        SSE intentionally bypasses ``_request`` because that helper waits for
        a complete JSON response. The response is kept open only for this
        generator invocation, and the bounded tuple timeout leaves room for
        the server's keep-alive comments.
        """
        saw_done = False
        try:
            response = requests.post(
                self._url("/engineering/query/stream"),
                json={"question": question},
                stream=True,
                timeout=(5.0, 30.0),
            )
            with response:
                status_code = getattr(response, "status_code", None)
                headers = getattr(response, "headers", {}) or {}
                content_type = headers.get("Content-Type") or headers.get(
                    "content-type", ""
                )
                if status_code is None:
                    raise ApiError(
                        "invalid_response",
                        "API 返回了无效的流式响应",
                    )
                if status_code >= 400:
                    detail = ""
                    try:
                        payload = response.json()
                        if isinstance(payload, dict):
                            detail = str(payload.get("detail", ""))
                    except (ValueError, AttributeError):
                        detail = ""
                    if status_code == 503:
                        raise ApiError(
                            "http_error",
                            "运行时当前不可用（Runtime not ready）",
                            status=503,
                            detail=detail,
                        )
                    raise ApiError(
                        "http_error",
                        f"请求失败（HTTP {status_code}）",
                        status=status_code,
                        detail=detail,
                    )
                if not str(content_type).lower().startswith("text/event-stream"):
                    raise ApiError(
                        "invalid_response",
                        "API 返回了无效的流式响应类型",
                        status=status_code,
                    )
                schema = headers.get("X-Engineering-Stream-Schema") or headers.get(
                    "x-engineering-stream-schema"
                )
                if schema != ENGINEERING_STREAM_SCHEMA:
                    raise ApiError(
                        "invalid_response",
                        "API 返回了未知的流式协议",
                        status=status_code,
                    )
                for raw_line in response.iter_lines(decode_unicode=True):
                    if isinstance(raw_line, bytes):
                        raw_line = raw_line.decode("utf-8", errors="replace")
                    line = str(raw_line or "")
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].lstrip())
                    except (TypeError, ValueError):
                        raise ApiError(
                            "invalid_response",
                            "API 返回了无法解析的流式事件",
                            status=status_code,
                        ) from None
                    if not isinstance(event, dict) or not isinstance(
                        event.get("type"), str
                    ):
                        raise ApiError(
                            "invalid_response",
                            "API 返回了无效的流式事件",
                            status=status_code,
                        )
                    if saw_done:
                        raise ApiError(
                            "invalid_response",
                            "流式响应在结束事件后仍有内容",
                            status=status_code,
                        )
                    if event["type"] == "done":
                        saw_done = True
                    yield event
                if not saw_done:
                    raise ApiError(
                        "invalid_response",
                        "流式响应未正常结束",
                        status=status_code,
                    )
        except ApiError:
            raise
        except requests.exceptions.Timeout:
            raise ApiError("timeout", "请求超时")
        except requests.exceptions.ConnectionError:
            raise ApiError("connection_error", "无法连接 API，请先启动后端")
        except requests.exceptions.RequestException as exc:
            raise ApiError("connection_error", f"请求失败: {type(exc).__name__}")
        except (UnicodeError, AttributeError, TypeError):
            raise ApiError("invalid_response", "API 返回了无效的流式响应")
