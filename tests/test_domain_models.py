import json
from core.domain.models import (
    compute_content_hash, make_document_id, make_chunk_id,
    DocumentRecord, ChunkRecord,
)


class TestContentHash:
    def test_same_content_same_hash(self):
        assert compute_content_hash("hello") == compute_content_hash("hello")
        assert len(compute_content_hash("hello")) == 32

    def test_different_content_different_hash(self):
        assert compute_content_hash("hello") != compute_content_hash("world")


class TestDocumentId:
    def test_same_source_same_id(self):
        assert make_document_id("notes.md") == make_document_id("notes.md")
        assert len(make_document_id("notes.md")) == 16

    def test_different_source_different_id(self):
        assert make_document_id("a.md") != make_document_id("b.md")


class TestChunkId:
    def test_same_input_same_id(self):
        assert make_chunk_id("doc_1", 0, "text") == make_chunk_id("doc_1", 0, "text")
        assert len(make_chunk_id("doc_1", 0, "text")) == 32

    def test_content_change_id_change(self):
        assert make_chunk_id("doc_1", 0, "a") != make_chunk_id("doc_1", 0, "b")

    def test_index_change_id_change(self):
        assert make_chunk_id("doc_1", 0, "a") != make_chunk_id("doc_1", 1, "a")

    def test_different_doc_same_text_not_merged(self):
        assert make_chunk_id("doc_a", 0, "same") != make_chunk_id("doc_b", 0, "same")


class TestDocumentRecord:
    def test_basic_creation(self):
        dr = DocumentRecord(
            document_id=make_document_id("test.txt"),
            source_name="test.txt",
            source_uri="/path/to/test.txt",
            content_hash=compute_content_hash("hello"),
            file_type="txt",
        )
        assert dr.source_name == "test.txt"
        assert dr.source_uri == "/path/to/test.txt"
        assert dr.version == dr.content_hash
        assert dr.created_at is not None
        assert dr.updated_at is not None


class TestChunkRecord:
    def test_from_document_record(self):
        dr = DocumentRecord(
            document_id=make_document_id("n.md"),
            source_name="n.md",
            source_uri="/n.md",
            content_hash=compute_content_hash("hi"),
            file_type="md",
        )
        cr = ChunkRecord.from_document_record(dr, 0, "hi", token_count=2)
        assert cr.document_id == dr.document_id
        assert cr.chunk_index == 0
        assert cr.token_count == 2
        assert len(cr.chunk_id) == 32

    def test_metadata_serializable(self):
        dr = DocumentRecord(
            document_id="id", source_name="f.txt",
            source_uri="/f.txt", content_hash="abc", file_type="txt",
        )
        cr = ChunkRecord.from_document_record(dr, 0, "text", 1)
        json.dumps(cr.metadata)  # 不抛异常
