"""G6-VERTICAL-02 tests for bounded project source context navigation."""

from __future__ import annotations

import pytest

from core.tool_agent import (
    INVALID_TOOL_ARGUMENTS,
    PROJECT_CONTEXT_FILE_NOT_FOUND,
    PROJECT_CONTEXT_LINE_OUT_OF_RANGE,
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
    build_readonly_tool_registry,
)
from core.tool_agent.tools.code_search import CODE_SEARCH_SPEC, CodeSearchHandler
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
    ReadProjectContextHandler,
)


class FakeRetrievalPort:
    supported_strategies = ("bm25",)

    def search(self, _query, _strategy, _top_k):
        return ()


def build_demo_project(tmp_path):
    repo = tmp_path / "demo_project"
    source_dir = repo / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "service.py").write_text(
        "class PaymentService:\n"
        "    def charge(self, amount):\n"
        "        if amount <= 0:\n"
        "            raise ValueError(\"invalid amount\")\n"
        "        return self.gateway.pay(amount)\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    return repo


def context_executor(repo):
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(repo))
    return ToolExecutor(registry)


class TestReadProjectContext:
    def test_returns_line_numbered_context_and_clips_file_edges(self, tmp_path):
        repo = build_demo_project(tmp_path)
        observation = context_executor(repo).execute(
            ToolCall.create(
                "read_project_context",
                {"path": "src/service.py", "line": 2, "context_lines": 30},
            )
        )

        assert observation.status == "ok"
        assert observation.result == {
            "path": "src/service.py",
            "start_line": 1,
            "end_line": 5,
            "lines": [
                {"line": 1, "text": "class PaymentService:"},
                {"line": 2, "text": "    def charge(self, amount):"},
                {"line": 3, "text": "        if amount <= 0:"},
                {"line": 4, "text": "            raise ValueError(\"invalid amount\")"},
                {"line": 5, "text": "        return self.gateway.pay(amount)"},
            ],
        }
        assert str(repo) not in str(observation.result)

    def test_combines_code_search_then_context_for_external_repo(self, tmp_path):
        repo = build_demo_project(tmp_path)
        registry = ToolRegistry()
        registry.register(CODE_SEARCH_SPEC, CodeSearchHandler(repo))
        registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(repo))
        executor = ToolExecutor(registry)

        search = executor.execute(
            ToolCall.create("code_search", {"query": "PaymentService"})
        )
        match = search.result["matches"][0]
        context = executor.execute(
            ToolCall.create(
                "read_project_context",
                {"path": match["path"], "line": match["line"], "context_lines": 5},
            )
        )

        assert match == {
            "path": "src/service.py",
            "line": 1,
            "text": "class PaymentService:",
        }
        assert context.status == "ok"
        assert any("def charge" in item["text"] for item in context.result["lines"])

    @pytest.mark.parametrize("path_kind", ["parent", "absolute", "drive_relative"])
    def test_parent_and_absolute_paths_are_rejected(self, tmp_path, path_kind):
        repo = build_demo_project(tmp_path)
        outside = tmp_path / "outside.py"
        outside.write_text("outside\n", encoding="utf-8")
        requested_path = {
            "parent": "../outside.py",
            "absolute": str(outside),
            "drive_relative": "C:outside.py",
        }[path_kind]

        observation = context_executor(repo).execute(
            ToolCall.create(
                "read_project_context",
                {"path": requested_path, "line": 1, "context_lines": 1},
            )
        )

        assert observation.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED
        assert str(outside) not in str(observation.to_dict())

    @pytest.mark.parametrize(
        ("path", "content"),
        [
            (".env", "TOKEN=secret\n"),
            ("src/api_key.py", "key = 'secret'\n"),
            ("src/credential.yaml", "token: secret\n"),
        ],
    )
    def test_secret_file_is_rejected(self, tmp_path, path, content):
        repo = build_demo_project(tmp_path)
        secret_file = repo / path
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(content, encoding="utf-8")

        observation = context_executor(repo).execute(
            ToolCall.create(
                "read_project_context",
                {"path": path, "line": 1, "context_lines": 1},
            )
        )

        assert observation.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED

    def test_symlink_escape_is_rejected(self, tmp_path):
        repo = build_demo_project(tmp_path)
        outside = tmp_path / "outside.py"
        outside.write_text("outside\n", encoding="utf-8")
        try:
            (repo / "src" / "escaped.py").symlink_to(outside)
        except OSError:
            pytest.skip("OS does not permit symlink creation")

        observation = context_executor(repo).execute(
            ToolCall.create(
                "read_project_context",
                {"path": "src/escaped.py", "line": 1, "context_lines": 1},
            )
        )

        assert observation.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED

    def test_missing_file_and_out_of_range_line_are_clear_errors(self, tmp_path):
        repo = build_demo_project(tmp_path)
        executor = context_executor(repo)
        missing = executor.execute(
            ToolCall.create(
                "read_project_context",
                {"path": "src/missing.py", "line": 1, "context_lines": 1},
            )
        )
        out_of_range = executor.execute(
            ToolCall.create(
                "read_project_context",
                {"path": "src/service.py", "line": 6, "context_lines": 1},
            )
        )

        assert missing.error_code == PROJECT_CONTEXT_FILE_NOT_FOUND
        assert out_of_range.error_code == PROJECT_CONTEXT_LINE_OUT_OF_RANGE

    @pytest.mark.parametrize(
        "arguments",
        [
            {"path": "src/service.py", "line": 0, "context_lines": 1},
            {"path": "src/service.py", "line": True, "context_lines": 1},
            {"path": "src/service.py", "line": 1, "context_lines": -1},
            {"path": "src/service.py", "line": 1, "context_lines": 31},
            {"path": "src/service.py", "line": 1, "context_lines": True},
        ],
    )
    def test_invalid_line_or_context_size_is_rejected_by_schema(self, tmp_path, arguments):
        observation = context_executor(build_demo_project(tmp_path)).execute(
            ToolCall.create("read_project_context", arguments)
        )
        assert observation.error_code == INVALID_TOOL_ARGUMENTS

    def test_default_registry_contains_navigation_tools(self, tmp_path):
        registry = build_readonly_tool_registry(
            repo_root=build_demo_project(tmp_path), retrieval_port=FakeRetrievalPort()
        )
        assert {"code_search", "read_project_context"} <= {
            spec.name for spec in registry.list_specs()
        }
