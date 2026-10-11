"""Reader v5: v4 bodies plus object/range identity from the SAME loaded file.

No extra I/O, code execution or output-body budget. AST spans are locations,
never evidence that their unread lines were acquired.
"""
from collections import Counter
from copy import deepcopy
import hashlib

from core.tool_agent.models import ToolSpec
from core.tool_agent.tools.read_project_targets import (
    READ_PROJECT_TARGETS_SPEC, ReadProjectTargetsHandler, _SYMBOL_SCHEMA, MAX_TARGETS,
)
from core.tool_agent.tools.source_navigation import python_symbols

READ_PROJECT_SNAPSHOT_VERSION = "read_project_context_v5"
MAX_REGION_OBJECTS = 32
SOURCE_SNAPSHOT_VERSION = "project_source_snapshot_v1"

_output = deepcopy(READ_PROJECT_TARGETS_SPEC.output_schema)
_output["properties"].update({
    "source_snapshot": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "schema_version": {"const": SOURCE_SNAPSHOT_VERSION},
            "content_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "line_count": {"type": "integer", "minimum": 0},
            "index_status": {"enum": ["parsed", "not_python", "parse_error"]},
        }, "required": ["schema_version", "content_sha256", "line_count", "index_status"],
    },
    "region_objects": {
        "type": "array", "maxItems": MAX_TARGETS,
        "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "region_index": {"type": "integer", "minimum": 0, "maximum": MAX_TARGETS-1},
                "truncated": {"type": "boolean"},
                "objects": {"type": "array", "maxItems": MAX_REGION_OBJECTS,
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "definition": {**_SYMBOL_SCHEMA, "type": "object"},
                            "qualified_name_unique": {"type": "boolean"},
                            "short_name_unique": {"type": "boolean"},
                        }, "required": ["definition", "qualified_name_unique", "short_name_unique"],
                    }},
            }, "required": ["region_index", "truncated", "objects"],
        },
    },
})
_output["required"].extend(["source_snapshot", "region_objects"])

READ_PROJECT_SNAPSHOT_SPEC = ToolSpec(
    name=READ_PROJECT_TARGETS_SPEC.name, version=READ_PROJECT_SNAPSHOT_VERSION,
    description=READ_PROJECT_TARGETS_SPEC.description + (
        " 文件内容 SHA、实际行数与 region_objects 来自同一次读取。对象位置并不代表未返回的正文。"
        "同绑定、同路径、同内容 SHA 的连续片段可共同覆盖完整对象；有洞、行裁剪、不同版本不能拼接。"
    ),
    input_schema=READ_PROJECT_TARGETS_SPEC.input_schema, output_schema=_output,
)


class ReadProjectSnapshotHandler(ReadProjectTargetsHandler):
    def execute(self, arguments):
        candidate, lines = self._load_source(arguments["path"])
        result = self._execute_loaded(candidate, lines, arguments)
        if candidate.suffix.lower() == ".py":
            spans, error = python_symbols(lines)
            status = error or "parsed"
        else:
            spans, status = (), "not_python"
        qualified = Counter(span.name for span in spans)
        short = Counter(span.name.rsplit(".", 1)[-1] for span in spans)
        result["source_snapshot"] = {
            "schema_version": SOURCE_SNAPSHOT_VERSION,
            "content_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
            "line_count": len(lines), "index_status": status,
        }
        result["region_objects"] = []
        for index, region in enumerate(result["regions"]):
            intersecting = [span for span in spans
                if span.start_line <= region["end_line"] and span.end_line >= region["start_line"]]
            result["region_objects"].append({
                "region_index": index, "truncated": len(intersecting) > MAX_REGION_OBJECTS,
                "objects": [{"definition": span.to_dict(),
                    "qualified_name_unique": qualified[span.name] == 1,
                    "short_name_unique": short[span.name.rsplit(".", 1)[-1]] == 1,
                } for span in intersecting[:MAX_REGION_OBJECTS]],
            })
        return result
