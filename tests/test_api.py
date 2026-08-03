import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import api.app


@pytest.fixture(autouse=True)
def mock_pipeline():
    """Mock the Pipeline class so lifespan creates a mock instead of real Pipeline"""
    with patch("api.app.Pipeline") as mock_cls:
        p = MagicMock()
        p.vector_store.count.return_value = 5
        # /health 现在通过 Config 属性访问
        from types import SimpleNamespace
        p.config = SimpleNamespace(
            embedding_provider="openai",
            retriever_strategy="hybrid",
            generator_provider="deepseek",
        )
        p.index_file.return_value = 3
        p.query.return_value = {
            "answer": "测试回答",
            "sources": [
                {"content": "测试内容", "source": "test.txt", "score": 0.85},
            ],
        }
        mock_cls.return_value = p
        yield


@pytest.fixture()
def client():
    with TestClient(api.app.app) as c:
        yield c


class TestHealth:
    def test_health_returns_status_and_count(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["docs_count"] == 5
        assert data["embedding_provider"] == "openai"
        assert data["retriever_strategy"] == "hybrid"
        assert data["generator_provider"] == "deepseek"

    def test_health_when_pipeline_not_ready(self, client):
        api.app.pipeline = None
        resp = client.get("/health")
        assert resp.status_code == 503


class TestStats:
    def test_stats_returns_config_and_count(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents_count"] == 5
        assert "config" in data

    def test_stats_when_pipeline_not_ready(self, client):
        api.app.pipeline = None
        resp = client.get("/stats")
        assert resp.status_code == 503


class TestIndex:
    def test_index_txt_file(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_name"] == "test.txt"
        assert data["chunks"] == 3
        assert data["status"] == "success"

    def test_index_unsupported_file_type(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("test.png", b"fake png", "image/png")},
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_index_empty_filename(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("", b"", "application/octet-stream")},
        )
        assert resp.status_code == 422

    def test_index_when_pipeline_not_ready(self, client):
        api.app.pipeline = None
        resp = client.post(
            "/index/file",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 503

    def test_index_pdf_file(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake pdf", "application/pdf")},
        )
        assert resp.status_code == 200

    def test_index_python_file(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("main.py", b"print('hello')", "text/x-python")},
        )
        assert resp.status_code == 200


class TestQuery:
    def test_query_returns_answer_and_sources(self, client):
        resp = client.post("/query", json={"question": "测试问题", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "测试回答"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["source"] == "test.txt"

    def test_query_with_default_top_k(self, client):
        resp = client.post("/query", json={"question": "测试问题"})
        assert resp.status_code == 200

    def test_query_empty_question(self, client):
        resp = client.post("/query", json={"question": "   "})
        assert resp.status_code == 400

    def test_query_when_pipeline_not_ready(self, client):
        api.app.pipeline = None
        resp = client.post("/query", json={"question": "测试问题"})
        assert resp.status_code == 503
