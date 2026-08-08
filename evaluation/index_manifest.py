"""G2-ER-05：IndexManifest 不可变模型与原子 JSON 写入。

记录一次实验语料入库的完整可复现快照（ExperimentConfig、CorpusEntry 清单、
逐文件入库结果、Dense/Sparse 数量一致性），并保证：
- UTF-8 JSON、字段明确、序列化稳定（sort_keys=True）；
- 不依赖 Python 对象地址，不写绝对 corpus_root，不写 API Key/对象 repr；
- 相同配置 + 相同 Corpus + 相同入库结果 -> 相同业务内容。
"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Union

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FileIndexRecord:
    """单个语料文件的入库结果"""

    relative_path: str
    sha256: str
    size_bytes: int
    document_id: str
    chunks: int
    status: str


@dataclass(frozen=True)
class IndexManifest:
    """一次实验入库的不可变清单"""

    schema_version: int = MANIFEST_SCHEMA_VERSION
    experiment_id: str = ""
    corpus_id: str = ""
    chunk_strategy: str = ""
    retriever_strategy: str = ""
    config: dict = field(default_factory=dict)
    corpus_entries: tuple = ()
    files: tuple = ()
    file_count: int = 0
    total_chunks: int = 0
    vector_store_count: int = 0
    sparse_index_count: Optional[int] = None
    corpus_scoped_tokenizer_behavior_fingerprint: Optional[str] = None
    actual_content_token_max: Optional[int] = None
    actual_model_input_token_max: Optional[int] = None
    actual_would_truncate_count: Optional[int] = None

    def to_dict(self) -> dict:
        """固定字段顺序的纯 dict；tuple 转 list，保证 JSON 可序列化"""
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "corpus_id": self.corpus_id,
            "chunk_strategy": self.chunk_strategy,
            "retriever_strategy": self.retriever_strategy,
            "config": self.config,
            "corpus_entries": [dict(e) for e in self.corpus_entries],
            "files": [asdict(f) for f in self.files],
            "file_count": self.file_count,
            "total_chunks": self.total_chunks,
            "vector_store_count": self.vector_store_count,
            "sparse_index_count": self.sparse_index_count,
            "corpus_scoped_tokenizer_behavior_fingerprint": (
                self.corpus_scoped_tokenizer_behavior_fingerprint
            ),
            "actual_content_token_max": self.actual_content_token_max,
            "actual_model_input_token_max": self.actual_model_input_token_max,
            "actual_would_truncate_count": self.actual_would_truncate_count,
        }

    def to_json(self) -> str:
        """UTF-8 JSON；sort_keys=True 使键顺序稳定，业务内容可复现"""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    def write_json(self, path: Union[str, Path]) -> None:
        """原子写入：同目录临时文件 -> flush -> fsync -> close -> os.replace。

        中途失败时原异常向外传播、清理临时文件，绝不留下半成品正式 Manifest。
        """
        target = Path(path)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self.to_json())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
