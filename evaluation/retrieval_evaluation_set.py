"""G2-EVAL-06：可复现的文档级检索评测集。

JSONL 测试集 → 严格解析与校验 → 绑定 ExperimentCorpus →
规范化 RetrievalCase → 稳定 evaluation_set_id。

正式标注使用 Corpus 中的规范相对文件路径（relevant_files），不使用
Chunk ID：Fixed/Recursive 的 Chunk ID 不同，chunk_size/overlap 变化后
也会变化，而文件相对路径可以跨 Chunk 策略保持稳定。
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Union

from evaluation.experiment_corpus import ExperimentCorpus

EVALUATION_SET_SCHEMA_VERSION = 1

_ALLOWED_FIELDS = frozenset({"case_id", "query", "relevant_files"})
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


@dataclass(frozen=True)
class RetrievalCase:
    """一个文档级检索用例；relevant_files 为规范化、排序后的 POSIX 相对路径"""

    case_id: str
    query: str
    relevant_files: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalEvaluationSet:
    """一次检索评测集的不可变内存快照，与 JSONL 文件路径/行顺序无关"""

    corpus_id: str
    cases: tuple[RetrievalCase, ...]
    evaluation_set_id: str

    @classmethod
    def load_jsonl(
        cls,
        path: Union[str, Path],
        corpus: ExperimentCorpus,
    ) -> "RetrievalEvaluationSet":
        """一次性读取 JSONL 并返回完全驻留内存的不可变快照。

        后续评测不应再次依赖原 JSONL 文件内容。
        """
        jsonl_path = Path(path)
        if not jsonl_path.exists():
            raise FileNotFoundError(f"JSONL 测试集文件不存在：{jsonl_path}")
        if not jsonl_path.is_file():
            raise ValueError(f"JSONL 测试集路径不是文件：{jsonl_path}")

        corpus_paths = {e.relative_path for e in corpus.entries}
        cases = []
        seen_case_ids = {}
        seen_queries = {}

        with jsonl_path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue  # 稳定行为：忽略纯空白行

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"第 {lineno} 行 JSON 解析失败：{exc}"
                    ) from exc
                if not isinstance(obj, dict):
                    raise ValueError(
                        f"第 {lineno} 行必须是 JSON object，实际是 "
                        f"{type(obj).__name__}"
                    )

                extra = sorted(set(obj) - _ALLOWED_FIELDS)
                if extra:
                    raise ValueError(
                        f"第 {lineno} 行包含未知字段：{', '.join(extra)}"
                    )
                missing = sorted(_ALLOWED_FIELDS - set(obj))
                if missing:
                    raise ValueError(
                        f"第 {lineno} 行缺少字段：{', '.join(missing)}"
                    )

                case_id = obj["case_id"]
                if not isinstance(case_id, str):
                    raise ValueError(
                        f"第 {lineno} 行 case_id 必须是字符串，实际 "
                        f"{type(case_id).__name__}"
                    )
                if not _CASE_ID_RE.match(case_id):
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id!r} 只允许字母、"
                        "数字、-、_"
                    )
                if case_id in seen_case_ids:
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id} 重复"
                        f"（首次出现在第 {seen_case_ids[case_id]} 行）"
                    )

                query = obj["query"]
                if not isinstance(query, str):
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id}：query 必须是字符串，"
                        f"实际 {type(query).__name__}"
                    )
                if not query.strip():
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id}：query 不能为空或只含空白"
                    )
                if query != query.strip():
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id}：query 首尾不允许空白"
                    )
                if query in seen_queries:
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id}：query 与第 "
                        f"{seen_queries[query]} 行完全重复"
                    )

                raw_files = obj["relevant_files"]
                if not isinstance(raw_files, list):
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id}：relevant_files "
                        f"必须是数组，实际 {type(raw_files).__name__}"
                    )
                if not raw_files:
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case_id}：relevant_files 不能为空"
                    )

                normalized_files = []
                seen_files = set()
                for raw in raw_files:
                    normalized = cls._normalize_relative_path(
                        raw, corpus_paths, lineno, case_id
                    )
                    if normalized in seen_files:
                        raise ValueError(
                            f"第 {lineno} 行 case_id={case_id}："
                            f"relevant_files 包含重复路径 {raw}"
                        )
                    seen_files.add(normalized)
                    normalized_files.append(normalized)
                normalized_files.sort()

                seen_case_ids[case_id] = lineno
                seen_queries[query] = lineno
                cases.append(RetrievalCase(
                    case_id=case_id,
                    query=query,
                    relevant_files=tuple(normalized_files),
                ))

        if not cases:
            raise ValueError("JSONL 测试集为空：没有任何有效 Case")

        cases.sort(key=lambda c: c.case_id)
        return cls(
            corpus_id=corpus.corpus_id,
            cases=tuple(cases),
            evaluation_set_id=cls._compute_id(corpus.corpus_id, cases),
        )

    @staticmethod
    def _normalize_relative_path(
        raw: str,
        corpus_paths: set,
        lineno: int,
        case_id: str,
    ) -> str:
        """把标注路径规范化为 POSIX 相对路径并与 CorpusEntry 精确匹配"""
        if not isinstance(raw, str):
            raise ValueError(
                f"第 {lineno} 行 case_id={case_id}：relevant_files 每项必须是"
                f"字符串，实际 {type(raw).__name__}"
            )
        s = raw.replace("\\", "/")
        posix = PurePosixPath(s).as_posix()
        if PurePosixPath(s).is_absolute() or _DRIVE_RE.match(s):
            raise ValueError(
                f"第 {lineno} 行 case_id={case_id}：relevant_files 不允许"
                f"绝对路径 {raw!r}"
            )
        if any(part == ".." for part in PurePosixPath(posix).parts):
            raise ValueError(
                f"第 {lineno} 行 case_id={case_id}：relevant_files 不允许"
                f".. 路径穿越 {raw!r}"
            )
        if posix not in corpus_paths:
            raise ValueError(
                f"第 {lineno} 行 case_id={case_id}：relevant_files 包含不属于 "
                f"ExperimentCorpus 的路径 {raw}"
            )
        return posix

    @staticmethod
    def _compute_id(corpus_id: str, cases) -> str:
        """无歧义规范 JSON 计算 SHA-256（12 位十六进制）。

        payload 绑定：schema_version、corpus.corpus_id、全部规范化 Case
        （case_id、query 原文、排序后的 relevant_files）。不使用字段拼接、
        repr、对象地址、JSONL 绝对路径、修改时间或输入行顺序。
        """
        ordered = sorted(cases, key=lambda c: c.case_id)
        payload = {
            "schema_version": EVALUATION_SET_SCHEMA_VERSION,
            "corpus_id": corpus_id,
            "cases": [
                {
                    "case_id": c.case_id,
                    "query": c.query,
                    "relevant_files": list(c.relevant_files),
                }
                for c in ordered
            ],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
