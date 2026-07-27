from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import hashlib


# ── 工具函数 ──────────────────────────────────────────

def compute_content_hash(content: str) -> str:
    """对文本内容计算 sha256 摘要（前 32 字符）"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


def make_document_id(source_name: str) -> str:
    """从原始文件名生成稳定的 document_id"""
    raw = f"doc:{source_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_chunk_id(document_id: str, chunk_index: int, content: str) -> str:
    """document_id + chunk_index + content → 稳定 chunk_id"""
    raw = f"{document_id}:{chunk_index}:{compute_content_hash(content)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── 领域模型 ──────────────────────────────────────────

@dataclass
class DocumentRecord:
    """文档级别的身份信息"""
    document_id: str
    source_name: str                           # 用户看到的文件名
    source_uri: str                            # 文件真实路径
    content_hash: str                          # 原始文件内容的 hash
    file_type: str                             # txt / md / pdf / py / java ...
    version: str = ""                          # 内容版本（默认用 content_hash）
    title: Optional[str] = None
    language: str = "zh"
    status: str = "indexing"                   # indexing / active / failed / deleted
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        if not self.version:
            self.version = self.content_hash


@dataclass
class ChunkRecord:
    """单个 chunk 的完整身份信息"""
    chunk_id: str
    document_id: str
    document_version: str
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    page_number: Optional[int] = None
    title_path: list = field(default_factory=list)
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def from_document_record(doc_rec: DocumentRecord, chunk_index: int,
                             content: str, token_count: int = 0,
                             page_number: int | None = None) -> "ChunkRecord":
        return ChunkRecord(
            chunk_id=make_chunk_id(doc_rec.document_id, chunk_index, content),
            document_id=doc_rec.document_id,
            document_version=doc_rec.version,
            chunk_index=chunk_index,
            content=content,
            content_hash=compute_content_hash(content),
            token_count=token_count,
            page_number=page_number,
            metadata={"source_name": doc_rec.source_name},
        )
