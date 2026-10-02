"""Source-reading coverage, continuation, compatibility and runtime boundaries."""

from __future__ import annotations

import pytest

from core.tool_agent import (
    AGENT_BUDGET_EXCEEDED,
    AgentDecisionOutcome,
    FinalAnswerAction,
    INVALID_TOOL_ARGUMENTS,
    PROJECT_CONTEXT_LINE_OUT_OF_RANGE,
    PROJECT_CONTEXT_PATH_NOT_ALLOWED,
    ToolAgentBudget,
    ToolAgentRuntime,
    ToolCall,
    ToolCallAction,
    ToolExecutor,
    ToolRegistry,
)
from core.tool_agent.tools.read_project_context import (
    READ_PROJECT_CONTEXT_SPEC,
    ReadProjectContextHandler,
)
from core.tool_agent.tools.source_navigation import (
    MAX_DEFINITION_CHARACTERS,
    MAX_DEFINITION_LINES,
)


def executor_for(root):
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(root))
    return ToolExecutor(registry)


def read(executor, *, path="service.py", line=1, **kwargs):
    return executor.execute(ToolCall.create("read_project_context", {
        "path": path, "line": line, "context_lines": 0, "mode": "definition", **kwargs,
    }))


def long_function(lines=75):
    return "def process(value):\n" + "    value += 1\n" * lines + "    return finish(value)\n"


def test_long_function_includes_tail_without_adjacent_code(tmp_path):
    source = "before = 1\n" + long_function() + "after = 2\n"
    (tmp_path / "service.py").write_text(source, encoding="utf-8")
    executor = executor_for(tmp_path)
    old = executor.execute(ToolCall.create("read_project_context", {
        "path": "service.py", "line": 2, "context_lines": 30,
    }))
    new = read(executor, line=2)
    assert old.status == new.status == "ok"
    assert not any("finish(value)" in item["text"] for item in old.result["lines"])
    assert new.result["definition"] == {"name": "process", "start_line": 2, "end_line": 78}
    assert new.result["start_line"] == 2 and new.result["end_line"] == 78
    assert new.result["lines"][-1]["text"] == "    return finish(value)"
    assert new.result["content_complete"] is True
    assert new.result["truncation_reasons"] == [] and new.result["next_line"] is None
    assert "after = 2" not in str(new.result) and "before = 1" not in str(new.result)


@pytest.mark.parametrize("anchor", [2, 3, 4, 6, 7])
def test_decorated_async_method_includes_multiline_signature(tmp_path, anchor):
    (tmp_path / "service.py").write_text(
        "class Worker:\n"
        "    @decorate(\n"
        "        enabled=True)\n"
        "    async def process(\n"
        "        self, value,\n"
        "    ):\n"
        "        return await finish(value)\n"
        "\n"
        "    def another(self):\n"
        "        return 0\n", encoding="utf-8",
    )
    result = read(executor_for(tmp_path), line=anchor).result
    assert result["definition"] == {"name": "Worker.process", "start_line": 2, "end_line": 7}
    assert result["content_complete"] is True
    assert "def another" not in str(result)


@pytest.mark.parametrize(("anchor", "name", "start", "end"), [
    (2, "Worker.outer", 2, 6), (3, "Worker.outer.inner", 3, 4),
    (4, "Worker.outer.inner", 3, 4), (6, "Worker.outer", 2, 6),
])
def test_nested_function_selects_innermost_anchor(tmp_path, anchor, name, start, end):
    (tmp_path / "service.py").write_text(
        "class Worker:\n"
        "    def outer(self):\n"
        "        def inner(value):\n"
        "            return value + 1\n"
        "        result = inner(1)\n"
        "        return result\n", encoding="utf-8",
    )
    result = read(executor_for(tmp_path), line=anchor).result
    assert result["definition"] == {"name": name, "start_line": start, "end_line": end}
    assert result["content_complete"] is True


def test_line_limited_continuation_covers_every_line_without_overlap(tmp_path):
    (tmp_path / "service.py").write_text(long_function(180), encoding="utf-8")
    executor = executor_for(tmp_path)
    first = read(executor).result
    assert len(first["lines"]) == MAX_DEFINITION_LINES
    assert first["content_complete"] is False
    assert first["truncation_reasons"] == ["line_limit"]
    second = read(executor, start_line=first["next_line"]).result
    assert second["definition"] == first["definition"]
    assert second["lines"][-1]["text"] == "    return finish(value)"
    assert second["next_line"] is None
    # The last page by itself does not contain the full function.
    assert second["content_complete"] is False
    assert second["truncation_reasons"] == ["continuation_page"]
    numbers = [item["line"] for item in first["lines"] + second["lines"]]
    assert numbers == list(range(1, 183))


def test_character_limit_includes_separators_and_allows_suffix_read(tmp_path):
    statement = "    value = '" + "x" * 180 + "'\n"
    (tmp_path / "service.py").write_text(
        "def process():\n" + statement * 70 + "    return value\n", encoding="utf-8",
    )
    executor = executor_for(tmp_path)
    first = read(executor).result
    assert "character_limit" in first["truncation_reasons"]
    assert len("\n".join(item["text"] for item in first["lines"])) <= MAX_DEFINITION_CHARACTERS
    assert len(first["lines"]) < MAX_DEFINITION_LINES
    second = read(executor, start_line=first["next_line"]).result
    assert second["end_line"] == 72
    assert second["next_line"] is None


def test_single_line_clipping_is_explicit_even_at_function_end(tmp_path):
    (tmp_path / "service.py").write_text(
        "def process():\n    return '" + "x" * 400 + "'\n", encoding="utf-8",
    )
    result = read(executor_for(tmp_path)).result
    assert result["end_line"] == 2 and result["next_line"] is None
    assert result["content_complete"] is False
    assert result["truncation_reasons"] == ["line_length_limit"]


@pytest.mark.parametrize(("path", "source", "anchor", "reason"), [
    ("service.py", "def broken(:\n    return 1\n", 1, "parse_error"),
    ("service.js", "function process() {\n  return 1;\n}\n", 1, "unsupported_language"),
    ("service.py", "class Worker:\n    def process(self):\n        return 1\n", 1, "no_function_at_line"),
])
def test_fallback_never_claims_complete_function(tmp_path, path, source, anchor, reason):
    (tmp_path / path).write_text(source, encoding="utf-8")
    observation = read(executor_for(tmp_path), path=path, line=anchor, context_lines=30)
    assert observation.status == "ok"
    result = observation.result
    assert result["fallback_reason"] == reason
    assert result["definition"] is None and result["content_complete"] is False
    assert len(result["lines"]) <= 61


def test_bom_and_unicode_function_are_parsed_without_execution(tmp_path):
    (tmp_path / "service.py").write_text(
        "\ufeffraise RuntimeError('must not execute')\n"
        "def 查询(输入):\n    return 输入\n", encoding="utf-8",
    )
    result = read(executor_for(tmp_path), line=2).result
    assert result["definition"]["name"] == "查询"
    assert result["content_complete"] is True


def test_class_anchor_fallback_preserves_useful_legacy_window(tmp_path):
    source = "before = 1\n" * 40 + "class Worker:\n" + "    value = 1\n" * 80
    (tmp_path / "service.py").write_text(source, encoding="utf-8")
    executor = executor_for(tmp_path)
    legacy = executor.execute(ToolCall.create("read_project_context", {
        "path": "service.py", "line": 41, "context_lines": 30,
    })).result
    fallback = read(executor, line=41).result
    for key in ("path", "start_line", "end_line", "lines"):
        assert fallback[key] == legacy[key]
    assert len(fallback["lines"]) == 61
    assert fallback["fallback_reason"] == "no_function_at_line"
    assert fallback["next_line"] is None and fallback["content_complete"] is False


def test_fallback_character_paging_stays_inside_original_window(tmp_path):
    source = "// " + "x" * 250 + "\n"
    (tmp_path / "service.js").write_text(source * 100, encoding="utf-8")
    executor = executor_for(tmp_path)
    first = read(executor, path="service.js", line=41).result
    assert first["start_line"] == 11 and first["next_line"] is not None
    assert first["truncation_reasons"] == ["character_limit"]
    second = read(
        executor, path="service.js", line=41, start_line=first["next_line"],
    ).result
    assert second["end_line"] == 71 and second["next_line"] is None
    assert second["content_complete"] is False
    numbers = [item["line"] for item in first["lines"] + second["lines"]]
    assert numbers == list(range(11, 72))
    for start in (10, 72):
        observation = read(executor, path="service.js", line=41, start_line=start)
        assert observation.error_code == PROJECT_CONTEXT_LINE_OUT_OF_RANGE


@pytest.mark.parametrize("kwargs", [
    {"mode": "file"}, {"start_line": True}, {"start_line": 0},
    {"start_line": 1.5}, {"mode": "window", "start_line": 1},
    {"unexpected": True},
])
def test_new_arguments_are_strictly_validated(tmp_path, kwargs):
    (tmp_path / "service.py").write_text(long_function(), encoding="utf-8")
    assert read(executor_for(tmp_path), **kwargs).error_code == INVALID_TOOL_ARGUMENTS


@pytest.mark.parametrize("start", [1, 5])
def test_continuation_cannot_escape_selected_function(tmp_path, start):
    (tmp_path / "service.py").write_text(
        "before = 1\ndef process():\n    return 1\nafter = 2\n", encoding="utf-8",
    )
    observation = read(executor_for(tmp_path), line=2, start_line=start)
    assert observation.error_code == PROJECT_CONTEXT_LINE_OUT_OF_RANGE


@pytest.mark.parametrize("path", ["../outside.py", "C:outside.py", "api_key.py", ".env"])
def test_definition_mode_reuses_path_and_secret_guards(tmp_path, path):
    (tmp_path / "api_key.py").write_text("def key():\n    return 'secret'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("KEY=secret\n", encoding="utf-8")
    observation = read(executor_for(tmp_path), path=path)
    assert observation.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED
    assert observation.result is None


def test_definition_metadata_reaches_decision_without_extra_tool_calls(tmp_path):
    (tmp_path / "service.py").write_text(long_function(), encoding="utf-8")
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(tmp_path))

    class Provider:
        calls = 0

        def decide(self, registry, query, *, context=()):
            self.calls += 1
            if self.calls == 1:
                action = ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={
                    "path": "service.py", "line": 1, "context_lines": 0, "mode": "definition",
                })
            else:
                result = context[-1].observation_result
                assert result["content_complete"] is True
                assert result["lines"][-1]["text"] == "    return finish(value)"
                action = FinalAnswerAction(action="final_answer", answer="末尾调用 finish(value)。[E1]")
            return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)

    provider = Provider()
    result = ToolAgentRuntime(registry=registry, provider=provider).run("说明 process 的实现")
    assert result.status == "completed"
    assert (result.iterations_used, result.tool_calls_used, result.tool_errors_used) == (2, 1, 0)
    assert result.evidence[0].start_line == 1 and result.evidence[0].end_line == 77
    assert result.evidence[0].kind == "project_code"
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)


@pytest.mark.parametrize(("body_lines", "expected_calls", "failure"), [
    (430, 4, None), (550, 4, AGENT_BUDGET_EXCEEDED),
])
def test_continuations_use_shared_five_four_budget(tmp_path, body_lines, expected_calls, failure):
    (tmp_path / "service.py").write_text(long_function(body_lines), encoding="utf-8")
    registry = ToolRegistry()
    registry.register(READ_PROJECT_CONTEXT_SPEC, ReadProjectContextHandler(tmp_path))

    class Provider:
        def decide(self, registry, query, *, context=()):
            if context and context[-1].observation_result["next_line"] is None:
                action = FinalAnswerAction(action="final_answer", answer="已读到末尾。[E4]")
            else:
                arguments = {"path": "service.py", "line": 1, "context_lines": 0, "mode": "definition"}
                if context:
                    arguments["start_line"] = context[-1].observation_result["next_line"]
                action = ToolCallAction(action="tool_call", tool_name="read_project_context", arguments=arguments)
            return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)

    result = ToolAgentRuntime(registry=registry, provider=Provider()).run("读取 process 实现")
    assert result.tool_calls_used == expected_calls
    assert result.iterations_used == 5
    assert result.reason_code == failure
    assert result.failure_code is None
    assert result.status == ("refused" if failure else "completed")
    assert result.evidence[-1].end_line == min(body_lines + 2, 4 * MAX_DEFINITION_LINES)
