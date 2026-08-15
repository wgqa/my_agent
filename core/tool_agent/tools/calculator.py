"""G4-TOOLS-03：calculator —— 确定性算术 Tool。

输入只允许 expression 字符串；用 ast.parse(mode="eval") + AST 白名单
evaluator 求值，**禁止 eval / exec / compile(..., "eval")**。只允许数字、
四则 / 整除 / 取余 / 幂 / 一元正负 / 括号；禁止名字、属性、函数调用、
下标、lambda、字符串、容器、comprehension。带 AST 节点数、表达式长度、
幂指数上限与有限结果检查，防止计算 DoS。
"""

from __future__ import annotations

import ast
import math
import operator

from core.tool_agent.models import ToolSpec

CALCULATOR_VERSION = "calculator_v1"

CALCULATOR_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "expression": {"type": "string", "minLength": 1, "maxLength": 200},
    },
    "additionalProperties": False,
    "required": ["expression"],
}

CALCULATOR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "number"},
    },
    "additionalProperties": False,
    "required": ["value"],
}

CALCULATOR_SPEC = ToolSpec(
    name="calculator",
    description=(
        "对纯算术表达式做确定性计算。当问题需要把数值表达式求值（例如计算 "
        "两个实验指标的差值、把 (a+b)*c 算出来）时使用。输入只允许一个 "
        "expression 字符串；只支持数字与 + - * / // % ** 及括号。"
    ),
    input_schema=CALCULATOR_INPUT_SCHEMA,
    output_schema=CALCULATOR_OUTPUT_SCHEMA,
    version=CALCULATOR_VERSION,
)

_MAX_NODES = 50
_MAX_EXPONENT = 1000

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorError(ValueError):
    """表达式不合法 / 不可安全求值。由 Executor 转成结构化 ToolObservation。"""


def _check_nodes(tree: ast.AST) -> None:
    if len(list(ast.walk(tree))) > _MAX_NODES:
        raise CalculatorError(f"AST 节点数超过上限 {_MAX_NODES}")


def _evaluate(node: ast.AST) -> object:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CalculatorError("只允许数字常量（禁止字符串 / 布尔 / 其它字面量）")
        return value
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        op_type = type(node.op)
        if op_type is ast.Pow:
            if not isinstance(right, int) or right < 0 or right > _MAX_EXPONENT:
                raise CalculatorError(
                    f"幂指数必须是 0~{_MAX_EXPONENT} 的整数（防计算 DoS）"
                )
            return left**right
        fn = _ALLOWED_BINOPS.get(op_type)
        if fn is None:
            raise CalculatorError("不支持的二元运算符")
        try:
            return fn(left, right)
        except ZeroDivisionError as exc:
            raise CalculatorError("除以零") from exc
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand)
        fn = _ALLOWED_UNARYOPS.get(type(node.op))
        if fn is None:
            raise CalculatorError("不支持的一元运算符")
        return fn(operand)
    raise CalculatorError(f"不支持的表达式节点：{type(node).__name__}")


def evaluate_expression(expression: str) -> object:
    """安全求值纯算术表达式；非法 / 超限一律抛 CalculatorError。"""
    if not isinstance(expression, str):
        raise CalculatorError("expression 必须是字符串")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"表达式语法错误：{exc.msg}") from exc
    _check_nodes(tree)
    result = _evaluate(tree)
    if isinstance(result, float) and not math.isfinite(result):
        raise CalculatorError("计算结果必须有限（不允许 NaN/Inf）")
    return result


class CalculatorHandler:
    """ToolHandler：输入 arguments["expression"]，返回 {"value": 结果}。"""

    def execute(self, arguments):
        return {"value": evaluate_expression(arguments["expression"])}
