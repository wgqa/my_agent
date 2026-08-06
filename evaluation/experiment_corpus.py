"""ExperimentRunner 第四步：可复现实验语料清单。

固定一次实验使用的文件集合（relative_path + sha256 + size_bytes），
生成与输入顺序、对象地址无关的稳定 corpus_id，保证实验可复现。
只读语料，不复制、不加载、不索引。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence, Union

_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".py", ".js", ".java"}


@dataclass(frozen=True)
class CorpusEntry:
    relative_path: str   # 规范化 POSIX 相对路径（输入顺序无关的排序键）
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ExperimentCorpus:
    corpus_root: Path
    entries: tuple
    corpus_id: str

    @classmethod
    def build(
        cls,
        corpus_root: Union[str, Path],
        relative_paths: Sequence[Union[str, Path]],
    ) -> "ExperimentCorpus":
        root = Path(corpus_root).resolve()
        if not root.is_dir():
            raise ValueError(f"corpus_root 必须存在且是目录: {root}")
        if not relative_paths:
            raise ValueError("文件列表不能为空")

        seen = set()
        basenames = set()
        entries = []
        for p in relative_paths:
            rp = Path(p)
            if rp.is_absolute():
                raise ValueError(f"relative_path 不允许绝对路径: {p}")
            # 规范化：统一 POSIX 分隔符、折叠 ./ 与重复斜杠（保留 .. 供拒绝检查）
            posix = PurePosixPath(rp).as_posix()
            if any(part == ".." for part in PurePosixPath(posix).parts):
                raise ValueError(f"禁止路径穿越（..）：{posix}")
            if posix in seen:
                raise ValueError(f"重复路径: {posix}")
            if PurePosixPath(posix).suffix.lower() not in _ALLOWED_EXTENSIONS:
                raise ValueError(f"不支持的扩展名: {posix}")

            # 真实路径解析（跟随符号链接）后必须仍在 corpus_root 内
            full = (root / posix).resolve()
            if not full.is_relative_to(root):
                raise ValueError(f"路径逃逸 corpus_root（符号链接指向外部）: {posix}")
            if not full.is_file():
                raise ValueError(f"不是普通文件: {posix}")

            # Pipeline.index_file 用 basename 生成 document_id，
            # 同名文件会互相覆盖，提前保护（不改 Pipeline 逻辑）
            base = PurePosixPath(posix).name
            if base in basenames:
                raise ValueError(
                    f"不同目录下存在同名文件（document_id 冲突风险）: {posix}"
                )
            basenames.add(base)

            data = full.read_bytes()  # 原始字节，不做文本解码
            seen.add(posix)
            entries.append(CorpusEntry(
                relative_path=posix,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            ))

        entries.sort(key=lambda e: e.relative_path)
        corpus_id = cls._compute_id(entries)
        return cls(corpus_root=root, entries=tuple(entries), corpus_id=corpus_id)

    @staticmethod
    def _compute_id(entries) -> str:
        """基于排序后的 relative_path/sha256/size 生成稳定 ID"""
        payload = "|".join(
            f"{e.relative_path}:{e.sha256}:{e.size_bytes}" for e in entries
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
