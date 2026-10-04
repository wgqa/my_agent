"""Engineering Reader: explicit file, line or Python-symbol targets.

One registered Reader replaces the old contract for Engineering only. Every
call reads one allowed file; discontinuous regions share a 120-line/8000-char
budget and retain independent locators. Missing/ambiguous symbols are data,
never silently replaced by another definition or a guessed text window.
"""

from __future__ import annotations

from core.tool_agent.models import PROJECT_CONTEXT_LINE_OUT_OF_RANGE, ToolExecutionError, ToolSpec
from core.tool_agent.source_excerpt import MAX_DEFINITION_CHARACTERS, MAX_DEFINITION_LINES, MAX_LINE_LENGTH
from core.tool_agent.tools.read_project_context import ReadProjectContextHandler
from core.tool_agent.tools.source_navigation import bounded_lines, locate_function, python_symbols


READ_PROJECT_TARGETS_VERSION = "read_project_context_v4"
MAX_TARGETS = 4
MAX_CANDIDATE_SYMBOLS = 5


def _target_schema(kind, properties, required):
    return {
        "type": "object", "properties": {"kind": {"const": kind}, **properties},
        "required": ["kind", *required], "additionalProperties": False,
    }


READ_PROJECT_TARGETS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 500},
        "target": {"oneOf": [
            _target_schema("file", {"start_line": {"type": "integer", "minimum": 1}}, ["start_line"]),
            _target_schema("window", {
                "line": {"type": "integer", "minimum": 1},
                "context_lines": {"type": "integer", "minimum": 0, "maximum": 30},
            }, ["line", "context_lines"]),
            _target_schema("definition", {
                "line": {"type": "integer", "minimum": 1},
                "start_line": {"type": "integer", "minimum": 1},
            }, ["line"]),
            _target_schema("symbols", {"names": {
                "type": "array", "minItems": 1, "maxItems": MAX_TARGETS, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
            }}, ["names"]),
            _target_schema("matching", {"query": {"type": "string", "minLength": 1, "maxLength": 200, "pattern": "\\S"}}, ["query"]),
        ]},
    },
    "required": ["path", "target"], "additionalProperties": False,
}

_SYMBOL_SCHEMA = {
    "type": ["object", "null"],
    "properties": {
        "name": {"type": "string", "maxLength": 500},
        "kind": {"enum": ["function", "class", "assignment"]},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
    },
    "required": ["name", "kind", "start_line", "end_line"], "additionalProperties": False,
}
_REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"const": "definition"},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "lines": {"type": "array", "minItems": 1, "maxItems": MAX_DEFINITION_LINES,
            "items": {"type": "object", "properties": {
                "line": {"type": "integer", "minimum": 1},
                "text": {"type": "string", "maxLength": MAX_LINE_LENGTH},
            }, "required": ["line", "text"], "additionalProperties": False}},
    },
    "required": ["mode", "start_line", "end_line", "lines"], "additionalProperties": False,
}
READ_PROJECT_TARGETS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "mode": {"const": "targets"},
        "selection_truncated": {"type": "boolean"},
        "regions": {"type": "array", "maxItems": MAX_TARGETS, "items": _REGION_SCHEMA},
        "targets": {"type": "array", "minItems": 1, "maxItems": MAX_TARGETS, "items": {
            "type": "object",
            "properties": {
                "requested": {"type": "string", "maxLength": 500},
                "status": {"enum": ["read", "empty", "not_found", "ambiguous", "unsupported_language", "parse_error", "output_limit"]},
                "definition": _SYMBOL_SCHEMA,
                "region_index": {"type": ["integer", "null"], "minimum": 0, "maximum": MAX_TARGETS - 1},
                "content_complete": {"type": "boolean"},
                "truncation_reasons": {"type": "array", "uniqueItems": True, "items": {
                    "enum": ["line_limit", "character_limit", "line_length_limit", "continuation_page"],
                }},
                "next_line": {"type": ["integer", "null"], "minimum": 1},
                "fallback_reason": {"type": ["string", "null"]},
                "candidates": {"type": "array", "maxItems": MAX_CANDIDATE_SYMBOLS, "items": {**_SYMBOL_SCHEMA, "type": "object"}},
                "candidates_truncated": {"type": "boolean"},
            },
            "required": ["requested", "status", "definition", "region_index", "content_complete", "truncation_reasons", "next_line", "fallback_reason", "candidates", "candidates_truncated"],
            "additionalProperties": False,
        }},
    },
    "required": ["path", "mode", "selection_truncated", "regions", "targets"], "additionalProperties": False,
}

READ_PROJECT_TARGETS_SPEC = ToolSpec(
    name="read_project_context", version=READ_PROJECT_TARGETS_VERSION,
    description=(
        "读取当前绑定项目一个已知相对路径；已知 path 可以直接读，无需先搜索文件名。"
        '参数仅 path 与 target。例如文档/小文件用 target={"kind":"file","start_line":1}；'
        'Python 函数、方法或默认常量用 target={"kind":"symbols","names":["Class.method","DEFAULT_VALUE"]}，'
        "同文件最多四个目标，共享120行/8000字符上限，单行300字符。不执行表达式、不追踪未读取的导入。"
        "具名目标按 AST 定位，短名只在唯一匹配时读取；歧义/不存在返回候选或缺口，不代用其他函数。"
        '只知道某文件内的被测标识符时，用 target={"kind":"matching","query":"identifier"}，'
        "Python 中匹配函数/常量定义名及正文并读取最多四个定义，不把导入命中当成测试实现；"
        "其他允许文本（包括 md/rst 文档）按 literal 命中读取前后30行，重叠窗口合并，共享同一正文上限。"
        "selection_truncated 表示更多匹配定义没取得，不代表全量覆盖或受影响集合。"
        '已有搜索行号也可 target={"kind":"definition","line":42} 读取包含该行的 Python 函数，'
        '或 target={"kind":"window","line":42,"context_lines":30} 读取文档/常量窗口。'
        "definition 续读保持原 line，添加 start_line=next_line；file 用 start_line=next_line。"
        "symbols 截断时，可据返回的 definition.start_line 切换 definition 续读函数，其他对象用 file 续读。"
        "regions 各有真实连续行号，分别成为可引用证据；targets 中的名字、候选位置不是源码正文。"
        "content_complete 只表示请求对象正文是否完整取得，不表示任务完成或测试通过。"
        "fallback_reason、截断和未返回的目标必须明确说明。仅允许原 Reader 的安全文件范围。"
    ),
    input_schema=READ_PROJECT_TARGETS_INPUT_SCHEMA, output_schema=READ_PROJECT_TARGETS_OUTPUT_SCHEMA,
)


class ReadProjectTargetsHandler(ReadProjectContextHandler):
    def execute(self, arguments):
        candidate, source_lines = self._load_source(arguments["path"])
        target = arguments["target"]
        regions, targets = [], []
        selection_truncated = False
        used_lines = used_characters = 0

        def add(requested, start=None, end=None, definition=None, status="read", fallback=None, candidates=(), continuation=False):
            nonlocal used_lines, used_characters
            item = {"requested": requested, "status": status, "definition": definition,
                "region_index": None, "content_complete": False, "truncation_reasons": [],
                "next_line": None, "fallback_reason": fallback,
                "candidates": [span.to_dict() for span in candidates[:MAX_CANDIDATE_SYMBOLS]],
                "candidates_truncated": len(candidates) > MAX_CANDIDATE_SYMBOLS}
            targets.append(item)
            if start is None:
                return
            if not source_lines:
                item["status"] = "empty"
                return
            if not 1 <= start <= end <= len(source_lines):
                raise ToolExecutionError(PROJECT_CONTEXT_LINE_OUT_OF_RANGE)
            for index, region in enumerate(regions):
                if region["start_line"] == start and region["end_line"] == end:
                    previous = next(value for value in targets[:-1] if value["region_index"] == index)
                    reasons = list(previous["truncation_reasons"])
                    if continuation and "continuation_page" not in reasons:
                        reasons.append("continuation_page")
                    item.update(region_index=index, truncation_reasons=reasons,
                        next_line=previous["next_line"], content_complete=fallback is None and not reasons)
                    return
            lines, reasons, next_line = bounded_lines(source_lines, start, end,
                max_line_length=MAX_LINE_LENGTH, max_lines=MAX_DEFINITION_LINES-used_lines,
                max_characters=max(0, MAX_DEFINITION_CHARACTERS-used_characters-bool(regions)))
            item.update(truncation_reasons=reasons, next_line=next_line)
            if continuation:
                reasons.append("continuation_page")
            if not lines:
                item["status"] = "output_limit"
                return
            if not any(line["text"] for line in lines):
                item["status"] = "output_limit" if next_line is not None else "empty"
                return
            item["region_index"] = len(regions)
            item["content_complete"] = fallback is None and not reasons and next_line is None
            regions.append({"mode": "definition", "start_line": lines[0]["line"], "end_line": lines[-1]["line"], "lines": lines})
            used_lines += len(lines)
            used_characters += sum(len(line["text"]) for line in lines)+len(lines)-1+bool(len(regions)>1)

        kind = target["kind"]
        if kind == "matching" and candidate.suffix.lower() != ".py":
            query = target["query"].lower()
            windows = []
            for number, line in enumerate(source_lines, 1):
                if query not in line.lower():
                    continue
                start, end = max(1, number-30), min(len(source_lines), number+30)
                if windows and start <= windows[-1][1]+1:
                    windows[-1] = (windows[-1][0], max(end, windows[-1][1]))
                else:
                    windows.append((start, end))
            selection_truncated = len(windows)>MAX_TARGETS
            if not windows:
                add(target["query"], status="not_found")
            for start, end in windows[:MAX_TARGETS]:
                add(target["query"], start, end)
        elif kind in ("symbols", "matching"):
            spans, error = python_symbols(source_lines) if candidate.suffix.lower() == ".py" else ((), "unsupported_language")
            if kind == "matching":
                query = target["query"].lower()
                matches = [span for span in spans if span.kind != "class" and
                    (query in span.name.lower() or any(query in line.lower() for line in source_lines[span.start_line-1:span.end_line]))]
                matches.sort(key=lambda span: (query not in span.name.lower(), span.start_line, span.name))
                selection_truncated = len(matches)>MAX_TARGETS
                if error or not matches:
                    add(target["query"], status=error or "not_found")
                for span in matches[:MAX_TARGETS]:
                    add(span.name, span.start_line, span.end_line, definition=span.to_dict())
            for name in target.get("names", ()):
                matches = [span for span in spans if span.name == name or ("." not in name and span.name.endswith("."+name))]
                if error or len(matches) != 1:
                    add(name, status=error or ("not_found" if not matches else "ambiguous"), candidates=matches)
                else:
                    span = matches[0]
                    add(name, span.start_line, span.end_line, definition=span.to_dict())
        elif kind == "file":
            add("file", target["start_line"], len(source_lines), continuation=target["start_line"]>1)
        else:
            line = target["line"]
            if not 1 <= line <= len(source_lines):
                raise ToolExecutionError(PROJECT_CONTEXT_LINE_OUT_OF_RANGE)
            if kind == "definition":
                span, fallback = locate_function(source_lines, line) if candidate.suffix.lower() == ".py" else (None, "unsupported_language")
                start = span.start_line if span else max(1, line-30)
                end = span.end_line if span else min(len(source_lines), line+30)
                requested_start = target.get("start_line", start)
                if not start <= requested_start <= end:
                    raise ToolExecutionError(PROJECT_CONTEXT_LINE_OUT_OF_RANGE)
                definition = {**span.to_dict(), "kind": "function"} if span else None
                add("definition", requested_start, end, definition=definition, fallback=fallback, continuation=requested_start>start)
            else:
                add("window", max(1, line-target["context_lines"]), min(len(source_lines), line+target["context_lines"]))
        return {"path": candidate.relative_to(self._root).as_posix(), "mode": "targets",
            "selection_truncated": selection_truncated, "regions": regions, "targets": targets}
