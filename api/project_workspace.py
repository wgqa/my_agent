"""Resolve the single read-only Engineering Project Workspace v1 binding."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ENGINEERING_PROJECT_ROOT_ENV = "ENGINEERING_PROJECT_ROOT"
DEFAULT_PROJECT_NAME = "my_agent"


@dataclass(frozen=True)
class EngineeringProject:
    """System-selected project identity. The model never supplies ``root``."""

    root: Path
    project_name: str
    source: Literal["default_repo", "configured"]


def resolve_engineering_project(
    default_root: str | os.PathLike,
    *,
    configured_root: str | None = None,
    default_project_name: str = DEFAULT_PROJECT_NAME,
) -> EngineeringProject:
    """Resolve the configured root or the release-compatible default root.

    A nonempty explicit value must name an existing directory. It never falls
    back to ``default_root`` on an invalid configured value.
    """

    raw_root = (
        os.getenv(ENGINEERING_PROJECT_ROOT_ENV)
        if configured_root is None
        else configured_root
    )
    if raw_root is None or raw_root == "":
        root = Path(default_root)
        if not root.is_dir():
            raise ValueError("default engineering project root must be a directory")
        return EngineeringProject(
            root=root.resolve(),
            project_name=default_project_name,
            source="default_repo",
        )

    try:
        root = Path(raw_root).expanduser()
    except (OSError, ValueError) as exc:
        raise ValueError("ENGINEERING_PROJECT_ROOT is invalid") from exc
    if not root.exists():
        raise ValueError("ENGINEERING_PROJECT_ROOT does not exist")
    if not root.is_dir():
        raise ValueError("ENGINEERING_PROJECT_ROOT must be a directory")

    resolved_root = root.resolve()
    return EngineeringProject(
        root=resolved_root,
        project_name=resolved_root.name or "configured-project",
        source="configured",
    )
