"""Small task obligations attached to the existing Planner call.

The model classifies intent; the program owns source checks and minimum
obligations. This is not a second planner or a semantic answer reviewer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

TASK_CONTRACT_VERSION = "hybrid_task_contract_v1"
_OPERATIONS = {"file_status", "source_read", "change_analysis", "knowledge_answer",
               "test_execution", "other"}
_OBJECTS = {"files", "source_files", "function", "documents", "tests", "knowledge", "other"}
_SCOPES = {"working_tree", "commit_range", "project", "knowledge", "unspecified"}
_STATUSES = {"any", "added", "modified", "deleted", "renamed", "untracked"}
_STATUS_TERMS = {
    "added": r"added|新增|新建",
    "modified": r"modified|修改|更改",
    "deleted": r"deleted|删除|删掉|移除",
    "renamed": r"renamed|重命名|改名",
    "untracked": r"untracked|未跟踪|未追踪",
}
_FLAGS = ("requires_source_body", "requires_diff", "requires_complete_list",
          "requires_test_execution", "requires_knowledge")
_FIELDS = {"operation", "object_kind", "target_paths", "target_symbols", "scope_mode", "base_ref",
           "head_ref", "status", *_FLAGS}


def _task_text(request: str) -> str:
    # Only the product's context envelope has this shape. History resolves
    # referents; it cannot replace or weaken the current user request.
    try:
        value = json.loads(request)
    except (ValueError, TypeError):
        return request
    if (isinstance(value, dict) and set(value) == {"current_request", "reference_context"}
            and isinstance(value.get("current_request"), str)):
        return value["current_request"]
    return request


@dataclass(frozen=True)
class HybridTaskContract:
    operation: str
    object_kind: str
    target_paths: tuple[str, ...]
    target_symbols: tuple[str, ...]
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
        if (type(self.target_symbols) is not tuple or len(self.target_symbols) > 4
                or len(set(self.target_symbols)) != len(self.target_symbols)
                or any(type(s) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,199}", s)
                       for s in self.target_symbols)):
            raise ValueError("Invalid target symbols")
        if self.scope_mode == "commit_range":
            for ref in (self.base_ref, self.head_ref):
                if (type(ref) is not str or ref.startswith("-")
                        or not re.fullmatch(r"[A-Za-z0-9_./~^-]{1,100}", ref)):
                    raise ValueError("Invalid Git ref")
        elif self.base_ref is not None or self.head_ref is not None:
            raise ValueError("Git refs require commit_range")
        if self.operation != "file_status" and self.status != "any":
            raise ValueError("Status filter requires file_status")
        if self.operation == "file_status" and self.scope_mode not in {"working_tree", "commit_range"}:
            raise ValueError("File status requires an explicit Git scope")
        if self.operation == "file_status" and self.object_kind not in {"files", "source_files", "documents", "tests"}:
            raise ValueError("File-status object must be a file category")
        if self.operation == "file_status" and self.target_symbols:
            raise ValueError("Function bodies are not file-status targets")

    @classmethod
    def from_dict(cls, obj: object, *, user_request: str,
                  current_request: str | None = None) -> "HybridTaskContract":
        if (type(obj) is not dict or set(obj) != _FIELDS
                or type(obj["target_paths"]) is not list or type(obj["target_symbols"]) is not list):
            raise ValueError("Invalid task contract fields")
        contract = cls(**{**obj, "target_paths": tuple(obj["target_paths"]),
                          "target_symbols": tuple(obj["target_symbols"])})
        text = _task_text(user_request) if current_request is None else current_request
        # Ground explicit targets/scopes in the original task, never tool text.
        if any(path not in user_request for path in contract.target_paths):
            raise ValueError("Task target is not present in the request/context")
        if any(symbol not in user_request for symbol in contract.target_symbols):
            raise ValueError("Task symbol is not present in the request/context")
        explicit_symbols = set(re.findall(
            r"(?<![\w/.])([A-Za-z_][A-Za-z0-9_.]*)\s*函数", text))
        explicit_symbols.update(re.findall(
            r"\bfunction\s+([A-Za-z_][A-Za-z0-9_.]*)", text, re.I))
        if not explicit_symbols <= set(contract.target_symbols):
            raise ValueError("Explicit function targets cannot be omitted")
        if contract.status != "any" and not re.search(_STATUS_TERMS[contract.status], text, re.I):
            raise ValueError("A status restriction must come from the current request")
        if contract.operation == "file_status":
            explicit_only = {status for status, term in _STATUS_TERMS.items()
                             if re.search(rf"(?:只|仅|\bonly\b).{{0,60}}(?:{term})", text, re.I)}
            if explicit_only and explicit_only != {contract.status}:
                raise ValueError("An explicit status-only request cannot be broadened")
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
            r"(?:解释|分析).{0,24}(?:源码|函数.{0,8}实现|代码实现)|"
            r"(?:read|explain|inspect)\b.{0,40}(?:source|implementation|code body)", text, re.I))
        diff = bool(re.search(r"(?:读取|查看|分析|解释|read|inspect)\s*.{0,20}\bdiff\b", text, re.I))
        tests = bool(re.search(r"(?:运行|执行).{0,16}测试|\b(?:run|execute)\b.{0,25}\btests?\b", text, re.I))
        complete = contract.operation in {"file_status", "change_analysis"} and bool(re.search(
            r"全部|所有|完整|穷举|\ball\b|\bcomplete\b", text, re.I))
        return replace(
            contract,
            object_kind=("source_files" if contract.operation == "file_status"
                and re.search(r"(?:源码|源代码)文件|\bsource (?:code )?files\b", text, re.I)
                else contract.object_kind),
            requires_source_body=contract.requires_source_body or body
                or contract.operation == "source_read" or bool(contract.target_symbols),
            requires_diff=contract.requires_diff or diff or contract.operation == "change_analysis",
            requires_test_execution=contract.requires_test_execution or tests or contract.operation == "test_execution",
            requires_complete_list=contract.requires_complete_list or complete,
            requires_knowledge=contract.requires_knowledge or contract.operation == "knowledge_answer"
                or bool(re.search(r"(?:依据|根据|查阅|检索).{0,16}知识库|"
                                  r"\b(?:from|based on|consult)\b.{0,30}\bknowledge base\b", text, re.I)),
        )

    def to_dict(self) -> dict:
        return {name: (list(getattr(self, name)) if name in {"target_paths", "target_symbols"} else getattr(self, name))
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
            min_distinct_project_code_paths=max(
                max(1, len(self.target_paths)) if self.requires_source_body and body_kind == "project_code" else 0,
                legacy.min_distinct_project_code_paths if self.operation == "other" else 0),
            router_version=TASK_CONTRACT_VERSION,
        )

    def scope_matches(self, evidence) -> bool:
        if self.scope_mode not in {"working_tree", "commit_range"}:
            return True
        if getattr(evidence, "tool_name", None) not in {"changed_files", "git_diff"}:
            if self.scope_mode == "commit_range" and getattr(evidence, "kind", "").startswith("project_"):
                # The current Reader cannot read historical refs. Current
                # source bodies do not prove a commit-range implementation.
                return False
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
        if (self.operation == "change_analysis" and self.requires_complete_list
                and self.scope_mode in {"working_tree", "commit_range"} and not self.target_paths):
            inventories = [item for item in evidence
                           if getattr(item, "granularity", None) == "status_list"
                           and getattr(item, "completeness", None) == "complete"]
            if len(inventories) != 1:
                return "CHANGE_SCOPE_NOT_ESTABLISHED"
            requested = {row[0] for row in inventories[0].status_entries}
            covered = {path for item in evidence if getattr(item, "granularity", None) == "diff"
                       and getattr(item, "completeness", None) == "complete"
                       for path in item.scope_paths}
            if not requested <= covered:
                return "CHANGE_SCOPE_INCOMPLETE"
        if self.requires_diff and not any(
                getattr(item, "granularity", None) == "diff"
                and getattr(item, "completeness", None) == "complete" for item in evidence):
            return "REQUIRED_DIFF_MISSING"
        if self.requires_source_body and self.target_paths:
            bodies = {getattr(item, "path", None) for item in evidence
                      if getattr(item, "kind", None) in {"project_code", "project_doc", "project_test"}
                      and getattr(item, "granularity", "source_body") == "source_body"
                      and getattr(item, "completeness", "complete") == "complete"}
            if not set(self.target_paths) <= bodies:
                return "REQUESTED_SOURCE_BODY_MISSING"
        return None

    def status_rows(self, evidence):
        from core.tool_agent.project_files import classify_project_evidence_path
        rows = evidence.status_entries
        category = {"source_files": "project_code", "documents": "project_doc",
                    "tests": "project_test"}.get(self.object_kind)
        if category:
            rows = tuple(row for row in rows if classify_project_evidence_path(row[0]) == category)
        if self.target_paths:
            rows = tuple(row for row in rows if row[0] in self.target_paths or row[2] in self.target_paths)
        return rows

    def source_context_error(self, context, cited_evidence) -> str | None:
        """Function explanations use complete Reader definitions, not headers."""
        if not self.requires_source_body or not (self.target_symbols or self.object_kind == "function"):
            return None
        available = set()
        locations = {(getattr(item, "path", None), getattr(item, "start_line", None),
                      getattr(item, "end_line", None)) for item in cited_evidence}
        for item in context:
            if item.tool_name != "read_project_context" or item.observation_status != "ok":
                continue
            result = item.observation_result
            if type(result) is not dict:
                continue
            path = result.get("path")
            definitions = []
            if result.get("mode") == "definition" and result.get("content_complete") is True:
                definitions.append((result.get("definition"), result))
            elif result.get("mode") == "targets" and result.get("selection_truncated") is False:
                regions = result.get("regions", [])
                for target in result.get("targets", []):
                    index = target.get("region_index")
                    if (target.get("status") == "read" and target.get("content_complete") is True
                            and type(index) is int and 0 <= index < len(regions)):
                        region = regions[index]
                        definition = target.get("definition")
                        definitions.append((definition, region))
                        if (definition is None and target.get("requested") == "file"
                                and path.endswith(".py")):
                            # Reuse the Reader's existing syntactic index for
                            # a complete file; never execute imported code.
                            from core.tool_agent.tools.source_navigation import python_symbols
                            spans, error = python_symbols([line["text"] for line in region["lines"]])
                            if error is None:
                                definitions.extend((span.to_dict(), region) for span in spans
                                                   if span.kind == "function")
            for definition, region in definitions:
                if (type(definition) is dict and (path, region.get("start_line"), region.get("end_line")) in locations):
                    name = definition.get("name")
                    if type(name) is str:
                        available.update((name, name.split(".")[-1]))
        if (self.target_symbols and not set(self.target_symbols) <= available) or not available:
            return "REQUESTED_FUNCTION_BODY_INCOMPLETE"
        return None

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
