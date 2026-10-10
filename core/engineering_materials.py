"""Run-local facts from validated tool observations; never additional I/O.

Legacy evidence types stay frozen. Candidate material records retain the
scope and completeness which the old kind/count projection discarded.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from jsonschema import Draft202012Validator

from core.engineering_requirement_contract import canonical_json, digest, relative_path
from core.tool_agent.models import ToolCall, ToolObservation, ToolSpec
from core.tool_agent.project_files import classify_project_evidence_path
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence
from core.tool_agent.source_excerpt import (
    MAX_PROJECT_CHANGE_CHARACTERS, project_context_fragments, project_context_snippet,
)

MATERIAL_SCHEMA_VERSION = "engineering_material_v1"
LEDGER_SCHEMA_VERSION = "engineering_material_ledger_v1"
TOOL_RESULT_SCHEMA_VERSION = "engineering_tool_result_evidence_v1"
MATERIAL_ADAPTER_VERSION = "engineering_material_adapters_v1"


def registered_material_specs() -> dict[tuple[str, str], ToolSpec]:
    # A closed registry: an unknown version/schema cannot become arbitrary JSON
    # evidence merely because its tool has a familiar name.
    from core.tool_agent.tools.calculator import CALCULATOR_SPEC
    from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC, CODE_SEARCH_TEST_SPEC
    from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC, GIT_DIFF_SPEC
    from core.tool_agent.tools.knowledge_search import KNOWLEDGE_SEARCH_SPEC
    from core.tool_agent.tools.project_info import PROJECT_INFO_SPEC, PROJECT_INFO_DOCUMENTATION_SPEC
    from core.tool_agent.tools.read_project_context import READ_PROJECT_CONTEXT_SPEC
    from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_SPEC
    from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC
    specs = (CALCULATOR_SPEC, CODE_SEARCH_SPEC, CODE_SEARCH_TEST_SPEC,
             CHANGED_FILES_SPEC, GIT_DIFF_SPEC, KNOWLEDGE_SEARCH_SPEC,
             PROJECT_INFO_SPEC, PROJECT_INFO_DOCUMENTATION_SPEC,
             READ_PROJECT_CONTEXT_SPEC, READ_PROJECT_TARGETS_SPEC, FIND_TESTS_SPEC)
    return {(s.name, s.version): s for s in specs}


def check_material_spec(spec: ToolSpec) -> None:
    known = registered_material_specs().get((spec.name, spec.version))
    if (known is None or known.input_schema != spec.input_schema
            or known.output_schema != spec.output_schema):
        raise ValueError("MATERIAL_ADAPTER_UNAVAILABLE")


def capability_manifest(specs) -> tuple[dict, ...]:
    result = []
    for spec in specs:
        check_material_spec(spec)
        result.append({"tool_name": spec.name, "tool_version": spec.version,
                       "input_schema": spec.input_schema, "output_schema": spec.output_schema,
                       "adapter_version": MATERIAL_ADAPTER_VERSION})
    return tuple(sorted(result, key=lambda item: item["tool_name"]))


RESULT_TYPES = {"code_search": "locator_set", "changed_files": "change_list",
                "find_tests": "test_candidates", "calculator": "calculation",
                "get_project_info": "project_binding", "read_project_context": "reader_locator"}


@dataclass(frozen=True)
class ToolResultEvidence:
    evidence_id: str
    tool_name: str
    tool_version: str
    arguments_json: str
    payload_json: str
    kind: str = "tool_result"
    schema_version: str = TOOL_RESULT_SCHEMA_VERSION

    def __post_init__(self):
        if (not re.fullmatch(r"E[1-9][0-9]*", self.evidence_id)
                or self.kind != "tool_result" or self.schema_version != TOOL_RESULT_SCHEMA_VERSION
                or self.tool_name not in RESULT_TYPES):
            raise ValueError("invalid structured tool evidence identity")
        spec = registered_material_specs().get((self.tool_name, self.tool_version))
        if spec is None:
            raise ValueError("unknown structured tool result version")
        arguments, payload = self.arguments, self.payload
        if canonical_json(arguments) != self.arguments_json or canonical_json(payload) != self.payload_json:
            raise ValueError("structured evidence must contain canonical JSON")
        Draft202012Validator(spec.input_schema).validate(arguments)
        Draft202012Validator(spec.output_schema).validate(payload)
        _check_result_paths(self.tool_name, payload)
        if self.tool_name == "changed_files":
            if (payload["returned_count"] != len(payload["changes"])
                    or payload["total_count"] < payload["returned_count"]):
                raise ValueError("inconsistent change list counts")
        if self.tool_name == "find_tests" and payload["returned_count"] != len(payload["candidates"]):
            raise ValueError("inconsistent test candidate count")

    @property
    def arguments(self):
        return json.loads(self.arguments_json)

    @property
    def payload(self):
        return json.loads(self.payload_json)

    @property
    def result_type(self):
        return RESULT_TYPES[self.tool_name]

    @property
    def content_sha256(self):
        return digest({"tool_name": self.tool_name, "tool_version": self.tool_version,
                       "arguments": self.arguments, "payload": self.payload})

    def to_dict(self):
        return {"schema_version": self.schema_version, "evidence_id": self.evidence_id,
                "kind": self.kind, "tool_name": self.tool_name, "tool_version": self.tool_version,
                "result_type": self.result_type, "arguments": self.arguments, "payload": self.payload,
                "content_sha256": self.content_sha256}


def _check_result_paths(tool_name, result):
    paths = []
    if tool_name in {"code_search", "changed_files", "find_tests"}:
        key = {"code_search": "matches", "changed_files": "changes", "find_tests": "candidates"}[tool_name]
        for item in result[key]:
            paths.append(item["path"])
            if "old_path" in item:
                paths.append(item["old_path"])
    elif tool_name == "get_project_info":
        paths.extend(result.get("documentation_entrypoints", ()))
    elif tool_name == "read_project_context":
        paths.append(result["path"])
    for path in paths:
        relative_path(path)


@dataclass(frozen=True)
class MaterialRecord:
    evidence: EngineeringEvidence | KnowledgeEvidence | ToolResultEvidence
    source_kinds: tuple[str, ...]
    form: str
    details_json: str
    provenance_json: str
    schema_version: str = MATERIAL_SCHEMA_VERSION

    def __post_init__(self):
        if (type(self.evidence) not in (EngineeringEvidence, KnowledgeEvidence, ToolResultEvidence)
                or self.schema_version != MATERIAL_SCHEMA_VERSION
                or self.form not in {"knowledge", "body", "diff", "locator", "list", "candidate", "calculation", "binding"}
                or type(self.source_kinds) is not tuple
                or not set(self.source_kinds).issubset({"knowledge", "project_code", "project_doc", "project_test",
                                                      "project_change", "calculation", "project_binding"})):
            raise TypeError("invalid material record")
        for value in (self.details_json, self.provenance_json):
            if canonical_json(json.loads(value)) != value:
                raise ValueError("material metadata must be canonical")

    @property
    def details(self):
        return json.loads(self.details_json)

    def to_dict(self):
        return {"schema_version": self.schema_version, "evidence": self.evidence.to_dict(),
                "source_kinds": list(self.source_kinds), "form": self.form,
                "details": self.details, "provenance": json.loads(self.provenance_json)}


class MaterialLedger:
    """A private accumulator per run; snapshots and payloads are detached.

    Only the existing executor's successful observations enter this ledger.
    Failed observations stay in the actual decision context as diagnostics.
    """
    def __init__(self, specs, initial_evidence=(), *, binding_identity=None, knowledge_provenance=()):
        self.capabilities = capability_manifest(specs)
        self._specs = {s.name: s for s in specs}
        self._records: list[MaterialRecord] = []
        self._identities: set[str] = set()
        self.binding_identity = binding_identity
        if binding_identity is not None and not re.fullmatch(r"[a-f0-9]{64}", binding_identity):
            raise ValueError("invalid binding snapshot identity")
        for item in initial_evidence:
            if type(item) not in (EngineeringEvidence, KnowledgeEvidence):
                raise TypeError("invalid initial candidate material")
            knowledge_identity = next((entry for entry in knowledge_provenance
                if entry["source_name"] == getattr(item, "source_name", None)
                and entry["chunk_id"] == getattr(item, "chunk_id", None)
                and entry["rank"] == getattr(item, "rank", None)), None)
            self._add(item, (item.kind,), "knowledge" if item.kind == "knowledge" else "body",
                      {"content_complete": None, "completeness_scope": "returned_seed"},
                      {"source": "planned_retrieval" if item.kind == "knowledge" else "initial_evidence",
                       "binding_identity": binding_identity, "returned_content_sha256": digest(item.to_dict()),
                       "knowledge_identity": knowledge_identity})

    @property
    def records(self):
        return tuple(self._records)

    @property
    def evidence(self):
        return tuple(record.evidence for record in self._records)

    def snapshot(self):
        return {"schema_version": LEDGER_SCHEMA_VERSION, "adapter_version": MATERIAL_ADAPTER_VERSION,
                "binding_identity": self.binding_identity,
                "materials": [record.to_dict() for record in self._records]}

    @property
    def snapshot_sha256(self):
        return digest(self.snapshot())

    def _add(self, evidence, sources, form, details, provenance):
        from dataclasses import replace
        identity = evidence.to_dict()
        identity.pop("evidence_id")
        key = digest({"content": identity, "details": details,
                      "binding_identity": self.binding_identity})
        if key in self._identities:
            return None
        item = replace(evidence, evidence_id=f"E{len(self._records) + 1}")
        record = MaterialRecord(item, tuple(sources), form, canonical_json(details), canonical_json(provenance))
        self._records.append(record)
        self._identities.add(key)
        return item

    def observe(self, call: ToolCall, observation: ToolObservation):
        if type(call) is not ToolCall or type(observation) is not ToolObservation:
            raise TypeError("materials require actual tool call and observation")
        if observation.call_id != call.call_id or observation.tool_name != call.tool_name:
            raise ValueError("material observation/call mismatch")
        if observation.status != "ok":
            return ()
        spec = self._specs.get(call.tool_name)
        if spec is None:
            raise ValueError("MATERIAL_ADAPTER_UNAVAILABLE")
        check_material_spec(spec)
        arguments, result = call.arguments_copy(), observation.result
        Draft202012Validator(spec.input_schema).validate(arguments)
        Draft202012Validator(spec.output_schema).validate(result)
        provenance = {"source": "tool_observation", "call_id": call.call_id,
                      "tool_name": spec.name, "tool_version": spec.version,
                      "input_schema_sha256": digest(spec.input_schema), "output_schema_sha256": digest(spec.output_schema),
                      "arguments": arguments, "binding_identity": self.binding_identity,
                      "returned_content_sha256": digest(result)}
        candidates = []
        if spec.name == "read_project_context":
            for index, fragment in enumerate(project_context_fragments(result)):
                item = EngineeringEvidence("E1", classify_project_evidence_path(result["path"]),
                                           result["path"], fragment["start_line"], fragment["end_line"],
                                           project_context_snippet(fragment))
                target_results = [t for t in result.get("targets", ()) if t.get("region_index") == index]
                complete = fragment.get("content_complete")
                if target_results:
                    complete = all(t.get("content_complete") is True for t in target_results)
                candidates.append((item, (item.kind,), "body", {
                    "content_complete": complete, "completeness_scope": "requested_object",
                    "targets": target_results, "request": arguments,
                    "selection_targets": result.get("targets", []),
                    "selection_truncated": result.get("selection_truncated", False),
                    "definition": fragment.get("definition"),
                    "truncation_reasons": fragment.get("truncation_reasons", []),
                }))
            # Ambiguous/not-found Reader targets are locator facts, not bodies.
            if not candidates:
                candidates.append((self._tool_fact(spec, arguments, result),
                                   (classify_project_evidence_path(result["path"]),), "locator",
                                   {"content_complete": False, "completeness_scope": "requested_object", "request": arguments}))
        elif spec.name == "git_diff":
            item = EngineeringEvidence("E1", "project_change", result["path"], result["start_line"],
                                       result["end_line"], result["diff"][:MAX_PROJECT_CHANGE_CHARACTERS])
            projected = len(result["diff"]) > MAX_PROJECT_CHANGE_CHARACTERS
            candidates.append((item, ("project_change",), "diff", {
                "content_complete": not result["truncated"] and not projected,
                "tool_truncated": result["truncated"], "projection_truncated": projected,
                "completeness_scope": "requested_diff", "request": arguments}))
        elif spec.name == "knowledge_search":
            for match in result["matches"]:
                item = KnowledgeEvidence("E1", "knowledge", match["source_name"], match.get("chunk_id"),
                                         match.get("score"), match["rank"], match["snippet"])
                candidates.append((item, ("knowledge",), "knowledge",
                                   {"content_complete": None, "completeness_scope": "returned_chunk"}))
        else:
            item = self._tool_fact(spec, arguments, result)
            sources, form, complete = {
                "changed_files": (("project_change",), "list", not result.get("truncated", False)),
                "find_tests": (("project_test",), "candidate", not result.get("truncated", False)),
                "code_search": ((arguments.get("artifact_kind", "any"),), "locator", None),
                "calculator": (("calculation",), "calculation", True),
                "get_project_info": (("project_binding", "project_doc"), "binding", True),
            }[spec.name]
            if sources == ("any",):
                sources = ("project_code", "project_doc", "project_test")
            candidates.append((item, sources, form, {"content_complete": complete,
                               "completeness_scope": "tool_visible_scope", "request": arguments,
                               "omitted_sensitive_count": result.get("omitted_sensitive_count", 0),
                               "documentation_truncated": result.get("documentation_truncated"),
                               "limitations": {"code_search": "bounded literal locations; no global absence or implementation proof",
                                   "find_tests": "lexical candidates; no body/impact/execution proof",
                                   "get_project_info": "binding and conventional entrypoints; no project overview body"}.get(spec.name)}))
        return tuple(added for item, sources, form, details in candidates
                     if (added := self._add(item, sources, form, details, provenance)) is not None)

    @staticmethod
    def _tool_fact(spec, arguments, result):
        return ToolResultEvidence("E1", spec.name, spec.version, canonical_json(arguments), canonical_json(result))
