from __future__ import annotations

import shutil
import shlex
import subprocess
import time
from typing import Any

from ..ledger import now_iso

DEFAULT_SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=5")
REMOTE_SHELL_CANDIDATES = ("zsh", "bash", "sh")
LOCAL_SHELL_CANDIDATES = ("/bin/zsh", "/bin/bash", "/bin/sh")


def _run_command(
    args: list[str],
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _resolve_local_shell() -> str:
    for candidate in LOCAL_SHELL_CANDIDATES:
        if candidate.startswith("/") and shutil.which(candidate):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "/bin/sh"


def inspect_worker(worker: str, *, timeout: int = 5) -> dict[str, Any]:
    started = time.monotonic()
    if worker == "forge-m2":
        shell = _resolve_local_shell()
        return {
            "name": worker,
            "kind": "local",
            "launch": "local",
            "host": "localhost",
            "reachable": True,
            "shell": shell,
            "probe_ms": int((time.monotonic() - started) * 1000),
            "error": None,
        }

    if worker == "forge-dellmac":
        probe_command = " || ".join(f"command -v {candidate}" for candidate in REMOTE_SHELL_CANDIDATES)
        try:
            result = _run_command(
                ["ssh", *DEFAULT_SSH_OPTIONS, "dellmac", probe_command],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "name": worker,
                "kind": "ssh",
                "launch": "ssh:dellmac",
                "host": "dellmac",
                "reachable": False,
                "shell": None,
                "probe_ms": int((time.monotonic() - started) * 1000),
                "error": "remote shell probe timed out",
            }
        shell = (result.stdout or "").strip().splitlines()
        shell_path = shell[0].strip() if shell else None
        error = None
        reachable = result.returncode == 0 and bool(shell_path)
        if not reachable:
            error = (result.stderr or result.stdout).strip() or "remote shell probe failed"
        return {
            "name": worker,
            "kind": "ssh",
            "launch": "ssh:dellmac",
            "host": "dellmac",
            "reachable": reachable,
            "shell": shell_path,
            "probe_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        }

    raise ValueError(f"Unsupported worker: {worker}")


def inspect_workers(*, timeout: int = 5) -> dict[str, Any]:
    workers = [inspect_worker("forge-m2", timeout=timeout), inspect_worker("forge-dellmac", timeout=timeout)]
    issues = [f"{worker['name']}: {worker['error']}" for worker in workers if worker.get("error")]
    return {
        "ready": len(issues) == 0,
        "workers": workers,
        "issues": issues,
    }


def _wrap_cwd(command: str, cwd: str | None) -> str:
    if not cwd:
        return command
    return f"cd {shlex.quote(cwd)} && {command}"


def run_forge_command(
    *,
    worker: str,
    command: str,
    cwd: str | None = None,
    timeout: int = 3600,
    dry_run: bool = False,
) -> dict[str, Any]:
    started_at = now_iso()
    wrapped_command = _wrap_cwd(command, cwd)

    if worker == "forge-m2":
        profile = inspect_worker(worker)
        shell = profile["shell"]
        argv = [shell, "-lc", wrapped_command]
        launch = profile["launch"]
    elif worker == "forge-dellmac":
        profile = inspect_worker(worker)
        if not profile["reachable"] or not profile.get("shell"):
            raise RuntimeError(f"{worker} is unavailable: {profile.get('error') or 'shell not found'}")
        remote_command = f"{shlex.quote(profile['shell'])} -lc {shlex.quote(wrapped_command)}"
        argv = ["ssh", *DEFAULT_SSH_OPTIONS, profile["host"], remote_command]
        launch = profile["launch"]
    else:
        raise ValueError(f"Unsupported worker: {worker}")

    if dry_run:
        finished_at = now_iso()
        return {
            "worker": worker,
            "launch": launch,
            "command": command,
            "cwd": cwd,
            "started_at": started_at,
            "finished_at": finished_at,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "dry_run": True,
            "shell": profile["shell"],
            "host": profile["host"],
        }

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    finished_at = now_iso()
    return {
        "worker": worker,
        "launch": launch,
        "command": command,
        "cwd": cwd,
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "dry_run": False,
        "shell": profile["shell"],
        "host": profile["host"],
    }
