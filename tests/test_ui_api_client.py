"""G5-APP-04: ui.api_client 单元测试（不引入新依赖，纯 pytest + monkeypatch）。"""

from __future__ import annotations

import pytest

import requests
from ui.api_client import ApiClient, ApiError

BASE = "http://127.0.0.1:9999"


_NOJSON = object()


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        if self._payload is _NOJSON:
            raise ValueError("not json")
        return self._payload


def _install(monkeypatch, resp, exc=None):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        if exc is not None:
            raise exc
        return resp

    monkeypatch.setattr("ui.api_client.requests.request", fake_request)
    return captured


def test_health_get_url_and_parse(monkeypatch):
    payload = {"status": "ok", "docs_count": 3, "embedding_provider": "bge"}
    captured = _install(monkeypatch, _Resp(200, payload))
    client = ApiClient(base_url=BASE)
    assert client.health() == payload
    assert captured["method"] == "GET"
    assert captured["url"] == f"{BASE}/health"


def test_query_payload_question_and_top_k(monkeypatch):
    captured = _install(monkeypatch, _Resp(200, {"answer": "a", "sources": []}))
    client = ApiClient(base_url=BASE)
    assert client.query("问题", 5) == {"answer": "a", "sources": []}
    assert captured["method"] == "POST"
    assert captured["url"] == f"{BASE}/query"
    body = captured["kwargs"]["json"]
    assert body == {"question": "问题", "top_k": 5}


def test_agent_query_only_question_and_top_k(monkeypatch):
    captured = _install(monkeypatch, _Resp(200, {"status": "completed"}))
    client = ApiClient(base_url=BASE)
    assert client.agent_query("问题", 5)["status"] == "completed"
    body = captured["kwargs"]["json"]
    assert body == {"question": "问题", "top_k": 5}
    # 禁止 UI 偷偷塞 history / provider / budget 等非用户可控字段
    for forbidden in ("history", "provider", "model", "budget", "max_iterations",
                      "max_tool_calls", "max_tool_errors", "tool", "system_prompt"):
        assert forbidden not in body


def test_tool_agent_query_only_question(monkeypatch):
    captured = _install(monkeypatch, _Resp(200, {"status": "completed"}))
    client = ApiClient(base_url=BASE)
    assert client.tool_agent_query("问题")["status"] == "completed"
    body = captured["kwargs"]["json"]
    assert body == {"question": "问题"}
    assert set(body.keys()) == {"question"}


def test_index_file_sends_multipart(monkeypatch):
    captured = _install(monkeypatch, _Resp(200, {"file_name": "a.txt", "chunks": 2}))
    client = ApiClient(base_url=BASE)
    result = client.index_file(b"content", "a.txt")
    assert result["chunks"] == 2
    assert captured["url"] == f"{BASE}/index/file"
    assert "file" in captured["kwargs"]["files"]


def test_connection_error(monkeypatch):
    _install(monkeypatch, None, exc=requests.exceptions.ConnectionError())
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as excinfo:
        client.health()
    assert excinfo.value.kind == "connection_error"


def test_timeout(monkeypatch):
    _install(monkeypatch, None, exc=requests.exceptions.Timeout())
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as excinfo:
        client.query("q", 5)
    assert excinfo.value.kind == "timeout"


def test_503_json_detail(monkeypatch):
    _install(monkeypatch, _Resp(503, {"detail": "Agent runtime not initialized"}))
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as excinfo:
        client.agent_query("q", 5)
    err = excinfo.value
    assert err.kind == "http_error"
    assert err.status == 503
    assert "运行时" in err.message


def test_500_generic_error(monkeypatch):
    _install(monkeypatch, _Resp(500, {"detail": "boom"}))
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as excinfo:
        client.query("q", 5)
    err = excinfo.value
    assert err.kind == "http_error"
    assert err.status == 500
    assert "HTTP 500" in err.message


def test_non_json_response(monkeypatch):
    _install(monkeypatch, _Resp(200, payload=_NOJSON, text="<html>not json</html>"))
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as excinfo:
        client.health()
    assert excinfo.value.kind == "invalid_response"
