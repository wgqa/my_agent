"""Versioned requirements; models describe needs, never issue evidence or budgets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

from core.engineering_requirements import EngineeringEvidenceRequirement

REQUIREMENT_SCHEMA_VERSION = "engineering_evidence_requirements_v2"
MAX_REQUIREMENT_GOALS = 8
SOURCE_KINDS = frozenset({"knowledge", "project_code", "project_doc", "project_test",
                          "project_change", "calculation", "project_binding"})
DEPTH_SOURCES = {
    "locator": frozenset({"project_code", "project_doc", "project_test"}),
    "list": frozenset({"project_change"}),
    "candidate": frozenset({"project_test", "project_doc"}),
    "body": frozenset({"project_code", "project_doc", "project_test"}),
    "implementation": frozenset({"project_code", "project_test"}),
    "knowledge": frozenset({"knowledge"}),
    "diff": frozenset({"project_change"}),
    "calculation": frozenset({"calculation"}),
    "binding": frozenset({"project_binding"}),
    "direct": frozenset(),
    "unsupported": frozenset(),
}
PRODUCER_TOOLS = {
    "locator": ("code_search", "read_project_context"),
    "list": ("changed_files",),
    "candidate": ("find_tests", "get_project_info", "code_search"),
    "body": ("read_project_context",),
    "implementation": ("read_project_context",),
    "knowledge": (),  # Knowledge is acquired before the bounded Tool loop.
    "diff": ("git_diff",),
    "calculation": ("calculator",),
    "binding": ("get_project_info",),
    "direct": (), "unsupported": (),
}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bounded_text(value, label: str, limit: int) -> str:
    if (type(value) is not str or not value or value != value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise ValueError(f"{label} must be a bounded nonempty string")
    return value


def relative_path(value: str) -> str:
    bounded_text(value, "path", 500)
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if ("\\" in value or posix.is_absolute() or windows.is_absolute() or windows.drive
            or any(ord(c) < 32 for c in value)
            or any(part in (".", "..") for part in value.split("/"))
            or posix.as_posix() != value):
        raise ValueError("path must be a safe POSIX repository-relative path")
    return value


@dataclass(frozen=True)
class RequirementTarget:
    path: str | None = None
    symbol: str | None = None
    query: str | None = None
    change_mode: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None

    def __post_init__(self):
        if self.path is not None:
            relative_path(self.path)
        for name in ("symbol", "query", "base_ref", "head_ref"):
            value = getattr(self, name)
            if value is not None:
                bounded_text(value, name, 200)
        if self.change_mode not in (None, "working_tree", "commit_range"):
            raise ValueError("unknown change_mode")
        if (self.base_ref or self.head_ref) and self.change_mode != "commit_range":
            raise ValueError("comparison refs require commit_range")

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class RequirementGoal:
    goal_id: str
    deliverable: str
    request_basis: str
    source_kinds: tuple[str, ...]
    depth: str
    target: RequirementTarget
    full_range: bool = False

    def __post_init__(self):
        if self.goal_id not in {f"g{i}" for i in range(1, MAX_REQUIREMENT_GOALS + 1)}:
            raise ValueError("invalid program-assigned goal_id")
        bounded_text(self.deliverable, "deliverable", 200)
        bounded_text(self.request_basis, "request_basis", 300)
        if (type(self.depth) is not str or self.depth not in DEPTH_SOURCES
                or type(self.source_kinds) is not tuple
                or any(type(kind) is not str for kind in self.source_kinds)):
            raise ValueError("invalid depth/source_kinds")
        if (len(set(self.source_kinds)) != len(self.source_kinds)
                or not set(self.source_kinds).issubset(DEPTH_SOURCES[self.depth])
                or bool(self.source_kinds) != bool(DEPTH_SOURCES[self.depth])):
            raise ValueError("source_kinds incompatible with material depth")
        if type(self.target) is not RequirementTarget or type(self.full_range) is not bool:
            raise TypeError("invalid target or full_range")
        if self.depth == "direct" and any(self.target.to_dict().values()):
            raise ValueError("direct answer cannot carry a project target")
        if self.depth in {"binding", "calculation", "direct", "unsupported", "knowledge"} and self.full_range:
            raise ValueError("full_range is only a project material scope")

    def to_dict(self):
        return {"goal_id": self.goal_id, "deliverable": self.deliverable,
                "request_basis": self.request_basis, "source_kinds": list(self.source_kinds),
                "depth": self.depth, "target": self.target.to_dict(), "full_range": self.full_range}


@dataclass(frozen=True)
class RequirementContract:
    input_sha256: str
    goals: tuple[RequirementGoal, ...] = field(default=(), repr=False)
    legacy_requirement: EngineeringEvidenceRequirement | None = field(default=None, repr=False)
    schema_version: str = REQUIREMENT_SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != REQUIREMENT_SCHEMA_VERSION:
            raise ValueError("unknown requirement schema")
        if type(self.input_sha256) is not str or len(self.input_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.input_sha256):
            raise ValueError("invalid input identity")
        if type(self.goals) is not tuple or any(type(g) is not RequirementGoal for g in self.goals):
            raise TypeError("goals must be immutable RequirementGoal values")
        if self.legacy_requirement is not None:
            if type(self.legacy_requirement) is not EngineeringEvidenceRequirement or self.goals:
                raise ValueError("legacy adaptation must preserve exactly one original requirement")
        elif not 1 <= len(self.goals) <= MAX_REQUIREMENT_GOALS:
            raise ValueError("invalid goal count; empty plans are not an escape hatch")
        if [g.goal_id for g in self.goals] != [f"g{i}" for i in range(1, len(self.goals) + 1)]:
            raise ValueError("goals must have canonical program-assigned IDs")

    @property
    def required_evidence_groups(self):
        if self.legacy_requirement is not None:
            return self.legacy_requirement.required_evidence_groups
        groups = []
        for goal in self.goals:
            group = goal.source_kinds if goal.depth in {"body", "implementation", "diff", "knowledge"} else (("tool_result",) if goal.source_kinds else ())
            if group and group not in groups:
                groups.append(group)
        return tuple(groups)

    @property
    def min_distinct_project_code_paths(self):
        return self.legacy_requirement.min_distinct_project_code_paths if self.legacy_requirement else 0

    def to_dict(self):
        legacy = self.legacy_requirement
        return {"schema_version": self.schema_version, "input_sha256": self.input_sha256,
                "goals": [g.to_dict() for g in self.goals], "legacy_constraints": None if legacy is None else {
                    "requirement_profile": legacy.requirement_profile.value,
                    "required_evidence_groups": [list(g) for g in legacy.required_evidence_groups],
                    "min_distinct_project_code_paths": legacy.min_distinct_project_code_paths,
                    "router_version": legacy.router_version}}

    @property
    def contract_sha256(self):
        return digest(self.to_dict())


def requirement_input(snapshot) -> dict:
    from core.engineering_context import EngineeringContextSnapshot
    if type(snapshot) is not EngineeringContextSnapshot:
        raise TypeError("requirement input must be a context snapshot")
    return {"current_request": snapshot.original_input, "reference_context": snapshot.reference_context}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_requirement_output(content: str, snapshot) -> RequirementContract:
    input_sha = digest(requirement_input(snapshot))
    if type(content) is not str or len(content) > 24000:
        raise ValueError("invalid requirement output")
    payload = json.loads(content, object_pairs_hook=_unique_object)
    if type(payload) is not dict or set(payload) != {"schema_version", "goals"} or payload["schema_version"] != REQUIREMENT_SCHEMA_VERSION:
        raise ValueError("requirement envelope schema invalid")
    raw_goals = payload["goals"]
    if type(raw_goals) is not list or not 1 <= len(raw_goals) <= MAX_REQUIREMENT_GOALS:
        raise ValueError("requirement goal count invalid")
    fields = {"deliverable", "request_basis", "source_kinds", "depth", "target", "full_range"}
    target_fields = set(RequirementTarget.__dataclass_fields__)
    goals = []
    seen = set()
    for index, raw in enumerate(raw_goals, 1):
        if type(raw) is not dict or set(raw) != fields or type(raw["source_kinds"]) is not list:
            raise ValueError("requirement goal schema invalid")
        if type(raw["target"]) is not dict or set(raw["target"]) != target_fields:
            raise ValueError("target schema invalid")
        if type(raw["request_basis"]) is not str or raw["request_basis"] not in snapshot.original_input:
            raise ValueError("request_basis must come from the current request")
        identity = canonical_json(raw)
        if identity in seen:
            raise ValueError("duplicate goal")
        seen.add(identity)
        goals.append(RequirementGoal(f"g{index}", raw["deliverable"], raw["request_basis"],
                     tuple(raw["source_kinds"]), raw["depth"], RequirementTarget(**raw["target"]), raw["full_range"]))
    return RequirementContract(input_sha, tuple(goals))
