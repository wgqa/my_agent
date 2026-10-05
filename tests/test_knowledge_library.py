"""Real SQLite + BM25 product lifecycle, independent of providers and embeddings."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.app as backend
from core.knowledge_library import KnowledgeLibrary, KnowledgeDocumentNotFound
from core.loader.base import Document


def source(name, content):
    return Document(content, {"source_name": name})


def search(library, query):
    return library.retrieval_port.search(query, "bm25", 5)


@pytest.fixture
def library(tmp_path):
    return KnowledgeLibrary(tmp_path / "knowledge.sqlite3")


@pytest.fixture
def client(monkeypatch, library):
    monkeypatch.setattr(backend, "engineering_knowledge_backend", library)
    # These HTTP tests inject a real isolated library and deliberately do not
    # enter lifespan (which would replace it and initialize embedding models).
    return TestClient(backend.app)


def test_upload_update_delete_and_empty_library_are_immediately_searchable(library):
    port = library.retrieval_port
    assert not search(library, "oldmarker")
    first = library.upload("guide.md", [source("guide.md", "oldmarker 配置说明")], size_bytes=32)
    second = library.upload("other.txt", [source("other.txt", "othermarker 测试说明")], size_bytes=32)
    assert first["status"] == "create"
    assert port.search("oldmarker", "bm25", 5)
    assert port.search("othermarker", "bm25", 5)
    updated = library.upload("guide.md", [source("guide.md", "newmarker 配置更新")], size_bytes=32)
    assert updated["status"] == "update"
    assert updated["document"]["id"] == first["document"]["id"]
    assert not port.search("oldmarker", "bm25", 5)
    assert port.search("newmarker", "bm25", 5)
    library.delete_document(first["document"]["id"])
    assert not port.search("newmarker", "bm25", 5)
    assert port.search("othermarker", "bm25", 5)
    library.delete_document(second["document"]["id"])
    assert library.identity.file_count == library.identity.chunk_count == 0
    assert not port.search("othermarker", "bm25", 5)


def test_no_change_is_idempotent_and_does_not_increment_revision(library):
    first = library.upload("same.md", [source("same.md", "same marker")], size_bytes=11)
    second = library.upload("same.md", [source("same.md", "same marker")], size_bytes=11)
    assert second["status"] == "no_change"
    assert second["revision"] == first["revision"]
    assert library.identity.file_count == 1


def test_seed_deletion_is_not_undone_by_restart_and_uploads_persist(tmp_path):
    path = tmp_path / "knowledge.sqlite3"
    seeds = [source("seed.md", "seedmarker")]
    library = KnowledgeLibrary(path, seeds=seeds)
    seed_id = library.list_documents()["items"][0]["id"]
    library.delete_document(seed_id)
    uploaded = library.upload("uploaded.md", [source("uploaded.md", "persistmarker")], size_bytes=13)
    restored = KnowledgeLibrary(path, seeds=seeds)
    assert restored.identity.file_count == 1
    assert not search(restored, "seedmarker")
    assert search(restored, "persistmarker")
    assert restored.get_document(uploaded["document"]["id"])["content"] == "persistmarker"


def test_content_is_paginated_without_loss_and_list_filters_only_names(library):
    content = "中文内容🙂" * 30
    result = library.upload("说明.md", [source("说明.md", content)], size_bytes=500)
    identifier = result["document"]["id"]
    assert library.list_documents(query="说明")["total"] == 1
    assert library.list_documents(query="中文内容")["total"] == 0
    offset, combined = 0, ""
    while True:
        detail = library.get_document(identifier, offset=offset, limit=13)
        combined += detail["content"]
        if detail["next_offset"] is None:
            break
        offset = detail["next_offset"]
    assert combined == content


def test_failed_index_rebuild_rolls_back_text_chunks_and_revision(library, monkeypatch):
    first = library.upload("guide.md", [source("guide.md", "beforemarker")], size_bytes=12)
    revision = library.revision
    def fail(_connection):
        raise RuntimeError("index build failed")
    with monkeypatch.context() as patch:
        patch.setattr(library, "_build_snapshot", fail)
        with pytest.raises(RuntimeError):
            library.upload("guide.md", [source("guide.md", "aftermarker")], size_bytes=11)
        with pytest.raises(RuntimeError):
            library.delete_document(first["document"]["id"])
    assert library.revision == revision
    assert library.get_document(first["document"]["id"])["content"] == "beforemarker"
    assert search(library, "beforemarker")
    assert not search(library, "aftermarker")


def test_second_library_instance_observes_committed_mutations(tmp_path):
    path = tmp_path / "knowledge.sqlite3"
    first, second = KnowledgeLibrary(path), KnowledgeLibrary(path)
    uploaded = first.upload("one.md", [source("one.md", "concurrentmarker")], size_bytes=16)
    assert search(second, "concurrentmarker")
    first.delete_document(uploaded["document"]["id"])
    assert not search(second, "concurrentmarker")


def test_http_upload_replace_delete_lifecycle_uses_product_port(client, library):
    uploaded = client.post("/engineering/knowledge/documents", files={"file": ("HTTP.md", b"httpoldmarker")})
    assert uploaded.status_code == 200
    identifier = uploaded.json()["document"]["id"]
    assert search(library, "httpoldmarker")
    assert client.get("/engineering/knowledge/documents").json()["search_scope"] == "all_documents"
    assert client.get(f"/engineering/knowledge/documents/{identifier}").json()["content"] == "httpoldmarker"
    replaced = client.put(f"/engineering/knowledge/documents/{identifier}", files={"file": ("updated.md", b"httpnewmarker")})
    assert replaced.json()["document"]["id"] == identifier
    assert not search(library, "httpoldmarker")
    assert search(library, "httpnewmarker")
    assert client.delete(f"/engineering/knowledge/documents/{identifier}").status_code == 204
    assert not search(library, "httpnewmarker")
    assert client.get(f"/engineering/knowledge/documents/{identifier}").status_code == 404
    assert client.delete(f"/engineering/knowledge/documents/{identifier}").status_code == 404


@pytest.mark.parametrize("name,content,status", [
    ("../bad.md", b"text", 400), ("bad.exe", b"text", 400),
    ("empty.md", b"", 400), ("binary.md", b"\xff\xfe", 400),
    ("spaces.md", b"   ", 400),
    ("broken.pdf", b"not a PDF", 400),
])
def test_invalid_upload_is_rejected_without_changes(client, library, name, content, status):
    revision = library.revision
    assert client.post("/engineering/knowledge/documents", files={"file": (name, content)}).status_code == status
    assert library.identity.file_count == 0
    assert library.revision == revision


def test_size_limit_and_replacement_conflict_preserve_existing_content(client, library, monkeypatch):
    first = client.post("/engineering/knowledge/documents", files={"file": ("first.md", b"firstmarker")}).json()
    second = client.post("/engineering/knowledge/documents", files={"file": ("second.md", b"secondmarker")}).json()
    identifier = first["document"]["id"]
    assert client.put(f"/engineering/knowledge/documents/{identifier}", files={"file": ("second.md", b"changedmarker")}).status_code == 409
    assert library.identity.file_count == 2
    assert search(library, "firstmarker") and search(library, "secondmarker")
    monkeypatch.setattr(backend, "MAX_UPLOAD_BYTES", 4)
    assert client.post("/engineering/knowledge/documents", files={"file": ("big.md", b"12345")}).status_code == 413
    assert library.get_document(second["document"]["id"])["content"] == "secondmarker"


def test_pdf_upload_extracts_readable_content_and_keeps_page_provenance(client, library):
    import fitz
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "pdfuniquemarker")
        payload = document.tobytes()
    result = client.post("/engineering/knowledge/documents", files={"file": ("paper.pdf", payload)})
    assert result.status_code == 200
    detail = client.get("/engineering/knowledge/documents/" + result.json()["document"]["id"]).json()
    assert "pdfuniquemarker" in detail["content"]
    hit = search(library, "pdfuniquemarker")[0]
    assert hit.source_name == "paper.pdf" and hit.document_id == detail["id"]
    with library._connection() as connection:
        import json
        row = connection.execute("SELECT metadata FROM chunks WHERE id=?", (hit.chunk_id,)).fetchone()
    assert json.loads(row[0])["page_num"] == 1


def test_management_is_available_without_legacy_pipeline_or_model_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_MODE", "managed")
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_DB", str(tmp_path / "managed.sqlite3"))
    monkeypatch.setenv("ENGINEERING_CONVERSATION_DB", str(tmp_path / "conversations.sqlite3"))
    monkeypatch.delenv("ENGINEERING_KNOWLEDGE_CORPUS_ROOT", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    def fail(**_kwargs):
        raise RuntimeError("legacy unavailable")
    monkeypatch.setattr(backend, "Pipeline", fail)
    with TestClient(backend.app) as active:
        status = active.get("/engineering/knowledge").json()
        assert status["mode"] == "managed" and status["mutable"] is True
        assert status["verified"] is False
        uploaded = active.post("/engineering/knowledge/documents", files={"file": ("offline.md", b"offlineuniquemarker")})
        assert uploaded.status_code == 200
        assert search(backend.engineering_knowledge_backend, "offlineuniquemarker")
        assert active.get("/").status_code == 200
        assert active.get("/js/knowledge.js").status_code == 200


def test_product_runtime_and_management_share_the_same_live_port(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_MODE", "managed")
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_DB", str(tmp_path / "knowledge.sqlite3"))
    monkeypatch.setenv("ENGINEERING_CONVERSATION_DB", str(tmp_path / "conversations.sqlite3"))
    monkeypatch.delenv("ENGINEERING_KNOWLEDGE_CORPUS_ROOT", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    monkeypatch.setattr(backend, "Pipeline", lambda **_kwargs: None)
    ports = []
    real_builder = backend.build_tool_agent_runtime
    def capture(**kwargs):
        ports.append(kwargs["retrieval_port"])
        return real_builder(**kwargs)
    monkeypatch.setattr(backend, "build_tool_agent_runtime", capture)
    with TestClient(backend.app) as active:
        assert active.get("/capabilities").json()["features"]["engineering_agent"] is True
        port = ports[0]
        assert port is backend.engineering_knowledge_backend.retrieval_port
        response = active.post("/engineering/knowledge/documents", files={"file": ("runtime.md", b"runtimeuniquemarker")})
        assert port.search("runtimeuniquemarker", "bm25", 5)
        active.delete("/engineering/knowledge/documents/" + response.json()["document"]["id"])
        assert not port.search("runtimeuniquemarker", "bm25", 5)


def test_readonly_evaluation_mode_cannot_mutate_frozen_corpus(client, monkeypatch):
    monkeypatch.setattr(backend, "engineering_knowledge_backend", SimpleNamespace())
    assert client.get("/engineering/knowledge/documents").status_code == 409
    assert client.post("/engineering/knowledge/documents", files={"file": ("no.md", b"no")}).status_code == 409


def test_initialized_product_library_no_longer_requires_seed_corpus(tmp_path, monkeypatch):
    path = tmp_path / "knowledge.sqlite3"
    library = KnowledgeLibrary(path, seeds=[source("seed.md", "originalmarker")])
    library.delete_document(library.list_documents()["items"][0]["id"])
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_MODE", "managed")
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_DB", str(path))
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_CORPUS_ROOT", str(tmp_path / "missing-corpus"))
    def fail(*_args, **_kwargs):
        raise AssertionError("Initialized libraries must not reload deleted seeds")
    monkeypatch.setattr(backend, "build_verified_engineering_knowledge", fail)
    restored = backend._build_product_knowledge()
    assert restored.identity.file_count == 0
    assert not search(restored, "originalmarker")


def test_query_and_pagination_bounds(client):
    assert client.get("/engineering/knowledge/documents?limit=101").status_code == 422
    assert client.get("/engineering/knowledge/documents?offset=-1").status_code == 422
    assert client.get("/engineering/knowledge/documents/missing?limit=50001").status_code == 422
