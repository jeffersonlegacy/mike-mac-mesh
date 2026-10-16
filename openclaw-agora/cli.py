from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .council import council_choices
from .steward import Steward


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=False, default=str))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                print(f"{key}: {json.dumps(value, indent=2, sort_keys=False)}")
            else:
                print(f"{key}: {value}")
        return
    if isinstance(data, list):
        for item in data:
            print(item)
        return
    print(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agora", description="Agora control plane CLI")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="create runtime directories")

    brief = subparsers.add_parser("brief", help="create a task brief")
    brief.add_argument("request", nargs="+", help="task request text")
    brief.add_argument("--source", default="manual")
    brief.add_argument("--priority", default="normal")
    brief.add_argument("--risk", choices=["low", "medium", "high"])
    brief.add_argument("--worker", choices=["forge-m2", "forge-dellmac"])

    status = subparsers.add_parser("status", help="show task status")
    status.add_argument("task_id")

    state = subparsers.add_parser("state", help="show structured council state")
    state.add_argument("task_id")

    route = subparsers.add_parser("route", help="show or recompute route")
    route.add_argument("task_id")
    route.add_argument("--recompute", action="store_true")

    subparsers.add_parser("cast", help="show the Agora council roster")

    convene = subparsers.add_parser("convene", help="run a live council pass through the named agents")
    convene.add_argument("task_id")
    convene.add_argument("--agents", help="comma-separated council agent ids; defaults to the route order")
    convene.add_argument("--timeout", type=int, default=180)

    plan = subparsers.add_parser("plan", help="assign a planning turn")
    plan.add_argument("task_id")
    plan.add_argument("--agent", choices=council_choices())

    review = subparsers.add_parser("review", help="assign a review turn")
    review.add_argument("task_id")
    review.add_argument("--agent", choices=council_choices())

    approve = subparsers.add_parser("approve", help="approve a gated task")
    approve.add_argument("task_id")
    approve.add_argument("--by", default="human")
    approve.add_argument("--note")

    abort = subparsers.add_parser("abort", help="cancel a task")
    abort.add_argument("task_id")
    abort.add_argument("--reason", required=True)

    run = subparsers.add_parser("run", help="execute a forge command")
    run.add_argument("task_id")
    run.add_argument("--cmd", required=True)
    run.add_argument("--worker", choices=["forge-m2", "forge-dellmac"])
    run.add_argument("--cwd")
    run.add_argument("--timeout", type=int, default=3600)
    run.add_argument("--dry-run", action="store_true")

    ship = subparsers.add_parser("ship", help="write the final result artifact")
    ship.add_argument("task_id")
    ship.add_argument("--summary")

    artifacts = subparsers.add_parser("artifacts", help="list task artifacts")
    artifacts.add_argument("task_id")

    logs = subparsers.add_parser("logs", help="show task logs")
    logs.add_argument("task_id")
    logs.add_argument("--limit", type=int, default=20)

    memory = subparsers.add_parser("memory", help="show task memory candidates")
    memory.add_argument("task_id")

    watch = subparsers.add_parser("watch", help="launch the local visual council viewer")
    watch.add_argument("task_id", nargs="?")
    watch.add_argument("--host", default="127.0.0.1")
    watch.add_argument("--port", type=int, default=8765)
    watch.add_argument("--open-browser", action="store_true")

    recent = subparsers.add_parser("recent-tasks", help="list recent Agora task ids")
    recent.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("workers-status", help="inspect local and remote forge worker readiness")
    subparsers.add_parser("doctor", help="inspect overall Agora readiness")

    subparsers.add_parser("transport-status", help="inspect Telegram transport state")

    transport_webhook = subparsers.add_parser("transport-webhook", help="configure Telegram webhook mode")
    transport_webhook.add_argument("--url", required=True, help="public https webhook url or `auto` for Tailscale")
    transport_webhook.add_argument("--host", default="127.0.0.1", help="local listener host")
    transport_webhook.add_argument("--port", type=int, default=8787, help="local listener port")
    transport_webhook.add_argument("--path", default="/telegram-webhook", help="local listener path")
    transport_webhook.add_argument("--secret", help="reuse an existing webhook secret")

    subparsers.add_parser("transport-polling", help="switch Telegram back to polling mode")

    transport_funnel = subparsers.add_parser("transport-funnel", help="publish the local webhook listener with Tailscale Funnel")
    transport_funnel.add_argument("--port", type=int, default=8787, help="local listener port to publish")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in raw_argv
    argv = [item for item in raw_argv if item != "--json"]
    args = parser.parse_args(argv)
    args.json = as_json or getattr(args, "json", False)
    steward = Steward()

    if args.command == "init":
        result = steward.init_runtime()
    elif args.command == "brief":
        result = steward.brief(
            " ".join(args.request),
            source=args.source,
            priority=args.priority,
            risk_level=args.risk,
            worker=args.worker,
        )
    elif args.command == "status":
        result = steward.status(args.task_id)
    elif args.command == "state":
        result = steward.council_state(args.task_id)
    elif args.command == "route":
        result = steward.route(args.task_id, recompute=args.recompute)
    elif args.command == "cast":
        result = steward.cast()
    elif args.command == "convene":
        agent_ids = [item.strip() for item in (args.agents or "").split(",") if item.strip()] or None
        result = steward.convene(args.task_id, agent_ids=agent_ids, timeout=args.timeout)
    elif args.command == "plan":
        result = steward.plan(args.task_id, agent=args.agent)
    elif args.command == "review":
        result = steward.review(args.task_id, agent=args.agent)
    elif args.command == "approve":
        result = steward.approve(args.task_id, approver=args.by, note=args.note)
    elif args.command == "abort":
        result = steward.abort(args.task_id, reason=args.reason)
    elif args.command == "run":
        result = steward.run(
            args.task_id,
            command=args.cmd,
            worker=args.worker,
            cwd=args.cwd,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
    elif args.command == "ship":
        result = steward.ship(args.task_id, summary=args.summary)
    elif args.command == "artifacts":
        result = steward.artifacts(args.task_id)
    elif args.command == "logs":
        result = steward.logs(args.task_id, limit=args.limit)
    elif args.command == "memory":
        result = steward.memory(args.task_id)
    elif args.command == "watch":
        result = steward.watch(
            task_id=args.task_id,
            host=args.host,
            port=args.port,
            open_browser=args.open_browser,
        )
    elif args.command == "recent-tasks":
        result = steward.recent_tasks(limit=args.limit)
    elif args.command == "workers-status":
        result = steward.workers_status()
    elif args.command == "doctor":
        result = steward.doctor()
    elif args.command == "transport-status":
        result = steward.transport_status()
    elif args.command == "transport-webhook":
        result = steward.transport_webhook(
            args.url,
            host=args.host,
            port=args.port,
            path=args.path,
            secret=args.secret,
        )
    elif args.command == "transport-polling":
        result = steward.transport_polling()
    elif args.command == "transport-funnel":
        result = steward.transport_funnel(port=args.port)
    else:
        parser.error(f"unsupported command: {args.command}")
        return 2

    _print(result, args.json)
    return 0
