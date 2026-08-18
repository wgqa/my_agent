"""G5-APP-04: thin API client for the Streamlit RAG Agent Demo Console.

统一 HTTP 处理：base_url / timeout / JSON decoding / error classification。
页面层不再散落 requests.get/post；错误统一为 ApiError（kind 区分
connection_error / timeout / http_error / invalid_response），message 面向用户。
"""

from __future__ import annotations

import requests

DEFAULT_TIMEOUT = 30.0


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

    def agent_query(self, question: str, top_k: int) -> dict:
        # 后端 AgentQueryRequest extra=forbid：只允许 question + top_k
        return self._request(
            "POST", "/agent/query", json_body={"question": question, "top_k": top_k}
        )

    def tool_agent_query(self, question: str) -> dict:
        # 后端 ToolAgentQueryRequest extra=forbid：只允许 question
        return self._request(
            "POST", "/tool-agent/query", json_body={"question": question}
        )
