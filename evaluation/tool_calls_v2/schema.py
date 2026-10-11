"""Strict, versioned Gold contracts; Gold is never supplied to providers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator

PRIMARY_TOOLS = ("calculator", "code_search", "read_project_context", "changed_files", "git_diff", "find_tests")
SUPPORTED_TOOLS = (*PRIMARY_TOOLS, "get_project_info")
DATASET_DIR = Path(__file__).parent / "datasets"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive
            or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError("Expected a repo-relative POSIX path")
    return value


def _object(properties: dict, required: tuple | list) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_STRING = {"type": "string", "minLength": 1}
_PATH = {"type": "string", "minLength": 1}
_STRINGS = {"type": "array", "items": _STRING, "uniqueItems": True}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_LINE = _object({"line": {"type": "integer", "minimum": 1}, "sha256": _HASH}, ("line", "sha256"))


def _selector(kind: str, fields: dict, required: tuple) -> dict:
    return _object({"kind": {"const": kind}, **fields}, ("kind", *required))


SELECTOR_SCHEMA = {"oneOf": [
    _selector("source", {"path": _PATH, "lines": {"type": "array", "minItems": 1, "items": _LINE}}, ("path", "lines")),
    _selector("locate", {"path": _PATH, "line": {"type": "integer", "minimum": 1}, "sha256": _HASH}, ("path", "line", "sha256")),
    _selector("numeric", {"value": {"type": "number"}, "expressions": {**_STRINGS, "minItems": 1},
                          "tolerance": {"type": "number", "minimum": 0, "maximum": 0.000001}}, ("value", "expressions", "tolerance")),
    _selector("changes", {"mode": {"enum": ["working_tree", "commit_range"]}, "changes": {"type": "array", "items":
                          _object({"path": _PATH, "status": _STRING}, ("path", "status"))}, "exact": {"type": "boolean"},
                          "base_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"}, "head_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"}}, ("mode", "changes", "exact")),
    _selector("diff", {"path": _PATH, "mode": {"enum": ["working_tree", "commit_range"]},
                       "fragments": {**_STRINGS, "minItems": 1}, "base_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                       "head_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"}}, ("path", "mode", "fragments")),
    _selector("candidates", {"input_path": _PATH, "paths": {**_STRINGS, "minItems": 1}}, ("input_path", "paths")),
    _selector("reader_status", {"path": _PATH, "status": _STRING, "requested": _STRING}, ("path", "status", "requested")),
    _selector("error", {"tool": {"enum": list(PRIMARY_TOOLS)}, "path": _PATH, "code": _STRING}, ("tool", "code")),
    _selector("truncation", {"path": _PATH}, ("path",)),
    _selector("binding", {"project_name": _STRING, "source": {"enum": ["configured", "default_repo"]},
                          "available": {"type": "boolean"}}, ("project_name", "source", "available")),
]}
CALL_SCHEMA = _object({"tool": {"enum": list(SUPPORTED_TOOLS)}, "arguments": {"type": "object"}}, ("tool", "arguments"))
GOAL_SCHEMA = _object({"id": _STRING, "description": _STRING,
                      "alternatives": {"type": "array", "minItems": 1, "items": SELECTOR_SCHEMA}}, ("id", "description", "alternatives"))
CASE_SCHEMA = _object({
    "id": {"type": "string", "pattern": "^(dev|val)-[0-9]{3}$"},
    "split": {"enum": ["dev", "validation"]},
    "group": {"enum": ["target", "multistep", "recovery", "boundary"]},
    "focus_tool": {"enum": [None, *SUPPORTED_TOOLS]},
    "project": {"enum": ["fixture", "requests", "urllib3"]},
    "query": _STRING, "rationale": _STRING,
    "goals": {"type": "array", "items": GOAL_SCHEMA},
    "dependencies": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": _STRING}},
    "required_tools": {"type": "array", "items": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": list(SUPPORTED_TOOLS)}}},
    "first_actions": _STRINGS,
    "terminal_statuses": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": ["completed", "refused"]}},
    "refusal_codes": _STRINGS,
    "max_tool_calls": {"type": "integer", "minimum": 0, "maximum": 4},
    "forbidden_tools": _STRINGS,
    "reference_calls": {"type": "array", "maxItems": 4, "items": CALL_SCHEMA},
    "source_hashes": {"type": "object", "additionalProperties": _HASH},
    "fault": {"oneOf": [{"type": "null"}, _object({"tool": {"enum": list(PRIMARY_TOOLS)},
              "arguments_subset": {"type": "object"}, "code": {"const": "TOOL_EXECUTION_FAILED"}}, ("tool", "arguments_subset", "code"))]},
}, ("id", "split", "group", "focus_tool", "project", "query", "rationale", "goals", "dependencies", "required_tools",
    "first_actions", "terminal_statuses", "refusal_codes", "max_tool_calls", "forbidden_tools", "reference_calls", "source_hashes", "fault"))
_VALIDATOR = Draft202012Validator(CASE_SCHEMA)


def validate_case(case: dict) -> None:
    _VALIDATOR.validate(case)
    if (case["split"] == "dev") != case["id"].startswith("dev-"):
        raise ValueError("Case ID/split mismatch")
    ids = [goal["id"] for goal in case["goals"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate goal ID")
    for before, after in case["dependencies"]:
        if before not in ids or after not in ids or before == after:
            raise ValueError("Invalid goal dependency")
    # Reject cycles, including dependencies that would make a positive case unreachable.
    remaining, reached = list(case["dependencies"]), set()
    while remaining:
        nodes = {x for edge in remaining for x in edge}
        roots = nodes - {edge[1] for edge in remaining}
        if not roots:
            raise ValueError("Cyclic dependencies")
        reached.update(roots)
        remaining = [edge for edge in remaining if edge[0] not in reached]
    for path in case["source_hashes"]:
        relative_path(path)
    for goal in case["goals"]:
        for selector in goal["alternatives"]:
            for name in ("path", "input_path"):
                if name in selector:
                    relative_path(selector[name])
            if selector["kind"] == "source":
                numbers = [line["line"] for line in selector["lines"]]
                if len(set(numbers)) != len(numbers):
                    raise ValueError("Duplicate source line")


def load_cases(split: str = "all", dataset_dir: Path = DATASET_DIR) -> list[dict]:
    if split not in ("dev", "validation", "all"):
        raise ValueError("Unknown split")
    cases = []
    for name in (("dev", "validation") if split == "all" else (split,)):
        with (dataset_dir / f"{name}.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    case = json.loads(line)
                    validate_case(case)
                    cases.append(case)
    ids = [case["id"] for case in cases]
    queries = [case["query"].strip() for case in cases]
    if len(set(ids)) != len(ids) or len(set(queries)) != len(queries):
        raise ValueError("Duplicate case ID or query")
    return cases


def verify_gold_sources(case: dict, project_root: Path) -> None:
    for path, expected in case["source_hashes"].items():
        actual = text_digest((project_root / relative_path(path)).read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError(f"Gold source changed: {case['id']} / {path}")
