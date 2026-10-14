"""Small task obligations attached to the existing Planner call.

The model classifies intent; the program owns source checks and minimum
obligations. This is not a second planner or a semantic answer reviewer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

TASK_CONTRACT_VERSION = "hybrid_task_contract_v1"
_OPERATIONS = {"file_status", "source_read", "change_analysis", "knowledge_answer",
               "test_execution", "other"}
_OBJECTS = {"files", "source_files", "function", "documents", "tests", "knowledge", "other"}
_SCOPES = {"working_tree", "commit_range", "project", "knowledge", "unspecified"}
_STATUSES = {"any", "added", "modified", "deleted", "renamed", "untracked"}
_FLAGS = ("requires_source_body", "requires_diff", "requires_complete_list",
          "requires_test_execution", "requires_knowledge")
_FIELDS = {"operation", "object_kind", "target_paths", "scope_mode", "base_ref",
           "head_ref", "status", *_FLAGS}


def _task_text(request: str) -> str:
    # Only the product's context envelope has this shape. History resolves
    # referents; it cannot replace or weaken the current user request.
    try:
        value = json.loads(request)
    except (ValueError, TypeError):
        return request
    if isinstance(value, dict) and isinstance(value.get("current_request"), str):
        return value["current_request"]
    return request


@dataclass(frozen=True)
class HybridTaskContract:
    operation: str
    object_kind: str
    target_paths: tuple[str, ...]
    scope_mode: str
    base_ref: str | None
    head_ref: str | None
    status: str
    requires_source_body: bool
    requires_diff: bool
    requires_complete_list: bool
    requires_test_execution: bool
    requires_knowledge: bool

    def __post_init__(self):
        for name, allowed in (("operation", _OPERATIONS), ("object_kind", _OBJECTS),
                              ("scope_mode", _SCOPES), ("status", _STATUSES)):
            if type(getattr(self, name)) is not str or getattr(self, name) not in allowed:
                raise ValueError(f"Invalid task contract {name}")
        for name in _FLAGS:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"Task contract {name} must be boolean")
        if type(self.target_paths) is not tuple or len(self.target_paths) > 8:
            raise ValueError("Task contract target_paths must be bounded")
        if len(set(self.target_paths)) != len(self.target_paths):
            raise ValueError("Duplicate target path")
        for path in self.target_paths:
            if (type(path) is not str or not path or "\\" in path or ":" in path
                    or path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/"))):
                raise ValueError("Unsafe target path")
        if self.scope_mode == "commit_range":
            for ref in (self.base_ref, self.head_ref):
                if (type(ref) is not str or ref.startswith("-")
                        or not re.fullmatch(r"[A-Za-z0-9_./~^-]{1,100}", ref)):
                    raise ValueError("Invalid Git ref")
        elif self.base_ref is not None or self.head_ref is not None:
            raise ValueError("Git refs require commit_range")
        if self.operation != "file_status" and self.status != "any":
            raise ValueError("Status filter requires file_status")

    @classmethod
    def from_dict(cls, obj: object, *, user_request: str) -> "HybridTaskContract":
        if type(obj) is not dict or set(obj) != _FIELDS or type(obj["target_paths"]) is not list:
            raise ValueError("Invalid task contract fields")
        contract = cls(**{**obj, "target_paths": tuple(obj["target_paths"])})
        text = _task_text(user_request)
        # Ground explicit targets/scopes in the original task, never tool text.
        if any(path not in user_request for path in contract.target_paths):
            raise ValueError("Task target is not present in the request/context")
        from core.tool_agent.project_files import ALLOWED_SUFFIXES
        suffixes = "|".join(re.escape(suffix) for suffix in ALLOWED_SUFFIXES)
        explicit_paths = set(re.findall(
            rf"(?<![\w/.])(?:[\w.-]+/)*[\w.-]+(?:{suffixes})(?![\w/])", text, re.I))
        if not explicit_paths <= set(contract.target_paths):
            raise ValueError("Explicit file targets cannot be omitted")
        if contract.scope_mode == "commit_range":
            if any(ref not in user_request for ref in (contract.base_ref, contract.head_ref)):
                raise ValueError("Task Git scope is not grounded")
        refs = re.findall(r"\b[0-9a-f]{40}\b", text, re.I)
        if len(refs) == 2 and (contract.scope_mode != "commit_range"
                              or (contract.base_ref, contract.head_ref) != tuple(refs)):
            raise ValueError("Explicit commit range cannot be changed")
        if re.search(r"working_tree|当前工作区|工作区当前", text, re.I) and contract.scope_mode != "working_tree":
            raise ValueError("Explicit working-tree scope cannot be changed")
        # These are conservative obligation floors, not intent routing rules.
        # Merely saying 'source files' does not require reading their bodies.
        body = bool(re.search(
            r"(?:读取|阅读|查看|检查).{0,16}(?:源码|代码|正文)|"
            r"(?:解释|分析).{0,24}(?:源码|函数实现|代码实现)|"
            r"(?:read|explain|inspect)\b.{0,40}(?:source|implementation|code body)", text, re.I))
        diff = bool(re.search(r"(?:读取|查看|分析|解释|read|inspect)\s*.{0,20}\bdiff\b", text, re.I))
        tests = bool(re.search(r"(?:运行|执行).{0,16}测试|\b(?:run|execute)\b.{0,25}\btests?\b", text, re.I))
        complete = contract.operation == "file_status" and bool(re.search(
            r"全部|所有|完整|穷举|\ball\b|\bcomplete\b", text, re.I))
        return replace(
            contract,
            object_kind=("source_files" if contract.operation == "file_status"
                and re.search(r"(?:源码|源代码)文件|\bsource (?:code )?files\b", text, re.I)
                else contract.object_kind),
            requires_source_body=contract.requires_source_body or body or contract.operation == "source_read",
            requires_diff=contract.requires_diff or diff or contract.operation == "change_analysis",
            requires_test_execution=contract.requires_test_execution or tests or contract.operation == "test_execution",
            requires_complete_list=contract.requires_complete_list or complete,
            requires_knowledge=contract.requires_knowledge or contract.operation == "knowledge_answer",
        )

    def to_dict(self) -> dict:
        return {name: (list(self.target_paths) if name == "target_paths" else getattr(self, name))
                for name in sorted(_FIELDS)} | {"version": TASK_CONTRACT_VERSION}

    def to_requirement(self, legacy):
        # Reuse the existing evidence evaluator; only its input requirements
        # change. Unknown tasks retain their legacy minimums.
        from core.engineering_requirements import EngineeringEvidenceRequirement, EngineeringRequirementProfile
        groups = list(legacy.required_evidence_groups) if self.operation == "other" else []
        body_kind = {"documents": "project_doc", "tests": "project_test"}.get(self.object_kind, "project_code")
        for enabled, kind in ((self.requires_source_body, body_kind),
                              (self.requires_diff, "project_change"),
                              (self.requires_knowledge, "knowledge")):
            if enabled and (kind,) not in groups:
                groups.append((kind,))
        return EngineeringEvidenceRequirement(
            requirement_profile=EngineeringRequirementProfile.TASK_CONTRACT_V1,
            required_evidence_groups=tuple(groups),
            min_distinct_project_code_paths=(max(1, len(self.target_paths))
                if self.requires_source_body and body_kind == "project_code" else
                legacy.min_distinct_project_code_paths if self.operation == "other" else 0),
            router_version=TASK_CONTRACT_VERSION,
        )

    def scope_matches(self, evidence) -> bool:
        if self.scope_mode not in {"working_tree", "commit_range"}:
            return True
        if getattr(evidence, "tool_name", None) not in {"changed_files", "git_diff"}:
            return True
        try:
            args = json.loads(evidence.arguments_json)
        except (AttributeError, ValueError):
            return False
        if args.get("mode") != self.scope_mode:
            return False
        return self.scope_mode != "commit_range" or (
            args.get("base_ref") == self.base_ref and args.get("head_ref") == self.head_ref)

    def scoped_evidence(self, evidence):
        return tuple(item for item in evidence if self.scope_matches(item) and (
            not self.target_paths or getattr(item, "kind", None) == "knowledge"
            or getattr(item, "path", None) in self.target_paths
            or bool(set(getattr(item, "scope_paths", ())) & set(self.target_paths))))

    def material_error(self, evidence) -> str | None:
        if self.requires_test_execution:
            # The frozen registry has no test-execution tool. A test file or
            # find_tests candidate never proves that tests actually ran.
            return "TEST_EXECUTION_NOT_VERIFIED"
        if self.requires_source_body and self.target_paths:
            bodies = {getattr(item, "path", None) for item in evidence
                      if getattr(item, "kind", None) in {"project_code", "project_doc", "project_test"}
                      and getattr(item, "granularity", "source_body") == "source_body"
                      and getattr(item, "completeness", "complete") == "complete"}
            if not set(self.target_paths) <= bodies:
                return "REQUESTED_SOURCE_BODY_MISSING"
        return None

    def status_rows(self, evidence):
        from core.tool_agent.project_files import PROJECT_CODE_SUFFIXES
        rows = evidence.status_entries
        if self.object_kind == "source_files":
            rows = tuple(row for row in rows if PurePosixPath(row[0]).suffix.lower() in PROJECT_CODE_SUFFIXES)
        if self.target_paths:
            rows = tuple(row for row in rows if row[0] in self.target_paths or row[2] in self.target_paths)
        return rows

    def selection_error(self, evidence, selector) -> str | None:
        if self.operation != "file_status":
            return "TASK_REQUIRES_NON_STATUS_ANSWER"
        if not self.scope_matches(evidence):
            return "TASK_SCOPE_MISMATCH"
        if self.requires_complete_list and evidence.completeness != "complete":
            return "TASK_COMPLETE_LIST_MISSING"
        rows = self.status_rows(evidence)
        wanted = tuple(row for row in rows if self.status == "any" or row[1] == self.status)
        selected = tuple(row for row in rows if selector["operation"] == "list_all"
                         or row[1] == selector.get("status"))
        if selected != wanted:
            return "TASK_STATUS_SELECTION_MISMATCH"
        return None
