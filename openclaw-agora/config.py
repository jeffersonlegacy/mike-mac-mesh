from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_RUNTIME_ROOT = Path.home() / ".openclaw" / "agora"


@dataclass(frozen=True)
class AgoraPaths:
    package_root: Path
    workspace_root: Path
    runtime_root: Path
    tasks_root: Path
    queue_root: Path
    events_root: Path
    locks_root: Path
    cache_root: Path
    policies_root: Path
    templates_root: Path


def resolve_paths() -> AgoraPaths:
    package_root = Path(__file__).resolve().parent
    workspace_root = Path(
        os.environ.get("AGORA_WORKSPACE_ROOT", package_root.parent)
    ).expanduser()
    runtime_root = Path(os.environ.get("AGORA_HOME", DEFAULT_RUNTIME_ROOT)).expanduser()
    return AgoraPaths(
        package_root=package_root,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        tasks_root=runtime_root / "tasks",
        queue_root=runtime_root / "queue",
        events_root=runtime_root / "events",
        locks_root=runtime_root / "locks",
        cache_root=runtime_root / "cache",
        policies_root=runtime_root / "policies",
        templates_root=package_root / "templates",
    )
