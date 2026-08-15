"""Tests for Gate 4 Structured Tool Agent core (G4-TOOL-02).

Covers: ToolSpec construction + schema validation + immutability, ToolCall
call_id generation, ToolObservation cross-field invariants, ToolRegistry
semantics (dup reject / deterministic sorted specs / no handler exposure),
and the ToolExecutor fixed pipeline (UNKNOWN_TOOL / INVALID_TOOL_ARGUMENTS /
TOOL_PERMISSION_DENIED / TOOL_BUDGET_EXCEEDED / TOOL_EXECUTION_FAILED /
TOOL_RESULT_INVALID / success). Uses only Fake Handlers; no LLM, no real
tools, no Agent loop, no network, no Holdout.
"""

from __future__ import annotations

import pytest

from core.tool_agent import (
    INVALID_TOOL_ARGUMENTS,
    TOOL_BUDGET_EXCEEDED,
    TOOL_EXECUTION_FAILED,
    TOOL_PERMISSION_DENIED,
    TOOL_RESULT_INVALID,
    UNKNOWN_TOOL,
    RegisteredTool,
    ToolCall,
    ToolExecutor,
    ToolObservation,
    ToolRegistry,
    ToolSpec,
    json_deep_copy,
)

# ---- fixtures ----

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "additionalProperties": False,
    "required": ["query"],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"echo": {"type": "string"}},
    "additionalProperties": False,
    "required": ["echo"],
}

# 宽松 output：任意 object 内容都通过 jsonschema，用于隔离 JSON-safety 检查。
LOOSE_OUTPUT_SCHEMA = {"type": "object"}


def make_spec(
    name: str = "echo",
    input_schema: dict = INPUT_SCHEMA,
    output_schema: dict = OUTPUT_SCHEMA,
    version: str = "v1",
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="an echo tool",
        input_schema=input_schema,
        output_schema=output_schema,
        version=version,
    )


class EchoHandler:
    """合法成功 handler：返回 {"echo": <query>}。"""

    def execute(self, arguments):
        return {"echo": arguments["query"]}


class FailingHandler:
    """执行即抛异常。"""

    def execute(self, arguments):
        raise RuntimeError("boom-secret-detail")


class InvalidOutputHandler:
    """返回不符合 output_schema 的结果。"""

    def execute(self, arguments):
        return {"echo": 123}


class CountingHandler:
    """计数 + 合法返回，用于验证 handler calls=0。"""

    def __init__(self):
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return {"echo": arguments["query"]}


class SharedResultHandler:
    """返回内部持久可变对象，用于验证 observation 不反向污染。"""

    def __init__(self):
        self.internal = {"echo": "v1"}

    def execute(self, arguments):
        return self.internal


class BytesOutputHandler:
    def execute(self, arguments):
        return {"data": b"raw-bytes"}


class SetOutputHandler:
    def execute(self, arguments):
        return {"data": {1, 2, 3}}


class CustomObjectOutputHandler:
    def execute(self, arguments):
        return {"data": object()}


class NaNOutputHandler:
    def execute(self, arguments):
        return {"data": float("nan")}


class InfOutputHandler:
    def execute(self, arguments):
        return {"data": float("inf")}


def build_executor(
    *tools,
    allowed_tools=None,
) -> ToolExecutor:
    registry = ToolRegistry()
    for spec, handler in tools:
        registry.register(spec, handler)
    return ToolExecutor(registry, allowed_tools=allowed_tools)


# ---- 1. ToolSpec 合法构造 ----
# ---- 2. ToolSpec 非法 / 空字段 ----
# ---- 3. ToolSpec 非法 JSON schema ----
# ---- 4. input object 缺 additionalProperties:false 被拒 ----


class TestToolSpec:
    def test_valid_spec(self):
        spec = make_spec()
        assert spec.name == "echo"
        assert spec.description == "an echo tool"
        assert spec.version == "v1"
        assert spec.input_schema_copy() == INPUT_SCHEMA
        assert spec.output_schema_copy() == OUTPUT_SCHEMA
        assert spec.to_dict()["name"] == "echo"

    @pytest.mark.parametrize("field", ["name", "description", "version"])
    def test_empty_field_rejected(self, field):
        kwargs = {"name": "echo", "description": "d", "input_schema": INPUT_SCHEMA,
                  "output_schema": OUTPUT_SCHEMA, "version": "v1"}
        kwargs[field] = ""
        with pytest.raises((TypeError, ValueError)):
            ToolSpec(**kwargs)

    def test_name_with_whitespace_rejected(self):
        with pytest.raises(ValueError):
            make_spec(name="  echo  ")

    def test_invalid_json_schema_rejected(self):
        with pytest.raises(ValueError, match="JSON Schema"):
            ToolSpec(
                name="x",
                description="d",
                # properties 必须是 object，此处非法 → check_schema 失败
                input_schema={"type": "object", "properties": "not-an-object",
                              "additionalProperties": False},
                output_schema={"type": "object"},
                version="v1",
            )

    def test_input_root_must_be_object(self):
        with pytest.raises(ValueError, match="根类型必须是 object"):
            ToolSpec(
                name="x",
                description="d",
                input_schema={"type": "string", "additionalProperties": False},
                output_schema={"type": "object"},
                version="v1",
            )

    def test_input_object_missing_additional_properties_false_rejected(self):
        # 缺失 additionalProperties
        with pytest.raises(ValueError, match="additionalProperties"):
            ToolSpec(
                name="x",
                description="d",
                input_schema={"type": "object", "properties": {"a": {"type": "string"}}},
                output_schema={"type": "object"},
                version="v1",
            )
        # additionalProperties: True 同样拒绝
        with pytest.raises(ValueError, match="additionalProperties"):
            ToolSpec(
                name="x",
                description="d",
                input_schema={"type": "object", "properties": {"a": {"type": "string"}},
                              "additionalProperties": True},
                output_schema={"type": "object"},
                version="v1",
            )

    # ---- 5. schema 外部 mutation 不影响 ToolSpec ----

    def test_schema_external_mutation_does_not_affect_spec(self):
        inp = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
            "required": ["query"],
        }
        spec = ToolSpec(
            name="m",
            description="d",
            input_schema=inp,
            output_schema={"type": "object", "properties": {"echo": {"type": "string"}},
                           "additionalProperties": False, "required": ["echo"]},
            version="v1",
        )
        inp["properties"]["query"]["type"] = "number"  # 嵌套 mutation
        inp["additionalProperties"] = True
        inp["extra"] = "injected"
        assert spec.input_schema_copy() == {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
            "required": ["query"],
        }

    def test_spec_schema_copy_is_detached(self):
        spec = make_spec()
        exported = spec.input_schema_copy()
        exported["properties"]["query"]["type"] = "number"
        assert spec.input_schema_copy()["properties"]["query"]["type"] == "string"


# ---- 6. 重复 register 被拒 ----
# ---- 7. Registry deterministic sorted specs ----
# ---- 8. Registry 不暴露 handler ----


class TestToolRegistry:
    def test_register_and_duplicate_rejected(self):
        registry = ToolRegistry()
        registry.register(make_spec("b"), EchoHandler())
        with pytest.raises(ValueError, match="已注册"):
            registry.register(make_spec("b"), EchoHandler())
        assert len(registry) == 1

    def test_register_requires_toolhandler(self):
        registry = ToolRegistry()
        with pytest.raises(TypeError, match="ToolHandler"):
            registry.register(make_spec("a"), "not-a-handler")
        # 类（而非实例）会被拒绝：不允许把类注册为 handler
        with pytest.raises(TypeError, match="实例"):
            registry.register(make_spec("a"), EchoHandler)

    def test_list_specs_deterministic_sorted(self):
        registry = ToolRegistry()
        for name in ("z_tool", "a_tool", "m_tool"):
            registry.register(make_spec(name), EchoHandler())
        names = [spec.name for spec in registry.list_specs()]
        assert names == ["a_tool", "m_tool", "z_tool"]
        # 重复调用结果一致
        assert [spec.name for spec in registry.list_specs()] == names

    def test_registry_does_not_expose_handler(self):
        registry = ToolRegistry()
        registry.register(make_spec("echo"), EchoHandler())
        spec = registry.get_spec("echo")
        assert isinstance(spec, ToolSpec)
        assert "handler" not in spec.to_dict()
        for s in registry.list_specs():
            assert isinstance(s, ToolSpec)
            assert "handler" not in s.to_dict()
        assert registry.get_spec("nope") is None
        assert registry.resolve("echo") is not None  # 内部执行路径

    def test_resolve_unknown_is_none(self):
        registry = ToolRegistry()
        assert registry.resolve("missing") is None


# ---- 9. Runtime 生成 call_id ----


class TestToolCall:
    def test_call_id_is_system_generated_unique(self):
        c1 = ToolCall.create("echo", {"query": "a"})
        c2 = ToolCall.create("echo", {"query": "b"})
        assert c1.call_id
        assert c1.call_id.startswith("call_")
        assert c1.call_id != c2.call_id

    def test_arguments_are_copied(self):
        args = {"query": "x"}
        call = ToolCall.create("echo", args)
        args["query"] = "y"
        assert call.arguments_copy() == {"query": "x"}

    def test_empty_tool_name_rejected(self):
        with pytest.raises((TypeError, ValueError)):
            ToolCall.create("", {"query": "x"})

    def test_non_json_arguments_rejected(self):
        with pytest.raises((TypeError, ValueError)):
            ToolCall.create("echo", {"data": b"bytes"})


# ---- ToolObservation 跨字段不变量 ----


class TestToolObservation:
    def test_ok_invariants(self):
        obs = ToolObservation(call_id="c1", tool_name="echo", status="ok",
                              result={"echo": "hi"}, error_code=None)
        assert obs.status == "ok"
        assert obs.error_code is None

    def test_ok_requires_result(self):
        with pytest.raises(ValueError):
            ToolObservation(call_id="c1", tool_name="echo", status="ok",
                            result=None, error_code=None)

    def test_ok_forbids_error_code(self):
        with pytest.raises(ValueError):
            ToolObservation(call_id="c1", tool_name="echo", status="ok",
                            result={"echo": "hi"}, error_code=UNKNOWN_TOOL)

    def test_error_requires_error_code(self):
        with pytest.raises(ValueError):
            ToolObservation(call_id="c1", tool_name="echo", status="error",
                            result=None, error_code=None)

    def test_error_forbids_result(self):
        with pytest.raises(ValueError):
            ToolObservation(call_id="c1", tool_name="echo", status="error",
                            result={"echo": "hi"}, error_code=UNKNOWN_TOOL)

    def test_refused_like_error(self):
        obs = ToolObservation(call_id="c1", tool_name="echo", status="refused",
                              result=None, error_code=UNKNOWN_TOOL)
        assert obs.status == "refused"
        assert obs.error_code == UNKNOWN_TOOL

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            ToolObservation(call_id="c1", tool_name="echo", status="pending",
                            result=None, error_code=UNKNOWN_TOOL)

    def test_unknown_error_code_rejected(self):
        with pytest.raises(ValueError, match="error_code 未知"):
            ToolObservation(call_id="c1", tool_name="echo", status="error",
                            result=None, error_code="NOT_A_CODE")

    def test_non_json_result_rejected(self):
        with pytest.raises((TypeError, ValueError)):
            ToolObservation(call_id="c1", tool_name="echo", status="ok",
                            result={"data": b"x"}, error_code=None)


# ---- Executor 流水线 ----


class TestToolExecutor:
    def test_unknown_tool(self):
        executor = build_executor((make_spec(), EchoHandler()))
        obs = executor.execute(ToolCall.create("missing", {"query": "x"}))
        assert obs.status == "error"
        assert obs.error_code == UNKNOWN_TOOL
        assert obs.result is None

    def test_invalid_arguments_handler_zero_calls(self):
        counter = CountingHandler()
        executor = build_executor((make_spec(), counter))
        obs = executor.execute(ToolCall.create("echo", {"wrong": "arg"}))
        assert obs.error_code == INVALID_TOOL_ARGUMENTS
        assert counter.calls == 0

    def test_extra_argument_rejected(self):
        counter = CountingHandler()
        executor = build_executor((make_spec(), counter))
        # additionalProperties:false → 多出的字段触发 INVALID_TOOL_ARGUMENTS
        obs = executor.execute(ToolCall.create("echo", {"query": "x", "extra": 1}))
        assert obs.error_code == INVALID_TOOL_ARGUMENTS
        assert counter.calls == 0

    def test_permission_denied_handler_zero_calls(self):
        counter = CountingHandler()
        executor = build_executor((make_spec(), counter), allowed_tools=frozenset({"calculator"}))
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_PERMISSION_DENIED
        assert counter.calls == 0

    def test_budget_denied_handler_zero_calls(self):
        counter = CountingHandler()
        executor = build_executor((make_spec(), counter))
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}), tool_call_allowed=False)
        assert obs.error_code == TOOL_BUDGET_EXCEEDED
        assert counter.calls == 0

    def test_handler_success(self):
        executor = build_executor((make_spec(), EchoHandler()))
        obs = executor.execute(ToolCall.create("echo", {"query": "hello"}))
        assert obs.status == "ok"
        assert obs.error_code is None
        assert obs.result == {"echo": "hello"}

    def test_handler_exception_no_traceback(self):
        executor = build_executor((make_spec(), FailingHandler()))
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.status == "error"
        assert obs.error_code == TOOL_EXECUTION_FAILED
        assert obs.result is None
        serialized = str(obs.to_dict())
        assert "boom-secret-detail" not in serialized
        assert "RuntimeError" not in serialized
        assert "Traceback" not in serialized

    def test_invalid_output(self):
        executor = build_executor((make_spec(), InvalidOutputHandler()))
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_RESULT_INVALID

    def test_non_json_bytes_result(self):
        executor = build_executor(
            (make_spec(output_schema=LOOSE_OUTPUT_SCHEMA), BytesOutputHandler())
        )
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_RESULT_INVALID

    def test_non_json_set_result(self):
        executor = build_executor(
            (make_spec(output_schema=LOOSE_OUTPUT_SCHEMA), SetOutputHandler())
        )
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_RESULT_INVALID

    def test_non_json_custom_object_result(self):
        executor = build_executor(
            (make_spec(output_schema=LOOSE_OUTPUT_SCHEMA), CustomObjectOutputHandler())
        )
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_RESULT_INVALID

    def test_nan_result_rejected(self):
        executor = build_executor(
            (make_spec(output_schema=LOOSE_OUTPUT_SCHEMA), NaNOutputHandler())
        )
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_RESULT_INVALID

    def test_inf_result_rejected(self):
        executor = build_executor(
            (make_spec(output_schema=LOOSE_OUTPUT_SCHEMA), InfOutputHandler())
        )
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        assert obs.error_code == TOOL_RESULT_INVALID

    def test_result_is_detached_from_handler(self):
        shared = SharedResultHandler()
        executor = build_executor((make_spec(), shared))
        obs = executor.execute(ToolCall.create("echo", {"query": "x"}))
        obs.result["echo"] = "mutated"
        assert shared.internal["echo"] == "v1"
        # 再次执行返回独立拷贝
        obs2 = executor.execute(ToolCall.create("echo", {"query": "x"}))
        obs2.result["echo"] = "mutated2"
        assert shared.internal["echo"] == "v1"

    def test_registry_spec_mutation_does_not_pollute(self):
        registry = ToolRegistry()
        spec = make_spec()
        registry.register(spec, EchoHandler())
        # 通过 get_spec 拿到的 spec 修改拷贝，不影响 registry 内部
        external = registry.get_spec("echo")
        exported = external.input_schema_copy()
        exported["properties"]["query"]["type"] = "number"
        assert registry.get_spec("echo").input_schema_copy()["properties"]["query"]["type"] == "string"
        # 直接构造 spec 的外部 dict 也不能污染
        assert spec.input_schema_copy()["properties"]["query"]["type"] == "string"


# ---- json_deep_copy 直接测试 ----


class TestJsonDeepCopy:
    def test_roundtrip(self):
        assert json_deep_copy({"a": [1, 2, {"b": True}]}) == {"a": [1, 2, {"b": True}]}

    def test_tuple_becomes_list(self):
        assert json_deep_copy((1, 2)) == [1, 2]

    def test_non_string_key_rejected(self):
        with pytest.raises(TypeError, match="key"):
            json_deep_copy({1: "a"})

    def test_callable_rejected(self):
        with pytest.raises(TypeError, match="callable"):
            json_deep_copy(lambda: None)

    def test_nan_inf_rejected(self):
        with pytest.raises(ValueError, match="NaN/Infinity"):
            json_deep_copy(float("nan"))
        with pytest.raises(ValueError, match="NaN/Infinity"):
            json_deep_copy(float("inf"))

    def test_bytes_set_rejected(self):
        with pytest.raises(TypeError):
            json_deep_copy(b"x")
        with pytest.raises(TypeError):
            json_deep_copy({1, 2})


# ---- Registry 内部保存 RegisteredTool ----


class TestRegisteredToolBinding:
    def test_registry_stores_registered_tool(self):
        registry = ToolRegistry()
        spec = make_spec()
        handler = EchoHandler()
        registry.register(spec, handler)
        registered = registry.resolve("echo")
        assert isinstance(registered, RegisteredTool)
        assert registered.spec is spec
        assert registered.handler is handler
