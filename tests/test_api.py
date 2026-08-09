import os
import tempfile

import pytest
from fastapi import HTTPException
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
        p.index_file.return_value = {
            "status": "create",
            "document_id": "doc_mock",
            "chunks": 3,
        }
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
        assert data["status"] in ("success", "create", "update", "no_change")

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


class _RecordingReader:
    """Fake file-like that fails if read() is called without an explicit size."""

    def __init__(self, data):
        self._data = data
        self._pos = 0
        self.sizes = []

    def read(self, size=-1):
        self.sizes.append(size)
        if size is None or size < 0:
            raise AssertionError("read() called without explicit size")
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


class TestUploadSecurity:
    def test_unicode_filename_uploads_ok(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("测试文档.md", "内容".encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200
        assert resp.json()["file_name"] == "测试文档.md"

    def test_slash_traversal_rejected_and_pipeline_not_called(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("../evil.md", b"x", "text/markdown")},
        )
        assert resp.status_code == 400
        api.app.pipeline.index_file.assert_not_called()

    def test_backslash_traversal_rejected_and_pipeline_not_called(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("..\\evil.md", b"x", "text/markdown")},
        )
        assert resp.status_code == 400
        api.app.pipeline.index_file.assert_not_called()

    def test_empty_file_returns_400_and_pipeline_not_called(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("empty.md", b"", "text/markdown")},
        )
        assert resp.status_code == 400
        api.app.pipeline.index_file.assert_not_called()

    def test_file_over_limit_returns_413_and_pipeline_not_called(self, client, monkeypatch):
        monkeypatch.setattr(api.app, "MAX_UPLOAD_BYTES", 16)
        resp = client.post(
            "/index/file",
            files={"file": ("big.md", b"x" * 64, "text/markdown")},
        )
        assert resp.status_code == 413
        api.app.pipeline.index_file.assert_not_called()

    def test_pipeline_exception_returns_generic_500_without_leak(self, client):
        p = api.app.pipeline

        def boom(path):
            raise RuntimeError("secret=super-secret at /var/secret/path")

        p.index_file.side_effect = boom
        resp = client.post(
            "/index/file",
            files={"file": ("x.md", b"data", "text/markdown")},
        )
        assert resp.status_code == 500
        body = resp.text
        assert "super-secret" not in body
        assert "/var/secret/path" not in body

    def test_temp_file_cleaned_after_response(self, client):
        p = api.app.pipeline
        captured = {}

        def check_exists(path):
            captured["path"] = path
            assert os.path.exists(path), "temp file must exist during pipeline execution"
            return {"status": "create", "document_id": "doc_mock", "chunks": 3}

        p.index_file.side_effect = check_exists
        resp = client.post(
            "/index/file",
            files={"file": ("cleanup.md", b"data", "text/markdown")},
        )
        assert resp.status_code == 200
        assert not os.path.exists(captured["path"])
        assert not os.path.exists(os.path.dirname(captured["path"]))

    def test_consecutive_same_filename_gets_different_temp_paths(self, client):
        p = api.app.pipeline
        paths = []

        def capture(path):
            paths.append(path)
            return {"status": "create", "document_id": "doc_mock", "chunks": 3}

        p.index_file.side_effect = capture
        for _ in range(2):
            resp = client.post(
                "/index/file",
                files={"file": ("same.md", b"x", "text/markdown")},
            )
            assert resp.status_code == 200
        assert len(paths) == 2
        assert paths[0] != paths[1]

    def test_response_keeps_original_filename_and_fields(self, client):
        resp = client.post(
            "/index/file",
            files={"file": ("report.md", b"# hi", "text/markdown")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_name"] == "report.md"
        assert data["chunks"] == 3
        assert data["status"] == "create"

    def test_validate_filename_rejects_path_separators_and_dots(self):
        for bad in ("../evil.md", "..\\evil.md", "a/b.md", "a\\b.md", ".", ".."):
            with pytest.raises(HTTPException) as ei:
                api.app._validate_filename(bad)
            assert ei.value.status_code == 400

    @pytest.mark.parametrize(
        "bad",
        [
            'evil:name.md',
            'evil<name.md',
            'evil>name.md',
            'evil"name.md',
            'evil|name.md',
            'evil?name.md',
            'evil*name.md',
        ],
    )
    def test_validate_filename_rejects_windows_illegal_chars(self, bad):
        with pytest.raises(HTTPException) as ei:
            api.app._validate_filename(bad)
        assert ei.value.status_code == 400

    @pytest.mark.parametrize(
        "bad",
        ["evil\x00name.md", "evil\nname.md", "evil\rname.md", "evil\tname.md"],
    )
    def test_validate_filename_rejects_control_chars(self, bad):
        with pytest.raises(HTTPException) as ei:
            api.app._validate_filename(bad)
        assert ei.value.status_code == 400

    def test_validate_filename_rejects_overlong_name(self):
        with pytest.raises(HTTPException) as ei:
            api.app._validate_filename("a" * 300 + ".md")
        assert ei.value.status_code == 400

    def test_chunked_copy_reads_with_explicit_size(self):
        data = b"y" * (api.app.UPLOAD_CHUNK_SIZE * 2 + 50)
        reader = _RecordingReader(data)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.bin")
            total = api.app._copy_upload(reader, path, api.app.MAX_UPLOAD_BYTES)
        assert total == len(data)
        assert reader.sizes
        assert all(s is not None and s > 0 for s in reader.sizes)
        assert len(reader.sizes) >= 3

    def test_chunked_copy_stops_when_over_limit(self):
        reader = _RecordingReader(b"z" * 100)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.bin")
            with pytest.raises(HTTPException) as ei:
                api.app._copy_upload(reader, path, max_bytes=10)
            assert ei.value.status_code == 413
