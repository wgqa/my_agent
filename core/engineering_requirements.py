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
ROUTER_VERSION = "engineering_requirement_router_v1"


class EngineeringRequirementProfile(str, Enum):
    """The only profiles that the bounded Router may produce."""

    THEORY_CODE_V1 = "THEORY_CODE_V1"
    CHANGE_TEST_V1 = "CHANGE_TEST_V1"
    DIAGNOSIS_SINGLE_V1 = "DIAGNOSIS_SINGLE_V1"
    DIAGNOSIS_CROSS_FILE_V1 = "DIAGNOSIS_CROSS_FILE_V1"
    DOCS_CODE_V1 = "DOCS_CODE_V1"
    NO_ADDITIONAL_REQUIREMENT = "NO_ADDITIONAL_REQUIREMENT"


THEORY_CODE_V1 = EngineeringRequirementProfile.THEORY_CODE_V1
CHANGE_TEST_V1 = EngineeringRequirementProfile.CHANGE_TEST_V1
DIAGNOSIS_SINGLE_V1 = EngineeringRequirementProfile.DIAGNOSIS_SINGLE_V1
DIAGNOSIS_CROSS_FILE_V1 = EngineeringRequirementProfile.DIAGNOSIS_CROSS_FILE_V1
DOCS_CODE_V1 = EngineeringRequirementProfile.DOCS_CODE_V1
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
        if self.router_version != ROUTER_VERSION:
            raise ValueError(f"router_version must equal {ROUTER_VERSION!r}")
        expected_groups, expected_min_paths = _FROZEN_PROFILE_SPECS[profile]
        if groups != expected_groups:
            raise ValueError("required_evidence_groups do not match frozen profile")
        if self.min_distinct_project_code_paths != expected_min_paths:
            raise ValueError("min_distinct_project_code_paths does not match frozen profile")
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
    five public kinds are intentionally ignored.
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


_CHANGE_SIGNALS = ("change", "commit", "diff", "变更")
_TEST_SIGNALS = ("test", "regression", "测试", "回归")
_DOC_SIGNALS = ("documentation", "readme", "doc", "文档")
_IMPLEMENTATION_SIGNALS = (
    "implementation",
    "current implementation",
    "code",
    "实现",
    "当前实现",
)
_CONSISTENCY_SIGNALS = (
    "consistency",
    "correspondence",
    "still accurate",
    "一致性",
    "是否对应",
)
_THEORY_SIGNALS = ("principle", "mechanism", "theory", "原理", "机制")
_SOURCE_SIGNALS = ("implementation", "source", "code", "当前实现")
_COMPARE_SIGNALS = ("compare", "relate", "对照", "结合")
_DIAGNOSIS_SIGNALS = (
    "failure",
    "error",
    "fallback",
    "validation",
    "config",
    "runtime behavior",
    "异常",
    "失败",
    "回退",
    "校验",
    "配置",
)
_DIAGNOSIS_DETAIL_SIGNALS = (
    "reason",
    "path",
    "behavior",
    "propagation",
    "diagnosis",
    "原因",
    "路径",
    "行为",
    "传播",
    "诊断",
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


def route_engineering_evidence_requirement(
    question: str,
) -> EngineeringEvidenceRequirement:
    """Route one question using bounded lexical semantics only."""

    if type(question) is not str or not question.strip():
        raise ValueError("question must be a non-empty string")
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
    elif _has_any(normalized, _DIAGNOSIS_SIGNALS) and _has_any(
        normalized, _DIAGNOSIS_DETAIL_SIGNALS
    ):
        profile = (
            DIAGNOSIS_CROSS_FILE_V1
            if _has_any(normalized, _CROSS_FILE_SIGNALS)
            else DIAGNOSIS_SINGLE_V1
        )
    else:
        profile = NO_ADDITIONAL_REQUIREMENT

    groups, min_paths = _FROZEN_PROFILE_SPECS[profile]
    return EngineeringEvidenceRequirement(
        requirement_profile=profile,
        required_evidence_groups=groups,
        min_distinct_project_code_paths=min_paths,
    )


__all__ = [
    "PUBLIC_EVIDENCE_KINDS",
    "ROUTER_VERSION",
    "EngineeringRequirementProfile",
    "EngineeringEvidenceRequirement",
    "EvidenceRequirementState",
    "FROZEN_PROFILE_SPECS",
    "THEORY_CODE_V1",
    "CHANGE_TEST_V1",
    "DIAGNOSIS_SINGLE_V1",
    "DIAGNOSIS_CROSS_FILE_V1",
    "DOCS_CODE_V1",
    "NO_ADDITIONAL_REQUIREMENT",
    "route_engineering_evidence_requirement",
    "evaluate_evidence_requirement",
]
