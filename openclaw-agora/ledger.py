from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import DEFAULT_TIMEZONE, AgoraPaths
from .council import council_agent_ids

TASK_DIRS = ("council", "council/checkpoints", "execution", "execution/artifacts", "memory")


def now_iso() -> str:
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(timespec="seconds")


def generate_task_id() -> str:
    stamp = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y%m%d-%H%M%S")
    return f"agora-{stamp}-{secrets.token_hex(2)}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = f"{json.dumps(payload, indent=2, sort_keys=False)}\n"
    tmp_path = path.with_suffix(f"{path.suffix}.tmp-{secrets.token_hex(4)}")
    tmp_path.write_text(data, encoding="utf-8")
    os.replace(tmp_path, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{json.dumps(payload, sort_keys=False)}\n")


def ensure_runtime_dirs(paths: AgoraPaths) -> None:
    for directory in (
        paths.runtime_root,
        paths.tasks_root,
        paths.queue_root,
        paths.events_root,
        paths.locks_root,
        paths.cache_root,
        paths.policies_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def task_root(paths: AgoraPaths, task_id: str) -> Path:
    return paths.tasks_root / task_id


def task_paths(paths: AgoraPaths, task_id: str) -> dict[str, Path]:
    root = task_root(paths, task_id)
    mapping = {
        "root": root,
        "state": root / "state.json",
        "brief": root / "brief.md",
        "route": root / "route.json",
        "approvals": root / "approvals.json",
        "result": root / "result.md",
        "events": root / "events.jsonl",
        "roster": root / "council" / "roster.md",
        "transcript": root / "council" / "transcript.md",
        "synthesis": root / "council" / "synthesis.md",
        "council_state": root / "council" / "state.json",
        "council_checkpoints": root / "council" / "checkpoints",
        "plan": root / "execution" / "plan.md",
        "commands": root / "execution" / "commands.jsonl",
        "tests": root / "execution" / "test-results.md",
        "artifacts": root / "execution" / "artifacts",
        "memory": root / "memory" / "candidate-notes.md",
    }
    for agent_id in council_agent_ids():
        mapping[agent_id] = root / "council" / f"{agent_id}.md"
    return mapping


def create_task_skeleton(paths: AgoraPaths, task_id: str) -> dict[str, Path]:
    ensure_runtime_dirs(paths)
    files = task_paths(paths, task_id)
    for directory in TASK_DIRS:
        (files["root"] / directory).mkdir(parents=True, exist_ok=True)
    for name in ("events", "commands"):
        files[name].touch(exist_ok=True)
    return files


def append_task_event(
    paths: AgoraPaths,
    task_id: str,
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    append_jsonl(
        task_paths(paths, task_id)["events"],
        {
            "at": now_iso(),
            "event": event_type,
            "payload": payload or {},
        },
    )


def load_task(paths: AgoraPaths, task_id: str) -> dict[str, Any]:
    files = task_paths(paths, task_id)
    if not files["state"].exists():
        raise FileNotFoundError(f"Unknown task: {task_id}")
    return {
        "task_id": task_id,
        "files": files,
        "state": read_json(files["state"]),
        "route": read_json(files["route"]),
        "approvals": read_json(files["approvals"]),
    }


def save_state(paths: AgoraPaths, task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = now_iso()
    write_json(task_paths(paths, task_id)["state"], state)
    return state


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def list_artifact_paths(paths: AgoraPaths, task_id: str) -> list[Path]:
    artifact_root = task_paths(paths, task_id)["artifacts"]
    if not artifact_root.exists():
        return []
    return sorted(path for path in artifact_root.rglob("*") if path.is_file())
