"""Bounded Python function navigation; no filesystem access or code execution."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Sequence

MAX_DEFINITION_LINES = 120
MAX_DEFINITION_CHARACTERS = 8000
MAX_DEFINITION_NAME_LENGTH = 500


@dataclass(frozen=True)
class FunctionSpan:
    name: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


def locate_function(
    source_lines: Sequence[str], line: int,
) -> tuple[FunctionSpan | None, str | None]:
    """Find the innermost function containing the anchor, including decorators.

    Class anchors do not expand to an entire class. Syntax errors explicitly
    fall back to text; source is parsed, never imported or executed.
    """
    source = "\n".join(source_lines).removeprefix("\ufeff")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None, "parse_error"

    candidates: list[FunctionSpan] = []
    stack: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
    while stack:
        node, scope = stack.pop()
        child_scope = scope
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            child_scope = (*scope, node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            end = node.end_lineno
            if end is not None and start <= line <= end:
                candidates.append(FunctionSpan(".".join(child_scope), start, end))
        stack.extend((child, child_scope) for child in ast.iter_child_nodes(node))

    if not candidates:
        return None, "no_function_at_line"
    span = min(candidates, key=lambda item: (item.end_line - item.start_line, -item.start_line))
    if len(span.name) > MAX_DEFINITION_NAME_LENGTH:
        return None, "symbol_name_limit"
    return span, None


def bounded_lines(
    source_lines: Sequence[str], start: int, end: int, *, max_line_length: int,
) -> tuple[list[dict], list[str], int | None]:
    """Return bounded content and explicitly account for every text truncation.

    The character budget includes separators between returned lines. A clipped
    individual line cannot be repaired by moving to the next line; its reason
    is retained even when no suffix remains.
    """
    items: list[dict] = []
    reasons: list[str] = []
    used_characters = 0
    for number in range(start, end + 1):
        if len(items) == MAX_DEFINITION_LINES:
            reasons.append("line_limit")
            break
        raw = source_lines[number - 1]
        text = raw[:max_line_length]
        size = len(text) + bool(items)
        if used_characters + size > MAX_DEFINITION_CHARACTERS:
            reasons.append("character_limit")
            break
        items.append({"line": number, "text": text})
        used_characters += size
        if len(raw) > max_line_length and "line_length_limit" not in reasons:
            reasons.append("line_length_limit")
    next_line = items[-1]["line"] + 1 if items[-1]["line"] < end else None
    return items, reasons, next_line
