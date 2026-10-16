from __future__ import annotations

import json
from typing import Any

from ..adapters import (
    render_agent_assignment,
    render_brief,
    render_plan_file,
    render_result,
)
from ..config import AgoraPaths, resolve_paths
from ..council import CHAIR_ID, COUNCIL_MEMBERS, council_choices, council_roster
from ..council_runtime import run_council_session
from ..council_state import build_initial_council_state, render_synthesis_markdown
from ..forge import inspect_workers, run_forge_command
from ..ledger import (
    append_jsonl,
    append_task_event,
    create_task_skeleton,
    generate_task_id,
    list_artifact_paths,
    load_jsonl,
    load_task,
    now_iso,
    read_json,
    save_state,
    task_paths,
    write_json,
    ensure_runtime_dirs,
)
from ..router import decide_route
from ..transport import (
    configure_polling,
    configure_webhook,
    enable_funnel,
    inspect_telegram_webhook,
    load_transport_status,
)
from ..viewer import recent_task_ids, start_viewer

VALID_STATUSES = {
    "new",
    "triaged",
    "planning",
    "reviewing",
    "approved",
    "executing",
    "verifying",
    "synthesizing",
    "done",
    "blocked",
    "cancelled",
}


class Steward:
    def __init__(self, paths: AgoraPaths | None = None) -> None:
        self.paths = paths or resolve_paths()

    def init_runtime(self) -> dict[str, str]:
        ensure_runtime_dirs(self.paths)
        return {
            "runtime_root": str(self.paths.runtime_root),
            "tasks_root": str(self.paths.tasks_root),
            "queue_root": str(self.paths.queue_root),
        }

    def brief(
        self,
        request_text: str,
        *,
        source: str = "manual",
        priority: str = "normal",
        risk_level: str | None = None,
        worker: str | None = None,
    ) -> dict[str, Any]:
        task_id = generate_task_id()
        files = create_task_skeleton(self.paths, task_id)
        route = decide_route(
            request_text,
            risk_override=risk_level,
            worker_override=worker,
        )
        state = {
            "task_id": task_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "source": source,
            "request_text": request_text,
            "status": "triaged",
            "priority": priority,
            "risk_level": route["risk_level"],
            "approval_required": route["approval_required"],
            "assigned_agents": route["assigned_agents"],
            "assigned_workers": route["assigned_workers"],
            "final_owner": "steward",
        }
        approvals = {
            "required": route["approval_required"],
            "approved": not route["approval_required"],
            "approved_by": None,
            "approved_at": None,
            "notes": [],
        }

        write_json(files["state"], state)
        write_json(files["route"], route)
        write_json(files["approvals"], approvals)
        files["roster"].write_text(
            "\n".join(
                [
                    "# Council Roster",
                    "",
                    *[
                        f"- `{member.id}`: {member.name} ({member.title}) - {member.mandate}"
                        for member in COUNCIL_MEMBERS
                    ],
                    "",
                ]
            ),
            encoding="utf-8",
        )
        files["brief"].write_text(
            render_brief(
                self.paths.templates_root / "task-brief.template.md",
                request_text=request_text,
                route=route,
                approval_required=approvals["required"],
            ),
            encoding="utf-8",
        )
        for agent in council_choices():
            assignment_type = "council-turn"
            if agent == route["chair"]:
                assignment_type = "chair-turn"
            elif agent == route["planning_lead"]:
                assignment_type = "planning-turn"
            elif agent == route["review_lead"]:
                assignment_type = "review-turn"
            files[agent].write_text(
                render_agent_assignment(
                    agent=agent,
                    assignment_type=assignment_type,
                    task_id=task_id,
                    request_text=request_text,
                    route=route,
                    state=state,
                ),
                encoding="utf-8",
            )
        files["synthesis"].write_text(
            "# Steward Synthesis\n\nPending.\n",
            encoding="utf-8",
        )
        files["transcript"].write_text(
            "# Council Transcript\n\nPending.\n",
            encoding="utf-8",
        )
        write_json(
            files["council_state"],
            build_initial_council_state(
                task_id=task_id,
                request_text=request_text,
                route=route,
                agent_ids=route["council_order"],
            ),
        )
        files["plan"].write_text(
            render_plan_file(task_id, request_text, route),
            encoding="utf-8",
        )
        files["tests"].write_text("# Verification\n\nPending.\n", encoding="utf-8")
        files["memory"].write_text("# Candidate Notes\n\nPending.\n", encoding="utf-8")
        files["result"].write_text("# Result\n\nPending.\n", encoding="utf-8")

        append_task_event(
            self.paths,
            task_id,
            "task.created",
            payload={
                "source": source,
                "risk_level": state["risk_level"],
                "worker": route["assigned_workers"][0],
            },
        )
        append_task_event(
            self.paths,
            task_id,
            "route.assigned",
            payload=route,
        )
        return self.status(task_id)

    def status(self, task_id: str) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        files = task["files"]
        return {
            **task,
            "files": {name: str(path) for name, path in files.items()},
            "task_root": str(files["root"]),
            "artifacts": [str(path) for path in list_artifact_paths(self.paths, task_id)],
        }

    def route(self, task_id: str, *, recompute: bool = False) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        if recompute:
            route = decide_route(task["state"]["request_text"])
            write_json(task["files"]["route"], route)
            state = task["state"]
            state["risk_level"] = route["risk_level"]
            state["approval_required"] = route["approval_required"]
            state["assigned_agents"] = route["assigned_agents"]
            state["assigned_workers"] = route["assigned_workers"]
            save_state(self.paths, task_id, state)
            approvals = task["approvals"]
            approvals["required"] = route["approval_required"]
            if not approvals["required"]:
                approvals["approved"] = True
            write_json(task["files"]["approvals"], approvals)
            append_task_event(
                self.paths,
                task_id,
                "route.recomputed",
                payload=route,
            )
        return self.status(task_id)

    def _set_status(self, task_id: str, status: str) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        task = load_task(self.paths, task_id)
        state = task["state"]
        state["status"] = status
        save_state(self.paths, task_id, state)
        append_task_event(self.paths, task_id, "state.changed", payload={"status": status})
        return self.status(task_id)

    def plan(self, task_id: str, *, agent: str | None = None) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        selected_agent = agent or task["route"]["planning_lead"]
        task["files"][selected_agent].write_text(
            render_agent_assignment(
                agent=selected_agent,
                assignment_type="plan",
                task_id=task_id,
                request_text=task["state"]["request_text"],
                route=task["route"],
                state={**task["state"], "status": "planning"},
            ),
            encoding="utf-8",
        )
        append_task_event(
            self.paths,
            task_id,
            "plan.assigned",
            payload={"agent": selected_agent},
        )
        return self._set_status(task_id, "planning")

    def review(self, task_id: str, *, agent: str | None = None) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        selected_agent = agent or task["route"]["review_lead"]
        task["files"][selected_agent].write_text(
            render_agent_assignment(
                agent=selected_agent,
                assignment_type="review",
                task_id=task_id,
                request_text=task["state"]["request_text"],
                route=task["route"],
                state={**task["state"], "status": "reviewing"},
            ),
            encoding="utf-8",
        )
        append_task_event(
            self.paths,
            task_id,
            "review.assigned",
            payload={"agent": selected_agent},
        )
        return self._set_status(task_id, "reviewing")

    def approve(
        self,
        task_id: str,
        *,
        approver: str = "human",
        note: str | None = None,
    ) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        approvals = task["approvals"]
        approvals["approved"] = True
        approvals["approved_by"] = approver
        approvals["approved_at"] = now_iso()
        if note:
            approvals["notes"].append({"at": now_iso(), "note": note, "by": approver})
        write_json(task["files"]["approvals"], approvals)
        append_task_event(
            self.paths,
            task_id,
            "approval.granted",
            payload={"by": approver, "note": note or ""},
        )
        return self._set_status(task_id, "approved")

    def abort(self, task_id: str, *, reason: str) -> dict[str, Any]:
        append_task_event(
            self.paths,
            task_id,
            "task.cancelled",
            payload={"reason": reason},
        )
        return self._set_status(task_id, "cancelled")

    def run(
        self,
        task_id: str,
        *,
        command: str,
        worker: str | None = None,
        cwd: str | None = None,
        timeout: int = 3600,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        approvals = task["approvals"]
        if approvals["required"] and not approvals["approved"]:
            raise RuntimeError(f"Task {task_id} requires approval before execution.")

        chosen_worker = worker or task["state"]["assigned_workers"][0]
        self._set_status(task_id, "executing")
        result = run_forge_command(
            worker=chosen_worker,
            command=command,
            cwd=cwd,
            timeout=timeout,
            dry_run=dry_run,
        )
        files = task["files"]
        stamp = result["started_at"].replace(":", "").replace("-", "")
        stdout_path = files["artifacts"] / f"{stamp}-stdout.log"
        stderr_path = files["artifacts"] / f"{stamp}-stderr.log"
        stdout_path.write_text(result["stdout"], encoding="utf-8")
        stderr_path.write_text(result["stderr"], encoding="utf-8")

        command_record = {
            "task_id": task_id,
            "worker": chosen_worker,
            "command": command,
            "cwd": cwd,
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
            "returncode": result["returncode"],
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "dry_run": result["dry_run"],
        }
        append_jsonl(files["commands"], command_record)
        files["tests"].write_text(
            "\n".join(
                [
                    "# Verification",
                    "",
                    f"- Latest worker: `{chosen_worker}`",
                    f"- Exit code: `{result['returncode']}`",
                    f"- Stdout: `{stdout_path}`",
                    f"- Stderr: `{stderr_path}`",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        append_task_event(
            self.paths,
            task_id,
            "forge.run",
            payload={
                "worker": chosen_worker,
                "returncode": result["returncode"],
                "dry_run": dry_run,
            },
        )
        next_status = "verifying" if result["returncode"] == 0 else "blocked"
        self._set_status(task_id, next_status)
        return {
            **result,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "task_id": task_id,
        }

    def ship(self, task_id: str, *, summary: str | None = None) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        if task["state"]["status"] != "blocked":
            self._set_status(task_id, "synthesizing")
        append_task_event(self.paths, task_id, "task.shipped", payload={"summary": summary or ""})
        if task["state"]["status"] != "blocked":
            self._set_status(task_id, "done")

        task = load_task(self.paths, task_id)
        command_rows = load_jsonl(task["files"]["commands"])
        task["files"]["result"].write_text(
            render_result(
                task_id=task_id,
                state=task["state"],
                route=task["route"],
                approvals=task["approvals"],
                command_rows=command_rows,
                summary=summary,
            ),
            encoding="utf-8",
        )
        task["files"]["synthesis"].write_text(
            (summary or "Steward synthesis completed.") + "\n",
            encoding="utf-8",
        )
        return self.status(task_id)

    def artifacts(self, task_id: str) -> list[str]:
        return [str(path) for path in list_artifact_paths(self.paths, task_id)]

    def logs(self, task_id: str, *, limit: int = 20) -> dict[str, Any]:
        files = task_paths(self.paths, task_id)
        return {
            "events": load_jsonl(files["events"])[-limit:],
            "commands": load_jsonl(files["commands"])[-limit:],
        }

    def memory(self, task_id: str) -> str:
        return task_paths(self.paths, task_id)["memory"].read_text(encoding="utf-8")

    def council_state(self, task_id: str) -> dict[str, Any]:
        return read_json(task_paths(self.paths, task_id)["council_state"])

    def cast(self) -> dict[str, Any]:
        return {
            "chair": CHAIR_ID,
            "members": council_roster(),
        }

    def convene(
        self,
        task_id: str,
        *,
        agent_ids: list[str] | None = None,
        timeout: int = 180,
    ) -> dict[str, Any]:
        task = load_task(self.paths, task_id)
        order = agent_ids or list(task["route"]["council_order"])
        for agent_id in order:
            if agent_id not in task["files"]:
                raise ValueError(f"Unknown council agent for task: {agent_id}")
        self._set_status(task_id, "planning")
        try:
            result = run_council_session(
                task_id=task_id,
                request_text=task["state"]["request_text"],
                route=task["route"],
                files=task["files"],
                agent_ids=order,
                timeout=timeout,
            )
        except RuntimeError as exc:
            append_task_event(
                self.paths,
                task_id,
                "council.failed",
                payload={"order": order, "error": str(exc)},
            )
            self._set_status(task_id, "blocked")
            raise
        if isinstance(result.get("council_state"), dict):
            task["files"]["council_state"].write_text(
                f"{json.dumps(result['council_state'], indent=2, sort_keys=False)}\n",
                encoding="utf-8",
            )
            task["files"]["synthesis"].write_text(
                render_synthesis_markdown(result["council_state"]),
                encoding="utf-8",
            )
        append_task_event(
            self.paths,
            task_id,
            "council.convened",
            payload={
                "order": order,
                "turns": len(result["turns"]),
            },
        )
        self._set_status(task_id, "reviewing")
        return {
            **result,
            "status": self.status(task_id)["state"]["status"],
        }

    def transport_status(self) -> dict[str, Any]:
        return load_transport_status()

    def workers_status(self) -> dict[str, Any]:
        return inspect_workers()

    def doctor(self) -> dict[str, Any]:
        transport = load_transport_status()
        telegram_api = inspect_telegram_webhook()
        workers = inspect_workers()
        issues: list[str] = []

        if transport["telegram"]["mode"] != "webhook":
            issues.append("telegram is not in webhook mode")
        if not transport["tailscale"]["running"]:
            issues.append("tailscale is not running")
        if not telegram_api["configured"]:
            issues.append("telegram bot token is not configured")
        elif not telegram_api["reachable"]:
            issues.append(f"telegram webhook inspection failed: {telegram_api['error']}")
        elif not telegram_api["matches_configured_webhook"]:
            issues.append("telegram live webhook does not match the configured webhook URL")
        if telegram_api.get("last_error_message"):
            issues.append(f"telegram reported delivery errors: {telegram_api['last_error_message']}")
        issues.extend(workers["issues"])

        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "transport": transport,
            "telegram_api": telegram_api,
            "workers": workers,
        }

    def watch(
        self,
        *,
        task_id: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        open_browser: bool = False,
    ) -> dict[str, Any]:
        return start_viewer(
            self.paths,
            task_id=task_id,
            host=host,
            port=port,
            open_browser=open_browser,
        )

    def recent_tasks(self, *, limit: int = 20) -> dict[str, Any]:
        return {"tasks": recent_task_ids(self.paths, limit=limit)}

    def transport_webhook(
        self,
        public_url: str,
        *,
        host: str = "127.0.0.1",
        port: int = 8787,
        path: str = "/telegram-webhook",
        secret: str | None = None,
    ) -> dict[str, Any]:
        return configure_webhook(
            public_url,
            webhook_host=host,
            webhook_port=port,
            webhook_path=path,
            secret_value=secret,
        )

    def transport_polling(self) -> dict[str, Any]:
        return configure_polling()

    def transport_funnel(self, *, port: int = 8787) -> dict[str, Any]:
        return enable_funnel(port=port)
