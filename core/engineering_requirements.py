"""Deterministic System C evidence requirements.

This module is deliberately independent from the evaluator and from repository
content. It turns a user question into one frozen structural requirement and
evaluates only the public evidence already collected by the Runtime.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


PUBLIC_EVIDENCE_KINDS = (
    "knowledge",
    "project_code",
    "project_doc",
    "project_change",
    "project_test",
)
_PUBLIC_EVIDENCE_KINDS = frozenset(PUBLIC_EVIDENCE_KINDS)
_REQUIREMENT_SOURCE_GRANULARITIES = {
    "project_code": frozenset({"source_body"}),
    "project_doc": frozenset({"source_body"}),
    "project_test": frozenset({"source_body"}),
    "project_change": frozenset({"diff"}),
}
# v5 adds only bound-project overviews to the existing document requirement.
# v4 remains selectable for reproducible R02 comparisons. Frozen profile
# shapes and all source/mixed requirements stay intact.
LEGACY_ROUTER_VERSION = "engineering_requirement_router_v4"
ROUTER_VERSION = "engineering_requirement_router_v5"
_SUPPORTED_ROUTER_VERSIONS = (LEGACY_ROUTER_VERSION, ROUTER_VERSION, "hybrid_task_contract_v1")


class EngineeringRequirementProfile(str, Enum):
    """The only profiles that the bounded Router may produce."""

    THEORY_CODE_V1 = "THEORY_CODE_V1"
    CHANGE_TEST_V1 = "CHANGE_TEST_V1"
    DIAGNOSIS_SINGLE_V1 = "DIAGNOSIS_SINGLE_V1"
    DIAGNOSIS_CROSS_FILE_V1 = "DIAGNOSIS_CROSS_FILE_V1"
    DOCS_CODE_V1 = "DOCS_CODE_V1"
    PROJECT_CODE_V1 = "PROJECT_CODE_V1"
    PROJECT_DOC_V1 = "PROJECT_DOC_V1"
    PROJECT_TEST_V1 = "PROJECT_TEST_V1"
    NO_ADDITIONAL_REQUIREMENT = "NO_ADDITIONAL_REQUIREMENT"
    TASK_CONTRACT_V1 = "TASK_CONTRACT_V1"


THEORY_CODE_V1 = EngineeringRequirementProfile.THEORY_CODE_V1
CHANGE_TEST_V1 = EngineeringRequirementProfile.CHANGE_TEST_V1
DIAGNOSIS_SINGLE_V1 = EngineeringRequirementProfile.DIAGNOSIS_SINGLE_V1
DIAGNOSIS_CROSS_FILE_V1 = EngineeringRequirementProfile.DIAGNOSIS_CROSS_FILE_V1
DOCS_CODE_V1 = EngineeringRequirementProfile.DOCS_CODE_V1
PROJECT_CODE_V1 = EngineeringRequirementProfile.PROJECT_CODE_V1
PROJECT_DOC_V1 = EngineeringRequirementProfile.PROJECT_DOC_V1
PROJECT_TEST_V1 = EngineeringRequirementProfile.PROJECT_TEST_V1
NO_ADDITIONAL_REQUIREMENT = EngineeringRequirementProfile.NO_ADDITIONAL_REQUIREMENT


_FROZEN_PROFILE_SPECS = MappingProxyType(
    {
        THEORY_CODE_V1: (
            (("knowledge",), ("project_code", "project_doc")),
            1,
        ),
        CHANGE_TEST_V1: (
            (("project_change",), ("project_test",)),
            0,
        ),
        DIAGNOSIS_SINGLE_V1: ((("project_code",),), 1),
        DIAGNOSIS_CROSS_FILE_V1: ((("project_code",),), 2),
        DOCS_CODE_V1: ((("project_doc",), ("project_code",)), 1),
        PROJECT_CODE_V1: ((("project_code",),), 1),
        PROJECT_DOC_V1: ((("project_doc",),), 0),
        PROJECT_TEST_V1: ((("project_test",),), 0),
        NO_ADDITIONAL_REQUIREMENT: ((), 0),
    }
)
FROZEN_PROFILE_SPECS = _FROZEN_PROFILE_SPECS


def _strict_non_negative_int(value: object, label: str) -> None:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError(f"{label} must be a strict int")
    if value < 0:
        raise ValueError(f"{label} must be non-negative")


def _canonical_profile(value: object) -> EngineeringRequirementProfile:
    if isinstance(value, EngineeringRequirementProfile):
        return value
    if type(value) is str:
        try:
            return EngineeringRequirementProfile(value)
        except ValueError as exc:
            raise ValueError(f"unknown requirement profile: {value!r}") from exc
    raise TypeError("requirement_profile must be a frozen EngineeringRequirementProfile")


def _canonical_groups(value: object) -> tuple[tuple[str, ...], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("required_evidence_groups must be a sequence of groups")
    groups: list[tuple[str, ...]] = []
    for group in value:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            raise TypeError("each evidence group must be a sequence")
        items = tuple(group)
        if not items:
            raise ValueError("evidence groups must not be empty")
        if any(type(kind) is not str for kind in items):
            raise TypeError("evidence kinds must be strings")
        if any(kind not in _PUBLIC_EVIDENCE_KINDS for kind in items):
            raise ValueError("evidence kind is not a public EngineeringEvidence kind")
        if len(set(items)) != len(items):
            raise ValueError("evidence kinds must not repeat inside a group")
        group_tuple = tuple(items)
        if group_tuple in groups:
            raise ValueError("evidence groups must not repeat")
        groups.append(group_tuple)
    return tuple(groups)


@dataclass(frozen=True)
class EngineeringEvidenceRequirement:
    """Immutable minimum public-evidence shape for one Engineering request."""

    requirement_profile: EngineeringRequirementProfile
    required_evidence_groups: tuple[tuple[str, ...], ...]
    min_distinct_project_code_paths: int
    router_version: str = ROUTER_VERSION

    def __post_init__(self) -> None:
        profile = _canonical_profile(self.requirement_profile)
        groups = _canonical_groups(self.required_evidence_groups)
        _strict_non_negative_int(
            self.min_distinct_project_code_paths,
            "min_distinct_project_code_paths",
        )
        if type(self.router_version) is not str or not self.router_version.strip():
            raise ValueError("router_version must be a non-empty string")
        if self.router_version not in _SUPPORTED_ROUTER_VERSIONS:
            raise ValueError("router_version must be a supported system policy version")
        if profile is EngineeringRequirementProfile.TASK_CONTRACT_V1:
            if self.router_version != "hybrid_task_contract_v1":
                raise ValueError("Task contract requires its own policy version")
            if self.min_distinct_project_code_paths > 8:
                raise ValueError("Task contract source targets exceed bound")
        else:
            if self.router_version == "hybrid_task_contract_v1":
                raise ValueError("Legacy profiles retain the legacy policy version")
            expected_groups, expected_min_paths = _FROZEN_PROFILE_SPECS[profile]
            if groups != expected_groups:
                raise ValueError("required_evidence_groups do not match frozen profile")
            if self.min_distinct_project_code_paths != expected_min_paths:
                raise ValueError("min_distinct_project_code_paths do not match frozen profile")
        if profile is DIAGNOSIS_CROSS_FILE_V1 and self.min_distinct_project_code_paths < 2:
            raise ValueError("cross-file Diagnosis requires at least two code paths")
        object.__setattr__(self, "requirement_profile", profile)
        object.__setattr__(self, "required_evidence_groups", groups)


@dataclass(frozen=True)
class EvidenceRequirementState:
    """Immutable shape-only result returned by the evidence evaluator."""

    satisfied: bool
    missing_evidence_groups: tuple[tuple[str, ...], ...]
    evidence_kind_counts: Mapping[str, int]
    distinct_project_code_paths: int
    required_min_distinct_project_code_paths: int

    def __post_init__(self) -> None:
        if type(self.satisfied) is not bool:
            raise TypeError("satisfied must be a strict bool")
        groups = _canonical_groups(self.missing_evidence_groups)
        _strict_non_negative_int(
            self.distinct_project_code_paths,
            "distinct_project_code_paths",
        )
        _strict_non_negative_int(
            self.required_min_distinct_project_code_paths,
            "required_min_distinct_project_code_paths",
        )
        if not isinstance(self.evidence_kind_counts, Mapping):
            raise TypeError("evidence_kind_counts must be a Mapping")
        counts: dict[str, int] = {}
        for kind in PUBLIC_EVIDENCE_KINDS:
            value = self.evidence_kind_counts.get(kind, 0)
            _strict_non_negative_int(value, f"evidence_kind_counts[{kind!r}]")
            counts[kind] = value
        unknown = set(self.evidence_kind_counts) - _PUBLIC_EVIDENCE_KINDS
        if unknown:
            raise ValueError("evidence_kind_counts contains an unknown evidence kind")
        if self.satisfied and groups:
            raise ValueError("satisfied state cannot have missing evidence groups")
        object.__setattr__(self, "missing_evidence_groups", groups)
        object.__setattr__(
            self,
            "evidence_kind_counts",
            MappingProxyType(counts),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "missing_evidence_groups": [list(group) for group in self.missing_evidence_groups],
            "evidence_kind_counts": dict(self.evidence_kind_counts),
            "distinct_project_code_paths": self.distinct_project_code_paths,
            "required_min_distinct_project_code_paths": (
                self.required_min_distinct_project_code_paths
            ),
        }


def _public_value(item: object, key: str) -> object:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def evaluate_evidence_requirement(
    requirement: EngineeringEvidenceRequirement,
    public_evidence: Sequence[object],
) -> EvidenceRequirementState:
    """Evaluate only public evidence kind/count/path shape.

    Snippet text, answers, questions, Gold, and semantic relevance are not
    consulted. ``changed_files`` and other observations without one of the
    five public kinds are intentionally ignored. Structured ToolResultEvidence
    must also have a requirement-compatible source granularity and complete
    material; its boolean eligibility flag alone is not sufficient.
    """

    if not isinstance(requirement, EngineeringEvidenceRequirement):
        raise TypeError("requirement must be EngineeringEvidenceRequirement")
    if isinstance(public_evidence, (str, bytes, Mapping)) or not isinstance(
        public_evidence, Sequence
    ):
        raise TypeError("public_evidence must be a sequence")
    counts = {kind: 0 for kind in PUBLIC_EVIDENCE_KINDS}
    code_paths: set[str] = set()
    for item in public_evidence:
        kind = _public_value(item, "kind")
        if kind not in _PUBLIC_EVIDENCE_KINDS:
            continue
        eligible = _public_value(item, "requirement_eligible")
        granularity = _public_value(item, "granularity")
        completeness = _public_value(item, "completeness")
        if eligible is not None:
            if type(eligible) is not bool or not eligible:
                continue
            if (
                granularity not in _REQUIREMENT_SOURCE_GRANULARITIES.get(kind, ())
                or completeness != "complete"
            ):
                continue
        elif granularity is not None and (
            granularity not in _REQUIREMENT_SOURCE_GRANULARITIES.get(kind, ())
            or completeness != "complete"
        ):
            # Fail closed for any structured source metadata even if a caller
            # omitted the convenience eligibility field.
            continue
        counts[kind] += 1
        if kind == "project_code":
            path = _public_value(item, "path")
            if type(path) is str and path.strip():
                code_paths.add(path)

    missing = tuple(
        group
        for group in requirement.required_evidence_groups
        if not any(counts[kind] >= 1 for kind in group)
    )
    distinct_paths = len(code_paths)
    path_shape_satisfied = (
        requirement.min_distinct_project_code_paths == 0
        or (
            not missing
            and counts["project_code"] == 0
        )
        or distinct_paths >= requirement.min_distinct_project_code_paths
    )
    satisfied = not missing and path_shape_satisfied
    return EvidenceRequirementState(
        satisfied=satisfied,
        missing_evidence_groups=missing,
        evidence_kind_counts=counts,
        distinct_project_code_paths=distinct_paths,
        required_min_distinct_project_code_paths=(
            requirement.min_distinct_project_code_paths
        ),
    )


def _normalize_signal_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[^\w\s\u3400-\u9fff]", " ", value)


def _has_signal(text: str, signal: str) -> bool:
    normalized_signal = _normalize_signal_text(signal)
    if any("\u3400" <= char <= "\u9fff" for char in normalized_signal):
        return normalized_signal in text
    pattern = rf"(?<![\w]){re.escape(normalized_signal)}(?![\w])"
    return re.search(pattern, text) is not None


def _has_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(_has_signal(text, signal) for signal in signals)


_CHANGE_SIGNALS = (
    "change",
    "changed",
    "changes",
    "commit",
    "diff",
    "变更",
    "变动",
    "修改",
)
_TEST_SIGNALS = (
    "test",
    "tests",
    "testing",
    "regression",
    "test coverage",
    "测试",
    "测试覆盖",
    "回归",
)
_DOC_SIGNALS = ("documentation", "readme", "doc", "文档")
_IMPLEMENTATION_SIGNALS = (
    "implementation",
    "current implementation",
    "code",
    "实现",
    "当前实现",
    "工程实现",
    "源码实现",
)
_CONSISTENCY_SIGNALS = (
    "consistency",
    "correspondence",
    "still accurate",
    "compare",
    "against",
    "versus",
    "check",
    "review",
    "relation",
    "relate",
    "correspond",
    "核对",
    "检查",
    "判断",
    "比较",
    "对比",
    "差异",
    "差距",
    "对应",
    "一致性",
    "是否对应",
)
_THEORY_SIGNALS = (
    "principle",
    "mechanism",
    "theory",
    "aggregation",
    "verification",
    "explicit state",
    "control flow",
    "原则",
    "原理",
    "机制",
    "显式 state",
    "流程控制",
    "证据聚合",
    "控制面",
)
_SOURCE_SIGNALS = (
    "implementation",
    "source",
    "code",
    "current implementation",
    "当前实现",
    "工程实现",
    "源码实现",
)
_COMPARE_SIGNALS = (
    "compare",
    "relate",
    "map",
    "mapping",
    "against",
    "versus",
    "结合",
    "对照",
    "映射",
    "对应",
    "比较",
    "对比",
)
_DIAGNOSIS_SIGNALS = (
    "failure",
    "error",
    "fallback",
    "validation",
    "config",
    "runtime behavior",
    "early termination",
    "异常",
    "失败",
    "回退",
    "校验",
    "配置",
    "诊断",
    "提前结束",
)
_DIAGNOSIS_DETAIL_SIGNALS = (
    "reason",
    "path",
    "behavior",
    "propagation",
    "diagnosis",
    "field",
    "control state",
    "原因",
    "路径",
    "行为",
    "传播",
    "诊断",
    "字段",
    "控制状态",
)
_CROSS_FILE_SIGNALS = (
    "cross-file",
    "cross file",
    "cross module",
    "cross-module",
    "propagation",
    "call chain",
    "calling chain",
    "caller / callee",
    "caller callee",
    "between components",
    "between layers",
    "跨文件",
    "跨模块",
    "传播",
    "调用链",
    "组件之间",
    "层之间",
)
_PROJECT_SCOPE_SIGNALS = (
    "current project",
    "current repository",
    "project snapshot",
    "repo-relative",
    "current source",
    "current code",
    "current implementation",
    "project code",
    "project source",
    "repository source",
    "repository code",
    "repo source",
    "repo code",
    "current snapshot",
    "工程快照",
    "当前工程",
    "当前仓库",
    "当前源码",
    "当前代码",
    "当前实现",
    "项目代码",
    "项目源码",
    "仓库源码",
    "仓库代码",
)
# PRODUCT-REPAIR-23: repository/source-navigation intent. Users ask about the
# bound repository's source, module/function/file locations, or call
# relationships without saying "当前项目/当前仓库". These bounded lexical
# patterns activate the Repository Evidence requirement instead of silently
# falling through to NO_ADDITIONAL_REQUIREMENT. Generic technology-knowledge
# phrasings (原理/怎么实现 without a location or call token) must NOT match.
_REPO_SOURCE_SIGNALS = (
    "源码",
    "源代码",
    "source code",
    "codebase",
    "代码库",
)
_REPO_LOCATION_SIGNALS = (
    "哪个文件",
    "在哪个文件",
    "哪个模块",
    "哪个函数",
    "哪个方法",
    "哪里实现",
    "在哪里实现",
    "在哪实现",
    "哪里定义",
    "在哪里定义",
    "实现位置",
    "模块在哪里",
    "函数在哪里",
    "where implemented",
    "which file",
    "which module",
    "which function",
    "where defined",
    "where is",
    "where are",
)
_REPO_CODE_ARTIFACT_SIGNALS = (
    "函数",
    "模块",
    "方法",
    "逻辑",
    "实现",
    "代码",
    "function",
    "module",
    "method",
    "logic",
    "implementation",
    "code",
)
_REPO_CALL_RELATION_SIGNALS = (
    "谁调用",
    "谁调用了",
    "被谁调用",
    "调用者",
    "调用链",
    "调用关系",
    "调用点",
    "who calls",
    "call chain",
    "caller",
    "callee",
)


def _repo_navigation_intent(normalized: str) -> bool:
    """True when the question names the bound repository's code directly.

    Three bounded tiers: an explicit source reference alone is a repository
    question; a call-relationship question always targets concrete code; a
    location question only counts when it co-occurs with a code artifact,
    which keeps "原理/怎么实现" style knowledge questions unrouted.
    """

    if _has_any(normalized, _REPO_SOURCE_SIGNALS):
        return True
    if _has_any(normalized, _REPO_CALL_RELATION_SIGNALS):
        return True
    return _has_any(normalized, _REPO_LOCATION_SIGNALS) and _has_any(
        normalized, _REPO_CODE_ARTIFACT_SIGNALS
    )


_DOCUMENT_EVIDENCE_SIGNALS = (
    "依据", "根据", "阅读", "查阅", "引用", "总结", "概括",
    "according to", "based on", "read", "cite", "summarize", "summarise",
)

_OVERVIEW_SCOPE_PATTERN = re.compile(
    r"(?:当前|目前|现在|这个|本|此|我们|咱们)(?:的|这个|当前|目前|现在|绑定的){0,3}(?:项目|仓库|工程)"
    r"|\b(?:this|current|our)\s+(?:project|repository|repo)\b",
    re.IGNORECASE,
)


def _repo_overview_intent(question: str) -> bool:
    """A description of the bound project's purpose, rather than a root fact.

    This is one document-evidence domain, not a list of known badcases. More
    specific source/diagnosis tasks retain their requirements. Presentation
    advice and a clause qualified by directory/binding metadata are excluded.
    """
    text = _normalize_signal_text(question)
    scopes = list(_OVERVIEW_SCOPE_PATTERN.finditer(text))
    if not scopes or _repo_navigation_intent(text) or _has_any(text, _SOURCE_SIGNALS):
        return False
    if _has_any(text, ("面试", "简历", "话术", "模板", "如何介绍", "怎么介绍", "怎样介绍",
                       "how to describe", "how to introduce", "resume", "interview")):
        return False
    if _has_any(text, _DIAGNOSIS_SIGNALS) and _has_any(text, _DIAGNOSIS_DETAIL_SIGNALS):
        return False
    for scope in scopes:
        before, after = text[:scope.start()], text[scope.end():]
        if re.search(r"(?:介绍(?:一下)?|概述|概括|简述|概览|说一下|讲一下|聊一下)\s*$", before):
            if re.match(r"\s*(?:的?(?:情况|概况|概览|用途|功能|主要能力|整体架构))?(?:\s*[，,。.!！？?；;]|\s*$)", after):
                return True
        if re.search(r"\b(?:introduce|describe|summarize|summarise|overview of|tell me about)\s+(?:the\s+)?$", before):
            if re.match(r"\s*(?:(?:purpose|features|capabilities|architecture)\b)?(?:\s*[,.!?;]|\s*$)", after):
                return True
        if re.match(r"\s*(?:主要|到底|是|都|的)*(?:做什么|干什么|有什么功能|有哪些能力|用途|功能|概览|概况)", after):
            return True
        if re.search(r"\bwhat\s+(?:does|is)\s+(?:the\s+)?$", before) and re.match(r"\s+(?:do|about|for)\b", after):
            return True
    return False
_REPOSITORY_DOCUMENT_SCOPE_SIGNALS = ("项目", "仓库", "工程", "project", "repository", "repo")
_LOCAL_DOCUMENT_PATH_PATTERN = re.compile(
    r"(?<![a-zA-Z0-9_:/.\-])(?:[a-zA-Z0-9_.\-]+/)*"
    r"(?:[a-zA-Z0-9_.\-]+|(?<=/)[\w.\-]+)\.(?:md|rst|txt)"
    r"(?![a-zA-Z0-9_\-]|\.[a-zA-Z0-9_\-])",
    re.IGNORECASE,
)
_UNICODE_DOCUMENT_PATH_PATTERN = re.compile(
    r"(?<![\w:/.\-])(?:[\w.\-]+/)*[\w.\-]+\.(?:md|rst|txt)"
    r"(?![a-zA-Z0-9_\-]|\.[a-zA-Z0-9_\-])",
    re.IGNORECASE,
)


def _document_reference_context(question: str) -> tuple[tuple[str, ...], str]:
    """Separate literal document names from the surrounding request signals."""

    remaining = unicodedata.normalize("NFKC", question).replace("\\", "/")
    paths: list[str] = []
    # ASCII starts keep an adjacent Chinese verb (根据README.md) outside the
    # filename. The second pass supports delimited Unicode names/directories.
    for pattern in (_LOCAL_DOCUMENT_PATH_PATTERN, _UNICODE_DOCUMENT_PATH_PATTERN):
        matches = list(pattern.finditer(remaining))
        paths.extend(match.group() for match in matches)
        for match in reversed(matches):
            remaining = remaining[:match.start()] + " " * len(match.group()) + remaining[match.end():]
    return tuple(paths), _normalize_signal_text(remaining)


def _repo_document_intent(question: str) -> bool:
    """Recognize an explicit local-document evidence request, not its topic.

    A read/citation operation must accompany either a local document filename
    or a repository-scoped document reference. Generic writing/design questions
    and abstract documentation comparisons stay outside this hard minimum.
    This does not inspect the filesystem or presume the document exists.
    """

    paths, intent = _document_reference_context(question)
    if not _has_any(intent, _DOCUMENT_EVIDENCE_SIGNALS):
        return False
    if _repo_navigation_intent(intent) or _has_any(intent, _SOURCE_SIGNALS):
        return False
    # Import the leaf classifier at call time: tool_agent's package facade
    # imports this requirement module while it is being initialized.
    from core.tool_agent.project_files import classify_project_evidence_path

    for path in paths:
        if ".." not in path.split("/") and classify_project_evidence_path(path) == "project_doc":
            return True
    if paths:
        return False
    return _has_any(intent, _REPOSITORY_DOCUMENT_SCOPE_SIGNALS) and _has_any(
        intent, _DOC_SIGNALS
    )


_TEST_INSPECTION_SIGNALS = (
    "which", "where", "read", "cite", "locate", "existing", "cover", "covers",
    "哪些", "哪个", "哪里", "阅读", "查阅", "引用", "定位", "已有", "覆盖",
)
_REPOSITORY_TEST_SCOPE_SIGNALS = (
    "repository tests", "repo tests", "project tests", "仓库测试", "项目测试",
    "仓库里的测试", "仓库中的测试", "项目里的测试", "项目中的测试",
)
_LOCAL_TEST_PATH_PATTERN = re.compile(
    r"(?<![\w:/.\-])(?:[\w.\-]+/)*[\w.\-]+\."
    r"(?:py|rb|java|cs|go|js|jsx|ts|tsx|rs|c|cc|cpp|h|hpp|php|sh|sql)"
    r"(?![a-zA-Z0-9_\-]|\.[a-zA-Z0-9_\-])",
    re.IGNORECASE,
)


def _repo_test_intent(question: str) -> bool:
    """Require test evidence only for inspection of the bound repo's tests.

    Test design advice is not an inspection request. Existing mixed/source
    profiles keep their precedence; no filename or symbol is hard-coded.
    """
    text = unicodedata.normalize("NFKC", question).replace("\\", "/")
    matches = list(_LOCAL_TEST_PATH_PATTERN.finditer(text))
    for match in reversed(matches):
        text = text[:match.start()] + " " * len(match.group()) + text[match.end():]
    intent = _normalize_signal_text(text)
    if not _has_any(intent, _TEST_INSPECTION_SIGNALS):
        return False
    if _repo_navigation_intent(intent) or _has_any(intent, _SOURCE_SIGNALS):
        return False
    from core.tool_agent.project_files import is_test_path

    if any(".." not in match.group().split("/") and is_test_path(match.group()) for match in matches):
        return True
    return _has_any(intent, _TEST_SIGNALS) and (
        _has_any(intent, _PROJECT_SCOPE_SIGNALS)
        or _has_any(intent, _REPOSITORY_TEST_SCOPE_SIGNALS)
    )


def route_engineering_evidence_requirement(
    question: str,
    *,
    router_version: str = ROUTER_VERSION,
) -> EngineeringEvidenceRequirement:
    """Route one question using bounded lexical semantics only."""

    if type(question) is not str or not question.strip():
        raise ValueError("question must be a non-empty string")
    if router_version not in _SUPPORTED_ROUTER_VERSIONS:
        raise ValueError("Unsupported requirement router_version")
    normalized = _normalize_signal_text(question)

    if _has_any(normalized, _CHANGE_SIGNALS) and _has_any(normalized, _TEST_SIGNALS):
        profile = CHANGE_TEST_V1
    elif (
        _has_any(normalized, _DOC_SIGNALS)
        and _has_any(normalized, _IMPLEMENTATION_SIGNALS)
        and _has_any(normalized, _CONSISTENCY_SIGNALS)
    ):
        profile = DOCS_CODE_V1
    elif (
        _has_any(normalized, _THEORY_SIGNALS)
        and _has_any(normalized, _SOURCE_SIGNALS)
        and _has_any(normalized, _COMPARE_SIGNALS)
    ):
        profile = THEORY_CODE_V1
    elif router_version == ROUTER_VERSION and _repo_overview_intent(question):
        profile = PROJECT_DOC_V1
    elif _repo_document_intent(question):
        # An explicit document source outranks a diagnosis topic. Mixed
        # docs/code and theory/code requests retain their priorities above.
        profile = PROJECT_DOC_V1
    elif _repo_test_intent(question):
        profile = PROJECT_TEST_V1
    elif _has_any(normalized, _DIAGNOSIS_SIGNALS) and _has_any(
        normalized, _DIAGNOSIS_DETAIL_SIGNALS
    ):
        profile = (
            DIAGNOSIS_CROSS_FILE_V1
            if _has_any(normalized, _CROSS_FILE_SIGNALS)
            else DIAGNOSIS_SINGLE_V1
        )
    elif _has_any(normalized, _PROJECT_SCOPE_SIGNALS):
        profile = PROJECT_CODE_V1
    elif _repo_navigation_intent(normalized):
        # PRODUCT-REPAIR-23 fallback: explicit source references, module or
        # function location questions, and call-relationship questions name
        # the bound repository even without a project-scope qualifier.
        profile = PROJECT_CODE_V1
    else:
        profile = NO_ADDITIONAL_REQUIREMENT

    groups, min_paths = _FROZEN_PROFILE_SPECS[profile]
    return EngineeringEvidenceRequirement(
        requirement_profile=profile,
        required_evidence_groups=groups,
        min_distinct_project_code_paths=min_paths,
        router_version=router_version,
    )


__all__ = [
    "PUBLIC_EVIDENCE_KINDS",
    "ROUTER_VERSION",
    "LEGACY_ROUTER_VERSION",
    "EngineeringRequirementProfile",
    "EngineeringEvidenceRequirement",
    "EvidenceRequirementState",
    "FROZEN_PROFILE_SPECS",
    "THEORY_CODE_V1",
    "CHANGE_TEST_V1",
    "DIAGNOSIS_SINGLE_V1",
    "DIAGNOSIS_CROSS_FILE_V1",
    "DOCS_CODE_V1",
    "PROJECT_CODE_V1",
    "PROJECT_DOC_V1",
    "PROJECT_TEST_V1",
    "NO_ADDITIONAL_REQUIREMENT",
    "route_engineering_evidence_requirement",
    "evaluate_evidence_requirement",
]
