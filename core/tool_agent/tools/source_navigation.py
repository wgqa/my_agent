"""Bounded Python function navigation; no filesystem access or code execution."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Sequence

from core.tool_agent.source_excerpt import MAX_DEFINITION_CHARACTERS, MAX_DEFINITION_LINES

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


@dataclass(frozen=True)
class SymbolSpan:
    name: str
    kind: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind,
            "start_line": self.start_line, "end_line": self.end_line,
        }


def python_symbols(source_lines: Sequence[str]) -> tuple[tuple[SymbolSpan, ...], str | None]:
    """Index syntactic definitions, never import code or evaluate values.

    Assignment targets are exposed only at module/class scope. Qualified names
    preserve enclosing classes/functions, including actual test class names.
    Duplicate definitions remain separate so callers can report ambiguity.
    """
    try:
        tree = ast.parse("\n".join(source_lines).removeprefix("\ufeff"))
    except (SyntaxError, ValueError, RecursionError):
        return (), "parse_error"
    spans: list[SymbolSpan] = []
    stack = [(tree, (), False)]
    while stack:
        node, scope, in_function = stack.pop()
        child_scope, child_in_function = scope, in_function
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            child_scope = (*scope, node.name)
            child_in_function = in_function or not isinstance(node, ast.ClassDef)
            name = ".".join(child_scope)
            if len(name) <= MAX_DEFINITION_NAME_LENGTH and node.end_lineno is not None:
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                spans.append(SymbolSpan(name, "class" if isinstance(node, ast.ClassDef) else "function", start, node.end_lineno))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and not in_function:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for item in ast.walk(target):
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and node.end_lineno is not None:
                        name = ".".join((*scope, item.id))
                        if len(name) <= MAX_DEFINITION_NAME_LENGTH:
                            spans.append(SymbolSpan(name, "assignment", node.lineno, node.end_lineno))
        stack.extend((child, child_scope, child_in_function) for child in ast.iter_child_nodes(node))
    return tuple(sorted(spans, key=lambda span: (span.start_line, span.name))), None


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
    max_lines: int = MAX_DEFINITION_LINES,
    max_characters: int = MAX_DEFINITION_CHARACTERS,
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
        if len(items) == max_lines:
            reasons.append("line_limit")
            break
        raw = source_lines[number - 1]
        text = raw[:max_line_length]
        size = len(text) + bool(items)
        if used_characters + size > max_characters:
            reasons.append("character_limit")
            break
        items.append({"line": number, "text": text})
        used_characters += size
        if len(raw) > max_line_length and "line_length_limit" not in reasons:
            reasons.append("line_length_limit")
    next_line = (items[-1]["line"] + 1 if items[-1]["line"] < end else None) if items else start
    return items, reasons, next_line
