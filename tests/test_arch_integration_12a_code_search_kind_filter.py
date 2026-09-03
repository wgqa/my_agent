"""Provider-free tests for ARCH-INTEGRATION-12A code-search filtering."""

from __future__ import annotations

from types import SimpleNamespace

from core.tool_agent import INVALID_TOOL_ARGUMENTS, ToolCall, ToolExecutor, ToolRegistry
from core.tool_agent.runtime import _evidence_from_project_context
from core.tool_agent.tools.code_search import (
    CODE_SEARCH_SPEC,
    CodeSearchHandler,
    classify_project_evidence_path,
)
from core.tool_agent.tools.read_project_context import ReadProjectContextHandler


SHARED_LITERAL = "SHARED_EVIDENCE_LITERAL"


def _synthetic_repo(tmp_path):
    repo = tmp_path / "synthetic_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "service.py").write_text(
        f"def service():\n    return '{SHARED_LITERAL}'\n",
        encoding="utf-8",
    )
    (repo / "docs" / "README.md").write_text(
        f"# Design note\n{SHARED_LITERAL} is documented here.\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_service.py").write_text(
        f"def test_service():\n    assert '{SHARED_LITERAL}'\n",
        encoding="utf-8",
    )
    return repo


def _search(repo, arguments):
    return CodeSearchHandler(repo).execute(arguments)["matches"]


def _runtime_kind(repo, path):
    result = ReadProjectContextHandler(repo).execute(
        {"path": path, "line": 1, "context_lines": 5}
    )
    observation = SimpleNamespace(
        status="ok",
        tool_name="read_project_context",
        result=result,
    )
    evidence = _evidence_from_project_context(observation)
    assert evidence is not None
    return evidence.kind


def test_same_literal_filter_separates_source_docs_and_tests_by_runtime_kind(tmp_path):
    repo = _synthetic_repo(tmp_path)
    all_matches = _search(repo, {"query": SHARED_LITERAL})
    assert [match["path"] for match in all_matches] == [
        "docs/README.md",
        "src/service.py",
        "tests/test_service.py",
    ]

    code_matches = _search(
        repo, {"query": SHARED_LITERAL, "artifact_kind": "project_code"}
    )
    doc_matches = _search(
        repo, {"query": SHARED_LITERAL, "artifact_kind": "project_doc"}
    )
    assert [match["path"] for match in code_matches] == ["src/service.py"]
    assert [match["path"] for match in doc_matches] == ["docs/README.md"]
    assert not {match["path"] for match in code_matches} & {
        "docs/README.md",
        "tests/test_service.py",
    }
    assert not {match["path"] for match in doc_matches} & {
        "src/service.py",
        "tests/test_service.py",
    }

    paths = {"docs/README.md", "src/service.py", "tests/test_service.py"}
    runtime_kinds = {path: _runtime_kind(repo, path) for path in paths}
    assert runtime_kinds == {
        path: classify_project_evidence_path(path) for path in paths
    }
    assert runtime_kinds == {
        "docs/README.md": "project_doc",
        "src/service.py": "project_code",
        "tests/test_service.py": "project_test",
    }


def test_omitted_artifact_kind_is_byte_for_byte_equivalent_to_any(tmp_path):
    repo = _synthetic_repo(tmp_path)
    omitted = _search(repo, {"query": SHARED_LITERAL})
    explicit_any = _search(repo, {"query": SHARED_LITERAL, "artifact_kind": "any"})
    assert omitted == explicit_any
    assert CODE_SEARCH_SPEC.input_schema["properties"]["artifact_kind"]["enum"] == [
        "any",
        "project_code",
        "project_doc",
    ]


def test_project_test_filter_is_not_added_to_code_search_and_find_tests_remains_owner(
    tmp_path,
):
    repo = _synthetic_repo(tmp_path)
    registry = ToolRegistry()
    registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(repo))
    observation = ToolExecutor(registry).execute(
        ToolCall.create(
            "code_search",
            {"query": SHARED_LITERAL, "artifact_kind": "project_test"},
        )
    )
    assert observation.error_code == INVALID_TOOL_ARGUMENTS
    assert "find_tests" in CODE_SEARCH_SPEC.description
    assert "read_project_context" in CODE_SEARCH_SPEC.description
    assert "project_code" in CODE_SEARCH_SPEC.description
    assert "project_doc" in CODE_SEARCH_SPEC.description
