import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import api.app
from api import schemas


@pytest.fixture(autouse=True)
def mock_pipeline():
    """Mock the Pipeline class so lifespan creates a mock instead of real Pipeline"""
    with patch("api.app.Pipeline") as mock_cls:
        p = MagicMock()
        p.vector_store.count.return_value = 5
        # /health 现在通过 Config 属性访问
        from types import SimpleNamespace
        p.config = SimpleNamespace(
            _path="/secret/local/config.yaml",
            vector_store_path="/home/user/private/vector_store",
            embedding_provider="openai",
            embedding_model="text-embedding-test",
            chunker_strategy="recursive",
            chunk_size=512,
            chunk_overlap=64,
            retriever_strategy="hybrid",
            top_k=5,
            reranker_enabled=True,
            generator_provider="deepseek",
            generator_model="deepseek-test",
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
        assert data["config"]["embedding_provider"] == "openai"
        assert data["config"]["retriever_strategy"] == "hybrid"
        assert data["config"]["generator_provider"] == "deepseek"
        assert data["config"]["embedding_model"] == "text-embedding-test"
        assert "_path" not in data
        assert "vector_store_path" not in data
        assert "/secret/local" not in resp.text
        assert "/home/user/private" not in resp.text

    def test_stats_when_pipeline_not_ready(self, client):
        api.app.pipeline = None
        resp = client.get("/stats")
        assert resp.status_code == 503


class TestCapabilities:
    @pytest.mark.parametrize(
        "pipeline_ready,agent_ready,tool_ready",
        [
            (True, True, True),
            (True, False, True),
            (True, True, False),
            (True, False, False),
            (False, False, False),
        ],
    )
    def test_capabilities_reports_independent_runtime_readiness(
        self, client, monkeypatch, pipeline_ready, agent_ready, tool_ready
    ):
        monkeypatch.setattr(api.app, "pipeline", object() if pipeline_ready else None)
        monkeypatch.setattr(
            api.app, "agent_runtime", object() if agent_ready else None
        )
        monkeypatch.setattr(
            api.app,
            "tool_agent_runtime",
            object() if tool_ready else None,
        )

        resp = client.get("/capabilities")

        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "capabilities_response_v1"
        assert data["pipeline_ready"] is pipeline_ready
        assert data["agent_runtime_ready"] is agent_ready
        assert data["tool_agent_runtime_ready"] is tool_ready
        assert data["features"] == {
            "indexing": pipeline_ready,
            "basic_rag": pipeline_ready,
            "agentic_rag": agent_ready,
            "structured_tool_agent": tool_ready,
        }

    def test_capabilities_is_200_when_all_runtimes_unavailable(self, client, monkeypatch):
        monkeypatch.setattr(api.app, "pipeline", None)
        monkeypatch.setattr(api.app, "agent_runtime", None)
        monkeypatch.setattr(api.app, "tool_agent_runtime", None)

        resp = client.get("/capabilities")

        assert resp.status_code == 200
        assert resp.json()["features"] == {
            "indexing": False,
            "basic_rag": False,
            "agentic_rag": False,
            "structured_tool_agent": False,
        }


class TestOpenAPIContract:
    def test_release_endpoints_have_explicit_response_contracts(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        document = resp.json()
        paths = document["paths"]
        assert "/capabilities" in paths
        assert "/stats" in paths

        stats_schema = paths["/stats"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        capabilities_schema = paths["/capabilities"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert stats_schema["$ref"].endswith("/StatsResponse")
        assert capabilities_schema["$ref"].endswith("/CapabilitiesResponse")

        components = document["components"]["schemas"]
        assert "PublicConfigResponse" in components
        assert "FeatureCapabilities" in components
        assert "StatsResponse" in components
        assert "CapabilitiesResponse" in components


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


class TestCORS:
    def test_cors_allows_localhost_8501(self, client):
        resp = client.get("/health", headers={"Origin": "http://localhost:8501"})
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8501"

    def test_cors_allows_127_0_0_1_8501(self, client):
        resp = client.get("/health", headers={"Origin": "http://127.0.0.1:8501"})
        assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:8501"

    def test_cors_denies_evil_origin(self, client):
        resp = client.get("/health", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in resp.headers

    def test_cors_preflight_allows_expected_methods_and_headers(self, client):
        resp = client.options(
            "/query",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8501"
        assert "POST" in resp.headers.get("access-control-allow-methods", "")
        assert "content-type" in resp.headers.get("access-control-allow-headers", "").lower()

    def test_cors_does_not_allow_credentials(self, client):
        resp = client.options(
            "/query",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-credentials") != "true"

    def test_cors_config_no_wildcard_origin(self):
        cors = [m for m in api.app.app.user_middleware if m.cls is CORSMiddleware]
        assert cors
        mw = cors[0]
        opts = getattr(mw, "kwargs", None)
        if opts is None:
            opts = mw.options
            if isinstance(opts, tuple):
                opts = opts[1]
        assert "*" not in opts["allow_origins"]
        assert opts["allow_origins"] == [
            "http://localhost:8501",
            "http://127.0.0.1:8501",
        ]
        assert opts["allow_credentials"] is False
        assert opts["allow_methods"] == ["GET", "POST"]
        assert opts["allow_headers"] == ["Content-Type"]


class TestQueryInput:
    def test_top_k_zero_rejected(self, client):
        resp = client.post("/query", json={"question": "测试问题", "top_k": 0})
        assert resp.status_code == 422

    def test_top_k_above_max_rejected(self, client):
        resp = client.post("/query", json={"question": "测试问题", "top_k": 51})
        assert resp.status_code == 422

    @pytest.mark.parametrize("top_k", [1, 50])
    def test_top_k_min_and_max_valid(self, client, top_k):
        resp = client.post("/query", json={"question": "测试问题", "top_k": top_k})
        assert resp.status_code == 200

    def test_question_too_long_rejected(self, client):
        resp = client.post("/query", json={"question": "q" * 4001})
        assert resp.status_code == 422

    def test_history_too_many_messages_rejected(self, client):
        history = [{"role": "user", "content": "x"} for _ in range(21)]
        resp = client.post("/query", json={"question": "测试问题", "history": history})
        assert resp.status_code == 422

    def test_history_invalid_role_rejected(self, client):
        resp = client.post(
            "/query",
            json={"question": "测试问题", "history": [{"role": "system", "content": "x"}]},
        )
        assert resp.status_code == 422

    def test_history_content_too_long_rejected(self, client):
        resp = client.post(
            "/query",
            json={
                "question": "测试问题",
                "history": [{"role": "user", "content": "c" * 8001}],
            },
        )
        assert resp.status_code == 422

    def test_valid_history_passed_as_plain_dict(self, client):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "在的"},
        ]
        resp = client.post("/query", json={"question": "测试问题", "history": history})
        assert resp.status_code == 200
        call_kwargs = api.app.pipeline.query.call_args.kwargs
        assert call_kwargs["history"] == history
        assert all(isinstance(m, dict) for m in call_kwargs["history"])

    def test_history_uses_default_factory_not_shared_mutable(self):
        r1 = schemas.QueryRequest(question="a")
        r2 = schemas.QueryRequest(question="b")
        assert r1.history == []
        assert r2.history == []
        assert r1.history is not r2.history
        assert schemas.QueryRequest.model_fields["history"].default_factory is not None


class TestQueryException:
    def test_query_exception_returns_generic_500_without_leak(self, client):
        p = api.app.pipeline

        def boom(question, top_k=5, history=None):
            raise RuntimeError("secret=super-secret at /var/secret/path")

        p.query.side_effect = boom
        resp = client.post("/query", json={"question": "测试问题"})
        assert resp.status_code == 500
        body = resp.text
        assert "super-secret" not in body
        assert "/var/secret/path" not in body
        assert "Traceback" not in body


class TestUploadCleanup:
    @pytest.fixture
    def recording_tempdir(self, monkeypatch):
        real = tempfile.TemporaryDirectory
        created = []

        class Rec:
            def __call__(self, *args, **kwargs):
                td = real(*args, **kwargs)
                created.append(td.name)
                return td

        monkeypatch.setattr(api.app.tempfile, "TemporaryDirectory", Rec())
        return created

    def test_413_cleans_temp_directory(self, client, monkeypatch, recording_tempdir):
        monkeypatch.setattr(api.app, "MAX_UPLOAD_BYTES", 16)
        resp = client.post(
            "/index/file",
            files={"file": ("big.md", b"x" * 64, "text/markdown")},
        )
        assert resp.status_code == 413
        assert recording_tempdir
        assert not os.path.exists(recording_tempdir[0])

    def test_500_cleans_temp_directory(self, client, recording_tempdir):
        p = api.app.pipeline
        p.index_file.side_effect = RuntimeError("index boom")
        resp = client.post(
            "/index/file",
            files={"file": ("boom.md", b"data", "text/markdown")},
        )
        assert resp.status_code == 500
        assert recording_tempdir
        assert not os.path.exists(recording_tempdir[0])


# ---------------------------------------------------------------------------
# G3-RUNTIME-05B：/agent/query
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, content):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]


class _FakePlannerClient:
    def __init__(self, content):
        self._content = content
        self.calls = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        return _FakeResp(self._content)


class _FakeDirectClient:
    def __init__(self, response):
        self._response = response
        self.calls = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls += 1
        return self._response


class _FakeGen:
    def __init__(self, answer):
        self._answer = answer
        self.calls = 0

    def generate(self, question, blocks):
        self.calls += 1
        return self._answer


_SINGLE_PLAN_JSON = json.dumps(
    {
        "query_type": "fact",
        "retrieval_required": True,
        "action": "single_retrieval",
        "reason_code": "SIMPLE_FACT",
        "subqueries": [],
    },
    ensure_ascii=False,
)
_DECOMPOSED_PLAN_JSON = json.dumps(
    {
        "query_type": "comparison",
        "retrieval_required": True,
        "action": "decomposed_retrieval",
        "reason_code": "COMPARISON_EVIDENCE",
        "subqueries": [
            {"id": "sq1", "query": "甲", "evidence_target": "t", "required": True},
            {"id": "sq2", "query": "乙", "evidence_target": "t", "required": True},
        ],
    },
    ensure_ascii=False,
)


def _install_agent_runtime(monkeypatch, *, plan_json, index, gen_answer):
    """用 Fake 注入一个与网络无关的 AgentRuntime 到 api.app.agent_runtime。"""
    from core.retriever.bm25_only import BM25OnlyRetriever
    from core.agent_runtime import build_pipeline_agent_runtime

    retriever = BM25OnlyRetriever()
    retriever.build_sparse_index(index)
    gen = _FakeGen(gen_answer)
    pipeline = SimpleNamespace(retriever=retriever, generator=gen)
    planner_client = _FakePlannerClient(plan_json)
    rt = build_pipeline_agent_runtime(
        pipeline,
        planner_provider="deepseek",
        api_key="sk-api-test",
        planner_client=planner_client,
        direct_answer_client=_FakeDirectClient(_FakeResp("42")),
    )
    monkeypatch.setattr(api.app, "agent_runtime", rt)
    return planner_client, gen


class TestAgentQuery:
    def test_completed(self, client, monkeypatch):
        planner_client, gen = _install_agent_runtime(
            monkeypatch,
            plan_json=_SINGLE_PLAN_JSON,
            index=[("c1", "alpha beta", {"document_id": "d1", "source_name": "a.md"})],
            gen_answer="答案 [C1]",
        )
        resp = client.post("/agent/query", json={"question": "alpha", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "agent_query_response_v1"
        assert data["status"] == "completed"
        assert data["answer"] == "答案 [C1]"
        assert data["error_code"] is None
        assert len(data["sources"]) == 1
        s = data["sources"][0]
        assert s["citation_id"] == "[C1]"
        assert s["chunk_id"] == "c1"
        assert s["document_id"] == "d1"
        assert s["source"] == "a.md"
        assert s["rank"] == 1
        assert data["route"]["route"] == "single_retrieval"
        assert data["verification"]["status"] == "supported"
        assert len(data["trace"]) >= 7
        assert planner_client.calls == 1
        assert gen.calls == 1

    def test_refused(self, client, monkeypatch):
        _planner_client, gen = _install_agent_runtime(
            monkeypatch,
            plan_json=_SINGLE_PLAN_JSON,
            index=[],
            gen_answer="不应被调用",
        )
        resp = client.post("/agent/query", json={"question": "alpha"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "refused"
        assert data["answer"] == "现有资料不足，无法可靠回答该问题。"
        assert data["error_code"] is None
        assert data["sources"] == []
        assert gen.calls == 0

    def test_decomposed_completed(self, client, monkeypatch):
        planner_client, gen = _install_agent_runtime(
            monkeypatch,
            plan_json=_DECOMPOSED_PLAN_JSON,
            index=[
                ("c1", "甲 alpha", {"document_id": "d1", "source_name": "a.md"}),
                ("c2", "乙 beta", {"document_id": "d2", "source_name": "b.md"}),
            ],
            gen_answer="答案 [C1][C2]",
        )
        resp = client.post("/agent/query", json={"question": "alpha"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["error_code"] is None
        assert data["route"]["route"] == "decomposed_retrieval"
        assert data["route"]["router_policy_version"] == "adaptive_retrieval_policy_v1"
        assert data["route"]["strategy_reason_code"] == "DECOMPOSED_BM25_PRIMARY"
        assert data["verification"]["reason_code"] == "SUPPORTED"
        assert len(data["sources"]) == 2
        by_citation = {s["citation_id"]: s for s in data["sources"]}
        assert by_citation["[C1]"]["query_id"] == "sq1"
        assert by_citation["[C2]"]["query_id"] == "sq2"
        assert planner_client.calls == 1
        assert gen.calls == 1

    def test_decomposed_refused(self, client, monkeypatch):
        _planner_client, gen = _install_agent_runtime(
            monkeypatch,
            plan_json=_DECOMPOSED_PLAN_JSON,
            index=[],
            gen_answer="不应被调用",
        )
        resp = client.post("/agent/query", json={"question": "alpha"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "refused"
        assert data["answer"] == "现有资料不足，无法可靠回答该问题。"
        assert data["verification"]["reason_code"] == "INCOMPLETE_SUBQUERY_EVIDENCE"
        assert data["sources"] == []  # refused 的 API sources 必须为空
        assert gen.calls == 0

    def test_not_initialized_503(self, client, monkeypatch):
        monkeypatch.setattr(api.app, "agent_runtime", None)
        resp = client.post("/agent/query", json={"question": "alpha"})
        assert resp.status_code == 503

    def test_history_accepted_for_agentic_runtime(self, client, monkeypatch):
        _install_agent_runtime(
            monkeypatch,
            plan_json=_SINGLE_PLAN_JSON,
            index=[],
            gen_answer="x",
        )
        resp = client.post(
            "/agent/query",
            json={
                "question": "alpha",
                "history": [{"role": "user", "content": "旧问题"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        context_event = next(
            event for event in data["trace"]
            if event["event_type"] == "context_prepared"
        )
        assert context_event["data"]["history_messages_received"] == 1

    @pytest.mark.parametrize(
        "history",
        [
            [{"role": "system", "content": "x"}],
            [{"role": "user", "content": "   "}],
            [{"role": "user", "content": "x" * 8001}],
            [{"role": "user", "content": "x"}] * 21,
        ],
    )
    def test_history_validation(self, client, history):
        resp = client.post(
            "/agent/query", json={"question": "alpha", "history": history}
        )
        assert resp.status_code == 422

    def test_no_key_or_prompt_leak(self, client, monkeypatch):
        _install_agent_runtime(
            monkeypatch,
            plan_json=_SINGLE_PLAN_JSON,
            index=[("c1", "alpha beta", {"document_id": "d1", "source_name": "a.md"})],
            gen_answer="答案 [C1]",
        )
        resp = client.post("/agent/query", json={"question": "alpha"})
        assert resp.status_code == 200
        body = resp.text
        assert "sk-api-test" not in body
        assert "Traceback" not in body
        assert "你是一个只处理问题自身信息" not in body  # direct prompt 不泄漏
        assert "你是一个知识库问答助手" not in body  # grounded prompt 不泄漏
