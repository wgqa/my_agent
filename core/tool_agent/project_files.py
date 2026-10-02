"""Shared, deterministic project-file classification for tools and Runtime.

Readable file suffixes and source-code suffixes are separate policies. These
helpers classify paths only; filesystem access checks remain with the tools.
"""

from __future__ import annotations

from pathlib import PurePosixPath


ALLOWED_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".php",
        ".properties",
        ".py",
        ".rb",
        ".rs",
        ".rst",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)

PROJECT_CODE_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".ts",
        ".tsx",
    }
)

_TEST_DIR_NAMES = frozenset({"test", "tests", "__tests__"})
_PYTHON_SUFFIXES = frozenset({".py", ".rb"})
_JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx"})


def is_test_path(path: str) -> bool:
    """Return whether a repo-relative path follows a conventional test shape."""

    normalised = path.replace("\\", "/")
    parsed = PurePosixPath(normalised)
    name = parsed.name.lower()
    suffix = parsed.suffix.lower()
    parts = {part.lower() for part in parsed.parts[:-1]}
    if suffix not in ALLOWED_SUFFIXES:
        return False
    if parts & _TEST_DIR_NAMES:
        return True
    if suffix == ".go":
        return name.endswith("_test.go")
    if suffix in _PYTHON_SUFFIXES:
        return name.startswith("test_") or name.endswith("_test" + suffix)
    if suffix in _JS_SUFFIXES:
        return ".test." in name or ".spec." in name
    stem = parsed.stem.lower()
    if suffix in {".java", ".cs"}:
        return stem.endswith("test") or stem.endswith("tests")
    return name.endswith("_test" + suffix)


def classify_project_evidence_path(path: str) -> str:
    """Classify a repo-relative path as test, source code, or project document."""

    if is_test_path(path):
        return "project_test"
    if PurePosixPath(path).suffix.lower() in PROJECT_CODE_SUFFIXES:
        return "project_code"
    return "project_doc"


__all__ = [
    "ALLOWED_SUFFIXES",
    "PROJECT_CODE_SUFFIXES",
    "classify_project_evidence_path",
    "is_test_path",
]
