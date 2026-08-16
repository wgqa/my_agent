"""G4-EVAL-06A：Gate4ToolUseCase 与 Gate4ToolUseEvaluationSet 强类型契约。

Gate 4 Tool-Agent Dev 基准：JSONL 严格解析 → 跨字段不变量 fail-fast →
稳定 evaluation_set_id（canonical JSON + SHA-256 前 12 位）。

本模块只实现数据模型、严格 Loader 与身份绑定。不实现 Tool-Agent
Runtime、不调用任何 LLM、不产生任何运行指标。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, Union

GATE4_TOOL_USE_CASE_SCHEMA_VERSION = "gate4_tool_use_case_v1"
GATE4_TOOL_USE_SET_SCHEMA_VERSION = "gate4_tool_use_set_v1"
GATE4_TOOL_USE_MANIFEST_SCHEMA_VERSION = "gate4_tool_use_manifest_v1"

CATEGORIES = (
    "direct_answer",
    "calculator",
    "code_search",
    "knowledge_search",
    "multi_step",
    "refusal_safety",
)
CATEGORY_COUNT_PER_TYPE = 4  # 正式 v1：六类各 4 条，共 24
TERMINALS = ("completed", "refused")
FIRST_ACTIONS = ("final_answer", "tool_call", "refuse")
TOOLS = ("calculator", "code_search", "knowledge_search")
ASSERTION_TYPES = (
    "answer_contains",
    "answer_contains_all",
    "answer_number_equals",
    "answer_nonempty",
    "path_contains",
    "status_equals",
)
REFUSE_REASON_CODES = ("UNSUPPORTED_REQUEST", "UNSAFE_REQUEST")

# tool 类 category 与其期望首工具一一对应
_CATEGORY_FIRST_TOOL = {
    "calculator": "calculator",
    "code_search": "code_search",
    "knowledge_search": "knowledge_search",
}
_SINGLE_TOOL_CATEGORIES = frozenset(_CATEGORY_FIRST_TOOL)
_NON_TOOL_CATEGORIES = frozenset({"direct_answer", "refusal_safety"})

_CASE_ALLOWED_FIELDS = frozenset({
    "schema_version",
    "case_id",
    "query",
    "category",
    "expected_terminal",
    "expected_first_action",
    "expected_first_tool",
    "expected_first_tools",
    "required_tools",
    "allowed_tool_sequences",
    "forbidden_tools",
    "completion_assertions",
    "allowed_refuse_reason_codes",
    "knowledge_gold",
    "tags",
    "rationale",
})
_ASSERTION_ALLOWED_FIELDS = frozenset(ASSERTION_TYPES)
_KNOWLEDGE_GOLD_ALLOWED_FIELDS = frozenset({"source_name", "evidence_phrase"})

_CASE_ID_RE = re.compile(r"g4q[0-9]{3}")
_MAX_QUERY_CHARS = 4000
_MAX_RATIONALE_CHARS = 2000
_MAX_EVIDENCE_CHARS = 1000
_MAX_SOURCE_NAME_CHARS = 500

# Manifest 冻结常量：code_search Gold 绑定的 source commit 与 knowledge
# corpus（corpus_id=870e5864df67、37 files，公开冻结语料）
CODE_REFERENCE_COMMIT = "91627bb3ac5566f15f66be57bb8af2f3d553f203"
KNOWLEDGE_CORPUS_ID = "870e5864df67"
KNOWLEDGE_CORPUS_FILE_COUNT = 37


def _freeze(value: Any) -> Any:
    """递归冻结：嵌套 list → tuple，保证外部引用无法改动 Gold。"""
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    """递归还原：冻结后的 tuple → 全新 list（用于 JSON 序列化）。"""
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class CompletionAssertion:
    """一条确定性 completion assertion（不用 LLM-as-Judge）。

    type 决定 value 的类型约束；value 构造时递归冻结为不可变（list→tuple），
    to_dict() 返回全新深拷贝副本。因此外部修改原始 JSON/list 或
    to_dict() 返回值都不会改变 EvaluationSet Gold。
    """

    type: str
    value: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(self.value))

    def to_dict(self) -> dict:
        return {self.type: _thaw(self.value)}


@dataclass(frozen=True)
class KnowledgeGold:
    """knowledge_search 类的 Gold 证据登记：source_name + evidence phrase。

    只登记语料来源与关键证据短语，不把全文写进 dataset。
    """

    source_name: str
    evidence_phrase: str

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "evidence_phrase": self.evidence_phrase,
        }


@dataclass(frozen=True)
class Gate4ToolUseCase:
    """一个 Gate 4 Tool-Agent Dev 评测 Case。

    构造后立即执行 category 跨字段不变量（fail-fast），frozen 保证不可变。
    """

    schema_version: str
    case_id: str
    query: str
    category: str
    expected_terminal: str
    expected_first_action: str
    expected_first_tool: str | None
    expected_first_tools: tuple[str, ...]
    required_tools: tuple[str, ...]
    allowed_tool_sequences: tuple[tuple[str, ...], ...]
    forbidden_tools: tuple[str, ...]
    completion_assertions: tuple[CompletionAssertion, ...]
    allowed_refuse_reason_codes: tuple[str, ...]
    knowledge_gold: KnowledgeGold | None
    tags: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "query": self.query,
            "category": self.category,
            "expected_terminal": self.expected_terminal,
            "expected_first_action": self.expected_first_action,
            "expected_first_tool": self.expected_first_tool,
            "expected_first_tools": list(self.expected_first_tools),
            "required_tools": list(self.required_tools),
            "allowed_tool_sequences": [
                list(seq) for seq in self.allowed_tool_sequences
            ],
            "forbidden_tools": list(self.forbidden_tools),
            "completion_assertions": [
                a.to_dict() for a in self.completion_assertions
            ],
            "allowed_refuse_reason_codes": list(
                self.allowed_refuse_reason_codes
            ),
            "knowledge_gold": (
                self.knowledge_gold.to_dict() if self.knowledge_gold else None
            ),
            "tags": list(self.tags),
            "rationale": self.rationale,
        }
        return out


@dataclass(frozen=True)
class Gate4ToolUseEvaluationSet:
    """一次 Gate 4 评测集的不可变内存快照，与 JSONL 行顺序无关。

    evaluation_set_id 只绑定语义（schema_version / 全部规范化 Case），
    不绑定时间、路径、行顺序、输入文件对象地址。
    """

    cases: tuple[Gate4ToolUseCase, ...]
    evaluation_set_id: str
    schema_version: str = GATE4_TOOL_USE_SET_SCHEMA_VERSION

    def to_dict(self) -> dict:
        """按 case_id 排序输出语义快照；含 evaluation_set_id（仅快照展示，
        不作为身份计算输入，避免自指）。"""
        return {
            "schema_version": self.schema_version,
            "evaluation_set_id": self.evaluation_set_id,
            "cases": [
                c.to_dict()
                for c in sorted(self.cases, key=lambda c: c.case_id)
            ],
        }

    @property
    def case_count(self) -> int:
        return len(self.cases)

    @property
    def category_counts(self) -> dict[str, int]:
        counts = {cat: 0 for cat in CATEGORIES}
        for case in self.cases:
            counts[case.category] += 1
        return counts

    @classmethod
    def load_jsonl(cls, path: Union[str, Path]) -> "Gate4ToolUseEvaluationSet":
        """一次性读取 JSONL 并返回完全驻留内存的不可变快照。

        Loader 必须严格（沿用项目一贯标准）：unknown/missing field reject、
        duplicate case_id reject、unknown category reject、unknown Tool name
        reject、empty/whitespace query reject、duplicate tags reject、invalid
        sequence reject、contradictory Gold reject。不做隐式类型转换。
        """
        jsonl_path = Path(path)
        if not jsonl_path.exists():
            raise FileNotFoundError(f"JSONL 评测集文件不存在：{jsonl_path}")
        if not jsonl_path.is_file():
            raise ValueError(f"JSONL 评测集路径不是文件：{jsonl_path}")

        cases: list[Gate4ToolUseCase] = []
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

                case = cls._parse_case(obj, lineno)

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

        if not cases:
            raise ValueError(
                "评测集不能为空：JSONL 不含任何有效 Gate4ToolUseCase"
                "（空文件或只有空白行）"
            )

        cases.sort(key=lambda c: c.case_id)
        set_obj = cls(
            cases=tuple(cases),
            evaluation_set_id=cls._compute_id(cases),
        )
        cls._validate_set_invariants(set_obj)
        return set_obj

    # ------------------------------------------------------------------ #
    # 字段级解析
    # ------------------------------------------------------------------ #

    @classmethod
    def _parse_case(cls, obj: dict, lineno: int) -> Gate4ToolUseCase:
        ctx = f"第 {lineno} 行"

        extra = sorted(set(obj) - _CASE_ALLOWED_FIELDS)
        if extra:
            raise ValueError(f"{ctx} 包含未知字段：{', '.join(extra)}")
        missing = sorted(_CASE_ALLOWED_FIELDS - set(obj))
        if missing:
            raise ValueError(f"{ctx} 缺少字段：{', '.join(missing)}")

        schema_version = obj["schema_version"]
        if (
            not isinstance(schema_version, str)
            or schema_version != GATE4_TOOL_USE_CASE_SCHEMA_VERSION
        ):
            raise ValueError(
                f"{ctx}：schema_version 必须是 "
                f"{GATE4_TOOL_USE_CASE_SCHEMA_VERSION!r}，实际 "
                f"{schema_version!r}"
            )

        case_id = obj["case_id"]
        if not isinstance(case_id, str):
            raise ValueError(
                f"{ctx}：case_id 必须是字符串，实际 {type(case_id).__name__}"
            )
        if _CASE_ID_RE.fullmatch(case_id) is None:
            raise ValueError(
                f"{ctx}：case_id={case_id!r} 必须是 g4q 加 3 位数字（如 g4q001）"
            )

        query = cls._require_clean_str(
            obj["query"], ctx, "query", _MAX_QUERY_CHARS
        )

        category = obj["category"]
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError(
                f"{ctx} case_id={case_id}：category 必须是 "
                f"{', '.join(CATEGORIES)} 之一，实际 {category!r}"
            )

        expected_terminal = obj["expected_terminal"]
        if (
            not isinstance(expected_terminal, str)
            or expected_terminal not in TERMINALS
        ):
            raise ValueError(
                f"{ctx} case_id={case_id}：expected_terminal 必须是 "
                f"{', '.join(TERMINALS)} 之一，实际 {expected_terminal!r}"
            )

        expected_first_action = obj["expected_first_action"]
        if (
            not isinstance(expected_first_action, str)
            or expected_first_action not in FIRST_ACTIONS
        ):
            raise ValueError(
                f"{ctx} case_id={case_id}：expected_first_action 必须是 "
                f"{', '.join(FIRST_ACTIONS)} 之一，实际 "
                f"{expected_first_action!r}"
            )

        expected_first_tool = obj["expected_first_tool"]
        if expected_first_tool is not None:
            if not isinstance(expected_first_tool, str):
                raise ValueError(
                    f"{ctx} case_id={case_id}：expected_first_tool 必须是字符串"
                    f"或 null，实际 {type(expected_first_tool).__name__}"
                )
            if expected_first_tool not in TOOLS:
                raise ValueError(
                    f"{ctx} case_id={case_id}：expected_first_tool 必须是 "
                    f"{', '.join(TOOLS)} 之一，实际 {expected_first_tool!r}"
                )

        expected_first_tools = cls._normalize_tool_list(
            obj["expected_first_tools"],
            ctx,
            case_id,
            "expected_first_tools",
            allow_empty=True,
        )

        required_tools = cls._normalize_tool_list(
            obj["required_tools"],
            ctx,
            case_id,
            "required_tools",
            allow_empty=True,
        )

        forbidden_tools = cls._normalize_tool_list(
            obj["forbidden_tools"],
            ctx,
            case_id,
            "forbidden_tools",
            allow_empty=True,
        )

        raw_sequences = obj["allowed_tool_sequences"]
        if not isinstance(raw_sequences, list):
            raise ValueError(
                f"{ctx} case_id={case_id}：allowed_tool_sequences 必须是数组，"
                f"实际 {type(raw_sequences).__name__}"
            )
        sequences: list[tuple[str, ...]] = []
        seen_sequences: set[tuple[str, ...]] = set()
        for seq_idx, raw_seq in enumerate(raw_sequences):
            if not isinstance(raw_seq, list) or not raw_seq:
                raise ValueError(
                    f"{ctx} case_id={case_id}：allowed_tool_sequences[{seq_idx}] "
                    "必须是非空数组"
                )
            seq_tools: list[str] = []
            for tool in raw_seq:
                if not isinstance(tool, str) or tool not in TOOLS:
                    raise ValueError(
                        f"{ctx} case_id={case_id}：allowed_tool_sequences 中 "
                        f"每项必须是 {', '.join(TOOLS)} 之一，实际 {tool!r}"
                    )
                if tool in seq_tools:
                    raise ValueError(
                        f"{ctx} case_id={case_id}：allowed_tool_sequences[{seq_idx}] "
                        f"含重复工具 {tool!r}"
                    )
                seq_tools.append(tool)
            seq_tuple = tuple(seq_tools)
            if seq_tuple in seen_sequences:
                raise ValueError(
                    f"{ctx} case_id={case_id}：allowed_tool_sequences 存在重复序列 "
                    f"{list(seq_tuple)}"
                )
            seen_sequences.add(seq_tuple)
            sequences.append(seq_tuple)

        completion_assertions = cls._parse_assertions(
            obj["completion_assertions"], ctx, case_id
        )

        allowed_refuse_reason_codes = cls._normalize_str_list(
            obj["allowed_refuse_reason_codes"],
            ctx,
            case_id,
            "allowed_refuse_reason_codes",
            allow_empty=True,
            max_chars=64,
        )
        for code in allowed_refuse_reason_codes:
            if code not in REFUSE_REASON_CODES:
                raise ValueError(
                    f"{ctx} case_id={case_id}：allowed_refuse_reason_codes 每项"
                    f"必须是 {', '.join(REFUSE_REASON_CODES)} 之一，实际 {code!r}"
                )

        knowledge_gold = cls._parse_knowledge_gold(
            obj["knowledge_gold"], ctx, case_id
        )

        tags = cls._normalize_str_list(
            obj["tags"],
            ctx,
            case_id,
            "tags",
            allow_empty=False,
            max_chars=64,
        )

        rationale = cls._require_clean_str(
            obj["rationale"], ctx, "rationale", _MAX_RATIONALE_CHARS
        )

        case = Gate4ToolUseCase(
            schema_version=schema_version,
            case_id=case_id,
            query=query,
            category=category,
            expected_terminal=expected_terminal,
            expected_first_action=expected_first_action,
            expected_first_tool=expected_first_tool,
            expected_first_tools=expected_first_tools,
            required_tools=required_tools,
            allowed_tool_sequences=tuple(sequences),
            forbidden_tools=forbidden_tools,
            completion_assertions=completion_assertions,
            allowed_refuse_reason_codes=allowed_refuse_reason_codes,
            knowledge_gold=knowledge_gold,
            tags=tags,
            rationale=rationale,
        )
        cls._validate_category_invariants(case, ctx)
        return case

    @staticmethod
    def _require_clean_str(
        raw: object, ctx: str, label: str, max_chars: int
    ) -> str:
        if not isinstance(raw, str):
            raise ValueError(
                f"{ctx}：{label} 必须是字符串，实际 {type(raw).__name__}"
            )
        if not raw.strip():
            raise ValueError(f"{ctx}：{label} 不能为空或只含空白")
        if raw != raw.strip():
            raise ValueError(f"{ctx}：{label} 首尾不允许空白")
        if len(raw) > max_chars:
            raise ValueError(f"{ctx}：{label} 超过 {max_chars} 字符上限")
        return raw

    @staticmethod
    def _normalize_str_list(
        raw: object,
        ctx: str,
        case_id: str,
        label: str,
        allow_empty: bool,
        max_chars: int,
    ) -> tuple[str, ...]:
        if not isinstance(raw, list):
            raise ValueError(
                f"{ctx} case_id={case_id}：{label} 必须是数组，"
                f"实际 {type(raw).__name__}"
            )
        if not raw and not allow_empty:
            raise ValueError(f"{ctx} case_id={case_id}：{label} 不能为空")

        seen: set[str] = set()
        out: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 每项必须是字符串，"
                    f"实际 {type(item).__name__}"
                )
            if not item.strip():
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 不允许空字符串或纯空白"
                )
            if item != item.strip():
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 首尾不允许空白"
                )
            if len(item) > max_chars:
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 每项超过 {max_chars} "
                    "字符上限"
                )
            if item in seen:
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 包含重复值 {item!r}"
                )
            seen.add(item)
            out.append(item)
        return tuple(sorted(out))

    @classmethod
    def _normalize_tool_list(
        cls,
        raw: object,
        ctx: str,
        case_id: str,
        label: str,
        allow_empty: bool,
    ) -> tuple[str, ...]:
        values = cls._normalize_str_list(
            raw, ctx, case_id, label, allow_empty, max_chars=64
        )
        for tool in values:
            if tool not in TOOLS:
                raise ValueError(
                    f"{ctx} case_id={case_id}：{label} 每项必须是 "
                    f"{', '.join(TOOLS)} 之一，实际 {tool!r}"
                )
        return values

    @classmethod
    def _parse_assertions(
        cls,
        raw: object,
        ctx: str,
        case_id: str,
    ) -> tuple[CompletionAssertion, ...]:
        if not isinstance(raw, list) or not raw:
            raise ValueError(
                f"{ctx} case_id={case_id}：completion_assertions 必须是非空数组"
            )
        out: list[CompletionAssertion] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(
                    f"{ctx} case_id={case_id}：completion_assertions[{idx}] "
                    f"必须是 JSON object，实际 {type(item).__name__}"
                )
            extra = sorted(set(item) - _ASSERTION_ALLOWED_FIELDS)
            if extra:
                raise ValueError(
                    f"{ctx} case_id={case_id}：completion_assertions[{idx}] "
                    f"包含未知字段：{', '.join(extra)}"
                )
            keys = [k for k in ASSERTION_TYPES if k in item]
            if len(keys) != 1:
                raise ValueError(
                    f"{ctx} case_id={case_id}：completion_assertions[{idx}] "
                    "必须恰好含一个断言类型，实际 "
                    f"{','.join(keys) if keys else '无'}"
                )
            a_type = keys[0]
            value = item[a_type]
            cls._validate_assertion_value(
                a_type, value, ctx, case_id, idx
            )
            out.append(CompletionAssertion(type=a_type, value=value))
        return tuple(out)

    @staticmethod
    def _validate_assertion_value(
        a_type: str,
        value: object,
        ctx: str,
        case_id: str,
        idx: int,
    ) -> None:
        where = f"{ctx} case_id={case_id} completion_assertions[{idx}]"
        if a_type in ("answer_contains", "path_contains", "status_equals"):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{where}.{a_type} 必须是非空字符串，实际 {value!r}"
                )
        elif a_type == "answer_contains_all":
            if not isinstance(value, list) or not value:
                raise ValueError(
                    f"{where}.answer_contains_all 必须是非空字符串数组"
                )
            for v in value:
                if not isinstance(v, str) or not v.strip():
                    raise ValueError(
                        f"{where}.answer_contains_all 每项必须是非空字符串"
                    )
            if len(set(value)) != len(value):
                raise ValueError(
                    f"{where}.answer_contains_all 不允许重复值"
                )
        elif a_type == "answer_number_equals":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{where}.answer_number_equals 必须是数字（不允许 bool）"
                )
            if isinstance(value, float) and value != value:  # NaN
                raise ValueError(
                    f"{where}.answer_number_equals 不允许 NaN"
                )
        elif a_type == "answer_nonempty":
            if not isinstance(value, bool) or value is not True:
                raise ValueError(
                    f"{where}.answer_nonempty 必须为 true"
                )

    @classmethod
    def _parse_knowledge_gold(
        cls, raw: object, ctx: str, case_id: str
    ) -> KnowledgeGold | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError(
                f"{ctx} case_id={case_id}：knowledge_gold 必须是 JSON object"
                f"或 null，实际 {type(raw).__name__}"
            )
        extra = sorted(set(raw) - _KNOWLEDGE_GOLD_ALLOWED_FIELDS)
        if extra:
            raise ValueError(
                f"{ctx} case_id={case_id}：knowledge_gold 包含未知字段："
                f"{', '.join(extra)}"
            )
        missing = sorted(_KNOWLEDGE_GOLD_ALLOWED_FIELDS - set(raw))
        if missing:
            raise ValueError(
                f"{ctx} case_id={case_id}：knowledge_gold 缺少字段："
                f"{', '.join(missing)}"
            )
        source_name = cls._require_clean_str(
            raw["source_name"], ctx, "knowledge_gold.source_name",
            _MAX_SOURCE_NAME_CHARS,
        )
        evidence_phrase = cls._require_clean_str(
            raw["evidence_phrase"], ctx, "knowledge_gold.evidence_phrase",
            _MAX_EVIDENCE_CHARS,
        )
        return KnowledgeGold(
            source_name=source_name, evidence_phrase=evidence_phrase
        )

    # ------------------------------------------------------------------ #
    # 跨字段不变量
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_category_invariants(case: Gate4ToolUseCase, ctx: str) -> None:
        cid = case.case_id
        if case.category == "direct_answer":
            if case.required_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：direct_answer 的 required_tools 必须为空"
                )
            if case.expected_terminal != "completed":
                raise ValueError(
                    f"{ctx} case_id={cid}：direct_answer 的 expected_terminal "
                    "必须为 completed"
                )
            if case.expected_first_action != "final_answer":
                raise ValueError(
                    f"{ctx} case_id={cid}：direct_answer 的 "
                    "expected_first_action 必须为 final_answer"
                )
            if case.expected_first_tool is not None or case.expected_first_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：direct_answer 不允许设置 "
                    "expected_first_tool(s)"
                )
        elif case.category in _SINGLE_TOOL_CATEGORIES:
            if case.expected_terminal != "completed":
                raise ValueError(
                    f"{ctx} case_id={cid}：{case.category} 的 expected_terminal "
                    "必须为 completed"
                )
            if case.expected_first_action != "tool_call":
                raise ValueError(
                    f"{ctx} case_id={cid}：{case.category} 的 "
                    "expected_first_action 必须为 tool_call"
                )
            expected = _CATEGORY_FIRST_TOOL[case.category]
            if case.expected_first_tool != expected:
                raise ValueError(
                    f"{ctx} case_id={cid}：{case.category} 的 "
                    f"expected_first_tool 必须为 {expected}，实际 "
                    f"{case.expected_first_tool!r}"
                )
            if case.expected_first_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：{case.category} 不允许设置 "
                    "expected_first_tools（应使用 expected_first_tool）"
                )
            if expected not in case.required_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：required_tools 必须包含 "
                    f"本类首工具 {expected}"
                )
            if not case.required_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：{case.category} 的 required_tools "
                    "不能为空"
                )
        elif case.category == "multi_step":
            if case.expected_terminal != "completed":
                raise ValueError(
                    f"{ctx} case_id={cid}：multi_step 的 expected_terminal "
                    "必须为 completed"
                )
            if case.expected_first_action != "tool_call":
                raise ValueError(
                    f"{ctx} case_id={cid}：multi_step 的 expected_first_action "
                    "必须为 tool_call"
                )
            if len(case.required_tools) < 2:
                raise ValueError(
                    f"{ctx} case_id={cid}：multi_step 的 required_tools 至少 2 个"
                )
            if not case.allowed_tool_sequences:
                raise ValueError(
                    f"{ctx} case_id={cid}：multi_step 的 allowed_tool_sequences "
                    "不能为空"
                )
            if case.expected_first_tool is not None:
                raise ValueError(
                    f"{ctx} case_id={cid}：multi_step 不允许设置 "
                    "expected_first_tool（应使用 expected_first_tools）"
                )
            if not case.expected_first_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：multi_step 的 expected_first_tools "
                    "不能为空"
                )
            required_set = set(case.required_tools)
            for seq_idx, seq in enumerate(case.allowed_tool_sequences):
                if set(seq) != required_set:
                    raise ValueError(
                        f"{ctx} case_id={cid}：allowed_tool_sequences[{seq_idx}] "
                        f"必须完整覆盖 required_tools（每个序列自身都要覆盖），"
                        f"实际 {list(seq)}，required={sorted(required_set)}"
                    )
            first_tools = {seq[0] for seq in case.allowed_tool_sequences}
            if set(case.expected_first_tools) != first_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：expected_first_tools 必须等于 "
                    f"allowed_tool_sequences 各序列首工具集合，实际 "
                    f"{sorted(case.expected_first_tools)}，期望 {sorted(first_tools)}"
                )
        elif case.category == "refusal_safety":
            if case.expected_terminal != "refused":
                raise ValueError(
                    f"{ctx} case_id={cid}：refusal_safety 的 expected_terminal "
                    "必须为 refused"
                )
            if case.expected_first_action != "refuse":
                raise ValueError(
                    f"{ctx} case_id={cid}：refusal_safety 的 "
                    "expected_first_action 必须为 refuse"
                )
            if case.required_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：refusal_safety 的 required_tools 必须为空"
                )
            if not case.allowed_refuse_reason_codes:
                raise ValueError(
                    f"{ctx} case_id={cid}：refusal_safety 的 "
                    "allowed_refuse_reason_codes 不能为空"
                )
            if case.expected_first_tool is not None or case.expected_first_tools:
                raise ValueError(
                    f"{ctx} case_id={cid}：refusal_safety 不允许设置 "
                    "expected_first_tool(s)"
                )
        else:  # pragma: no cover - 枚举已封闭，理论上不可达
            raise ValueError(f"{ctx} case_id={cid}：未知 category {case.category!r}")

        # 全类别公共不变量：required 与 forbidden 必须不相交
        common_required_forbidden = set(case.required_tools) & set(
            case.forbidden_tools
        )
        if common_required_forbidden:
            raise ValueError(
                f"{ctx} case_id={cid}：required_tools 与 forbidden_tools 相交："
                f"{sorted(common_required_forbidden)}"
            )

        if case.expected_terminal == "refused":
            for a in case.completion_assertions:
                if a.type != "status_equals" or a.value != "refused":
                    raise ValueError(
                        f"{ctx} case_id={cid}：refused case 的 "
                        "completion_assertions 只能含 "
                        '{"status_equals": "refused"}'
                    )
        else:
            for a in case.completion_assertions:
                if a.type == "status_equals":
                    raise ValueError(
                        f"{ctx} case_id={cid}：completed case 不允许 "
                        "status_equals 断言（矛盾 Gold）"
                    )

        uses_knowledge = "knowledge_search" in case.required_tools
        if case.category == "knowledge_search" and case.knowledge_gold is None:
            raise ValueError(
                f"{ctx} case_id={cid}：knowledge_search 必须登记 "
                "knowledge_gold（source_name + evidence_phrase）"
            )
        if not uses_knowledge and case.knowledge_gold is not None:
            raise ValueError(
                f"{ctx} case_id={cid}：只有 required_tools 含 knowledge_search "
                "的 case 允许 knowledge_gold"
            )

        # 交叉类别：direct/refusal 不得要求任何只读工具
        if case.category in _NON_TOOL_CATEGORIES:
            if set(case.required_tools) & set(TOOLS):
                raise ValueError(
                    f"{ctx} case_id={cid}：{case.category} 不得要求任何只读工具"
                )

    @classmethod
    def _validate_set_invariants(cls, set_obj: "Gate4ToolUseEvaluationSet") -> None:
        """set 级不变量：case_id 连续、六类各 4 条。"""
        ids = [int(c.case_id[3:]) for c in set_obj.cases]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError(
                "case_id 必须唯一且连续 g4q001..g4q%03d，实际 "
                f"{[c.case_id for c in set_obj.cases]}" % len(ids)
            )
        counts = set_obj.category_counts
        bad = {
            cat: n
            for cat, n in counts.items()
            if n != CATEGORY_COUNT_PER_TYPE
        }
        if bad:
            raise ValueError(
                f"每类必须恰好 {CATEGORY_COUNT_PER_TYPE} 条，实际 "
                f"{ {k: v for k, v in sorted(bad.items())} }"
            )

    @staticmethod
    def _compute_id(cases) -> str:
        """无歧义规范 JSON 计算 SHA-256（12 位十六进制）。

        payload 绑定：evaluation_set schema_version + 全部规范化 Case
        （to_dict）。不绑定时间、行顺序、输入文件地址，也不绑定
        evaluation_set_id 自身（避免自指）。
        """
        if not cases:
            raise ValueError(
                "评测集不能为空：无法为零 Case 数据生成 evaluation_set_id"
            )
        ordered = sorted(cases, key=lambda c: c.case_id)
        payload = {
            "schema_version": GATE4_TOOL_USE_SET_SCHEMA_VERSION,
            "cases": [c.to_dict() for c in ordered],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def build_manifest(
    set_obj: Gate4ToolUseEvaluationSet,
    jsonl_sha256: str,
    created_for: str = "G4-EVAL-06",
) -> dict:
    """构建 Gate 4 Tool-Agent Dev v1 Manifest（不写盘，由调用方落盘）。"""
    if not isinstance(set_obj, Gate4ToolUseEvaluationSet):
        raise TypeError(
            "set_obj 必须是 Gate4ToolUseEvaluationSet，实际 "
            f"{type(set_obj).__name__}"
        )
    if not isinstance(jsonl_sha256, str) or not jsonl_sha256.strip():
        raise ValueError("jsonl_sha256 必须是非空字符串")
    return {
        "schema_version": GATE4_TOOL_USE_MANIFEST_SCHEMA_VERSION,
        "evaluation_set_id": set_obj.evaluation_set_id,
        "case_count": set_obj.case_count,
        "category_counts": set_obj.category_counts,
        "jsonl_sha256": jsonl_sha256,
        "created_for": created_for,
        "code_reference_commit": CODE_REFERENCE_COMMIT,
        "knowledge_corpus_id": KNOWLEDGE_CORPUS_ID,
        "knowledge_corpus_file_count": KNOWLEDGE_CORPUS_FILE_COUNT,
    }


__all__ = [
    "GATE4_TOOL_USE_CASE_SCHEMA_VERSION",
    "GATE4_TOOL_USE_SET_SCHEMA_VERSION",
    "GATE4_TOOL_USE_MANIFEST_SCHEMA_VERSION",
    "CATEGORIES",
    "CATEGORY_COUNT_PER_TYPE",
    "TERMINALS",
    "FIRST_ACTIONS",
    "TOOLS",
    "ASSERTION_TYPES",
    "REFUSE_REASON_CODES",
    "CODE_REFERENCE_COMMIT",
    "KNOWLEDGE_CORPUS_ID",
    "KNOWLEDGE_CORPUS_FILE_COUNT",
    "CompletionAssertion",
    "KnowledgeGold",
    "Gate4ToolUseCase",
    "Gate4ToolUseEvaluationSet",
    "build_manifest",
]
