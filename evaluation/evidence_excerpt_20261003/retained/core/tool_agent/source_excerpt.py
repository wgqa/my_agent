"""Shared bounds for Reader observations and their public source excerpts.

The public excerpt contains every line returned by Reader. Display previews
must not silently replace that content with a shorter citation artifact.
"""

from __future__ import annotations


MAX_CONTEXT_LINES = 30
MAX_LINE_LENGTH = 300
MAX_DEFINITION_LINES = 120
MAX_DEFINITION_CHARACTERS = 8000
MAX_WINDOW_LINES = 2 * MAX_CONTEXT_LINES + 1
MAX_WINDOW_CHARACTERS = MAX_WINDOW_LINES * MAX_LINE_LENGTH + MAX_WINDOW_LINES - 1
MAX_PROJECT_CONTEXT_CHARACTERS = max(MAX_WINDOW_CHARACTERS, MAX_DEFINITION_CHARACTERS)
MAX_PROJECT_CHANGE_CHARACTERS = 2000


def project_evidence_character_limit(kind: str) -> int:
    if kind == "project_change":
        return MAX_PROJECT_CHANGE_CHARACTERS
    if kind in ("project_code", "project_doc", "project_test"):
        return MAX_PROJECT_CONTEXT_CHARACTERS
    raise ValueError(f"unknown project evidence kind: {kind!r}")


def project_context_snippet(result: dict) -> str | None:
    """Return the complete, bounded Reader text or reject inconsistent data.

    Line numbers are checked against the advertised range so an excerpt cannot
    carry a locator for lines absent from the actual observation. These bounds
    describe returned text, including Reader's existing per-line clipping;
    they do not claim to reconstruct the original file's omitted characters.
    """

    mode = result.get("mode", "window")
    if mode == "window":
        max_lines, max_characters = MAX_WINDOW_LINES, MAX_WINDOW_CHARACTERS
    elif mode == "definition":
        max_lines, max_characters = MAX_DEFINITION_LINES, MAX_DEFINITION_CHARACTERS
    else:
        return None
    start, end, lines = result.get("start_line"), result.get("end_line"), result.get("lines")
    if (
        type(start) is not int or type(end) is not int
        or start < 1 or end < start
        or type(lines) is not list
        or not 1 <= len(lines) <= max_lines
        or end - start + 1 != len(lines)
    ):
        return None
    texts: list[str] = []
    for number, item in enumerate(lines, start):
        if (
            type(item) is not dict
            or type(item.get("line")) is not int or item["line"] != number
            or type(item.get("text")) is not str
            or len(item["text"]) > MAX_LINE_LENGTH
        ):
            return None
        texts.append(item["text"])
    snippet = "\n".join(texts)
    if not snippet or len(snippet) > max_characters:
        return None
    return snippet
