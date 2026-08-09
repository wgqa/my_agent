"""G3-DATA-02A：Gate3Case 与 Gate3EvaluationSet 强类型契约。

强类型评测集：JSONL 严格解析 → 绑定 ExperimentCorpus → 规范化
Gate3Case（evidence obligations + answerability 跨字段不变量）→
稳定 evaluation_set_id。

本模块只实现数据模型与身份绑定。不实现 QueryPlan / Planner /
Router / EvidenceBundle / Agent；不生成真实问题；不划分 dev/holdout。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence, Union

from evaluation.experiment_corpus import ExperimentCorpus

GATE3_CASE_SCHEMA_VERSION = "gate3_case_v1"
GATE3_EVALUATION_SET_SCHEMA_VERSION = "gate3_evaluation_set_v1"

QUERY_TYPES = (
    "fact",
    "comparison",
    "causal",
    "multi_entity",
    "code_symbol",
    "troubleshooting",
    "unanswerable_or_no_retrieval",
)
ANSWERABILITY_VALUES = ("answerable", "unanswerable", "no_retrieval")
DECOMPOSITION_EXPECTED_VALUES = ("required", "optional", "forbidden")

_CASE_ALLOWED_FIELDS = frozenset({
    "schema_version",
    "case_id",
    "query",
    "query_type",
    "answerability",
    "decomposition_expected",
    "retrieval_required",
    "evidence_obligations",
    "relevant_files",
    "tags",
})
_OBLIGATION_ALLOWED_FIELDS = frozenset({
    "obligation_id",
    "description",
    "relevant_files",
    "required",
})
_CASE_ID_RE = re.compile(r"g3q[0-9]{3}")
_OBLIGATION_ID_RE = re.compile(r"o[1-9][0-9]*")
_DRIVE_RE = re.compile(r"^[A-Za-z]:/")
_MAX_QUERY_CHARS = 4000
_MAX_DESCRIPTION_CHARS = 500


@dataclass(frozen=True)
class EvidenceObligation:
    """一条 evidence obligation：要求最终检索覆盖其 relevant_files。"""

    obligation_id: str
    description: str
    relevant_files: tuple[str, ...]
    required: bool

    def to_dict(self) -> dict:
        return {
            "obligation_id": self.obligation_id,
            "description": self.description,
            "relevant_files": list(self.relevant_files),
            "required": self.required,
        }


@dataclass(frozen=True)
class Gate3Case:
    """一个 Gate 3 评测 Case；relevant_files / tags 规范化后排序去重。

    answerability 跨字段不变量在构造前 fail-fast（见 load_jsonl 的
    _validate_answerability_invariants），frozen 保证不可变内存快照。
    """

    schema_version: str
    case_id: str
    query: str
    query_type: str
    answerability: str
    decomposition_expected: str
    retrieval_required: bool
    evidence_obligations: tuple[EvidenceObligation, ...]
    relevant_files: tuple[str, ...]
    tags: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "query": self.query,
            "query_type": self.query_type,
            "answerability": self.answerability,
            "decomposition_expected": self.decomposition_expected,
            "retrieval_required": self.retrieval_required,
            "evidence_obligations": [
                o.to_dict() for o in self.evidence_obligations
            ],
            "relevant_files": list(self.relevant_files),
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class Gate3EvaluationSet:
    """一次 Gate 3 评测集的不可变内存快照，与 JSONL 行顺序无关。

    evaluation_set_id 只绑定语义（schema_version / corpus_id /
    规范化 Case），不绑定时间、路径、行顺序或输入文件。
    """

    corpus_id: str
    cases: tuple[Gate3Case, ...]
    evaluation_set_id: str
    schema_version: str = GATE3_EVALUATION_SET_SCHEMA_VERSION

    def to_dict(self) -> dict:
        """按 case_id 排序输出语义快照；不包含 evaluation_set_id（身份自指）。"""
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "cases": [
                c.to_dict()
                for c in sorted(self.cases, key=lambda c: c.case_id)
            ],
        }

    @classmethod
    def load_jsonl(
        cls,
        path: Union[str, Path],
        corpus: ExperimentCorpus,
    ) -> "Gate3EvaluationSet":
        """一次性读取 JSONL 并返回完全驻留内存的不可变快照。

        后续评测不应再次依赖原 JSONL 文件内容。
        """
        if not isinstance(corpus, ExperimentCorpus):
            raise TypeError(
                f"corpus 必须是 ExperimentCorpus，实际 {type(corpus).__name__}"
            )

        jsonl_path = Path(path)
        if not jsonl_path.exists():
            raise FileNotFoundError(f"JSONL 评测集文件不存在：{jsonl_path}")
        if not jsonl_path.is_file():
            raise ValueError(f"JSONL 评测集路径不是文件：{jsonl_path}")

        corpus_paths = {e.relative_path for e in corpus.entries}
        cases: list[Gate3Case] = []
        seen_case_ids: dict[str, int] = {}
        seen_queries: dict[str, int] = {}

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

                extra = sorted(set(obj) - _CASE_ALLOWED_FIELDS)
                if extra:
                    raise ValueError(
                        f"第 {lineno} 行包含未知字段：{', '.join(extra)}"
                    )
                missing = sorted(_CASE_ALLOWED_FIELDS - set(obj))
                if missing:
                    raise ValueError(
                        f"第 {lineno} 行缺少字段：{', '.join(missing)}"
                    )

                case = cls._parse_case(obj, corpus_paths, lineno)

                if case.case_id in seen_case_ids:
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case.case_id} 重复"
                        f"（首次出现在第 {seen_case_ids[case.case_id]} 行）"
                    )
                if case.query in seen_queries:
                    raise ValueError(
                        f"第 {lineno} 行 case_id={case.case_id}：query 与第 "
                        f"{seen_queries[case.query]} 行完全重复"
                    )

                seen_case_ids[case.case_id] = lineno
                seen_queries[case.query] = lineno
                cases.append(case)

        cases.sort(key=lambda c: c.case_id)
        return cls(
            corpus_id=corpus.corpus_id,
            cases=tuple(cases),
            evaluation_set_id=cls._compute_id(corpus.corpus_id, cases),
        )

    @classmethod
    def _parse_case(
        cls,
        obj: dict,
        corpus_paths: set,
        lineno: int,
    ) -> Gate3Case:
        """解析单行对象为 Gate3Case，执行字段级约束与跨字段不变量。"""
        ctx = f"第 {lineno} 行"

        schema_version = obj["schema_version"]
        if (
            not isinstance(schema_version, str)
            or schema_version != GATE3_CASE_SCHEMA_VERSION
        ):
            raise ValueError(
                f"{ctx}：schema_version 必须是 {GATE3_CASE_SCHEMA_VERSION!r}，"
                f"实际 {schema_version!r}"
            )

        case_id = obj["case_id"]
        if not isinstance(case_id, str):
            raise ValueError(
                f"{ctx}：case_id 必须是字符串，实际 {type(case_id).__name__}"
            )
        if _CASE_ID_RE.fullmatch(case_id) is None:
            raise ValueError(
                f"{ctx}：case_id={case_id!r} 必须是 g3q 加 3 位数字（如 g3q001）"
            )

        query = obj["query"]
        if not isinstance(query, str):
            raise ValueError(
                f"{ctx} case_id={case_id}：query 必须是字符串，"
                f"实际 {type(query).__name__}"
            )
        if not query.strip():
            raise ValueError(
                f"{ctx} case_id={case_id}：query 不能为空或只含空白"
            )
        if query != query.strip():
            raise ValueError(
                f"{ctx} case_id={case_id}：query 首尾不允许空白"
            )
        if len(query) > _MAX_QUERY_CHARS:
            raise ValueError(
                f"{ctx} case_id={case_id}：query 超过 {_MAX_QUERY_CHARS} "
                "字符上限"
            )

        query_type = obj["query_type"]
        if not isinstance(query_type, str) or query_type not in QUERY_TYPES:
            raise ValueError(
                f"{ctx} case_id={case_id}：query_type 必须是 "
                f"{', '.join(QUERY_TYPES)} 之一，实际 {query_type!r}"
            )

        answerability = obj["answerability"]
        if (
            not isinstance(answerability, str)
            or answerability not in ANSWERABILITY_VALUES
        ):
            raise ValueError(
                f"{ctx} case_id={case_id}：answerability 必须是 "
                f"{', '.join(ANSWERABILITY_VALUES)} 之一，实际 "
                f"{answerability!r}"
            )

        decomposition_expected = obj["decomposition_expected"]
        if (
            not isinstance(decomposition_expected, str)
            or decomposition_expected not in DECOMPOSITION_EXPECTED_VALUES
        ):
            raise ValueError(
                f"{ctx} case_id={case_id}：decomposition_expected 必须是 "
                f"{', '.join(DECOMPOSITION_EXPECTED_VALUES)} 之一，实际 "
                f"{decomposition_expected!r}"
            )

        retrieval_required = obj["retrieval_required"]
        if not isinstance(retrieval_required, bool):
            raise ValueError(
                f"{ctx} case_id={case_id}：retrieval_required 必须是布尔值，"
                f"实际 {type(retrieval_required).__name__}"
            )

        raw_obligations = obj["evidence_obligations"]
        if not isinstance(raw_obligations, list):
            raise ValueError(
                f"{ctx} case_id={case_id}：evidence_obligations 必须是数组，"
                f"实际 {type(raw_obligations).__name__}"
            )
        obligations = [
            cls._parse_obligation(o, corpus_paths, ctx, case_id)
            for o in raw_obligations
        ]
        obligations = cls._validate_obligation_ids(obligations, ctx, case_id)

        relevant_files = cls._normalize_path_list(
            obj["relevant_files"],
            corpus_paths,
            ctx,
            case_id,
            "relevant_files",
            allow_empty=True,
        )

        raw_tags = obj["tags"]
        if not isinstance(raw_tags, list):
            raise ValueError(
                f"{ctx} case_id={case_id}：tags 必须是数组，"
                f"实际 {type(raw_tags).__name__}"
            )
        for tag in raw_tags:
            if not isinstance(tag, str):
                raise ValueError(
                    f"{ctx} case_id={case_id}：tags 每项必须是字符串，"
                    f"实际 {type(tag).__name__}"
                )
            if not tag.strip():
                raise ValueError(
                    f"{ctx} case_id={case_id}：tags 不允许空字符串"
                )
        tags = sorted(set(raw_tags))

        case = Gate3Case(
            schema_version=schema_version,
            case_id=case_id,
            query=query,
            query_type=query_type,
            answerability=answerability,
            decomposition_expected=decomposition_expected,
            retrieval_required=retrieval_required,
            evidence_obligations=tuple(obligations),
            relevant_files=tuple(relevant_files),
            tags=tuple(tags),
        )
        cls._validate_answerability_invariants(case, ctx)
        return case

    @classmethod
    def _parse_obligation(
        cls,
        raw: object,
        corpus_paths: set,
        ctx: str,
        case_id: str,
    ) -> EvidenceObligation:
        if not isinstance(raw, dict):
            raise ValueError(
                f"{ctx} case_id={case_id}：evidence_obligations 每项必须是 "
                f"JSON object，实际 {type(raw).__name__}"
            )
        extra = sorted(set(raw) - _OBLIGATION_ALLOWED_FIELDS)
        if extra:
            raise ValueError(
                f"{ctx} case_id={case_id}：evidence_obligations 包含未知字段："
                f"{', '.join(extra)}"
            )
        missing = sorted(_OBLIGATION_ALLOWED_FIELDS - set(raw))
        if missing:
            raise ValueError(
                f"{ctx} case_id={case_id}：evidence_obligations 缺少字段："
                f"{', '.join(missing)}"
            )

        obligation_id = raw["obligation_id"]
        if not isinstance(obligation_id, str):
            raise ValueError(
                f"{ctx} case_id={case_id}：obligation_id 必须是字符串，"
                f"实际 {type(obligation_id).__name__}"
            )
        if _OBLIGATION_ID_RE.fullmatch(obligation_id) is None:
            raise ValueError(
                f"{ctx} case_id={case_id}：obligation_id={obligation_id!r} "
                "必须是 o1..oN 数字编号"
            )

        description = raw["description"]
        if not isinstance(description, str):
            raise ValueError(
                f"{ctx} case_id={case_id}：description 必须是字符串，"
                f"实际 {type(description).__name__}"
            )
        if not description.strip():
            raise ValueError(
                f"{ctx} case_id={case_id}：description 不能为空或只含空白"
            )
        if description != description.strip():
            raise ValueError(
                f"{ctx} case_id={case_id}：description 首尾不允许空白"
            )
        if len(description) > _MAX_DESCRIPTION_CHARS:
            raise ValueError(
                f"{ctx} case_id={case_id}：description 超过 "
                f"{_MAX_DESCRIPTION_CHARS} 字符上限"
            )

        files = cls._normalize_path_list(
            raw["relevant_files"],
            corpus_paths,
            ctx,
            case_id,
            "evidence_obligations.relevant_files",
            allow_empty=False,
        )

        required = raw["required"]
        if not isinstance(required, bool):
            raise ValueError(
                f"{ctx} case_id={case_id}：required 必须是布尔值，"
                f"实际 {type(required).__name__}"
            )

        return EvidenceObligation(
            obligation_id=obligation_id,
            description=description,
            relevant_files=tuple(files),
            required=required,
        )

    @staticmethod
    def _validate_obligation_ids(
        obligations: Sequence[EvidenceObligation],
        ctx: str,
        case_id: str,
    ) -> tuple[EvidenceObligation, ...]:
        """按数字编号排序，并校验编号必须恰好是 o1..oN 连续。"""
        ordered = sorted(
            obligations, key=lambda o: int(o.obligation_id[1:])
        )
        for i, obligation in enumerate(ordered, 1):
            expected = f"o{i}"
            if obligation.obligation_id != expected:
                raise ValueError(
                    f"{ctx} case_id={case_id}：obligation_id 必须连续（o1..oN），"
                    f"发现 {obligation.obligation_id}（应期望 {expected}）"
                )
        return tuple(ordered)

    @staticmethod
    def _validate_answerability_invariants(
        case: Gate3Case,
        ctx: str,
    ) -> None:
        """answerability 跨字段不变量，构造前 fail-fast（设计文档 §10.1）。"""
        if case.answerability == "answerable":
            if not case.evidence_obligations:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：answerable 必须至少一个 "
                    "evidence_obligations"
                )
            if not any(o.required for o in case.evidence_obligations):
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：answerable 至少一个 "
                    "evidence_obligation 的 required 必须为 true"
                )
            if case.query_type == "unanswerable_or_no_retrieval":
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：answerable 的 query_type "
                    "不能是 unanswerable_or_no_retrieval"
                )
            if not case.retrieval_required:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：answerable 的 "
                    "retrieval_required 必须为 true"
                )
            union = sorted(
                {p for o in case.evidence_obligations for p in o.relevant_files}
            )
            if list(case.relevant_files) != union:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：answerable 顶层 "
                    "relevant_files 必须等于各 obligation relevant_files 的"
                    "排序去重并集"
                )
        elif case.answerability == "unanswerable":
            if case.evidence_obligations:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：unanswerable 的 "
                    "evidence_obligations 必须为空"
                )
            if case.relevant_files:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：unanswerable 的 "
                    "relevant_files 必须为空"
                )
            if case.decomposition_expected != "forbidden":
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：unanswerable 的 "
                    "decomposition_expected 必须为 forbidden"
                )
            if case.query_type != "unanswerable_or_no_retrieval":
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：unanswerable 的 query_type "
                    "必须为 unanswerable_or_no_retrieval"
                )
            if not case.retrieval_required:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：unanswerable 的 "
                    "retrieval_required 必须为 true"
                )
        elif case.answerability == "no_retrieval":
            if case.evidence_obligations:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：no_retrieval 的 "
                    "evidence_obligations 必须为空"
                )
            if case.relevant_files:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：no_retrieval 的 "
                    "relevant_files 必须为空"
                )
            if case.decomposition_expected != "forbidden":
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：no_retrieval 的 "
                    "decomposition_expected 必须为 forbidden"
                )
            if case.query_type != "unanswerable_or_no_retrieval":
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：no_retrieval 的 query_type "
                    "必须为 unanswerable_or_no_retrieval"
                )
            if case.retrieval_required:
                raise ValueError(
                    f"{ctx} case_id={case.case_id}：no_retrieval 的 "
                    "retrieval_required 必须为 false"
                )
        else:  # pragma: no cover - 枚举已封闭，理论上不可达
            raise ValueError(
                f"{ctx} case_id={case.case_id}：未知 answerability "
                f"{case.answerability!r}"
            )

    @classmethod
    def _normalize_path_list(
        cls,
        raw: object,
        corpus_paths: set,
        ctx: str,
        case_id: str,
        label: str,
        allow_empty: bool,
    ) -> list[str]:
        if not isinstance(raw, list):
            raise ValueError(
                f"{ctx} case_id={case_id}：{label} 必须是数组，"
                f"实际 {type(raw).__name__}"
            )
        if not raw and not allow_empty:
            raise ValueError(f"{ctx} case_id={case_id}：{label} 不能为空")

        normalized = []
        seen = set()
        for item in raw:
            posix = cls._normalize_relative_path(
                item, corpus_paths, ctx, case_id, label
            )
            if posix in seen:
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 包含重复路径 {item!r}"
                )
            seen.add(posix)
            normalized.append(posix)
        normalized.sort()
        return normalized

    @classmethod
    def _normalize_relative_path(
        cls,
        raw: object,
        corpus_paths: set,
        ctx: str,
        case_id: str,
        label: str,
    ) -> str:
        """把标注路径规范化为 POSIX 相对路径并与 CorpusEntry 精确匹配。"""
        if not isinstance(raw, str):
            raise ValueError(
                f"{ctx} case_id={case_id}：{label} 每项必须是字符串，"
                f"实际 {type(raw).__name__}"
            )
        s = raw.replace("\\", "/")
        posix = PurePosixPath(s).as_posix()
        if PurePosixPath(s).is_absolute() or _DRIVE_RE.match(s):
            raise ValueError(
                f"{ctx} case_id={case_id}：{label} 不允许绝对路径 {raw!r}"
            )
        if any(part == ".." for part in PurePosixPath(posix).parts):
            raise ValueError(
                f"{ctx} case_id={case_id}：{label} 不允许 .. 路径穿越 {raw!r}"
            )
        if posix not in corpus_paths:
            raise ValueError(
                f"{ctx} case_id={case_id}：{label} 包含不属于 "
                f"ExperimentCorpus 的路径 {raw!r}"
            )
        return posix

    @staticmethod
    def _compute_id(corpus_id: str, cases) -> str:
        """无歧义规范 JSON 计算 SHA-256（12 位十六进制）。

        payload 绑定：evaluation_set schema_version、corpus_id、全部
        规范化 Case（to_dict）。不绑定时间、绝对路径、行顺序、输入
        文件对象地址。
        """
        ordered = sorted(cases, key=lambda c: c.case_id)
        payload = {
            "schema_version": GATE3_EVALUATION_SET_SCHEMA_VERSION,
            "corpus_id": corpus_id,
            "cases": [c.to_dict() for c in ordered],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
