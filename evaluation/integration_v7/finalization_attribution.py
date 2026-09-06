"""Versioned, evaluation-only finalization attribution.

This module deliberately does not change Product Runtime behavior and does
not replace the frozen ``compute_premature_finalization`` metric.  It reports
three independent questions: what the Runtime trusted state says, whether
the frozen evaluator Gold evidence shape is present, and whether the Product
requirement matches that Gold shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence


FINALIZATION_ATTRIBUTION_VERSION = "integration_v7_finalization_attribution_v1"
_PUBLIC_EVIDENCE_KINDS = frozenset(
    {"knowledge", "project_code", "project_doc", "project_test", "project_change"}
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class FinalizationAttribution:
    """Independent Runtime, Gold, and Router-vs-Gold attribution fields."""

    runtime_requirement_satisfied: bool
    runtime_premature_finalization: bool
    gold_evidence_groups_satisfied: bool
    gold_min_project_code_paths_satisfied: bool
    gold_structural_evidence_satisfied: bool
    gold_incomplete_at_completion: bool
    router_gold_contract_match: bool

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if type(value) is not bool:
                raise TypeError(f"{name} must be a strict boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FINALIZATION_ATTRIBUTION_VERSION,
            "runtime_requirement_satisfied": self.runtime_requirement_satisfied,
            "runtime_premature_finalization": self.runtime_premature_finalization,
            "gold_evidence_groups_satisfied": self.gold_evidence_groups_satisfied,
            "gold_min_project_code_paths_satisfied": (
                self.gold_min_project_code_paths_satisfied
            ),
            "gold_structural_evidence_satisfied": self.gold_structural_evidence_satisfied,
            "gold_incomplete_at_completion": self.gold_incomplete_at_completion,
            "router_gold_contract_match": self.router_gold_contract_match,
        }


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _strict_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a strict boolean")
    return value


def _evidence_kind(item: object) -> object:
    return _field(item, "kind")


def _evidence_path(item: object) -> object:
    return _field(item, "path")


def _is_repo_relative_public_path(path: object) -> bool:
    if type(path) is not str or not path or path != path.strip():
        return False
    if "\x00" in path or "\\" in path or path.startswith("/"):
        return False
    if _WINDOWS_ABSOLUTE_PATH.match(path):
        return False
    pure = PurePosixPath(path)
    return bool(pure.parts) and all(part not in {"", ".", ".."} for part in pure.parts)


def _canonical_groups(value: object, name: str) -> tuple[tuple[str, ...], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of evidence groups")
    groups: list[tuple[str, ...]] = []
    for group in value:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            raise TypeError(f"{name} contains an invalid evidence group")
        group_tuple = tuple(group)
        if any(type(kind) is not str for kind in group_tuple):
            raise TypeError(f"{name} evidence kinds must be strings")
        if not group_tuple or any(kind not in _PUBLIC_EVIDENCE_KINDS for kind in group_tuple):
            raise ValueError(f"{name} contains an invalid evidence kind")
        if len(set(group_tuple)) != len(group_tuple) or group_tuple in groups:
            raise ValueError(f"{name} contains duplicate evidence groups or kinds")
        groups.append(group_tuple)
    return tuple(groups)


def _strict_non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{name} must be a non-negative strict integer")
    return value


def _runtime_requirement_contract(
    requirement: object,
) -> tuple[tuple[tuple[str, ...], ...], int] | None:
    if requirement is None:
        return None
    groups = _field(requirement, "required_evidence_groups")
    minimum = _field(requirement, "min_distinct_project_code_paths")
    return _canonical_groups(groups, "runtime requirement"), _strict_non_negative_int(
        minimum, "runtime requirement minimum"
    )


def attribute_finalization(
    *,
    final_status: str,
    runtime_requirement_state: object,
    runtime_requirement: object | None,
    frozen_case: Mapping[str, Any],
    public_evidence: Sequence[object],
) -> FinalizationAttribution:
    """Compute separated attribution without consulting Product routing logic.

    Runtime attribution reads only ``runtime_requirement_state`` and the final
    status.  Gold attribution reads only the frozen case's evidence shape and
    the already-collected public evidence.  Router-vs-Gold attribution is an
    exact structural comparison and cannot affect either finalization bool.
    """

    if not isinstance(frozen_case, Mapping):
        raise TypeError("frozen_case must be a mapping")
    if isinstance(public_evidence, (str, bytes, Mapping)) or not isinstance(
        public_evidence, Sequence
    ):
        raise TypeError("public_evidence must be a sequence")
    runtime_satisfied = _strict_bool(
        _field(runtime_requirement_state, "satisfied"),
        "runtime_requirement_state.satisfied",
    )
    is_completed = final_status == "completed"
    runtime_premature = is_completed and not runtime_satisfied

    gold_groups = _canonical_groups(
        frozen_case.get("required_evidence_groups"),
        "frozen case required_evidence_groups",
    )
    gold_minimum = _strict_non_negative_int(
        frozen_case.get("min_distinct_project_code_paths"),
        "frozen case min_distinct_project_code_paths",
    )
    evidence_kinds = {
        kind
        for item in public_evidence
        for kind in (_evidence_kind(item),)
        if type(kind) is str
    }
    gold_groups_satisfied = all(
        any(kind in evidence_kinds for kind in group) for group in gold_groups
    )
    code_paths = {
        path
        for item in public_evidence
        if _evidence_kind(item) == "project_code"
        for path in (_evidence_path(item),)
        if _is_repo_relative_public_path(path)
    }
    gold_minimum_satisfied = len(code_paths) >= gold_minimum
    gold_structural = gold_groups_satisfied and gold_minimum_satisfied
    router_contract = _runtime_requirement_contract(runtime_requirement)
    router_gold_match = router_contract == (gold_groups, gold_minimum)

    return FinalizationAttribution(
        runtime_requirement_satisfied=runtime_satisfied,
        runtime_premature_finalization=runtime_premature,
        gold_evidence_groups_satisfied=gold_groups_satisfied,
        gold_min_project_code_paths_satisfied=gold_minimum_satisfied,
        gold_structural_evidence_satisfied=gold_structural,
        gold_incomplete_at_completion=is_completed and not gold_structural,
        router_gold_contract_match=router_gold_match,
    )


__all__ = ["FINALIZATION_ATTRIBUTION_VERSION", "FinalizationAttribution", "attribute_finalization"]
